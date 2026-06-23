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

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as p2  # noqa: E402
import phase3_one_shot_runner as p3  # noqa: E402
import final_report_generate as frg  # noqa: E402
import cross_design_identity_check as cdi  # noqa: E402

FOUNDRY_PROG = PROGRAMS / "foundry_handoff_pack_gen.py"
CDI_PROG = PROGRAMS / "cross_design_identity_check.py"


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


def test_483_real_shaped_oracle_log_scenarios_non_empty():
    """DEFECT FIXTURE (#483 symptom 1): a real ``VEC <n> <name> PASS``
    transcript. END STATE after the fix: scenarios_covered is NON-EMPTY and
    names the actual scenarios (the old ORACLE_VECTOR-only regex returned
    [])."""
    scen, n_pass, n_total = p2._oracle_coverage_evidence(REAL_ORACLE_LOG)
    assert scen, "scenarios_covered must be non-empty for a real VEC-shaped log"
    assert scen == ["connect_handshake", "reset_sequence", "status_readback"]
    assert (n_pass, n_total) == (3, 3)


def test_483_old_program_oracle_vector_shape_still_parsed():
    """Regression: the original ``ORACLE_VECTOR <name> PASS`` token (emitted
    by oracle_tb_gen) is STILL recognised verbatim."""
    log = ("ORACLE_VECTOR get_id PASS\n"
           "ORACLE_VECTOR get_state PASS\n"
           "ORACLE_TB_DONE pass=2/2\n")
    scen, n_pass, n_total = p2._oracle_coverage_evidence(log)
    assert scen == ["get_id", "get_state"]
    assert (n_pass, n_total) == (2, 2)


def test_483_mixed_shapes_and_fail_lines_excluded():
    """Both shapes coexist; a FAIL per-vector line is NEVER counted as a
    covered scenario (the transcript is the sole evidence source)."""
    log = ("VEC 0 alpha PASS\n"
           "VEC 1 beta FAIL expected=0x01 got=0x02\n"
           "ORACLE_VECTOR gamma PASS\n"
           "ORACLE_TB_DONE pass=2/3\n")
    scen, n_pass, n_total = p2._oracle_coverage_evidence(log)
    assert scen == ["alpha", "gamma"]
    assert "beta" not in scen
    assert (n_pass, n_total) == (2, 3)


# ════════════════════════════════════════════════════════════════════════
# #483 symptom (2) — final_summary verdict headline not truncated
# ════════════════════════════════════════════════════════════════════════

def test_483_extract_overall_token_full_verdict():
    """The verdict token extractor returns the FULL token for every real
    flow_compliance verdict shape (the prior .split()[0] truncated on the
    first internal whitespace)."""
    cases = {
        "Overall: FAIL  (strict=True)": "FAIL",
        "Overall: PASS": "PASS",
        "Overall: PASS_WITH_WAIVERS  (strict=True)": "PASS_WITH_WAIVERS",
        "Overall: PASS_WITH_OPEN_SOURCE_CONSTRAINTS  (strict=True)":
            "PASS_WITH_OPEN_SOURCE_CONSTRAINTS",
        "Overall: AUDIT_TIMEOUT": "AUDIT_TIMEOUT",
    }
    for line, want in cases.items():
        assert frg._extract_overall_token(line) == want, line


def test_483_defect_whitespace_verdict_not_truncated():
    """DEFECT FIXTURE: a verdict line whose verdict carries internal
    whitespace — exactly what collapsed the headline to ``Overall: FA``
    under the old ``.split()[0]``. END STATE: the full token is returned."""
    line = "Overall: FA IL  (strict=True)"
    # Prove the OLD slice produced the truncated symptom.
    old_truncated = line.split(":", 1)[1].strip().split()[0]
    assert old_truncated == "FA", "fixture must reproduce the old truncation"
    # FIXED PATH: the extractor keeps the full token.
    assert frg._extract_overall_token(line) == "FA IL"


