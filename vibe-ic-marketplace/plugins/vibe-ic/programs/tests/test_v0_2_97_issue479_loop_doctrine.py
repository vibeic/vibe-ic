#!/usr/bin/env python3
"""tests/test_v0_2_97_issue479_loop_doctrine.py — ORGANIC #479 (MEDIUM, Bucket B)

Loop-skill doctrine capture (SKILL prose + compliance.yaml only; the two
DETERMINISTIC programs — acceptance_evidence_in_fix_comment_check.py +
defect_artifact_fixture_check.py — are #478's Bucket-A work, referenced here by
name).

#479 現象 (verification-round meta, loop-conditions layer):
  * core-agent-loop SKILL Step 2.5 only said "reproduce + full suite" and never
    bound the issue's `## 驗收` to verbatim execution; field-agent-loop
    §Verification traps had only two rules (pipeline exit-code, which-tree-runs)
    while the behaviour that actually caught two reopens this round — "run the
    acceptance command first, unit-test evidence second" — was only implicit.
  * `core-agent-loop/compliance.yaml` R5 only pattern-matched that "**本機驗證**："
    EXISTS; it never required the section to carry an acceptance-execution trace,
    so a bare "N/N PASS" close comment slipped through.

#479 建議修法 (Bucket B):
  1. core-agent-loop SKILL Step 2.5 + Step 4 close-comment shape: self-verify
     MUST execute the issue's `## 驗收` VERBATIM against the named defect
     artifact; the 本機驗證 section quotes (a) the command text + (b) its
     end-state output; new-tests-green + full-suite-green ALONE is insufficient
     to close. Name the two #478 gates. Carry the why_not_bucket_a note.
  2. core-agent-loop/compliance.yaml: ADD a requirement (additive) that the
     本機驗證 section carries an acceptance-execution trace — tolerant of issues
     with no acceptance section via 無驗收區 disclosure alternation.
  3. field-agent-loop §Verification traps gains rule 3 — "acceptance-criterion
     audit, not unit-test trust" — citing the #460/#466 pattern generically
     (coverage sub-gate the new tests never exercised; a guard that landed in
     prose instead of the runner) WITHOUT chip names.

ACCEPTANCE DOCTRINE (this batch): the defect artifact is a *close comment*
shaped like the #460/#466 现象 — a bare "N/N PASS" 本機驗證 section with no
acceptance trace. The `## 驗收`-equivalent for this Bucket-B item is:
  > a sample close comment WITH an acceptance trace passes the updated
  > compliance.yaml via _shared/skill_compliance_check.py, and one WITHOUT it
  > fails.
So the END-STATE we execute and assert is the real skill_compliance_check.py
exit code / verdict against those two fixtures (plus the 無驗收區 tolerance
case) — NOT merely an in-process regex.

chip-AGNOSTIC: synthetic generic fixtures only (no chip/vendor/SKU literals).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent  # plugins/vibe-ic/
sys.path.insert(0, str(PLUGIN_ROOT))

SKILLS = PLUGIN_ROOT / "skills"
CORE_SKILL = SKILLS / "core-agent-loop" / "SKILL.md"
CORE_COMPLIANCE = SKILLS / "core-agent-loop" / "compliance.yaml"
FIELD_SKILL = SKILLS / "field-agent-loop" / "SKILL.md"
CHECKER = PLUGIN_ROOT / "_shared" / "skill_compliance_check.py"

# Chip / vendor / SKU tokens that must NEVER appear as detection literals in the
# new sections. Mirrors source_chip_agnostic_check.py intent.
FORBIDDEN_CHIP_TOKENS = (
    "spm", "sha256", "subservient", "u_hawaii", "hawaii", "serv",
    "tsmc", "sg13g2", "ihp", "caravel", "chipignite", "sky130",
)

# A close comment that satisfies the original R1-R8 shape; the {verify} body is
# substituted per-test.
_BASE_COMMENT = """Core agent 已推送修復：abc1234

**問題**：extractor 未匹配 canonical pattern
**根因**：regex 太窄，未涵蓋同義詞
**修法**：放寬 regex（chip-AGNOSTIC），改動 programs/foo.py
**本機驗證**：{verify}

Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。field agent 複查若發現未完整，請 reopen 並補反證。
"""

# (defect artifact) the #460/#466-shape bad comment: a bare suite line, NO
# acceptance command, NO end-state output of the issue's ## 驗收.
DEFECT_VERIFY_BARE_SUITE = "340/340 PASS"

# A compliant comment: quotes the issue's ## 驗收 command verbatim + end-state.
GOOD_VERIFY_WITH_TRACE = """
- 驗收指令（逐字執行 issue 的 `## 驗收`）：
  ```
  python3 programs/foo_check.py fixture/ --stage 1
  ```
- 端態輸出：
  ```
  Overall: PASS (12/12 executed PASS)
  ```
