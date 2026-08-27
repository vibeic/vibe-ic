#!/usr/bin/env python3
r"""test_cvdp_task_router.py — FIRST-LAYER CVDP task-nature router.

Owner architecture (2026-07-05): CVDP spans five task natures; only pure-text
SPEC GENERATION (cid003) is the plugin's Phase-1 (spec→RTL) domain. completion /
functional-modification / optimization / debug are AI-led transforms of existing
RTL and must NOT be forced through Phase-1's doc extraction. The router decides
this deterministically from the dataset's own `cidNNN` label; on an unlabelled
general prompt it falls back to a structural signal + flags `needs_ai_parse`.

Run: python3 -m pytest programs/tests/test_cvdp_task_router.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmark"
_spec = importlib.util.spec_from_file_location(
    "cvdp_task_router", _BENCH / "cvdp_task_router.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["cvdp_task_router"] = R
_spec.loader.exec_module(R)


# --------------------------------------------------------------------------- #
# cid label decides deterministically; only cid003 → phase1_entry.
# --------------------------------------------------------------------------- #
def test_cid003_spec_generation_routes_to_phase1():
    v = R.classify_task_nature("Design a X.", has_context=False, cid="cid003")
    assert v["route"] == "phase1_entry"
    assert v["nature"] == "spec_generation"
    assert v["source"] == "cid_label"
    assert v["needs_ai_parse"] is False


@pytest.mark.parametrize("cid,nature", [
    ("cid002", "completion"),
    ("cid004", "functional_modification"),
    ("cid007", "optimization"),
    ("cid016", "debug"),
])
def test_non_spec_gen_cids_route_to_plugin_loop(cid, nature):
    v = R.classify_task_nature("...", has_context=True, cid=cid)
    assert v["route"] == "plugin_loop", cid
    assert v["nature"] == nature
    assert v["needs_ai_parse"] is False


# --------------------------------------------------------------------------- #
# cid normalisation (cid3 / cid03 → cid003).
# --------------------------------------------------------------------------- #
def test_cid_of_normalises_short_forms():
    assert R._cid_of({"categories": ["cid3", "medium"]}) == "cid003"
    assert R._cid_of({"categories": ["cid03"]}) == "cid003"
    assert R._cid_of({"categories": ["cid016", "easy"]}) == "cid016"
    assert R._cid_of({"categories": ["medium"]}) is None


# --------------------------------------------------------------------------- #
# Unlabelled general prompt → deterministic fallback + AI-parse flag.
# --------------------------------------------------------------------------- #
def test_general_prompt_no_context_falls_to_phase1_but_flags_ai_parse():
    v = R.classify_task_nature("Design a UART.", has_context=False, cid=None)
    assert v["route"] == "phase1_entry"
    assert v["needs_ai_parse"] is True
    assert v["source"] == "no_context_heuristic"


def test_general_prompt_with_context_falls_to_plugin_loop_and_flags_ai_parse():
    v = R.classify_task_nature("Fix this.", has_context=True, cid=None)
    assert v["route"] == "plugin_loop"
    assert v["nature"] == "transform_existing_rtl"
    assert v["needs_ai_parse"] is True


# --------------------------------------------------------------------------- #
# route_record end-to-end on record shapes.
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Every nature maps to a CONCRETE plugin entry (step or loop-of-steps), and
# every program/skill it names must actually EXIST (no fabricated entries).
# --------------------------------------------------------------------------- #
_PLUGIN = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("cid,entry", [
    ("cid003", "phase1_spec_to_rtl"),
    ("cid002", "completion_loop"),
    ("cid004", "modify_loop"),
    ("cid007", "optimize_loop"),
    ("cid016", "debug_loop"),
])
def test_each_cid_has_a_named_plugin_entry(cid, entry):
    v = R.classify_task_nature("x", has_context=True, cid=cid)
    pe = v["plugin_entry"]
    assert pe["name"] == entry
    assert pe["deterministic_first"] and pe["ai_backup"] and pe["verify"]


def test_rtl_functional_modification_does_not_route_to_physical_eco():
    """CVDP cid004 changes RTL before any released physical boundary exists."""
    pe = R.classify_task_nature(
        "change this RTL to match the new specification",
        has_context=True,
        cid="cid004",
    )["plugin_entry"]
    assert pe["ai_backup"] == ["rtl-repair"]
    assert "eco-plan" not in pe["ai_backup"]


def test_every_referenced_program_and_skill_exists():
    """The router must point ONLY at real plugin capabilities — a `.py` token
    resolves under programs/, any other token resolves under skills/<name>/."""
    for cid, t in R._CID_TASK.items():
        pe = t["plugin_entry"]
        for token in (pe["deterministic_first"] + pe["ai_backup"]
                      + pe["verify"]):
            if token.endswith(".py"):
                assert (_PLUGIN / "programs" / token).is_file(), \
                    f"{cid}: missing program {token}"
            else:
                assert (_PLUGIN / "skills" / token / "SKILL.md").is_file(), \
                    f"{cid}: missing skill {token}"


def test_no_nature_is_out_of_scope():
    # every route is either phase1_entry or plugin_loop — never a dead "ai_led".
    for cid in ("cid002", "cid003", "cid004", "cid007", "cid016"):
        v = R.classify_task_nature("x", has_context=True, cid=cid)
        assert v["route"] in ("phase1_entry", "plugin_loop")


def test_route_record_reads_cid_and_context():
    rec = {"id": "cvdp_copilot_x_0001", "categories": ["cid003", "easy"],
           "input": {"prompt": "Design.", "context": None}}
    out = R.route_record(rec)
    assert out["route"] == "phase1_entry"
    assert out["cid"] == "cid003"
    assert out["has_context"] is False

    rec2 = {"id": "cvdp_copilot_y_0002", "categories": ["cid016", "medium"],
            "input": {"prompt": "Debug.", "context": {"rtl/y.sv": "module y; endmodule"}}}
    out2 = R.route_record(rec2)
    assert out2["route"] == "plugin_loop"
    assert out2["nature"] == "debug"
    assert out2["plugin_entry"]["name"] == "debug_loop"
    assert out2["has_context"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
