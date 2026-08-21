#!/usr/bin/env python3
"""Smoke tests for l16_compliance_properties_actionable_check (layergate-6).

NEGATIVE CONTROL IS THE POINT. Every rail is asserted in BOTH directions:
a deliberately-gutted layer must FAIL and a well-formed layer must PASS on the
SAME rail. A test that can only pass proves nothing — that is exactly how a
dead read (`L16_COMPLIANCE.json`, a filename present in zero real runs) sat
undetected behind a green test for six plugin versions.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied
and no design/PDK/vendor name appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l16_compliance_properties_actionable_check.py")


def _run(project: Path, programs_dir: Path | None = None,
         *extra: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(project)]
    if programs_dir is not None:
        cmd += ["--programs-dir", str(programs_dir)]
    cmd += list(extra)
    return subprocess.run(cmd, capture_output=True, text=True)


def _cats(cp: subprocess.CompletedProcess) -> set[str]:
    return {f["category"] for f in json.loads(cp.stdout)["findings"]}


# ---------------------------------------------------------------------------
# Fixture builders — synthesized, neutral
# ---------------------------------------------------------------------------
def _mk_project(tmp: Path, l16: dict, *,
                l16_name: str = "L16_COMPLIANCE_PROPERTIES.json") -> Path:
    """A neutral design: 4 declared ports, one register, one clock domain."""
    proj = tmp / "run"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "widget_top",
        "ports": [
            {"name": "core_clk", "direction": "input", "width": 1},
            {"name": "core_rst_n", "direction": "input", "width": 1},
            {"name": "load_enable", "direction": "input", "width": 1},
            {"name": "result_valid", "direction": "output", "width": 1},
        ],
        "clock_domains": [{"name": "core_clk"}],
    }))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "registers": [{"name": "ctrl_mode"}, {"name": "status_flags"}]}))
    (gd / l16_name).write_text(json.dumps(l16))
    return proj


def _mk_programs_dir(tmp: Path, opens: str) -> Path:
    """A stand-in consumer program that opens exactly one L16 filename."""
    pdir = tmp / "programs_stub"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "professional_tb_gen.py").write_text(
        "from pathlib import Path\n"
        "def build_assertions(gd):\n"
        f"    return (gd / {opens!r}).read_text()\n")
    return pdir


_GOOD_PROPS = {
    "extraction_status": "EXTRACTED",
    "extraction_evidence": [{"line": 12, "quote": "…"}],
    "fields": {"properties": [
        # (a) explicit signal anchor that resolves in the design's own docs
        {"id": "p_valid_stable", "english_form":
         "the valid flag stays asserted until the transfer completes",
         "signals": ["result_valid"]},
        # (b) spec reference to a normative clause
        {"id": "p_reset_quiet", "english_form":
         "outputs are quiet while reset is asserted",
         "citation": "B4.1.2"},
        # (c) prose identifier that resolves in the design's own docs
        {"id": "p_load", "english_form":
         "load_enable shall be sampled on the rising edge"},
    ]},
}

# The SAME shape the Phase-1 extractor emits: the only "anchor" is the modal
# verb, and no token binds to anything the design declares.
_GUTTED_PROPS = {
    "extraction_status": "EXTRACTED",
    "fields": {"properties": [
        {"anchor_token": "must", "line": 735, "scope": "general",
         "english_form": "The toolchain must be built with the "
                         "commitlog option enabled."},
        {"anchor_token": "shall", "line": 864, "scope": "general",
         "english_form": "Integrators shall consult the release notes."},
    ]},
}


# ---------------------------------------------------------------------------
# RAIL 1 — consumer reachability. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_dead_read_when_consumer_opens_absent_filename(tmp_path):
    """GUTTED: consumer opens a name that exists in no run => FAIL."""
    proj = _mk_project(tmp_path, _GOOD_PROPS)
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE.json")
    r = _run(proj, pdir)
    assert r.returncode == 1, r.stdout
    assert "CONSUMER_DEAD_READ" in _cats(r)


def test_POSITIVE_no_dead_read_when_consumer_opens_the_real_filename(tmp_path):
    """WELL-FORMED: same layer, consumer opens the on-disk name => PASS."""
    proj = _mk_project(tmp_path, _GOOD_PROPS)
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE_PROPERTIES.json")
    r = _run(proj, pdir)
    assert r.returncode == 0, r.stdout
    assert "CONSUMER_DEAD_READ" not in _cats(r)


def test_POSITIVE_fallback_chain_is_not_a_dead_read(tmp_path):
    """A consumer with several literals, one of which resolves, is reachable."""
    proj = _mk_project(tmp_path, _GOOD_PROPS)
    pdir = tmp_path / "programs_stub2"
    pdir.mkdir()
    (pdir / "professional_tb_gen.py").write_text(
        "NAMES = ('L16_COMPLIANCE_PROPERTIES.json', 'L16_COMPLIANCE.json')\n")
    r = _run(proj, pdir)
    assert r.returncode == 0, r.stdout
    assert "CONSUMER_DEAD_READ" not in _cats(r)
    assert "CONSUMER_STALE_FILENAME_FALLBACK" in _cats(r)


def test_the_real_shipped_consumers_can_reach_l16(tmp_path):
    """Regression lock: the ACTUAL programs/ directory must not dead-read.

    This is the test that would have caught the six-version-old defect."""
    proj = _mk_project(tmp_path, _GOOD_PROPS)
    r = _run(proj)                      # default --programs-dir = programs/
    assert "CONSUMER_DEAD_READ" not in _cats(r), r.stdout


# ---------------------------------------------------------------------------
# RAIL 2 — actionability. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_no_actionable_property(tmp_path):
    """GUTTED: modal-verb 'anchors' only, nothing binds => FAIL."""
    proj = _mk_project(tmp_path, _GUTTED_PROPS)
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE_PROPERTIES.json")
    r = _run(proj, pdir)
    assert r.returncode == 1, r.stdout
    assert "NO_ACTIONABLE_PROPERTY_IN_CONSUMER_WINDOW" in _cats(r)


def test_POSITIVE_well_formed_properties_pass(tmp_path):
    """WELL-FORMED: anchor / citation / resolvable prose => PASS."""
    proj = _mk_project(tmp_path, _GOOD_PROPS)
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE_PROPERTIES.json")
    r = _run(proj, pdir)
    assert r.returncode == 0, r.stdout
    rep = json.loads(r.stdout)
    assert rep["info"]["actionable_ratio"] == 1.0
    assert rep["summary"]["error_count"] == 0


def test_anchor_token_alone_is_never_an_anchor(tmp_path):
    """The extractor's `anchor_token` is the modal verb — it binds nothing."""
    l16 = {"extraction_status": "EXTRACTED", "fields": {"properties": [
        {"anchor_token": "must", "english_form": "It must be so.",
         "scope": "general", "line": 1}]}}
    proj = _mk_project(tmp_path, l16)
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE_PROPERTIES.json")
    r = _run(proj, pdir)
    assert r.returncode == 1
    props = json.loads(r.stdout)["info"]["properties"]
    assert props[0]["actionable"] is False
    assert props[0]["how"] == "only_modal_anchor_token"