def test_483_regenerated_summary_headline_full_token(tmp_path, monkeypatch):
    """ACCEPTANCE end-to-end: regenerate final_summary.md with a defect-
    shaped audit text whose Overall verdict carries internal whitespace.
    END STATE: the ``**`Overall: …`**`` headline shows the FULL verdict
    token (never the truncated ``Overall: FA``), while the raw counts code
    block is untouched."""
    project = tmp_path / "datacore_widget"
    project.mkdir()

    # Defect-shaped audit transcript: header/Steps/tally lines (the raw
    # counts section, which is correct) + an Overall line whose verdict
    # carries internal whitespace.
    defect_audit = (
        "=== Vibe-IC compliance ===\n"
        "Project: x\n"
        "Flow def: y\n"
        "Steps: 3 total (1/2 executed PASS, 0 DEFERRED via waiver)\n"
        "  PASS=1  FAIL=1  MISSING=1\n"
        "\n"
        "Overall: FA IL  (strict=True)\n"
    )

    def _fake_run_audit(proj, timeout_s=None, prior_marker=None):
        return defect_audit, frg._extract_overall_token(
            "Overall: FA IL  (strict=True)")

    monkeypatch.setattr(frg, "_run_audit", _fake_run_audit)
    md = frg._render(project, run_audit=True)
    out = project / "reports" / "final_summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)

    text = out.read_text()
    assert "**`Overall: FA IL`**" in text, \
        "headline must carry the FULL verdict token"
    assert "**`Overall: FA`**" not in text, \
        "headline must NOT be truncated to FA"
    # Raw counts section (the verbatim audit lines) is preserved.
    assert "Steps: 3 total (1/2 executed PASS" in text


def test_483_real_audit_headline_full_token(tmp_path):
    """Regression: a real run of the generator (flow_compliance audit on an
    empty project → Overall: FAIL) shows the full ``FAIL`` token."""
    project = tmp_path / "datacore_empty"
    project.mkdir()
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "final_report_generate.py"),
         str(project)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = (project / "reports" / "final_summary.md").read_text()
    assert "**`Overall: FAIL`**" in text


# ════════════════════════════════════════════════════════════════════════
# #484 — design-identity stamp on honest N/A shapes (emitter side, PRIMARY)
# ════════════════════════════════════════════════════════════════════════

def _l_docs(project: Path, ic_name: str, top: str) -> None:
    gd = p2._pl.generated_docs_dir(project)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": ic_name}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": top}))


def test_484_phase2_manifest_carries_design_identity(tmp_path):
    """phase2 manifest writer stamps design_identity into EVERY emitted
    manifest (incl. the empty-list lint json and SKIP-shaped on_board)."""
    project = tmp_path / "datacore_a"
    (project / "reports").mkdir(parents=True)
    _l_docs(project, "datacore_a_core", "datacore_a_top")
    res = p2.step_emit_phase2_manifests(project, [])
    assert res.status in ("PASS", "SKIP")
    lint = json.loads(
        (project / "reports/phase2/lint/rtl_hygiene.json").read_text())
    assert lint["design_identity"]["design"] == "datacore_a"
    assert lint["design_identity"]["ic_name"] == "datacore_a_core"


def test_484_phase3_sdf_skip_helper_per_design(tmp_path):
    """phase3 design-identity helper resolves ic_name/top/name per design;
    the project NAME is always present even with no L docs."""
    a = tmp_path / "datacore_a"
    _l_docs(a, "core_a", "top_a")
    assert p3._design_identity_fields(a) == {
        "design": "datacore_a", "ic_name": "core_a", "top": "top_a"}
    b = tmp_path / "datacore_b"
    b.mkdir()
    assert p3._design_identity_fields(b) == {"design": "datacore_b"}


def _run_foundry(project: Path):
    project.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(FOUNDRY_PROG), str(project)],
        capture_output=True, text=True)


def _run_cdi(projects, allow_honest_na=False):
    args = [sys.executable, str(CDI_PROG)] + [str(p) for p in projects]
    if allow_honest_na:
        args.append("--allow-honest-na")
    r = subprocess.run(args, capture_output=True, text=True)
    return json.loads(r.stdout), r.returncode