- 全測試套件（CI 方式，雙樹）：340/340 PASS"""

# The tolerated no-acceptance-section disclosure form prescribed by the SKILL.
GOOD_VERIFY_NO_ACCEPT_SECTION = """
- 無驗收區（issue 未提供 ## 驗收），改以重演現象端態：
  ```
  python3 programs/foo.py repro/
  ```
- 端態輸出：repro now exits 0
- 全測試套件（CI 方式，雙樹）：340/340 PASS"""


def _read(p: Path) -> str:
    assert p.is_file(), f"missing file: {p}"
    return p.read_text()


def _write_comment(tmp_path: Path, name: str, verify_body: str) -> Path:
    f = tmp_path / name
    f.write_text(_BASE_COMMENT.format(verify=verify_body))
    return f


def _run_checker(comment_file: Path) -> subprocess.CompletedProcess:
    """Invoke the REAL skill_compliance_check.py end-to-end (not an in-process
    regex) — this is the issue's acceptance criterion."""
    return subprocess.run(
        [sys.executable, str(CHECKER),
         "--requirements", str(CORE_COMPLIANCE), str(comment_file)],
        capture_output=True, text=True)


# ===========================================================================
# (ACCEPTANCE / END-STATE) — execute the issue's 驗收 verbatim:
#   "a sample close comment WITH acceptance trace passes the updated
#    compliance.yaml via _shared/skill_compliance_check.py, and one WITHOUT
#    it fails."
# These run the real checker as a subprocess and assert the END-STATE
# (exit code + printed verdict), NOT an intermediate.
# ===========================================================================
def test_acceptance_defect_artifact_bare_suite_is_refused(tmp_path):
    """The #460/#466-shape defect artifact: a 本機驗證 section that is ONLY a
    bare 'N/N PASS' suite line, with no acceptance trace, must FAIL the gate."""
    bad = _write_comment(tmp_path, "bare_suite.md", DEFECT_VERIFY_BARE_SUITE)
    r = _run_checker(bad)
    assert r.returncode == 1, (
        f"bare-suite close comment must be refused (rc=1); got {r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")
    assert "FAIL" in r.stdout
    assert "R9_acceptance_execution_trace" in r.stdout


def test_acceptance_comment_with_trace_passes(tmp_path):
    """A compliant comment quoting the ## 驗收 command + end-state output must
    PASS the updated compliance.yaml end-to-end."""
    good = _write_comment(tmp_path, "with_trace.md", GOOD_VERIFY_WITH_TRACE)
    r = _run_checker(good)
    assert r.returncode == 0, (
        f"compliant close comment must pass (rc=0); got {r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")
    assert "PASS" in r.stdout
    assert "9/9 present" in r.stdout


def test_acceptance_no_section_disclosure_is_tolerated(tmp_path):
    """An issue with genuinely no ## 驗收 section: the prescribed 無驗收區
    disclosure form must PASS (tolerance branch of the alternation)."""
    ok = _write_comment(tmp_path, "no_accept.md", GOOD_VERIFY_NO_ACCEPT_SECTION)
    r = _run_checker(ok)
    assert r.returncode == 0, (
        f"無驗收區 disclosure must be tolerated (rc=0); got {r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")
    assert "PASS" in r.stdout


# ===========================================================================
# (compliance.yaml — additive + non-breaking)
# ===========================================================================
def test_r9_requirement_present_and_additive():
    """R9 added; R1-R8 (the original close-comment shape) all preserved."""
    sys.path.insert(0, str(PLUGIN_ROOT / "_shared"))
    from skill_compliance_check import _load_yaml  # noqa: E402

    doc = _load_yaml(CORE_COMPLIANCE)
    assert doc.get("skill") == "core-agent-loop"
    ids = [r["id"] for r in doc.get("requirements", [])]
    # additive: every pre-existing requirement still present
    for pre in ("R1_handoff_line", "R2_problem_section", "R3_root_cause_section",
                "R4_fix_section", "R5_local_verification_section",
                "R6_self_close_trailing_line", "R7_chip_agnostic_language",
                "R8_field_agent_not_debug_agent"):
        assert pre in ids, f"#479 broke a pre-existing requirement: {pre}"
    # new requirement present, with the tolerant alternation pattern
    assert "R9_acceptance_execution_trace" in ids
    r9 = next(r for r in doc["requirements"]
              if r["id"] == "R9_acceptance_execution_trace")
    assert "驗收" in r9["pattern"] and "無驗收區" in r9["pattern"], (
        "R9 must be tolerant via 驗收 | 無驗收區 alternation")
    # R9 is a blocking (required) check by default — bare N/N PASS must FAIL.
    assert r9.get("required", True) is True


def test_r5_still_only_checks_section_presence():
    """Regression guard: the additive R9 must not have weakened R5 — R5 still
    just asserts the 本機驗證 header exists (its job), R9 carries the new
    content requirement."""
    sys.path.insert(0, str(PLUGIN_ROOT / "_shared"))
    from skill_compliance_check import _load_yaml  # noqa: E402

    doc = _load_yaml(CORE_COMPLIANCE)
    r5 = next(r for r in doc["requirements"]
              if r["id"] == "R5_local_verification_section")
    assert r5["pattern"] == r"\*\*本機驗證\*\*："


