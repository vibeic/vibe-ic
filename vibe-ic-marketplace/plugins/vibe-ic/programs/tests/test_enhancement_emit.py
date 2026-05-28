"""Unit tests for enhancement_emit.py — the driver of the
benchmark-enhancement-capture closed loop (v0.1.35).

Eight cases cover the four-bucket routing + per-step target resolution:
  1. Bucket A is routed to the program file declared in CAPTURE_ROUTING.json
  2. Bucket B is routed to the skill file declared in CAPTURE_ROUTING.json
  3. Bucket C emits a YAML backlog with the expected ORGANIC- prefix + schema fields
  4. Bucket D emits a discard log (never silently drops)
  5. Same-bucket records targeting DIFFERENT steps land in DIFFERENT output files
  6. Same-bucket records targeting the SAME step are concatenated into ONE file
  7. Unknown step IDs fall back to the default_routing.bucket_B_skill_file
  8. Summary JSON records every target file touched for review
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "enhancement_emit.py"
ROUTING = Path(__file__).parent.parent.parent / "benchmark-harness" / "CAPTURE_ROUTING.json"
assert SCRIPT.exists(), f"missing program: {SCRIPT}"
assert ROUTING.exists(), f"missing routing table: {ROUTING}"


def run(tmp_path: Path, records: list) -> dict:
    rec_file = tmp_path / "recoveries.json"
    rec_file.write_text(json.dumps(records))
    out_dir = tmp_path / "candidates"
    r = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--records", str(rec_file),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"emit failed: {r.stderr}\n{r.stdout}"
    summary = json.loads((out_dir / "summary.json").read_text())
    return {"out_dir": out_dir, "summary": summary}


# ── 1. Bucket A routes to the program file declared in the routing table ──
def test_bucket_A_routes_per_step(tmp_path):
    rec = [{
        "step": "phase2.rtl_gen",
        "design": "div_16bit", "bucket": "A",
        "rule_name": "restoring-div-remainder-width",
        "docstring": "Restoring division remainder needs dividend_width + 1 bits.",
        "expected_signal": "WARN", "fix_action": "Widen remainder reg",
    }]
    res = run(tmp_path, rec)
    # routing for phase2.rtl_gen → programs/rtl_hygiene_lint.py
    a_files = res["summary"].get("bucket_A_files", [])
    assert any("rtl_hygiene_lint" in f for f in a_files), \
        f"phase2.rtl_gen Bucket A should route to rtl_hygiene_lint; got {a_files}"


# ── 2. Bucket B routes to the skill file declared in the routing table ──
def test_bucket_B_routes_per_step(tmp_path):
    rec = [{
        "step": "phase3.pnr_setup_repair",
        "design": "sha256", "bucket": "B",
        "skill_title": "PnR setup repair pattern",
        "pattern": "PnR must run repair_design + repair_timing -setup, not just hold-fix.",
        "when": "any OpenROAD PnR template",
        "what": "add the repair chain", "example": "sha256 -102 → +10 ns",
        "generality": "universal across OpenROAD-driven PnR",
    }]
    res = run(tmp_path, rec)
    # routing for phase3.pnr_setup_repair → skills/sta-review/SKILL.md
    b_files = res["summary"].get("bucket_B_files", [])
    assert b_files, "Bucket B file not emitted"
    targets = {entry["target"] for entry in b_files}
    assert "skills/sta-review/SKILL.md" in targets, \
        f"phase3.pnr_setup_repair Bucket B should route to sta-review; got {targets}"


# ── 3. Bucket C emits YAML with ORGANIC- prefix + required schema fields ──
def test_bucket_C_emits_backlog_yaml(tmp_path):
    rec = [{
        "step": "analog.A4_corner_sweep",
        "design": "u_hawaii_adc", "bucket": "C",
        "title": "Add converter-family templates",
        "pattern": "no ngspice template for adc / delta_sigma",
        "suggested_fix": "ship templates",
        "backlog_slug": "a4-converter-template",
        "backlog_type": "enhancement", "severity": "P1",
        "component": "program:analog_real_corner_sweep",
        "session_context": "captured from u_hawaii_adc rerun",
    }]
    res = run(tmp_path, rec)
    files = res["summary"].get("bucket_C_files", [])
    assert files and files[0].startswith("ORGANIC-"), \
        f"Bucket C should emit ORGANIC-prefixed yaml; got {files}"
    yaml_text = (Path(res["summary"]["bucket_C_dir"]) / files[0]).read_text()
    for required in ("type:", "severity:", "component:", "title:", "pattern:",
                     "suggested_fix:", "id:", "submitted_at:"):
        assert required in yaml_text, f"backlog yaml missing field: {required}"


# ── 4. Bucket D produces a discard log (no silent drops) ──
def test_bucket_D_records_discard(tmp_path):
    rec = [{
        "step": "phase2.rtl_gen",
        "design": "ProbXX_only", "bucket": "D",
        "why_discard": "encodes the specific hidden TB convention; pure overfit.",
    }]
    res = run(tmp_path, rec)
    d_file = res["summary"].get("bucket_D_file")
    assert d_file, "Bucket D file must be emitted"
    body = Path(d_file).read_text()
    assert "ProbXX_only" in body and "overfit" in body, \
        "Bucket D log must record the discard reason for honesty"


# ── 5. Same-bucket DIFFERENT-step records land in DIFFERENT output files ──
def test_same_bucket_different_steps_split(tmp_path):
    rec = [
        {"step": "phase3.pnr_setup_repair", "design": "sha256", "bucket": "B",
         "skill_title": "PnR repair", "pattern": "x", "when": "y",
         "what": "z", "example": "e", "generality": "g"},
        {"step": "analog.A2_topology", "design": "u_hawaii_adc", "bucket": "B",
         "skill_title": "ΔΣ topology", "pattern": "x", "when": "y",
         "what": "z", "example": "e", "generality": "g"},
    ]
    res = run(tmp_path, rec)
    targets = {e["target"] for e in res["summary"]["bucket_B_files"]}
    assert "skills/sta-review/SKILL.md" in targets, "phase3 route lost"
    assert "skills/analog-topology-select/SKILL.md" in targets, "analog route lost"
    assert len(targets) >= 2, f"different steps must land in different files; got {targets}"


# ── 6. Same-bucket SAME-step records concatenate into ONE output file ──
def test_same_bucket_same_step_concatenate(tmp_path):
    rec = [
        {"step": "phase2.rtl_gen", "design": "A", "bucket": "B",
         "skill_title": "Skill A", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "phase2.rtl_gen", "design": "B", "bucket": "B",
         "skill_title": "Skill B", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
    ]
    res = run(tmp_path, rec)
    b_files = res["summary"]["bucket_B_files"]
    assert len(b_files) == 1, \
        f"two B records on same step should yield 1 file; got {len(b_files)}"
    body = Path(b_files[0]["patch"]).read_text()
    assert "Skill A" in body and "Skill B" in body, \
        "both records must be in the single per-step file"


# ── 7. Unknown step ID falls back to default_routing.bucket_B_skill_file ──
def test_unknown_step_falls_back_to_default(tmp_path):
    rec = [{
        "step": "made.up.step", "design": "X", "bucket": "B",
        "skill_title": "Default fallback test", "pattern": "p", "when": "w",
        "what": "x", "example": "e", "generality": "g",
    }]
    res = run(tmp_path, rec)
    targets = {e["target"] for e in res["summary"]["bucket_B_files"]}
    routing = json.loads(ROUTING.read_text())
    default_skill = routing["default_routing"]["bucket_B_skill_file"]
    assert default_skill in targets, \
        f"unknown step should fall back to {default_skill}; got {targets}"


# ── 8. Summary records every target file the session would touch (audit trail) ──
def test_summary_records_routing_used(tmp_path):
    rec = [
        {"step": "phase3.pnr_setup_repair", "design": "sha256", "bucket": "B",
         "skill_title": "X", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
        {"step": "phase3.drc", "design": "sha256", "bucket": "B",
         "skill_title": "Y", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g"},
    ]
    res = run(tmp_path, rec)
    routing_used = res["summary"].get("routing_used", {})
    used_B = set(routing_used.get("bucket_B", []))
    assert {"skills/sta-review/SKILL.md", "skills/drc-fix/SKILL.md"} <= used_B, \
        f"summary must list every touched skill file; got {used_B}"


# ── v0.1.39 audit Finding 1 tests — honesty enforcement ──────────────────────
import importlib.util
_emit_spec = importlib.util.spec_from_file_location("enhancement_emit", str(SCRIPT))
_emit_mod = importlib.util.module_from_spec(_emit_spec)
_emit_spec.loader.exec_module(_emit_mod)


def test_emit_skill_section_refuses_missing_skill_title():
    """Audit Finding 1: caller MUST supply a generic skill_title — never default
    to a benchmark design slug (the honesty-rule violation that polluted
    ic-expert-agent.md through v0.1.38)."""
    rec = {"design": "Prob089_ece241_2014_q5a",
           "pattern": "p", "when": "w", "what": "x", "example": "e",
           "generality": "g"}
    with pytest.raises(ValueError, match="skill_title"):
        _emit_mod.emit_skill_section(rec)


def test_emit_backlog_refuses_missing_backlog_slug():
    """Audit Finding 1: backlog filenames are permanent record; never default
    to a Prob ID slug."""
    rec = {"design": "Prob089", "title": "x", "pattern": "y",
           "suggested_fix": "z"}
    with pytest.raises(ValueError, match="backlog_slug"):
        _emit_mod.emit_backlog(rec, "2026-05-28")


def test_scrub_design_leak_removes_prob_ids():
    """Audit Finding 1: enumerated benchmark-identifier tokens are scrubbed
    from free-text fields no matter where they appear."""
    s = _emit_mod._scrub_design_leak(
        "RTLLM benchmarks use rst_n. See VerilogEval Prob089 for example.")
    assert "Prob089" not in s
    assert "RTLLM" not in s
    assert "VerilogEval" not in s
    assert "[identifiers anonymized" in s


def test_scrub_design_leak_removes_from_parentheticals():
    """Audit Finding 1: design leaf names like `radix2_div` aren't in any
    enumeration. v0.1.40 (re-audit NEW-4) narrowed the bracket-strip to
    require the bracket interior to look like an identifier list — so
    `(from <snake_case_id>)` is killed but legitimate technical brackets
    are preserved (verified in the next test)."""
    s = _emit_mod._scrub_design_leak("A divider design (from radix2_div): fix.")
    assert "radix2_div" not in s, f"radix2_div should be scrubbed, got: {s!r}"
    assert "(from radix2_div)" not in s
    assert "[identifiers anonymized" in s


def test_scrub_design_leak_preserves_legitimate_technical_brackets():
    """v0.1.40 (re-audit NEW-4 fix) — the v0.1.39 broad-strip damaged
    legitimate technical parentheticals like `(per IEEE 1364)` and
    `(e.g. mod-256)` that contain no design identifier. Confirm these are
    preserved AND no spurious anonymization marker is appended."""
    cases = [
        "A counter (e.g. mod-256) wraps at zero.",
        "Refer to (refs 1, 2) for the math.",
        "Pattern: timing-violation (per IEEE 1364).",
    ]
    for c in cases:
        s = _emit_mod._scrub_design_leak(c)
        assert s == c, f"legitimate bracket damaged: input={c!r} got={s!r}"
        assert "anonymized" not in s, f"spurious marker on clean text: {s!r}"


def test_emit_skill_section_refuses_leaky_title():
    """v0.1.40 (re-audit F1 真補洞) — a sloppy caller passing a leaky
    skill_title is exactly the failure mode the prior audit warned about.
    Refuse such input rather than silently scrub the header."""
    rec = {"skill_title": "Moore latency in Prob089 sequence_detector",
           "pattern": "p", "when": "w", "what": "x", "example": "e",
           "generality": "g"}
    with pytest.raises(ValueError, match="skill_title contains a benchmark-design identifier"):
        _emit_mod.emit_skill_section(rec)


def test_emit_backlog_refuses_leaky_slug():
    """v0.1.40 (re-audit F1 真補洞) — backlog filename + YAML id are
    permanent record; refuse on leaky slug."""
    rec = {"title": "t", "pattern": "p", "suggested_fix": "f",
           "backlog_slug": "prob042-radix2-div-remainder"}
    with pytest.raises(ValueError, match="backlog_slug contains a benchmark-design identifier"):
        _emit_mod.emit_backlog(rec, "2026-05-28")


def test_emit_skill_section_accepts_clean_title():
    """A skill_title that's already general should pass through unchanged."""
    rec = {"skill_title": "Hidden-TB parameter override forces parameter declarations",
           "pattern": "p", "when": "w", "what": "x", "example": "e",
           "generality": "g"}
    out = _emit_mod.emit_skill_section(rec)
    assert "Hidden-TB parameter override" in out
    # No spurious anonymization marker on a clean title (header line only)
    header = out.split("**Pattern**:")[0]
    assert "anonymized" not in header


def test_scrub_design_leak_idempotent_on_clean_text():
    """A skill section that's already general should pass through unchanged
    (no spurious anonymization marker)."""
    clean = ("Pattern: a divider-class design that hardcoded width parameters. "
             "When to apply: any module the description names a width parameter.")
    s = _emit_mod._scrub_design_leak(clean)
    assert s == clean, f"clean text should be unchanged; got: {s}"
    assert "anonymized" not in s
