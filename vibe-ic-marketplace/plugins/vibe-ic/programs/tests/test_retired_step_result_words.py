"""The Phase-3 producers keep retired words out of StepResult rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _owner_declared as owner_declared  # noqa: E402
import die_level_deck_rule_attribution as dla  # noqa: E402
import phase3_one_shot_runner as runner  # noqa: E402
import verdict  # noqa: E402


class _Pdk:
    name = "fixture"
    drc_deck = "/fixture/density.rb"
    calibre_drc = None

    def __init__(self, project):
        self.tech_lef = project / "tech.lef"
        self.cell_lef = project / "cells.lef"
        self.tech_lef.write_text("LAYER lowcut\n  TYPE CUT ;\nEND lowcut\n")
        self.cell_lef.write_text("")


def _project(tmp_path, monkeypatch, rule, *, deck_source=""):
    project = tmp_path
    pnr = runner._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    (pnr / "unit.gds").write_bytes(b"fixture gds")
    (pnr / "unit.def").write_text(
        "VERSION 5.8 ;\nDESIGN unit ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\nEND DESIGN\n")
    (project / "state_out.json").write_text(json.dumps({
        "gds": (pnr / "unit.gds").relative_to(project).as_posix(),
        "def": (pnr / "unit.def").relative_to(project).as_posix(),
    }))
    pdk = _Pdk(project)
    rdb = ("<report-database><items><item>"
           f"<category>'{rule}'</category>"
           "<values><value>polygon: (0,0;0,100;100,100;100,0)</value>"
           "</values></item></items></report-database>")

    def fake_klayout(_gds, rpt, *_args):
        rpt.write_text(rdb)
        return 0, "", ""

    monkeypatch.setattr(runner, "_klayout_deck_exec", fake_klayout)
    monkeypatch.setattr(runner, "_tool_in_path", lambda _container, tool: tool == "klayout")
    monkeypatch.setattr(
        runner, "_docker_exec",
        lambda _container, _cmd, *args, **kwargs: (0, deck_source, ""))
    return project, pdk


def _observed_drc(project, pdk):
    """Make a producer refusal an observed verdict value for the control."""
    try:
        row = runner.step_drc(project, "unit", pdk, "fixture-container")
    except verdict.UnknownVerdictWord as exc:
        return None, f"UnknownVerdictWord:{str(exc).split()[0]}"
    return row, row.status


def test_stdcell_only_drc_uses_five_word_waiver_with_named_row(
        tmp_path, monkeypatch):
    project, pdk = _project(tmp_path, monkeypatch, "lowcut.1")

    row, observed = _observed_drc(project, pdk)

    assert observed == "PASS_WITH_WAIVERS"
    assert row.extras["stdcell_library_violations"] == 1
    assert row.extras["user_routing_violations"] == 0
    assert row.waiver_rows[0]["id"] == "TAPEOUT-AUTOGEN-DRC-CELLLIB"
    assert "foundry-qualified" in row.waiver_rows[0]["reason"]


def test_die_density_attribution_keeps_declared_tier_and_handoff(
        tmp_path, monkeypatch):
    source = (f"{dla.FILE_SEP}/fixture/density.rb\n"
              "chip_area = extent.sized(0.0).area\n"
              "# Rule COV1.a: whole die density\n"
              "if layer_one.area / chip_area < 0.3\n"
              "  extent.output('COV1.a', 'density')\n"
              "end\n")
    project, pdk = _project(tmp_path, monkeypatch, "COV1.a",
                            deck_source=source)
    declaration = project / "input/submission_template/tapeout_declaration.json"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(json.dumps(owner_declared.attest({
        "schema": "vibe-ic/tapeout_declaration/1",
        "answers": {"deliverable": "HARDMACRO"},
    })))
    fill = project / dla.FILL_REPORT_REL
    fill.parent.mkdir(parents=True)
    fill.write_text(json.dumps({
        "verdict": "PARTIAL", "floor": 0.30,
        "keepout": {"measurement_bbox_um": [0, 0, 100, 100]},
        "layers": [{"name": "layer_one", "density_after": 0.2,
                    "worst_window_after": 0.2, "floor": 0.3,
                    "ceiling_any_fill": 0.32}],
    }))

    row, observed = _observed_drc(project, pdk)

    assert observed == dla.TIER_PASS_WITH_ATTRIBUTION
    assert row.extras["die_level_rule_attribution"]["drc_tier"] == (
        dla.TIER_PASS_WITH_ATTRIBUTION)
    assert row.attribution == ""
    assert row.extras["unattributed_violations"] == 0
    assert row.waiver_rows == []
    handoff = project / "phase3/stage4/hardmacro" / dla.HANDOFF_NAME
    assert handoff.is_file()
    assert json.loads(handoff.read_text())["requirements"]


def test_declared_attribution_tier_is_accepted_but_retired_word_is_refused():
    tier = dla.TIER_PASS_WITH_ATTRIBUTION
    try:
        row = runner.StepResult("drc", tier)
    except verdict.UnknownVerdictWord as exc:
        observed = f"UnknownVerdictWord:{str(exc).split()[0]}"
    else:
        observed = row.status
    assert observed == tier
    assert row.waiver_rows == []
    assert runner._aggregate_verdict([row]) == tier
    canonical = verdict.StepVerdict.from_dict({"status": tier, "name": "drc"})
    assert canonical.blocks_run_pass and not canonical.is_green
    assert verdict.is_non_green(tier)
    assert verdict.run_verdict_record([canonical])["causes"][0]["status"] == tier
    with pytest.raises(verdict.UnknownVerdictWord):
        runner.StepResult("drc", "ENV_UNAVAILABLE")


def test_user_routing_drc_violation_remains_fail(tmp_path, monkeypatch):
    project, pdk = _project(tmp_path, monkeypatch, "m2.1")

    row, observed = _observed_drc(project, pdk)

    assert observed == "FAIL"
    assert row.extras["user_routing_violations"] == 1


def test_missing_pad_ring_program_records_unmeasured_tool_absent(
        tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "PROGRAMS_DIR", tmp_path)
    try:
        row = runner.step_pad_ring_gen(tmp_path)
    except verdict.UnknownVerdictWord as exc:
        observed = f"UnknownVerdictWord:{str(exc).split()[0]}"
    else:
        observed = row.status

    assert observed == "NOT_MEASURED"
    assert row.reason_class == verdict.ReasonClass.TOOL_ABSENT.value
    assert "pad_assignment_gen.py: program absent" in row.detail