# ===========================================================================
# (core-agent-loop SKILL.md — Step 2.5 + Step 4 prose)
# ===========================================================================
def test_core_skill_step25_binds_verbatim_acceptance():
    text = _read(CORE_SKILL)
    low = text.lower()
    # MUST execute the issue's ## 驗收 verbatim against the named defect artifact.
    assert "## 驗收" in text
    assert "verbatim" in low
    assert "defect artifact" in low
    # new-tests-green + full-suite-green ALONE is insufficient to close.
    assert "insufficient" in low
    assert "alone" in low
    # MUST quote (a) the acceptance command text + (b) its end-state output.
    assert "end-state" in low
    assert "acceptance command" in low or "acceptance command text" in low


def test_core_skill_names_the_two_478_gates():
    text = _read(CORE_SKILL)
    assert "acceptance_evidence_in_fix_comment_check.py" in text
    assert "defect_artifact_fixture_check.py" in text
    # exit 0 required before posting.
    assert "exit 0" in text.lower()


def test_core_skill_has_why_not_bucket_a_note():
    text = _read(CORE_SKILL)
    low = text.lower()
    assert "why_not_bucket_a" in low
    # the judgment residual: deciding whether a command IS the acceptance
    # criterion + whether output reached end-state needs reading judgment;
    # the deterministic half lives in the two #478 programs.
    assert "reading" in low and ("judgment" in low or "judgement" in low)
    assert "deterministic" in low
    assert "#478" in text


def test_core_skill_step4_close_comment_shows_acceptance_trace():
    text = _read(CORE_SKILL)
    # the close-comment template now carries a 驗收 trace + end-state, not just
    # an N/N PASS line.
    assert "驗收指令" in text
    assert "端態輸出" in text
    # the no-acceptance-section fallback is prescribed with the 無驗收區 wording.
    assert "無驗收區" in text


# ===========================================================================
# (field-agent-loop SKILL.md — §Verification traps rule 3)
# ===========================================================================
def test_field_skill_verification_trap_rule3_present():
    text = _read(FIELD_SKILL)
    low = text.lower()
    # rule 3 heading / phrase
    assert "acceptance-criterion audit" in low
    assert "not unit-test trust" in low
    # audit by FIRST running the acceptance command end-to-end on the real
    # benchmark; unit-test/suite evidence is secondary.
    assert "real benchmark" in low
    assert "## 驗收" in text
    assert "secondary" in low
    assert "end-to-end" in low or "end to end" in low
    # the rule is numbered 3 in the Verification traps list.
    assert re.search(r"3\.\s+\*\*Acceptance-criterion audit", text)


def test_field_skill_rule3_cites_460_466_pattern_generically():
    text = _read(FIELD_SKILL)
    low = text.lower()
    # cite the #460/#466 verification round generically (the two recurring
    # shapes), WITHOUT chip names.
    assert "#460" in text and "#466" in text
    # shape 1: a coverage sub-gate the new tests never exercised.
    assert "coverage" in low and ("sub-gate" in low or "sub gate" in low)
    # shape 2: a guard/rule that landed in prose instead of the runner.
    assert "prose" in low and "runner" in low


def test_field_skill_rule3_is_chip_agnostic():
    """No chip / vendor / SKU literal may appear in the new rule-3 text."""
    text = _read(FIELD_SKILL)
    anchor = "3. **Acceptance-criterion audit"
    idx = text.find(anchor)
    assert idx != -1, "rule 3 anchor not found"
    section = text[idx:]
    # bound the slice to the rule (until the next blank-then-heading or EOF)
    end = section.find("\n## ")
    if end != -1:
        section = section[:end]
    low = section.lower()
    for tok in FORBIDDEN_CHIP_TOKENS:
        assert not re.search(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", low), (
            f"chip/vendor/SKU token {tok!r} leaked into field-agent rule 3")


# ===========================================================================
# (chip-AGNOSTIC — the added core SKILL prose too)
# ===========================================================================
def test_core_skill_step25_additions_chip_agnostic():
    text = _read(CORE_SKILL)
    anchor = "Self-verify** before closing"
    idx = text.find(anchor)
    assert idx != -1
    # slice the amended Step-2 item (until Step 3 heading)
    end = text.find("### Step 3", idx)
    section = text[idx:end if end != -1 else len(text)]
    low = section.lower()
    for tok in FORBIDDEN_CHIP_TOKENS:
        assert not re.search(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", low), (
            f"chip/vendor/SKU token {tok!r} leaked into core-agent Step 2.5")


def test_source_chip_agnostic_guard_still_passes():
    """The whole-tree chip-AGNOSTIC source guard must stay PASS after the
    SKILL.md / compliance.yaml edits."""
    r = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "programs" /
                             "source_chip_agnostic_check.py"), "."],
        cwd=str(PLUGIN_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, (
        f"source_chip_agnostic_check FAILed after #479 edits\n"
        f"{r.stdout}\n{r.stderr}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
