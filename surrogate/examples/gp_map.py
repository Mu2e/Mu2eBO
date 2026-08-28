#!/usr/bin/env python
"""GP map over a BO leaderboard, fetched ENTIRELY through the MCP server.

This is what an MCP client (e.g. Claude) does under the hood: spawn
surrogate/mcp_server.py over stdio, call list_problems / stats / predict,
and render the GP's view of the search space -- predicted flash-per-POT
vs predicted sob for a Sobol sweep of the box, with the deployed damage
budget line.  Nothing here touches the GP directly; every number crosses
the MCP boundary.

Usage:
    python surrogate/examples/gp_map.py [mode] [out.png]   # default foilspf
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

MODE = sys.argv[1] if len(sys.argv) > 1 else "foilspf"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / f"gp_map_{MODE}.png"
N_SOBOL = 2000
CHUNK = 500
DEP_FLASH = 6.85443e-7  # deployed-target damage budget, MeV/POT


async def fetch():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=[str(REPO / "surrogate" / "mcp_server.py")])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            def payload(res):
                return res.structured_content

            probs = payload(await s.call_tool("list_problems", {}))
            if MODE not in probs:
                raise SystemExit(f"mode {MODE!r} not served; have {sorted(probs)}")
            spec = probs[MODE]
            meta = payload(await s.call_tool("stats", {"problem": MODE}))

            from scipy.stats import qmc
            unit = qmc.Sobol(d=spec["dims"], scramble=True, seed=1).random(N_SOBOL)
            lo, hi = spec["bounds_lo"], spec["bounds_hi"]
            pts = [[lo[j] + u[j] * (hi[j] - lo[j]) for j in range(spec["dims"])]
                   for u in unit]
            for j in spec["int_dims"]:
                for p in pts:
                    p[j] = round(p[j])

            mean, sigma = [], []
            for i in range(0, len(pts), CHUNK):
                out = payload(await s.call_tool(
                    "predict", {"problem": MODE, "points": pts[i:i + CHUNK]}))
                mean += out["mean"]
                sigma += out["sigma"]
            return spec, meta, mean, sigma


def main():
    spec, meta, mean, sigma = asyncio.run(fetch())
    sob = [m[0] for m in mean]
    flash = [10 ** -m[1] for m in mean]  # axis 1 is -log10(flash)
    ssob = [s[0] for s in sigma]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5.5))
    sc = ax.scatter(flash, sob, c=ssob, s=6, cmap="viridis", alpha=0.6)
    fig.colorbar(sc, ax=ax, label=r"GP $\sigma$(sob)")
    ax.axvline(DEP_FLASH, color="crimson", ls="--", lw=1.5,
               label=f"damage budget {DEP_FLASH:.3g} MeV/POT")
    ax.set_xscale("log")
    ax.set_xlabel("GP-predicted flash per POT [MeV/POT]")
    ax.set_ylabel("GP-predicted sob")
    ax.set_title(f"GP map via MCP -- mode={meta['problem']}, "
                 f"n={meta['n_rows']} board rows, {N_SOBOL} Sobol probes")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT, dpi=130)
    print(f"wrote {OUT} ({N_SOBOL} points, {meta['n_rows']}-row board)")


if __name__ == "__main__":
    main()
