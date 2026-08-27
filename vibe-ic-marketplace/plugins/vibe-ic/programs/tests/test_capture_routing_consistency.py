"""tests/test_capture_routing_consistency.py — v0.1.35

Integration / consistency gates for the closed-loop enhancement-capture flow.

Four cases:
  1. Every Bucket A program path declared in CAPTURE_ROUTING.json EXISTS on disk
     (or is explicitly null). Catches stale routing entries pointing at deleted
     / renamed program files.
  2. Every Bucket B skill path declared in CAPTURE_ROUTING.json EXISTS on disk.
     Catches stale routing entries pointing at deleted / renamed skill files.
  3. The fallback default_routing.bucket_B_skill_file EXISTS (so unknown-step
     fallback is always safe).
  4. End-to-end smoke: a 4-record recoveries.json (one per bucket) drives
     enhancement_emit.py to emit Bucket A + B + C + D outputs, and the per-step
     routing places Bucket B into the right target skill file.

These gates run alongside the existing tests/ integration set, so a routing
table that drifts away from the actual skill / program inventory FAILs CI
before it ships.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent.parent
ROUTING = PLUGIN_ROOT / "benchmark" / "CAPTURE_ROUTING.json"
EMIT_PROGRAM = PLUGIN_ROOT / "programs" / "enhancement_emit.py"
CAPTURE_SKILL = PLUGIN_ROOT / "skills" / "benchmark-enhancement-capture" / "SKILL.md"


def _routing() -> dict:
    return json.loads(ROUTING.read_text())


def test_capture_routing_file_present():
    """The routing table itself must exist."""
    assert ROUTING.is_file(), f"missing routing table: {ROUTING}"
    assert EMIT_PROGRAM.is_file(), f"missing emit program: {EMIT_PROGRAM}"
    assert CAPTURE_SKILL.is_file(), f"missing capture skill: {CAPTURE_SKILL}"


# ── 1. every Bucket A program path declared in routing exists on disk ──
def test_bucket_A_program_paths_exist():
    r = _routing()
    missing = []
    for step_id, cfg in r.get("steps", {}).items():
        prog = cfg.get("bucket_A_program")
        if not prog:
            continue
        # MEASURED 2026-08-27 on 40d0e14c08: BOTH exemptions that used to sit
        # here rested on a premise that is false in the shipped layout, and the
        # mcp-eda one was hiding three dead routes.
        #
        #   PLUGIN_ROOT/mcp-eda/src/index.js   -> exists
        #   PLUGIN_ROOT/tools/phase1_engine/   -> exists
        #
        # mcp-eda is NOT "a sibling package": it ships inside the plugin, so
        # PLUGIN_ROOT/<path> resolves it correctly. Skipping it meant this
        # gate - whose whole stated job is "catch stale routing entries
        # pointing at deleted / renamed program files" - was blind to exactly
        # the entries that were stale. mcp_eda.{synth,lint,cocotb} all pointed
        # at mcp-eda/src/tools/*.js, which have NEVER existed at any commit.
        #
        # The one real layout difference is an install that carries no mcp-eda
        # at all. That is handled by asking whether the ROOT DIRECTORY is
        # present rather than by exempting the path: absent -> nothing to
        # check; present -> the routed file must exist. A guard that cannot
        # fire on a broken shipped tree is not a guard.
        root = prog.split("/", 1)[0]
        if not (PLUGIN_ROOT / root).exists():
            continue
        candidate = PLUGIN_ROOT / prog
        if not candidate.is_file():
            missing.append(f"{step_id} → {prog}")
    assert not missing, (
        "Bucket A programs in CAPTURE_ROUTING.json missing on disk:\n  "
        + "\n  ".join(missing)
        + "\nFix: either add the program or null out the routing entry."
    )


# ── 2. every Bucket B skill path declared in routing exists on disk ──
def test_bucket_B_skill_paths_exist():
    r = _routing()
    missing = []
    for step_id, cfg in r.get("steps", {}).items():
        sk = cfg.get("bucket_B_skill_file")
        if not sk:
            continue
        candidate = PLUGIN_ROOT / sk
        if not candidate.is_file():
            missing.append(f"{step_id} → {sk}")
    assert not missing, (
        "Bucket B skill files in CAPTURE_ROUTING.json missing on disk:\n  "
        + "\n  ".join(missing)
        + "\nFix: either add the skill SKILL.md or update the routing entry."
    )


# ── 3. default_routing fallback skill MUST exist ──
def test_default_routing_skill_exists():
    r = _routing()
    fb = r.get("default_routing", {}).get("bucket_B_skill_file")
    assert fb, "default_routing.bucket_B_skill_file is missing"
    assert (PLUGIN_ROOT / fb).is_file(), (
        f"fallback skill {fb} declared in default_routing must exist on disk"
    )


# ── 4. end-to-end smoke: full 4-bucket emit through the program ──
def test_end_to_end_emit_smoke(tmp_path):
    recs = [
        {"step": "phase2.rtl_gen", "design": "smokeA", "bucket": "A",
         "rule_name": "smoke-rule", "docstring": "doc",
         "expected_signal": "WARN", "fix_action": "do x"},
        {"step": "phase3.pnr_setup_repair", "design": "smokeB", "bucket": "B",
         "skill_title": "Smoke B", "pattern": "p", "when": "w",
         "what": "x", "example": "e", "generality": "g", "why_not_bucket_a": "smoke: needs LLM judgment a regex cannot encode"},
        {"step": "analog.A4_corner_sweep", "design": "smokeC", "bucket": "C",
         "title": "Smoke backlog C", "pattern": "p", "suggested_fix": "f",
         "backlog_slug": "smoke-c", "backlog_type": "enhancement",
         "severity": "P3", "component": "x", "session_context": "test",
         "why_not_bucket_a": "smoke: large engineering effort, not a deterministic rule"},
        {"step": "phase2.rtl_gen", "design": "smokeD", "bucket": "D",
         "why_discard": "smoke discard reason"},
    ]
    rec_file = tmp_path / "recoveries.json"
    rec_file.write_text(json.dumps(recs))
    out_dir = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, str(EMIT_PROGRAM),
         "--records", str(rec_file), "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"emit failed: {r.stderr}\n{r.stdout}"
    summary = json.loads((out_dir / "summary.json").read_text())

    # all buckets present in totals (T = forked-EDA-tool track, 0 here)
    assert summary["totals"] == {"A": 1, "B": 1, "C": 1, "D": 1, "T": 0}, summary

    # Bucket B targeted sta-review (per routing)
    assert any(e["target"] == "skills/sta-review/SKILL.md"
               for e in summary.get("bucket_B_files", [])), summary

    # Bucket A targeted rtl_hygiene_lint.py (per routing for phase2.rtl_gen)
    assert any("rtl_hygiene_lint" in f for f in summary.get("bucket_A_files", [])), summary

    # Bucket C emitted ORGANIC-*.yaml
    assert any(f.startswith("ORGANIC-") for f in summary.get("bucket_C_files", [])), summary

    # Bucket D emitted with the discard reason
    d_path = Path(summary["bucket_D_file"])
    assert "smoke discard reason" in d_path.read_text()


# ── 5. Bucket-T (forked-EDA-tool) emit + attribution gate ──────────────
def test_bucket_t_emit_and_gate(tmp_path):
    ok = [{"step": "phase3.detailed_route", "design": "spm", "bucket": "T",
           "tool": "OpenROAD", "title": "router drops min area on via pads",
           "problem": "the router leaves via pads below min area and reports zero",
           "golden_sample": "reports/drc_repaired.rpt",
           "bad_sample": "reports/drc.rpt",
           "tool_enhancement": "patch via a non fixed edge instead of bailing",
           "pattern": "via pad on a fixed edge slips past min area",
           "suggested_fix": "patch via a non fixed edge", "backlog_slug": "or-drt-minarea",
           "backlog_type": "bug", "severity": "P1", "component": "forked-openroad",
           "session_context": "commercial DRC closure"}]
    rf = tmp_path / "ok.json"; rf.write_text(json.dumps(ok))
    r = subprocess.run([sys.executable, str(EMIT_PROGRAM), "--records", str(rf),
                        "--out-dir", str(tmp_path / "o")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    yamls = list((tmp_path / "o" / "bucket_T_forked_tool").glob("*.yaml"))
    assert yamls, "bucket_T backlog not emitted"
    txt = yamls[0].read_text()
    assert 'root_cause_layer: forked_tool' in txt
    assert 'tool: "OpenROAD"' in txt and 'generating_step: "phase3.detailed_route"' in txt

    # missing required field -> refused
    bad = [{k: v for k, v in ok[0].items() if k != "tool"}]
    rf2 = tmp_path / "bad.json"; rf2.write_text(json.dumps(bad))
    r2 = subprocess.run([sys.executable, str(EMIT_PROGRAM), "--records", str(rf2),
                         "--out-dir", str(tmp_path / "o2")],
                        capture_output=True, text=True, timeout=30)
    assert r2.returncode == 1 and "BUCKET-T GATE" in r2.stderr
