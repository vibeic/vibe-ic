#!/usr/bin/env python3
"""Tests for phase1_input_vs_generated_completeness_check.py — Phase 1
per-prompt coverage gate.

Pins the real behavior: harvest chip-AGNOSTIC design tokens from the
Phase 1 input prompt, then verify each lands somewhere in the union of
Phase 1 output haystacks (generated_docs/L*.json, human_docs/L*.md,
facts.yaml, PROVENANCE.md). The verdict is computed from
captured_pct = captured / distinct:

    PASS  >= warn_threshold (0.80)
    WARN  >= fail_threshold (0.50), < warn
    FAIL  < fail_threshold
    SKIP_LOW_TOKENS  distinct < 10
    SKIP  no prompt / no output

The FAIL case is the real defect this gate guards: facts the user stated
in the prompt were silently dropped by the NL ingester and never landed
in any L doc.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "phase1_input_vs_generated_completeness_check.py"

_spec = importlib.util.spec_from_file_location(
    "phase1_input_vs_generated_completeness_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# fixture builders
# ----------------------------------------------------------------------
# >=10 distinct design tokens so we clear the SKIP_LOW_TOKENS floor.
_RICH_PROMPT = (
    "Registers @0x40 @0x44 @0x48 run at 100 MHz on 1.8 V. "
    "REG_CTRL STATUS ENABLE DATA[7] ADDR[3] CONFIG RESET."
)


def _make_project(tmp_path: Path, prompt: str, gen_blob: str) -> Path:
    # Canonical layout: Phase-1 artefacts nest under phase1/ (resolved
    # via _path_layout.generated_docs_dir), matching how the runner and
    # the sibling phase1_doc_input_completeness_check write/read them.
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(prompt)
    gen = mod._pl.generated_docs_dir(proj)
    gen.mkdir(parents=True)
    (gen / "L1.json").write_text(gen_blob)
    return proj


def _report(proj: Path) -> dict:
    p = proj / "reports" / "phase1_input_vs_generated_completeness.json"
    return json.loads(p.read_text())


# ----------------------------------------------------------------------
# PASS — every prompt token survived into the generated docs
# ----------------------------------------------------------------------
def test_pass_all_tokens_captured(tmp_path):
    # The generated doc literally echoes the prompt, so 100% capture.
    proj = _make_project(tmp_path, _RICH_PROMPT,
                         json.dumps({"summary": _RICH_PROMPT}))
    rc = mod.main([str(proj)])
    assert rc == 0
    rep = _report(proj)
    assert rep["verdict"] == "PASS"
    assert rep["captured_pct"] == 1.0
    assert rep["distinct_tokens"] >= mod._MIN_TOKENS
    assert rep["missing"] == 0


# ----------------------------------------------------------------------
# FAIL — the real defect: stated facts dropped, none land in any L doc.
# ----------------------------------------------------------------------
def test_fail_tokens_dropped(tmp_path):
    proj = _make_project(tmp_path, _RICH_PROMPT,
                         json.dumps({"x": "unrelated content, no overlap"}))
    rc = mod.main([str(proj)])
    assert rc == 1
    rep = _report(proj)
    assert rep["verdict"] == "FAIL"
    assert rep["captured_pct"] < mod._DEFAULT_FAIL_PCT
    # The missing sample names the dropped facts.
    assert rep["missing"] >= mod._MIN_TOKENS
    assert rep["missing_sample"], "FAIL must surface the dropped tokens"


# ----------------------------------------------------------------------
# WARN band — between fail and warn thresholds returns rc 0 but WARN.
# ----------------------------------------------------------------------
def test_warn_partial_capture(tmp_path):
    # Echo enough tokens to clear the 50% FAIL floor but stay under the
    # 80% PASS bar -> WARN band (rc 0, but verdict WARN).
    partial = "Registers @0x40 @0x44 @0x48 run at 100 MHz REG_CTRL STATUS ENABLE"
    proj = _make_project(tmp_path, _RICH_PROMPT,
                         json.dumps({"partial": partial}))
    rc = mod.main([str(proj)])
    assert rc == 0
    rep = _report(proj)
    assert rep["verdict"] == "WARN"
    assert mod._DEFAULT_FAIL_PCT <= rep["captured_pct"] < mod._DEFAULT_WARN_PCT
    # pct must be derived from real counts, never self-asserted.
    assert rep["captured_pct"] == round(
        rep["captured"] / rep["distinct_tokens"], 4)


# ----------------------------------------------------------------------
# SKIP_LOW_TOKENS — under the signal floor never produces a verdict.
# ----------------------------------------------------------------------
def test_skip_low_tokens(tmp_path):
    proj = _make_project(tmp_path, "tiny @0x40 prompt",
                         json.dumps({"x": "tiny @0x40 prompt"}))
    rc = mod.main([str(proj)])
    assert rc == 0
    rep = _report(proj)
    assert rep["verdict"] == "SKIP_LOW_TOKENS"
    assert rep["distinct_tokens"] < mod._MIN_TOKENS


# ----------------------------------------------------------------------
# SKIP — no generated output yet (Phase 1 not run).
# ----------------------------------------------------------------------
def test_skip_no_generated_output(tmp_path):
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "prompt.md").write_text(_RICH_PROMPT)
    rc = mod.main([str(proj)])
    assert rc == 0  # honest SKIP, not a vacuous PASS


# ----------------------------------------------------------------------
# SKIP — no discoverable prompt.
# ----------------------------------------------------------------------
def test_skip_no_prompt(tmp_path):
    proj = tmp_path / "proj"
    gen = mod._pl.generated_docs_dir(proj)
    gen.mkdir(parents=True)
    (gen / "L1.json").write_text("{}")
    rc = mod.main([str(proj)])
    assert rc == 0


# ----------------------------------------------------------------------
# Input error — project dir missing -> rc 2 (never silently PASS).
# ----------------------------------------------------------------------
def test_error_missing_project_dir(tmp_path):
    rc = mod.main([str(tmp_path / "does_not_exist")])
    assert rc == 2


def test_error_no_args():
    assert mod.main([]) == 2


# ----------------------------------------------------------------------
# token harvester unit behavior — reference sections + URL slugs dropped
# ----------------------------------------------------------------------
def test_harvest_drops_reference_section_acronyms(tmp_path):
    text = (
        "The CTRL_REG drives DATA_BUS.\n"
        "## References\n"
        "See TVLSI and PATMOS proceedings.\n"
    )
    clean, _dirty = mod._harvest_tokens(text)
    # Design tokens before the references heading survive...
    assert any("CTRL_REG" == t or "DATA_BUS" == t for t in clean)
    # ...but academic-venue acronyms inside References are stripped.
    assert "TVLSI" not in clean
    assert "PATMOS" not in clean


def test_harvest_drops_url_slug(tmp_path):
    text = "See [contribute](CONTRIBUTING.md) and CTRL_REG matters."
    clean, _dirty = mod._harvest_tokens(text)
    assert "CONTRIBUTING" not in clean
    assert "CTRL_REG" in clean
