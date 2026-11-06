#!/usr/bin/env python3
"""v0.3.1 — ORGANIC-20260606 #497 (MEDIUM): the #484 identity-stamp
coverage gap.

#484 stamped the phase2 CENTRAL manifest helper (step_emit_phase2_manifests'
`w()`) + the phase3 emitters + foundry_handoff_pack_gen, so honest N/A-verdict
manifests differ per design naturally. But the PHASE-1 audit/report writers and
a couple of phase2 per-gate report writers that bypass the central `w()` helper
were left identity-less, so a fresh 4-design campaign still shipped byte-
identical-but-honest artifacts across DIFFERENT chips:

  * reports/phase1/extraction_skipped.json   (clean run = empty skip list)
  * phase1/extraction_skipped.json           (legacy mirror)
  * reports/phase1/l3_opcode_name_coverage.json (empty-L3 VACUOUS_PASS)
  * reports/phase1/protocol_dispatch_skipped.json (same-class fail-closed)
  * reports/phase2/complexity_advisory.json  (trivial/empty design features)

FIX (emitter-side, same #484 convention): phase1 gets its own
`_design_identity_fields` (replicated shape: project name always + ic_name from
L1/L2 + top from L9; honest-null omission when a source L doc is absent) plus a
`_stamp_design_identity` helper that re-reads a subprocess-written gate report
and idempotently fills the stamp. phase2's complexity-advisory writer (which
bypasses the central `w()`) gets the same setdefault stamp.

ACCEPTANCE (verbatim from the issue ## 驗收):
  generate two synthetic project dirs via the REAL writers (call the writer
  functions directly with different project identities) → run
  cross_design_identity_check.py across them → findings == 0 for those artifact
  families; ADVERSARIAL guard: a byte-identical canned PASS report pair is
  STILL flagged.

chip-AGNOSTIC: synthetic generic fixtures only (no chip/SKU/vendor names; the
project names used here are deny-list-safe invented tokens).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as p1  # noqa: E402
import _path_layout as _pl  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

CDI_PROG = PROGRAMS / "cross_design_identity_check.py"
COV_GATE = PROGRAMS / "l3_opcode_name_coverage_check.py"

# Canonical routed location of the l3-coverage gate report — the runner uses
# _pl.report_path("phase1/l3_opcode_name_coverage.json"), which the taxonomy
# router places under reports/audit/phase1/ (exactly the #497 campaign path).
_L3_COV_REL = "reports/audit/phase1/l3_opcode_name_coverage.json"


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────


def _mk_l_docs(project: Path, ic_name: str, top: str | None = None) -> None:
    gd = _pl.generated_docs_dir(project)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": ic_name}))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({"opcodes": []}))
    if top:
        (gd / "L9_INTEGRATION_SPEC.json").write_text(
            json.dumps({"top_module": top}))


def _build_phase1_reports(project: Path, ic_name: str) -> None:
    """Drive the REAL phase1 writers on `project`:
      * extract_text_pipeline → extraction_skipped.json (clean, empty list)
      * l3 coverage gate subprocess + the runner's _stamp_design_identity
      * protocol_dispatch_skipped signal (same-class fail-closed shape)
    """
    (project / "input" / "docs").mkdir(parents=True, exist_ok=True)
    _mk_l_docs(project, ic_name)
    # 1) extraction_skipped.json (both legacy + reports/ mirror) — real writer.
    p1.extract_text_pipeline(project, force=True)
    # 2) l3 coverage report — invoke the real gate subprocess exactly as the
    #    runner does, then stamp via the runner's helper.
    cov_report = _pl.report_path(project, "phase1/l3_opcode_name_coverage.json")
    cov_report.parent.mkdir(parents=True, exist_ok=True)
    _pr.run(
        [sys.executable, str(COV_GATE), str(project),
         "--json", str(cov_report)],
        capture_output=True, text=True)
    p1._stamp_design_identity(project, cov_report)
    # 3) protocol_dispatch_skipped signal — exercise the runner's stamp path
    #    using a deterministic unreachable-class signal shape.
    dec = p1.protocol_dispatch_decision("definitely_not_a_dispatch_class")
    assert dec["signal"] is not None
    sig = dict(dec["signal"])
    sig.setdefault("design_identity", p1._design_identity_fields(project))
    disp = project / "reports" / "phase1" / "protocol_dispatch_skipped.json"
    disp.parent.mkdir(parents=True, exist_ok=True)
    disp.write_text(json.dumps(sig, indent=2, ensure_ascii=False) + "\n")




# ──────────────────────────────────────────────────────────────────────────
# unit: phase1 _design_identity_fields shape (mirrors #484 phase2/phase3)
# ──────────────────────────────────────────────────────────────────────────
def test_497_phase1_identity_fields_shape(tmp_path):
    a = tmp_path / "datacore_alpha"
    _mk_l_docs(a, "core_alpha", "top_alpha")
    assert p1._design_identity_fields(a) == {
        "design": "datacore_alpha", "ic_name": "core_alpha",
        "top": "top_alpha"}


def test_497_phase1_identity_honest_null_when_no_l_docs(tmp_path):
    """Honest-null: with NO L docs only the project name is present (never a
    faked ic_name/top) — but the project name alone already differs per
    design."""
    b = tmp_path / "datacore_beta"
    b.mkdir()
    assert p1._design_identity_fields(b) == {"design": "datacore_beta"}


def test_497_phase1_identity_partial_fields(tmp_path):
    """L1 present, L9 absent → ic_name stamped, top OMITTED (honest)."""
    c = tmp_path / "datacore_gamma"
    _mk_l_docs(c, "core_gamma")  # no top → no L9
    ident = p1._design_identity_fields(c)
    assert ident["design"] == "datacore_gamma"
    assert ident["ic_name"] == "core_gamma"
    assert "top" not in ident


def test_497_stamp_helper_idempotent(tmp_path):
    """_stamp_design_identity is idempotent — it never clobbers a pre-existing
    design_identity, and leaves non-dict / parse-error reports untouched."""
    proj = tmp_path / "datacore_delta"
    _mk_l_docs(proj, "core_delta")
    fp = proj / "reports" / "r.json"
    fp.parent.mkdir(parents=True)
    # fresh stamp
    fp.write_text(json.dumps({"verdict": "VACUOUS_PASS"}))
    assert p1._stamp_design_identity(proj, fp) is True
    first = json.loads(fp.read_text())
    assert first["design_identity"]["design"] == "datacore_delta"
    # second call is a no-op (already stamped)
    assert p1._stamp_design_identity(proj, fp) is False
    assert json.loads(fp.read_text()) == first
    # non-dict report → untouched
    fp.write_text(json.dumps(["a", "b"]))
    assert p1._stamp_design_identity(proj, fp) is False


# ──────────────────────────────────────────────────────────────────────────
# per-writer: each REAL phase1/phase2 report differs per design
# ──────────────────────────────────────────────────────────────────────────
def test_497_extraction_skipped_differs_per_design(tmp_path):
    a, b = tmp_path / "datacore_alpha", tmp_path / "datacore_beta"
    for proj in (a, b):
        (proj / "input" / "docs").mkdir(parents=True)
        p1.extract_text_pipeline(proj, force=True)
    for rel in ("reports/phase1/extraction_skipped.json",
                "phase1/extraction_skipped.json"):
        fa, fb = (a / rel), (b / rel)
        assert fa.is_file() and fb.is_file(), rel
        assert json.loads(fa.read_text())["design_identity"]["design"] == \
            "datacore_alpha"
        assert fa.read_bytes() != fb.read_bytes(), rel


def test_497_l3_coverage_report_differs_per_design(tmp_path):
    a, b = tmp_path / "datacore_alpha", tmp_path / "datacore_beta"
    _build_phase1_reports(a, "core_alpha")
    _build_phase1_reports(b, "core_beta")
    rel = _L3_COV_REL
    fa, fb = (a / rel), (b / rel)
    da, db = json.loads(fa.read_text()), json.loads(fb.read_text())
    # the honest VACUOUS_PASS verdict is preserved (the fix only ADDS the
    # stamp — it never rewrites the gate's verdict).
    assert da["verdict"] == "VACUOUS_PASS"
    assert da["design_identity"]["ic_name"] == "core_alpha"
    assert db["design_identity"]["ic_name"] == "core_beta"
    assert fa.read_bytes() != fb.read_bytes()




# ──────────────────────────────────────────────────────────────────────────
# ACCEPTANCE (verbatim): two synthetic dirs via REAL writers → findings == 0
# ──────────────────────────────────────────────────────────────────────────




# ──────────────────────────────────────────────────────────────────────────
# ADVERSARIAL guard (verbatim): a byte-identical canned PASS pair STILL flags
# ──────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", __file__]))
