#!/usr/bin/env python3
"""fakeanakit: a stand-in for anakit's MCP server (list_analyses,
run_analysis) for tests/test_anakit_kit.py, driven through the real
KitClient over stdio. It remembers the --work-area it was started with,
answers run_analysis with canned numbers, and writes one ROOT-named file
into output_dir so the adapter has a file to report.

No `from __future__ import annotations` here (see tests/toykit.py).
"""
import sys
from pathlib import Path
from typing import Optional

CATALOGUE = {
    "ce_sensitivity": {
        "metrics": ["s_over_sqrt_b", "ce_abs_eff"],
        "parameters": {"input_correction": {"required": True}},
        "takes_data_files": True},
    "approx_ce_sensitivity": {
        "metrics": ["sensitivity"],
        "parameters": {"sig_eff": {"required": True}},
        "takes_data_files": False},
}


def started_with(argv):
    return argv[argv.index("--work-area") + 1] if "--work-area" in argv else None


def make_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("fakeanakit")
    work_area = started_with(sys.argv)

    @server.tool()
    def list_analyses() -> dict:
        return {"status": "success", "files": [], "message": "fake",
                "metadata": {"analyses": CATALOGUE,
                             "environment": f"work area {work_area}"}}

    @server.tool()
    def run_analysis(analysis: str, output_dir: str,
                     data_file: Optional[str] = None,
                     data_files: Optional[list] = None,
                     parameters: Optional[dict] = None,
                     max_events: Optional[int] = None,
                     timeout_s: int = 900) -> dict:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        nts = out / "nts.fake.root"
        nts.write_text("fake\n")
        inputs = data_files if data_files is not None else [data_file]
        return {"status": "success", "files": [str(nts)],
                "message": f"{analysis} over {len(inputs)} file(s)",
                "metadata": {"analysis": analysis, "work_area": work_area,
                             "n_input_files": len(inputs),
                             "used_data_file": data_file is not None,
                             "timeout_s": timeout_s,
                             "s_over_sqrt_b": 4.0, "ce_abs_eff": 6.7e-4,
                             "sensitivity": 4.0}}

    return server


if __name__ == "__main__":
    make_server().run("stdio")