# ---------------------------------------------------------------------------
# Status-vs-payload. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_status_claims_success_with_empty_payload(tmp_path):
    proj = _mk_project(tmp_path, {"extraction_status": "EXTRACTED",
                                  "fields": {"properties": []}})
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE_PROPERTIES.json")
    r = _run(proj, pdir)
    assert r.returncode == 1, r.stdout
    assert "STATUS_CONTRADICTS_PAYLOAD" in _cats(r)


def test_POSITIVE_honest_empty_passes(tmp_path):
    """An empty layer that SAYS it is empty is truthful and must PASS.

    Without this the gate would punish honesty and push producers toward
    inventing filler — the failure mode it exists to stop."""
    proj = _mk_project(tmp_path,
                       {"extraction_status": "EXTRACTION_FOUND_NOTHING",
                        "fields": {"properties": []}})
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE_PROPERTIES.json")
    r = _run(proj, pdir)
    assert r.returncode == 0, r.stdout
    assert "HONEST_EMPTY" in _cats(r)


# ---------------------------------------------------------------------------
# Modes and applicability
# ---------------------------------------------------------------------------
def test_advisory_flag_downgrades_a_real_failure(tmp_path):
    proj = _mk_project(tmp_path, _GUTTED_PROPS)
    pdir = _mk_programs_dir(tmp_path, "L16_COMPLIANCE.json")
    blocking = _run(proj, pdir)
    advisory = _run(proj, pdir, "--advisory")
    assert blocking.returncode == 1
    assert advisory.returncode == 0
    assert _cats(blocking) == _cats(advisory)   # same findings, different exit


def test_skips_cleanly_when_layer_absent(tmp_path):
    proj = tmp_path / "empty"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    assert _run(proj).returncode == 2


def test_no_design_or_vendor_literal_in_the_gate():
    """Generality lock: the gate must derive, never recognise."""
    src = PROG.read_text()
    body = src.split('"""', 2)[-1]          # skip the module docstring
    banned = ("sky130", "gf180", "ihp-sg13", "nangate", "ibex", "AXI",
              "ARVALID", "ACLK", "VDD", "VSS", "spm", "subservient")
    for tok in banned:
        assert tok not in body, f"design/PDK literal {tok!r} leaked into gate"
