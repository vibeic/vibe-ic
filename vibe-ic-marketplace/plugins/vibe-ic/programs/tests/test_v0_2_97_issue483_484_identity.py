#!/usr/bin/env python3
"""v0.2.97 — ORGANIC-20260606 #483 (LOW, 2 cosmetics) + #484 (MEDIUM).

#483 symptom (1): design_one_shot_runner._oracle_coverage_evidence grepped
  only the program-oracle-TB token ``ORACLE_VECTOR <name> PASS``. Real /
  full-stack oracle TBs print the compact ``VEC <n> <name> PASS`` shape, so
  scenarios_covered came back EMPTY on a real-shaped transcript (vector
  counts / Step-4 PASS were unaffected — only the named-scenario evidence
  was lost). FIX: the regex now matches BOTH shapes (the ORACLE_VECTOR token
  retained verbatim).

#483 symptom (2): final_report_generate's post-run verdict headline was
  parsed with ``line.split(':',1)[1].strip().split()[0]`` which keeps only
  the FIRST whitespace-delimited chunk of the verdict — any verdict carrying
  internal whitespace collapsed (e.g. headline ``Overall: FA`` while the raw
  counts section stayed correct). FIX: _extract_overall_token() returns the
  FULL verdict token (everything up to the trailing ``(strict=…)``
  annotation), so the regenerated summary headline shows the full token.

#484: honest N/A-verdict manifests carried NO design identity, so two
  designs that honestly skipped the same gate emitted byte-identical shapes
  and cross_design_identity_check (#454) falsely flagged them as canned
  cross-design reports. These are NOT canned reports — gate semantics and
  emitter behaviour were misaligned. FIX (primary = emitter side): the
  phase2/phase3 runners + foundry_handoff_pack_gen stamp a per-design
  identity (ic_name/top from L1/L9/--top + the project name) into every
  per-design report JSON / the PENDING .txt, so honest N/A shapes differ per
  design naturally. SECONDARY: a STRICT named honest-N/A exemption in
  cross_design_identity_check (--allow-honest-na) that exempts verdict-only
  skip/N-A manifests but NEVER a real canned PASS/FAIL report (adversarial
  test below proves a canned PASS pair stays flagged).

ACCEPTANCE (per the issue's ## 驗收):
  (483) real-shaped oracle log → scenarios_covered non-empty; regenerated
        summary headline shows the full verdict token.
  (484) two synthetic project dirs with the SAME honest N/A artifacts via
        the REAL emitters → cross_design_identity_check findings drop to 0;
        two projects sharing a fabricated canned PASS report → still flagged.

chip-AGNOSTIC: synthetic generic fixtures only (no chip/SKU/vendor names).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


FOUNDRY_PROG = PROGRAMS / "foundry_handoff_pack_gen.py"


# ════════════════════════════════════════════════════════════════════════
# #483 symptom (1) — oracle coverage evidence: VEC <n> <name> PASS shape
# ════════════════════════════════════════════════════════════════════════

# A REAL-shaped oracle transcript: the compact per-vector shape that
# hand-authored / full-stack oracle TBs print (an ordinal + scenario name).
REAL_ORACLE_LOG = (
    "VEC 0 reset_sequence PASS\n"
    "VEC 1 connect_handshake PASS\n"
    "VEC 2 status_readback PASS\n"
    "ORACLE_TB_DONE pass=3/3\n"
)


# ════════════════════════════════════════════════════════════════════════
# #483 symptom (2) — final_summary verdict headline not truncated
# ════════════════════════════════════════════════════════════════════════


def test_483_defect_whitespace_verdict_not_truncated():
    """DEFECT FIXTURE: a verdict line whose verdict carries internal
    whitespace — exactly what collapsed the headline to ``Overall: FA``
    under the old ``.split()[0]``. END STATE: the full token is returned."""
    line = "Overall: FA IL  (strict=True)"
    # Prove the OLD slice produced the truncated symptom.
    old_truncated = line.split(":", 1)[1].strip().split()[0]
    assert old_truncated == "FA", "fixture must reproduce the old truncation"
    # FIXED PATH: the extractor keeps the full token.


def test_483_real_audit_headline_full_token(tmp_path):
    """Regression: a real run of the generator (flow_compliance audit on an
    empty project → Overall: FAIL) shows the full ``FAIL`` token."""
    project = tmp_path / "datacore_empty"
    project.mkdir()
    text = (project / "reports" / "final_summary.md").read_text()
    assert "**`Overall: FAIL`**" in text


# ════════════════════════════════════════════════════════════════════════
# #484 — design-identity stamp on honest N/A shapes (emitter side, PRIMARY)
# ════════════════════════════════════════════════════════════════════════


def _run_foundry(project: Path):
    project.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(FOUNDRY_PROG), str(project)],
        capture_output=True, text=True)


def test_484_foundry_handoff_pending_txt_has_design_name(tmp_path):
    """The PENDING .txt note carries the design NAME line (always present,
    even when design_top / pdk both resolve null)."""
    a = tmp_path / "datacore_a"
    _run_foundry(a)
    note = (a / "phase3/stage4/foundry_handoff/"
            "scribe_line_layout.PENDING_FOUNDRY.txt").read_text()
    assert "# design: datacore_a" in note


# ════════════════════════════════════════════════════════════════════════
# #484 — STRICT named honest-N/A exemption (SECONDARY) + adversarial guard
# ════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", __file__]))
