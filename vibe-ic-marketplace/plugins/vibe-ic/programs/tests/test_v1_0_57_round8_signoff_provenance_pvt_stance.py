"""Round-8 caravel (7th IC) sign-off — two runner-vs-gate reconciliations
(same class as #692's durable-attestation pattern).

ORGANIC #693 [MED] — sign-off DRC report provenance stamp at EMIT TIME.
  The #620 PV-provenance append (`_v1_6_620_append_pv_signoff_provenance`)
  runs INSIDE step_canonicalize_artefacts at line ~7472, BEFORE the sign-off
  DRC report `reports/phase3/drc_signoff.rpt` is written at line ~7725. So at
  append time the report does not yet exist on disk, the declarer's
  `fp.is_file()` skips it, and Step-31 `provenance_check --output
  reports/phase3/drc_signoff.rpt` FAILs — even on a DRC-clean (0 violations) +
  LVS-match-uniquely layout. The fix re-runs the idempotent declarer right
  after the report is written, so the report gets a matching provenance entry
  (tool + output + REAL sha) at emit time.

  POSITIVE: write drc_signoff.rpt → declarer stamps it → provenance_check
            FAIL → PASS.
  §4.05 NEGATIVE no-leak: a report that does NOT exist on disk is NOT
            fabricated (the declarer skips it), so provenance still FAILs a
            missing/never-produced report. Idempotent: a second run adds
            nothing.

ORGANIC #694 [MED] — single-corner stance attestation defers pvt_matrix_check
  on a single-corner open PDK (e.g. sky130A ships nominal/tt only). #442's
  gate demands ≥2 corners OR an explicit single-corner disclosure, but the
  runner emitted neither — so a legitimate single-corner run was scored
  corner_count=0 hard FAIL. The runner now writes
  `reports/phase3/single_corner_stance.json` (corner names + rationale +
  review_required) when <2 corners are available and multi-corner is NOT
  claimed; pvt_matrix_check reads it and returns SINGLE_CORNER_STANCE_DISCLOSED
  (exit 0, PASS-with-review).

  POSITIVE: empty matrix + disclosed stance → pvt_matrix_check FAIL → DEFER.
  §4.05 NEGATIVE no-leak:
    - empty matrix that CLAIMS multi_corner=true STILL FAILs even with a
      stance present (the stance never rescues a contradictory claim);
    - a stance file that itself claims multi-corner does NOT rescue;
    - a malformed stance file does NOT rescue;
    - no stance at all → empty matrix still FAILs.

chip-AGNOSTIC: canonical PV paths, real sha256, structural JSON shape only —
no chip / vendor / SKU literal.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase3_one_shot_runner as P  # noqa: E402
import pvt_matrix_check as PMC      # noqa: E402

PROVCHK = str(PLUGIN / "programs" / "provenance_check.py")
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


# --------------------------------------------------------------------------
# #693 — sign-off DRC report provenance stamp at EMIT TIME
# --------------------------------------------------------------------------
#: A real, clean KLayout sign-off report database. The provenance declarer now
#: derives the tool from the artefact, so a fixture standing in for "the
#: sign-off DRC report" has to carry the format it claims.
_KLAYOUT_RDB = ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
                "<report-database>\n"
                "  <generator>drc: script='/pdk/tech/klayout/drc/deck.lydrc'"
                "</generator>\n"
                "  <top-cell>chip_top</top-cell>\n"
                "  <items></items>\n"
                "</report-database>\n")


def _sha(p):
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return "sha256:" + h.hexdigest()


def _mk_proj(tmp_path):
    (tmp_path / "provenance.jsonl").write_text(
        json.dumps({"tool": "openroad", "exit_code": 0,
                    "outputs": {"phase3/stage3/pnr/routed.def": "sha256:bb"}})
        + "\n")
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    return tmp_path


def _provchk(tmp_path, rel, tools):
    return subprocess.run(
        [sys.executable, PROVCHK, str(tmp_path),
         "--output", rel, "--tool", tools],
        capture_output=True, text=True)


def test_693_drc_signoff_declared_at_emit_time(tmp_path):
    """POSITIVE: once drc_signoff.rpt exists, the declarer stamps it and the
    Step-31 gate goes FAIL → PASS."""
    _mk_proj(tmp_path)
    rel = "reports/phase3/drc_signoff.rpt"
    # BEFORE: report not on disk → gate FAILs (nothing declares the path).
    assert _provchk(tmp_path, rel, "klayout,magic,openroad").returncode == 1
    # The runner writes the sign-off DRC report (emit step), THEN our fix
    # re-runs the declarer at emit time.
    (tmp_path / rel).write_text(_KLAYOUT_RDB)
    declared = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert rel in declared
    # AFTER: the gate now PASSes.
    assert _provchk(tmp_path, rel, "klayout,magic,openroad").returncode == 0


def _stamped(tmp_path, rel):
    entry = None
    for line in (tmp_path / "provenance.jsonl").read_text().splitlines():
        if line.strip() and rel in line:
            entry = json.loads(line)
    return entry


def test_693_real_sha_and_tool_stamped(tmp_path):
    _mk_proj(tmp_path)
    rel = "reports/phase3/drc_signoff.rpt"
    fp = tmp_path / rel
    fp.write_text(_KLAYOUT_RDB)
    P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    entry = _stamped(tmp_path, rel)
    assert entry is not None
    assert entry["tool"] == "klayout"
    assert entry["outputs"][rel] == _sha(fp)  # REAL hash, not a placeholder


def test_693_tool_is_derived_from_the_artefact_not_assumed(tmp_path):
    """The `klayout` above must be MEASURED, not a constant.

    The fixture used to be `"# Sign-off DRC report\\nviolations=0"` — a file
    with no producer signature at all — and the assertion `tool == "klayout"`
    still held, because the declarer hardcoded it. That is the laundering the
    Step-31 provenance allow-list could never see through: with `klayout`
    stamped unconditionally, removing `openroad` from the allow-list changes
    nothing at all.
    """
    _mk_proj(tmp_path)
    rel = "reports/phase3/drc_signoff.rpt"
    (tmp_path / rel).write_text(
        "# Sign-off DRC report (Step 31 alias).\n"
        "# Source: phase3/stage3/pnr/routed.drc.rpt\n"
        "# Tool: openroad\n#\n"
        "openroad / drt-pass: detailed_route invoked\n"
        "violation report: 0\nDRC clean: YES\n"
        + "".join(f"[INFO DRT-{2000 + i:04d}] region query size = {i}.\n"
                  for i in range(80)))
    P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert _stamped(tmp_path, rel)["tool"] == "openroad"
    # and the allow-list can now do its job
    assert _provchk(tmp_path, rel, "klayout,magic,svrfdrc").returncode == 1


def test_693_negative_absent_report_not_fabricated(tmp_path):
    """§4.05: a report that was never produced is NOT declared; the gate
    still FAILs (no blanket pass)."""
    _mk_proj(tmp_path)
    rel = "reports/phase3/drc_signoff.rpt"
    # do NOT create the report
    declared = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert rel not in declared
    assert _provchk(tmp_path, rel, "klayout,magic,openroad").returncode == 1


def test_693_idempotent_emit_time_rerun(tmp_path):
    _mk_proj(tmp_path)
    rel = "reports/phase3/drc_signoff.rpt"
    (tmp_path / rel).write_text("violations=0\n")
    P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    second = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert rel not in second
    cnt = (tmp_path / "provenance.jsonl").read_text().count(
        '"reports/phase3/drc_signoff.rpt"')
    assert cnt == 1


def test_693_source_calls_declarer_after_writing_drc_signoff(tmp_path):
    """Source pin: the emit-time #693 stamp re-runs the declarer in the same
    region that writes drc_signoff.rpt."""
    assert "#693" in _P3_SRC
    assert "drc_signoff.rpt" in _P3_SRC
    # the declarer is invoked from the drc_signoff emit block (after write).
    idx_write = _P3_SRC.index("drc_signoff.write_text(")
    idx_693 = _P3_SRC.index("#693: declared sign-off DRC report")
    assert idx_693 > idx_write


# --------------------------------------------------------------------------
# #694 — single-corner stance defers pvt_matrix_check
# --------------------------------------------------------------------------
def _matrix(tmp_path, payload):
    d = tmp_path / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pvt_matrix.json").write_text(json.dumps(payload))
    return tmp_path


def _stance(tmp_path, payload):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "single_corner_stance.json").write_text(json.dumps(payload))


_VALID_STANCE = {
    "program": "phase3_one_shot_runner",
    "stance": "SINGLE_CORNER_DISCLOSED",
    "corner_count": 0,
    "corners": [],
    "primary_corner": "TT",
    "multi_corner_claimed": False,
    "rationale": "single-corner PDK disclosed per #442/#694",
    "review_required": True,
}


def test_694_empty_matrix_with_stance_defers(tmp_path):
    """POSITIVE: empty matrix + valid disclosed stance → DEFER (exit 0),
    not FAIL."""
    _matrix(tmp_path, {"corners": [], "primary_corner": "TT"})
    _stance(tmp_path, _VALID_STANCE)
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 0
    assert rep["verdict"] == "SINGLE_CORNER_STANCE_DISCLOSED"
    assert rep["review_required"] is True


def test_694_empty_matrix_no_stance_still_fails(tmp_path):
    """§4.05: no stance at all → empty matrix still FAILs (#442 unchanged)."""
    _matrix(tmp_path, {"corners": [], "primary_corner": "TT"})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"


def test_694_contradictory_multi_corner_claim_still_fails_with_stance(tmp_path):
    """§4.05: an empty matrix that CLAIMS multi_corner=true STILL FAILs even
    with a valid stance present — the stance never rescues a contradictory
    claim."""
    _matrix(tmp_path, {"corners": [], "multi_corner": True})
    _stance(tmp_path, _VALID_STANCE)
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"
    assert "contradictory" in rep["reason"]


def test_694_stance_claiming_multi_corner_does_not_rescue(tmp_path):
    """§4.05: a stance file that itself claims multi-corner is not a valid
    single-corner disclosure → does NOT rescue."""
    _matrix(tmp_path, {"corners": [], "primary_corner": "TT"})
    _stance(tmp_path, {"stance": "SINGLE_CORNER_DISCLOSED",
                       "multi_corner_claimed": True})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"


def test_694_malformed_stance_does_not_rescue(tmp_path):
    """§4.05: a malformed / non-disclosing stance file does NOT rescue."""
    _matrix(tmp_path, {"corners": [], "primary_corner": "TT"})
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "single_corner_stance.json").write_text("{ not json")
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"


