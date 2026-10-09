#!/usr/bin/env python3
"""fakeanakit: a stand-in for anakit's MCP server (list_analyses,
run_analysis) for tests/test_anakit_kit.py, driven through the real
KitClient over stdio. It remembers the --musing it was started with,
answers run_analysis with canned numbers, and writes one ROOT-named file
into output_dir so the adapter has a file to report.

CATALOGUE is M. MacKenzie's list_analyses reply for the four analyses the
studies run, as of his main at 3ba8d23 (descriptions and units dropped).

No `from __future__ import annotations` here (see tests/toykit.py).
"""
import sys
from pathlib import Path
from typing import Optional


def _p(required, kind="number", minimum=None, maximum=None, default=None):
    return {"required": required, "default": default, "kind": kind,
            "minimum": minimum, "maximum": maximum}


CATALOGUE = {
    "muon_stop_rate": {
        "input_kind": "art_files", "takes_data_files": True,
        "metrics": ["n_events", "n_gen_events", "prescale",
                    "stops_per_gen_event", "stops_per_pot"],
        "parameters": {
            "prescale_filter": _p(False, "text",
                                  default="TargetStopPrescaleFilter"),
            "upstream_eff": _p(True, minimum=0.0)}},
    "edep": {
        "input_kind": "art_files", "takes_data_files": True,
        "metrics": ["n_events", "n_gen_events", "event_rate",
                    "avg_calo_edep_per_event_mev",
                    "avg_calo_edep_per_gen_event_mev",
                    "n_events_calo_edep_above_50mev",
                    "avg_trk_edep_per_event_mev",
                    "avg_trk_edep_per_gen_event_mev",
                    "n_events_selected", "selected_per_gen_event"],
        "parameters": {
            "selection": _p(False, "text",
                            default="event_calo_edep_vis > 50")}},
    "approx_ce_sensitivity": {
        "input_kind": "root_file", "takes_data_files": False,
        "metrics": ["sensitivity", "signal_box_low_mev",
                    "signal_box_high_mev", "signal_rate", "dio_background",
                    "cosmic_background", "total_background",
                    "signal_mpv_mev", "signal_fwhm_mev", "npot",
                    "cosmic_rate_per_s_per_mev"],
        "parameters": {
            "sig_eff": _p(False, minimum=0.0, maximum=1.0, default=0.0),
            "stops_per_pot": _p(False, minimum=0.0, maximum=1.0,
                                default=0.0),
            "npot": _p(False, minimum=0.0, default=1e18),
            "mean_pot_per_event": _p(False, minimum=1.0, default=1.6e7),
            "cosmic_rate_per_s_per_mev": _p(False, minimum=0.0,
                                            default=10.0 / 7.8e5),
            "selection": _p(False, "text",
                            default="event_calo_edep_vis > 10")}},
    "trigger_efficiency_ntuple": {
        "input_kind": "root_file", "takes_data_files": True,
        "metrics": ["n_events", "n_selected", "n_triggered", "efficiency",
                    "efficiency_err", "n_tracks_selected"],
        "parameters": {
            "trigger_paths": _p(True, "text"),
            "selection": _p(False, "text", default=(
                "status == 1 and pdg == 11 and downstream and p_front > 80"
                " and nactive >= 15 and chisq / ndof < 5"))}},
}


def started_with(argv):
    return argv[argv.index("--musing") + 1] if "--musing" in argv else None


def make_server():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("fakeanakit")
    musing = started_with(sys.argv)

    @server.tool()
    def list_analyses() -> dict:
        return {"status": "success", "files": [], "message": "fake",
                "metadata": {"analyses": CATALOGUE,
                             "environment": f"Musing {musing}"}}

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
        canned = {"stops_per_pot": 1.26e-3,
                  "avg_trk_edep_per_gen_event_mev": 6.58e-6,
                  "sensitivity": 1.35, "n_selected": 40.0}
        metrics = {m: canned.get(m, 1.0)
                   for m in CATALOGUE[analysis]["metrics"]}
        return {"status": "success", "files": [str(nts)],
                "message": f"{analysis} over {len(inputs)} file(s)",
                "metadata": {"analysis": analysis, "musing": musing,
                             "n_input_files": len(inputs),
                             "used_data_file": data_file is not None,
                             "timeout_s": timeout_s, **metrics}}

    return server


if __name__ == "__main__":
    make_server().run("stdio")