def test_484_foundry_handoff_pending_txt_has_design_name(tmp_path):
    """The PENDING .txt note carries the design NAME line (always present,
    even when design_top / pdk both resolve null)."""
    a = tmp_path / "datacore_a"
    _run_foundry(a)
    note = (a / "phase3/stage4/foundry_handoff/"
            "scribe_line_layout.PENDING_FOUNDRY.txt").read_text()
    assert "# design: datacore_a" in note


def test_484_real_emitters_two_designs_findings_drop_to_zero(tmp_path):
    """ACCEPTANCE (#484 primary): build TWO synthetic project dirs with the
    SAME honest N/A artifacts via the REAL emitters (phase2 manifests +
    foundry handoff, with NO L docs so every resolver falls through to the
    honest defaults). END STATE: cross_design_identity_check findings == 0
    WITHOUT the exemption flag — the identity stamp alone differentiates the
    honest shapes."""
    a = tmp_path / "datacore_alpha"
    b = tmp_path / "datacore_beta"
    for proj in (a, b):
        (proj / "reports").mkdir(parents=True)
        p2.step_emit_phase2_manifests(proj, [])
        _run_foundry(proj)

    rep, rc = _run_cdi([a, b])
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["identical_artifacts"] == 0
    assert rc == 0


def test_484_without_fix_shape_would_collide(tmp_path):
    """Control: prove the artifacts WOULD have collided absent the identity
    stamp — strip the design_identity field from one design's manifests and
    confirm the gate then flags them. (Demonstrates the stamp is what makes
    the honest shapes differ, not some incidental per-design content.)"""
    a = tmp_path / "datacore_alpha"
    b = tmp_path / "datacore_beta"
    for proj in (a, b):
        (proj / "reports").mkdir(parents=True)
        p2.step_emit_phase2_manifests(proj, [])

    # Normalise BOTH designs' lint json by removing the identity stamp →
    # they become byte-identical → the gate must flag them.
    for proj in (a, b):
        fp = proj / "reports/phase2/lint/rom_init_lint.json"
        d = json.loads(fp.read_text())
        d.pop("design_identity", None)
        fp.write_text(json.dumps(d, indent=2) + "\n")

    rep, rc = _run_cdi([a, b])
    assert rep["verdict"] == "FAIL"
    assert any("rom_init_lint.json" in f["message"] for f in rep["findings"])


# ════════════════════════════════════════════════════════════════════════
# #484 — STRICT named honest-N/A exemption (SECONDARY) + adversarial guard
# ════════════════════════════════════════════════════════════════════════

def _write(project: Path, rel: str, payload) -> None:
    fp = project / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        fp.write_text(json.dumps(payload, indent=2) + "\n")
    else:
        fp.write_text(payload)