def test_694_wrong_stance_string_does_not_rescue(tmp_path):
    """A stance file present but without the SINGLE_CORNER_DISCLOSED stance
    string does NOT rescue (only an explicit disclosure defers)."""
    _matrix(tmp_path, {"corners": [], "primary_corner": "TT"})
    _stance(tmp_path, {"stance": "SOMETHING_ELSE",
                       "multi_corner_claimed": False})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"


def test_694_two_corners_still_multi_unaffected(tmp_path):
    """The stance path NEVER touches a real multi-corner matrix."""
    _matrix(tmp_path, {"corners": [
        {"name": "a", "label": "SS"}, {"name": "b", "label": "FF"}]})
    _stance(tmp_path, _VALID_STANCE)  # stance present but irrelevant
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "MULTI_CORNER"


def test_694_single_real_corner_still_single_corner_only(tmp_path):
    """Exactly 1 corner is honest single-corner already (#442) and is not
    re-routed through the empty-matrix stance path."""
    _matrix(tmp_path, {"corners": [{"name": "lib_tt", "label": "TT"}]})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "SINGLE_CORNER_ONLY"


def test_694_runner_emits_stance_when_under_two_corners(tmp_path):
    """Source pin: the runner emits single_corner_stance.json only when <2
    corners and multi-corner is NOT claimed."""
    assert "#694" in _P3_SRC
    assert "single_corner_stance.json" in _P3_SRC
    assert "SINGLE_CORNER_DISCLOSED" in _P3_SRC
    # guarded by the <2-corner + not-multi_corner condition
    assert "len(corners) < 2 and not pvt.get(\"multi_corner\")" in _P3_SRC
