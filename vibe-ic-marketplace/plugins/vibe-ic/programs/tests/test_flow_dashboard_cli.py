"""tests/test_flow_dashboard_cli.py — pure-render tests for the flow dashboard.

No docker, no provider. We feed render_frame() a hand-built dict conforming
to the flow_dashboard_data.collect() contract and assert the frame content
and the width invariant. collect() is never called.
"""
from __future__ import annotations

import flow_dashboard_cli as fdc


def _sample_data() -> dict:
    """A small dict conforming to the contract: 3 phases, with a done step
    that has an output, a skipped step with a detail, and a pending step."""
    return {
        "project": "/abs/proj/spm_demo",
        "project_name": "spm_demo",
        "mode": "lightweight",
        "flow_version": "v1.3.42",
        "summary": {
            "total": 6, "done": 2, "skipped": 1, "waived": 0,
            "fail": 0, "missing": 0, "running": 1, "pending": 2,
        },
        "phases": [
            {
                "key": "phase1", "label": "Phase 1 · Spec → Design Docs",
                "icon": "P1", "done": 1, "total": 2,
                "steps": [
                    {
                        "id": "1", "name": "Ingest spec into L1-L23 JSON",
                        "stage": "phase1", "status": "done",
                        "status_label": "DONE", "blocks_on": [], "gate": "",
                        "detail": "",
                        "outputs": [
                            {
                                "rel": "phase1/generated_docs/L1.json",
                                "abs": "/abs/proj/spm_demo/phase1/generated_docs/L1.json",
                                "exists": True, "size": 4096, "mtime": 1720000000.0,
                            }
                        ],
                    },
                    {
                        "id": "2", "name": "Human-readable design MD",
                        "stage": "phase1", "status": "pending",
                        "status_label": "PENDING", "blocks_on": [1], "gate": "",
                        "detail": "", "outputs": [],
                    },
                ],
            },
            {
                "key": "phase2", "label": "Phase 2 · Docs → RTL → SOF",
                "icon": "P2", "done": 1, "total": 2,
                "steps": [
                    {
                        "id": "11", "name": "DFT insertion (scan chain stitch)",
                        "stage": "stage2", "status": "skipped",
                        "status_label": "SKIPPED", "blocks_on": [10], "gate": "",
                        "detail": "no scan requested in L-docs",
                        "outputs": [
                            {
                                "rel": "phase2/stage2/dft/scan_netlist.v",
                                "abs": "/abs/proj/spm_demo/phase2/stage2/dft/scan_netlist.v",
                                "exists": False, "size": 0, "mtime": 0.0,
                            }
                        ],
                    },
                    {
                        "id": "12", "name": "RTL generation from spec",
                        "stage": "stage1", "status": "done",
                        "status_label": "DONE", "blocks_on": [], "gate": "",
                        "detail": "",
                        "outputs": [
                            {
                                "rel": "phase2/stage1/rtl/spm.v",
                                "abs": "/abs/proj/spm_demo/phase2/stage1/rtl/spm.v",
                                "exists": True, "size": 62719, "mtime": 1720000100.0,
                            },
                            {
                                "rel": "phase2/stage1/rtl/spm_chip_top.v",
                                "abs": "/abs/proj/spm_demo/phase2/stage1/rtl/spm_chip_top.v",
                                "exists": True, "size": 2048, "mtime": 1720000101.0,
                            },
                        ],
                    },
                ],
            },
            {
                "key": "phase3", "label": "Phase 3 · Synth → PnR → GDS",
                "icon": "P3", "done": 0, "total": 2,
                "steps": [
                    {
                        "id": "31", "name": "Synthesis (yosys)",
                        "stage": "phase3", "status": "running",
                        "status_label": "RUNNING", "blocks_on": [12], "gate": "",
                        "detail": "",
                        "outputs": [
                            {
                                "rel": "phase3/synth/spm_netlist.v",
                                "abs": "/abs/proj/spm_demo/phase3/synth/spm_netlist.v",
                                "exists": False, "size": 0, "mtime": 0.0,
                            }
                        ],
                    },
                    {
                        "id": "32", "name": "Place & Route (OpenROAD)",
                        "stage": "phase3", "status": "pending",
                        "status_label": "PENDING", "blocks_on": [31], "gate": "",
                        "detail": "", "outputs": [],
                    },
                ],
            },
        ],
    }


