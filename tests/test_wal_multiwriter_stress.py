"""WAL multi-writer stress test: A/B reproducer for foilsf08 SqliteSaver crash.

Discriminates two hypotheses for the 2026-06-08 closed-loop crash where
10/10 children died with "file is not a database" at SqliteSaver.put_writes:

  H1: WAL on CephFS is fundamentally unsafe with N>>1 writers (shared -shm
      mmap is not POSIX-coherent across processes on Ceph).
  H2: The crash was foilsf08-specific (picker/env/version/etc.); vanilla
      multi-writer WAL on Ceph would have stayed clean.

Design:
  - 11 multiprocessing workers (mimics parent + 10 children) per cell.
  - Each worker opens its OWN SqliteSaver against the SAME shared DB file.
  - Each worker calls put_writes() in a loop with 10-50 KB random payloads
    at one write per ~10-30s (matches real child checkpoint cadence).
  - Cell A = CephFS path under graph_data/stress_test/ (production config).
  - Cell B = /tmp path (proposed fix).
  - Both cells run 15 min (or until any worker hits the production
    signature, whichever first; kill-switch terminates remaining workers).

Run:
  .venv/bin/python tests/test_wal_multiwriter_stress.py

Does NOT submit grid jobs, does NOT touch production checkpoints.sqlite.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import shutil
import sys
import time
import traceback
import uuid
from collections import Counter
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

N_WORKERS = 11
CELL_DURATION_S = 15 * 60
MIN_WRITE_INTERVAL_S = 10
MAX_WRITE_INTERVAL_S = 30
MIN_BLOB_BYTES = 10 * 1024
MAX_BLOB_BYTES = 50 * 1024

# Production crash signatures we want to count specifically.
PROD_SIGNATURES = (
    "file is not a database",
    "database disk image is malformed",
    "database is locked",
    "disk I/O error",
)


def classify(exc_text: str) -> str:
    low = exc_text.lower()
    for sig in PROD_SIGNATURES:
        if sig in low:
            return sig
    return "other"


def worker(worker_id: int, db_path: str, duration_s: int, out_q: mp.Queue, stop_evt) -> None:
    """One worker = one OS process = one SqliteSaver connection.

    Mirrors how each closed-loop child opens its own SqliteSaver against
    the shared checkpoints.sqlite. Loops put_writes() with realistic
    payload size + cadence until the deadline or a crash.
    """
    rng = random.Random(os.getpid() ^ worker_id)
    deadline = time.monotonic() + duration_s
    n_ok = 0
    first_err: str | None = None
    first_err_t = None

    try:
        with SqliteSaver.from_conn_string(db_path) as saver:
            # Force setup (creates tables + sets WAL) before the loop.
            saver.setup()
            thread_id = f"stress-w{worker_id:02d}-{uuid.uuid4().hex[:8]}"
            ckpt_ns = ""

            while time.monotonic() < deadline and not stop_evt.is_set():
                ckpt_id = uuid.uuid4().hex
                blob = rng.randbytes(rng.randint(MIN_BLOB_BYTES, MAX_BLOB_BYTES))
                cfg = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ckpt_ns,
                        "checkpoint_id": ckpt_id,
                    }
                }
                try:
                    saver.put_writes(
                        cfg,
                        writes=[("stress_channel", blob)],
                        task_id=f"task-{n_ok:06d}",
                    )
                    n_ok += 1
                except Exception as exc:  # noqa: BLE001 — we want to classify everything
                    first_err = f"{type(exc).__name__}: {exc}"
                    first_err_t = time.monotonic()
                    out_q.put({
                        "worker": worker_id,
                        "n_ok_before_crash": n_ok,
                        "error_class": classify(first_err),
                        "error_text": first_err,
                        "traceback": traceback.format_exc(limit=4),
                        "t_to_crash_s": None,
                    })
                    return
                time.sleep(rng.uniform(MIN_WRITE_INTERVAL_S, MAX_WRITE_INTERVAL_S))
    except Exception as exc:  # noqa: BLE001 — connection-open failure
        first_err = f"{type(exc).__name__}: {exc}"
        out_q.put({
            "worker": worker_id,
            "n_ok_before_crash": n_ok,
            "error_class": classify(first_err),
            "error_text": first_err,
            "traceback": traceback.format_exc(limit=4),
            "t_to_crash_s": None,
        })
        return

    out_q.put({
        "worker": worker_id,
        "n_ok_before_crash": n_ok,
        "error_class": "clean",
        "error_text": None,
        "traceback": None,
    })


def run_cell(label: str, db_path: Path, duration_s: int) -> dict:
    """Run one A/B cell. Returns summary dict."""
    print(f"\n=== Cell {label}: db={db_path} duration={duration_s}s workers={N_WORKERS} ===", flush=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Start from a clean DB to remove "unclean sidecar from prior session"
    # as a confounder — H1 should still reproduce even on a fresh DB.
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            p.unlink()

    ctx = mp.get_context("spawn")  # spawn => fresh interpreter = realistic
    out_q: mp.Queue = ctx.Queue()
    stop_evt = ctx.Event()
    procs = [
        ctx.Process(target=worker, args=(i, str(db_path), duration_s, out_q, stop_evt))
        for i in range(N_WORKERS)
    ]
    t0 = time.monotonic()
    for p in procs:
        p.start()

    results: list[dict] = []
    deadline = t0 + duration_s + 60
    # Drain results as they arrive; kill-switch on first production-signature crash.
    while time.monotonic() < deadline and any(p.is_alive() for p in procs):
        try:
            res = out_q.get(timeout=5)
        except Exception:
            continue
        res["t_from_start_s"] = round(time.monotonic() - t0, 1)
        results.append(res)
        print(
            f"  [{label}] worker {res['worker']:02d} -> {res['error_class']} "
            f"(n_ok={res['n_ok_before_crash']}, t={res['t_from_start_s']}s)",
            flush=True,
        )
        if res["error_class"] in PROD_SIGNATURES:
            print(f"  [{label}] kill-switch: production crash signature; terminating remaining workers", flush=True)
            stop_evt.set()
            time.sleep(2)
            for p in procs:
                if p.is_alive():
                    p.terminate()
            break

    for p in procs:
        p.join(timeout=10)
        if p.is_alive():
            p.kill()
            p.join(timeout=5)

    # Drain any stragglers from queue.
    while True:
        try:
            res = out_q.get_nowait()
            res.setdefault("t_from_start_s", round(time.monotonic() - t0, 1))
            results.append(res)
        except Exception:
            break

    counts = Counter(r["error_class"] for r in results)
    summary = {
        "label": label,
        "db_path": str(db_path),
        "wall_s": round(time.monotonic() - t0, 1),
        "n_results": len(results),
        "counts": dict(counts),
        "results": results,
    }
    print(f"  [{label}] summary: {dict(counts)} (wall={summary['wall_s']}s)", flush=True)
    return summary


def main() -> int:
    user = os.environ.get("USER", "unknown")
    # CephFS path for the WAL-incoherence repro; /data is CephFS too (graph_data
    # relocated off /app 2026-07-17), so the production-config intent is preserved.
    ceph_db = Path("/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/stress_test/test_ceph.sqlite")
    tmp_root = Path(f"/tmp/{user}/stress_test")
    tmp_db = tmp_root / "test_tmp.sqlite"

    cell_a = run_cell("A_ceph_wal", ceph_db, CELL_DURATION_S)
    cell_b = run_cell("B_tmp_wal", tmp_db, CELL_DURATION_S)

    print("\n=== A/B verdict ===", flush=True)
    print(f"  Cell A (Ceph + WAL):  {cell_a['counts']}", flush=True)
    print(f"  Cell B (tmpfs + WAL): {cell_b['counts']}", flush=True)

    # Cleanup hint (don't auto-delete; operator may want forensics).
    print(f"\nForensics retained at:\n  {ceph_db.parent}\n  {tmp_root}", flush=True)
    print("Remove with:  rm -rf  <those dirs>  when done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
