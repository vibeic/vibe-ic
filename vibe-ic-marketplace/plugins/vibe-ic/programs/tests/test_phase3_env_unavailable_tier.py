"""tests/test_phase3_env_unavailable_tier.py — v1.6.54

Verdict-tier split: ENV_UNAVAILABLE (tool absent in this environment)
vs WAIVED (design has not been verified — defer with waiver). Both
aggregate to PASS_WITH_WAIVERS, but the report rolls them up
separately so an audit can tell env-fixable from design-fixable
gaps at a glance."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from programs.phase3_one_shot_runner import (
    StepResult, _aggregate_verdict, _autogen_waivers_json,
    _tool_in_path, step_drc, step_lvs,
)


# ---------------------------------------------------------------------------
# verdict aggregation: ENV_UNAVAILABLE behaves like WAIVED.
# ---------------------------------------------------------------------------

def test_aggregate_verdict_env_unavailable_is_pass_with_waivers() -> None:
    plan = [
        StepResult("synth", "PASS"),
        StepResult("pnr", "PASS"),
        StepResult("gds", "PASS"),
        StepResult("drc", "ENV_UNAVAILABLE", detail="calibre missing"),
    ]
    assert _aggregate_verdict(plan) == "PASS_WITH_WAIVERS"


def test_aggregate_verdict_mixed_waived_and_env_unavailable() -> None:
    plan = [
        StepResult("synth", "PASS"),
        StepResult("drc", "ENV_UNAVAILABLE"),
        StepResult("lvs", "WAIVED"),
    ]
    assert _aggregate_verdict(plan) == "PASS_WITH_WAIVERS"


def test_aggregate_verdict_fail_dominates_env_unavailable() -> None:
    plan = [
        StepResult("synth", "FAIL"),
        StepResult("drc", "ENV_UNAVAILABLE"),
    ]
    assert _aggregate_verdict(plan) == "FAIL"


def test_aggregate_verdict_all_pass_no_env() -> None:
    plan = [
        StepResult("synth", "PASS"),
        StepResult("drc", "PASS"),
        StepResult("lvs", "PASS"),
    ]
    assert _aggregate_verdict(plan) == "PASS"


# ---------------------------------------------------------------------------
# _tool_in_path: integration smoke test using a real common tool.
# ---------------------------------------------------------------------------

def test_tool_in_path_for_common_binary() -> None:
    # `bash` is virtually guaranteed to exist; the helper should
    # return True when invoked with empty container (delegates to
    # `docker exec ""` — but actually for empty container it errors;
    # so we just patch _docker_exec to return rc=0).
    with patch(
        "programs.phase3_one_shot_runner._docker_exec",
        return_value=(0, "/bin/bash", ""),
    ):
        assert _tool_in_path("test-container", "bash") is True


def test_tool_in_path_returns_false_for_missing_binary() -> None:
    with patch(
        "programs.phase3_one_shot_runner._docker_exec",
        return_value=(1, "", "command not found"),
    ):
        assert _tool_in_path("test-container", "ghost-tool-xyz") is False


# ---------------------------------------------------------------------------
# step_drc / step_lvs: env-vs-design verdict split.
# ---------------------------------------------------------------------------

class _FakePdkConfig:
    """Minimal stand-in for PdkConfig to bypass _detect_pdk."""
    def __init__(self, drc_deck=None, calibre_drc=None,
                 calibre_lvs=None, calibre_lvs_device=None,
                 macro_gds=None, macro_v=None, name="test",
                 bridge_magicrc=None, bridge_netgen_setup=None):
        self.drc_deck = drc_deck
        self.calibre_drc = calibre_drc
        self.calibre_lvs = calibre_lvs
        self.calibre_lvs_device = calibre_lvs_device
        self.macro_gds = macro_gds
        self.macro_v = macro_v
        self.name = name
        # v1.3.83 step_lvs consults the PDK-bridge OSS-LVS tech before
        # dead-ending on a missing calibre binary; the fake must carry these
        # (default None = no bridge) or the attribute access raises.
        self.bridge_magicrc = bridge_magicrc
        self.bridge_netgen_setup = bridge_netgen_setup


def test_step_drc_env_unavailable_when_calibre_deck_present_but_binary_absent(
        tmp_path: Path) -> None:
    # 2026-07-12: step_drc first tries the native `svrfdrc` buddy (runs the
    # Calibre .rule deck license-free). Only when BOTH `calibre` AND the
    # svrfdrc buddy are absent does it emit ENV_UNAVAILABLE — and the
    # missing_tool names both.
    pdk = _FakePdkConfig(
        drc_deck=None,
        calibre_drc="/path/to/calibre_drc.rule")
    with patch(
        "programs.phase3_one_shot_runner._tool_in_path",
        return_value=False,
    ), patch(
        "programs.phase3_one_shot_runner._svrfdrc_bin_container",
        return_value=None,
    ):
        res = step_drc(tmp_path, "top", pdk, "test-container")
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras.get("missing_tool") == "calibre|svrfdrc"
    assert "ENV gap" in res.detail


def test_step_drc_waived_when_calibre_binary_present_but_svrf_engine_absent(
        tmp_path: Path) -> None:
    # 2026-07-12: sign-off DRC PREFERS the native `svrfdrc` buddy (runs the real
    # Calibre deck license-free). WAIVED (defer to offline `calibre`) now happens
    # ONLY when the buddy is unavailable while the `calibre` binary IS present.
    # Mock the buddy absent so the probe is deterministic (no real docker exec).
    pdk = _FakePdkConfig(
        drc_deck=None,
        calibre_drc="/path/to/calibre_drc.rule")
    with patch(
        "programs.phase3_one_shot_runner._tool_in_path",
        return_value=True,
    ), patch(
        "programs.phase3_one_shot_runner._svrfdrc_bin_container",
        return_value=None,
    ):
        res = step_drc(tmp_path, "top", pdk, "test-container")
    assert res.status == "WAIVED"
    assert "missing_tool" not in (res.extras or {})


def test_step_drc_env_unavailable_when_klayout_deck_but_no_binary(
        tmp_path: Path) -> None:
    """KLayout deck found but klayout not in PATH."""
    pdk = _FakePdkConfig(drc_deck="/path/to/rules.lydrc")
    # Need a GDS file to get past the SKIP-on-missing-GDS branch.
    gds_dir = tmp_path / "phase3" / "stage3" / "pnr"
    gds_dir.mkdir(parents=True, exist_ok=True)
    (gds_dir / "top.gds").write_text("dummy")
    with patch(
        "programs.phase3_one_shot_runner._tool_in_path",
        side_effect=lambda c, t: False if t == "klayout" else True,
    ):
        res = step_drc(tmp_path, "top", pdk, "test-container")
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras.get("missing_tool") == "klayout"


def test_step_lvs_env_unavailable_when_calibre_lvs_no_binary(
        tmp_path: Path) -> None:
    pdk = _FakePdkConfig(calibre_lvs="/path/to/calibre_lvs.rule")
    with patch(
        "programs.phase3_one_shot_runner._tool_in_path",
        return_value=False,
    ):
        res = step_lvs(tmp_path, "top", pdk, "test-container")
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras.get("missing_tool") == "calibre"


def test_step_lvs_env_unavailable_when_no_deck_and_no_tools(
        tmp_path: Path) -> None:
    # #443: the open-source LVS path needs magic + netgen; both absent
    # → ENV_UNAVAILABLE naming the gap.
    pdk = _FakePdkConfig()  # no calibre_lvs
    with patch(
        "programs.phase3_one_shot_runner._tool_in_path",
        return_value=False,
    ):
        res = step_lvs(tmp_path, "top", pdk, "test-container")
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras.get("missing_tool") == "magic,netgen"


def test_step_lvs_waived_only_for_missing_inputs_not_unconditionally(
        tmp_path: Path) -> None:
    # #443: tools + PDK tech present but NO GDS/netlist yet → WAIVED
    # naming the missing INPUT (the old unconditional "deferred to
    # dedicated extraction flow" auto-waive is retired).
    pdk = _FakePdkConfig()
    with patch(
        "programs.phase3_one_shot_runner._tool_in_path",
        return_value=True,
    ), patch(
        "programs.phase3_one_shot_runner._docker_exec",
        return_value=(0, "", ""),
    ):
        res = step_lvs(tmp_path, "top", pdk, "test-container")
    assert res.status == "WAIVED"
    assert "LVS inputs missing" in res.detail


# ---------------------------------------------------------------------------
# _autogen_waivers_json: ENV_UNAVAILABLE steps emit waiver entries with
# verdict_tier + missing_tool ticket.
# ---------------------------------------------------------------------------

def test_autogen_waivers_includes_env_unavailable_steps(
        tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    plan = [
        StepResult("synth", "PASS"),
        StepResult("drc", "ENV_UNAVAILABLE",
                   detail="calibre missing in env",
                   extras={"missing_tool": "calibre",
                           "calibre_drc_deck": "/x.rule"}),
        StepResult("lvs", "WAIVED",
                   detail="design defer; needs extraction",
                   extras={"extracted_netlist": "phase3/x.spice"}),
    ]
    _autogen_waivers_json(p, plan)
    waivers_file = p / "waivers.json"
    assert waivers_file.exists()
    data = json.loads(waivers_file.read_text())
    waivers = data["waivers"]
    assert len(waivers) == 2
    by_step = {w["step"]: w for w in waivers}
    assert by_step["drc"]["verdict_tier"] == "ENV_UNAVAILABLE"
    assert by_step["lvs"]["verdict_tier"] == "WAIVED"
    # ENV_UNAVAILABLE ticket cites the missing tool.
    assert "CALIBRE" in by_step["drc"]["ticket"]
    # ENV_UNAVAILABLE rationale flags ENV gap.
    assert "ENV gap" in by_step["drc"]["rationale"]
    # Reviewer action for ENV_UNAVAILABLE points at install + re-run.
    assert "install" in by_step["drc"]["reviewer_action"].lower()
    assert "re-run" in by_step["drc"]["reviewer_action"].lower()


def test_autogen_waivers_skipped_when_no_waiver_class_steps(
        tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    plan = [StepResult("synth", "PASS"), StepResult("pnr", "PASS")]
    _autogen_waivers_json(p, plan)
    assert not (p / "waivers.json").exists()


def test_autogen_waivers_respects_existing_human_authored_file(
        tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    (p / "waivers.json").write_text('{"_human_authored": true}')
    plan = [StepResult("drc", "ENV_UNAVAILABLE",
                       extras={"missing_tool": "calibre"})]
    _autogen_waivers_json(p, plan)
    # File was not overwritten.
    data = json.loads((p / "waivers.json").read_text())
    assert data == {"_human_authored": True}