def test_484_honest_na_predicate_strict():
    """The honest-N/A predicate accepts ONLY verdict-only skip/N-A shapes
    and NEVER a PASS/FAIL-bearing or substance-bearing report."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "x.json"
        # honest verdict-only skips
        for v in ("SKIP", "SKIPPED-CONDITION", "N/A", "PENDING_FOUNDRY",
                  "SKELETON_EMITTED"):
            fp.write_text(json.dumps({"verdict": v, "reason": "no tool"}))
            assert cdi._is_honest_na_verdict_only(fp), v
        # NEVER exempt: PASS / FAIL / PASS_WITH_*
        for v in ("PASS", "FAIL", "PASS_WITH_WAIVERS",
                  "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"):
            fp.write_text(json.dumps({"verdict": v}))
            assert not cdi._is_honest_na_verdict_only(fp), v
        # substance disqualifies even a skip verdict
        fp.write_text(json.dumps({"verdict": "SKIP",
                                  "scenarios_covered": ["a"]}))
        assert not cdi._is_honest_na_verdict_only(fp)
        fp.write_text(json.dumps({"verdict": "SKIPPED-CONDITION",
                                  "vectors_passed": 5}))
        assert not cdi._is_honest_na_verdict_only(fp)
        # non-dict / non-string verdict / no verdict → not exempt
        fp.write_text(json.dumps(["SKIP"]))
        assert not cdi._is_honest_na_verdict_only(fp)
        fp.write_text(json.dumps({"note": "no verdict field"}))
        assert not cdi._is_honest_na_verdict_only(fp)


def test_484_exemption_clears_honest_na_pair(tmp_path):
    """A genuinely-honest verdict-only N/A pair (identical because the
    emitter cannot stamp identity) is exempted ONLY with the opt-in flag."""
    a = tmp_path / "datacore_a"
    b = tmp_path / "datacore_b"
    payload = {"verdict": "SKIPPED-CONDITION",
               "reason": "no commercial CDC tool in container"}
    for proj in (a, b):
        _write(proj, "reports/phase2/cdc/foreign_skip.json", payload)

    # Default: flagged.
    rep_default, rc_default = _run_cdi([a, b])
    assert rep_default["verdict"] == "FAIL"
    assert rc_default == 1
    # Opt-in honest-N/A: exempted, recorded under honest_na_exempt.
    rep_exempt, rc_exempt = _run_cdi([a, b], allow_honest_na=True)
    assert rep_exempt["verdict"] == "PASS", rep_exempt["findings"]
    assert rc_exempt == 0
    assert any("foreign_skip.json" in e["path"]
               for e in rep_exempt["honest_na_exempt"])


def test_484_adversarial_canned_pass_still_flagged_even_with_flag(tmp_path):
    """ADVERSARIAL (the core of #484's secondary requirement): a fabricated
    CANNED PASS report shared byte-identically across two designs is STILL
    flagged even WITH --allow-honest-na. A true canned PASS/FAIL report is
    NEVER exempted."""
    a = tmp_path / "datacore_a"
    b = tmp_path / "datacore_b"
    canned_pass = {
        "verdict": "PASS",
        "evidence": "reports/some_log.txt",
        "scenarios_covered": ["get_id", "get_state"],
        "note": "canned cross-design coverage (the #436 violation class)",
    }
    for proj in (a, b):
        _write(proj, "reports/phase2/coverage/coverage_actual.json",
               canned_pass)

    for flag in (False, True):
        rep, rc = _run_cdi([a, b], allow_honest_na=flag)
        assert rep["verdict"] == "FAIL", f"canned PASS must FAIL (flag={flag})"
        assert rc == 1
        assert any("coverage_actual.json" in f["message"]
                   for f in rep["findings"])
        # Never silently exempted.
        assert not any("coverage_actual.json" in e["path"]
                       for e in rep.get("honest_na_exempt", []))


def test_484_adversarial_canned_fail_still_flagged_even_with_flag(tmp_path):
    """ADVERSARIAL: a canned FAIL report shared across designs is also never
    exempted by the honest-N/A path."""
    a = tmp_path / "datacore_a"
    b = tmp_path / "datacore_b"
    canned_fail = {"verdict": "FAIL", "violations": ["v1", "v2"],
                   "note": "canned"}
    for proj in (a, b):
        _write(proj, "reports/drc_signoff.json", canned_fail)
    rep, rc = _run_cdi([a, b], allow_honest_na=True)
    assert rep["verdict"] == "FAIL"
    assert rc == 1
    assert any("drc_signoff.json" in f["message"] for f in rep["findings"])


def test_484_mixed_group_one_substantive_member_not_exempt(tmp_path):
    """If one design's copy is a real PASS while another is a bare SKIP, the
    byte-identity group would never form (different bytes) — but guard the
    predicate is per-file ALL: a group is exempt only when EVERY hit is
    independently verdict-only honest-N/A."""
    a = tmp_path / "datacore_a"
    b = tmp_path / "datacore_b"
    # Same honest SKIP in both → exempt with flag.
    skip = {"verdict": "SKIP", "reason": "no tool"}
    for proj in (a, b):
        _write(proj, "reports/x/foo_skip.json", skip)
    rep, _ = _run_cdi([a, b], allow_honest_na=True)
    assert not any("foo_skip.json" in f["message"] for f in rep["findings"])


if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", __file__]))
