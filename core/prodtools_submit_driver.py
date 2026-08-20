#!/usr/bin/env python3
"""Submit one rendered entry through prodtools submit_entry.

Runs under the sourced Mu2e env, cwd = the stage dir holding the cnf.
Prints one line: SUBMIT_RESULT {"cluster_id", "jobsub_id", "status"}.
The ledger row lifecycle is submit_entry's own — a failed submission
closes its reservation before we exit. submit_entry's `cluster_id` is a
numeric STRING; `jobsub_id` is "CLUSTER.PROC@schedd" or None
(prodtools_exec.submit_cnf normalizes both).

--ledger is autoresearch's own derived path, not an operator flag, so we
mkdir its parent ourselves; prodtools' ensure_ledger_dir is documented
for the per-user ledger_for() default path only.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prodtools", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--origin", required=True)
    # From prodtools_exec's WFTOP/WFPROJECT; passed as args because this
    # runs standalone under the Mu2e env (no cross-env import).
    ap.add_argument("--wftop", required=True)
    ap.add_argument("--wfproject", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, args.prodtools)
    from utils.submit import SubmitOptions, submit_entry

    entry = json.loads(open(args.entry).read())[0]
    Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
    opts = SubmitOptions(ledger_db=args.ledger, dry_run=args.dry_run,
                         origin=args.origin,
                         wftop=args.wftop, wfproject=args.wfproject)
    result = submit_entry(entry, 0, opts)
    print("SUBMIT_RESULT " + json.dumps({
        "cluster_id": result.get("cluster_id"),
        "jobsub_id": result.get("jobsub_id"),
        "status": result.get("status"),
    }), flush=True)
    return 0 if result.get("cluster_id") else 1


if __name__ == "__main__":
    sys.exit(main())