def _visible_lines(frame: str):
    return frame.split("\n")


def test_render_frame_basic_content():
    data = _sample_data()
    frame = fdc.render_frame(data, width=100, color=False)

    # Every phase label appears.
    for ph in data["phases"]:
        assert ph["label"] in frame, f"missing phase label: {ph['label']}"

    # Done step icon and its output rel-path appear.
    assert "✔" in frame
    assert "phase2/stage1/rtl/spm.v" in frame  # first existing output of the done step
    assert "phase1/generated_docs/L1.json" in frame

    # The multi-output done step shows a (+N more) marker.
    assert "+1 more" in frame

    # Skipped step's detail text appears.
    assert "no scan requested in L-docs" in frame
    assert "⏭" in frame  # skipped icon

    # Running + pending icons present.
    assert "·" in frame  # pending icon


def test_render_frame_counts_reflect_summary():
    data = _sample_data()
    frame = fdc.render_frame(data, width=120, color=False)
    s = data["summary"]
    # Overall progress "done/total".
    assert f"{s['done']}/{s['total']}" in frame
    # Counts line segments.
    assert f"done {s['done']}" in frame
    assert f"running {s['running']}" in frame
    assert f"pending {s['pending']}" in frame
    assert f"skipped {s['skipped']}" in frame
    assert f"fail {s['fail']}" in frame
    assert f"missing {s['missing']}" in frame


def test_no_line_exceeds_width():
    data = _sample_data()
    for width in (40, 60, 80, 100, 140):
        frame = fdc.render_frame(data, width=width, color=False)
        for line in _visible_lines(frame):
            assert len(line) <= width, (
                f"line exceeds width={width} (len={len(line)}): {line!r}"
            )


def test_color_true_contains_ansi_escape():
    data = _sample_data()
    frame = fdc.render_frame(data, width=100, color=True)
    assert isinstance(frame, str)
    assert "\x1b[" in frame, "expected an ANSI escape when color=True"


def test_color_false_has_no_ansi_escape():
    data = _sample_data()
    frame = fdc.render_frame(data, width=100, color=False)
    assert "\x1b[" not in frame


def test_spinner_frame_advances():
    data = _sample_data()
    f0 = fdc.render_frame(data, width=100, color=False, spinner_frame=0)
    f1 = fdc.render_frame(data, width=100, color=False, spinner_frame=1)
    # The running step uses a spinner char that advances between frames.
    assert f0 != f1


def test_render_frame_empty_and_edge_data_never_raises():
    # Completely empty dict.
    assert isinstance(fdc.render_frame({}, color=False), str)
    assert isinstance(fdc.render_frame({}, color=True), str)

    # None-ish / wrong-typed fields.
    weird = {
        "project_name": None,
        "mode": None,
        "summary": None,
        "phases": None,
    }
    assert isinstance(fdc.render_frame(weird, color=False), str)

    # A phase with zero steps and a step missing most keys.
    edge = {
        "project_name": "edge",
        "summary": {},
        "phases": [
            {"key": "phase1", "label": "Phase 1", "icon": "", "steps": []},
            {
                "key": "phase2", "label": "Phase 2", "icon": "",
                "steps": [{"id": "x"}],  # no status/name/outputs
            },
            {"key": "phase3"},  # no label/steps at all
        ],
    }
    out = fdc.render_frame(edge, width=50, color=False)
    assert isinstance(out, str)
    for line in _visible_lines(out):
        assert len(line) <= 50


def test_helpers():
    # progress_bar boundaries.
    assert fdc.progress_bar(0, 10, 10) == "[" + "░" * 10 + "]"
    assert fdc.progress_bar(10, 10, 10) == "[" + "█" * 10 + "]"
    # Not-quite-full never shows a full bar.
    b = fdc.progress_bar(9, 10, 10)
    assert b.count("█") == 9
    # total=0 -> empty bar, no div-by-zero.
    assert fdc.progress_bar(0, 0, 5) == "[" + "░" * 5 + "]"
    # Any progress shows at least one cell.
    assert fdc.progress_bar(1, 1000, 10).count("█") >= 1

    # status_style known + unknown.
    icon, codes = fdc.status_style("done")
    assert icon == "✔"
    icon2, _ = fdc.status_style("bogus")
    assert icon2 == "?"
