#!/usr/bin/env python3
"""Analyze leaderboard_bo.tsv: convergence + 1D projections."""

import csv
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

LEADERBOARD = Path("/exp/mu2e/app/users/oksuzian/autoresearch/leaderboard_bo.tsv")
OUT_DIR = Path("/exp/mu2e/app/users/oksuzian/autoresearch/slides")

KNOBS = ["halfT", "nFoils", "deltaZ", "z0", "R_start", "R_mid", "R_end"]
KNOB_LABELS = {
    "halfT":   "halfT (mm)",
    "nFoils":  "nFoils",
    "deltaZ":  "deltaZ (mm)",
    "z0":      "z0 (mm)",
    "R_start": "R_start (mm)",
    "R_mid":   "R_mid (mm)",
    "R_end":   "R_end (mm)",
}
BASELINE = {"halfT": 0.0528, "nFoils": 37, "deltaZ": 22.222, "z0": 5871.0,
            "R_start": 75.0, "R_mid": 75.0, "R_end": 75.0}
BASELINE_SOB = 3.31
ONE_D_BEST = {"halfT": 0.125, "S": 3.81}


def load():
    rows = []
    with LEADERBOARD.open() as fh:
        reader = csv.reader(fh, delimiter="\t")
        for line in reader:
            if not line or line[0].startswith("#"):
                continue
            rows.append({
                "config": line[0],
                "halfT":  float(line[1]),
                "nFoils": float(line[2]),
                "deltaZ": float(line[3]),
                "z0":     float(line[4]),
                "R_start": float(line[5]),
                "R_mid":   float(line[6]),
                "R_end":   float(line[7]),
                "S":      float(line[8]),
            })
    return rows


def plot_convergence(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    iters = list(range(1, len(rows) + 1))
    sob   = [r["S"] for r in rows]
    best  = []
    cur = -1.0
    for s in sob:
        cur = max(cur, s)
        best.append(cur)

    ax.scatter(iters, sob, s=40, c="#888", alpha=0.7, label="per-iter S/sqrt(B)")
    ax.plot(iters, best, "o-", c="#1f77b4", lw=2, ms=6, label="best so far")
    ax.axhline(BASELINE_SOB, ls=":", c="#888", label=f"config_v00 baseline ({BASELINE_SOB})")
    ax.axhline(ONE_D_BEST["S"], ls="--", c="#d62728", label=f"1D scan winner ({ONE_D_BEST['S']})")
    ax.set_xlabel("BO iteration")
    ax.set_ylabel("Run1A CE  S / sqrt(B)")
    ax.set_title(f"7D Bayesian Optimization convergence ({len(rows)} evals)")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=10)
    ax.set_ylim(1.4, 4.1)

    out = OUT_DIR / "bo_convergence.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


def plot_projections(rows):
    fig, axes = plt.subplots(2, 4, figsize=(15, 7))
    axes = axes.flat

    for i, knob in enumerate(KNOBS):
        ax = axes[i]
        xs = [r[knob] for r in rows]
        ys = [r["S"]  for r in rows]
        # color by iteration
        c = list(range(len(rows)))
        sc = ax.scatter(xs, ys, c=c, cmap="viridis", s=50, alpha=0.85,
                        edgecolors="white", linewidths=0.5)
        ax.axvline(BASELINE[knob], ls=":", c="#888", lw=1, label="baseline")
        ax.axhline(BASELINE_SOB, ls=":", c="#888", lw=1)
        ax.axhline(ONE_D_BEST["S"], ls="--", c="#d62728", lw=1, label="1D winner")
        # mark best
        i_best = max(range(len(rows)), key=lambda j: rows[j]["S"])
        ax.scatter([rows[i_best][knob]], [rows[i_best]["S"]],
                   marker="*", s=300, c="gold", edgecolors="black", linewidths=1, zorder=10,
                   label=f"best ({rows[i_best]['S']:.3f})")
        ax.set_xlabel(KNOB_LABELS[knob])
        ax.set_ylabel("S/sqrt(B)")
        ax.grid(alpha=0.3)
        ax.set_ylim(1.4, 4.1)
        if i == 0:
            ax.legend(loc="lower right", fontsize=8)

    # the 8th panel: ranked top-10 table
    ax = axes[7]
    ax.axis("off")
    top = sorted(rows, key=lambda r: -r["S"])[:10]
    cell_text = [
        [r["config"].replace("config_bo", ""),
         f"{r['halfT']:.3f}", str(int(r["nFoils"])), f"{r['deltaZ']:.1f}",
         f"{r['z0']:.0f}", f"{r['R_start']:.0f}",
         f"{r['R_mid']:.0f}", f"{r['R_end']:.0f}",
         f"{r['S']:.3f}"]
        for r in top
    ]
    cols = ["bo", "halfT", "nFoils", "dZ", "z0",
            "R_s", "R_m", "R_e", "S/sqrt(B)"]
    tbl = ax.table(cellText=cell_text, colLabels=cols, loc="center",
                   cellLoc="center", colLoc="center", colColours=["#dde6f0"]*9)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1.0, 1.05)
    ax.set_title("Top 10 by S/sqrt(B)", fontsize=10)

    fig.suptitle(
        f"7D BO: 1D projections of S/sqrt(B) per knob ({len(rows)} evals, color = iteration)",
        fontsize=12,
    )
    fig.tight_layout()
    out = OUT_DIR / "bo_projections.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


def print_summary(rows):
    print(f"\n=== {len(rows)} evaluations ===")
    rows_s = sorted(rows, key=lambda r: -r["S"])
    print("\nTop 5:")
    for r in rows_s[:5]:
        print(f"  {r['config']}: S/sqrt(B) = {r['S']:.3f}  "
              f"halfT={r['halfT']:.3f} n={int(r['nFoils'])} dZ={r['deltaZ']:.1f} "
              f"z0={r['z0']:.0f} R=({r['R_start']:.0f},{r['R_mid']:.0f},{r['R_end']:.0f})")
    print(f"\n1D scan winner: S/sqrt(B) = {ONE_D_BEST['S']}  (halfT={ONE_D_BEST['halfT']}, others=baseline)")
    print(f"7D BO best:     S/sqrt(B) = {rows_s[0]['S']:.3f}  ({rows_s[0]['config']})")
    delta = (rows_s[0]['S'] - ONE_D_BEST['S']) / ONE_D_BEST['S'] * 100
    print(f"BO improvement over 1D winner: {delta:+.1f}%")


def main():
    rows = load()
    plot_convergence(rows)
    plot_projections(rows)
    print_summary(rows)


if __name__ == "__main__":
    main()
