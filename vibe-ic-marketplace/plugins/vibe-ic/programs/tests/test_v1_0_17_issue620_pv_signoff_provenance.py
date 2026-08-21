"""ORGANIC #620 [MEDIUM] — step_canonicalize_artefacts idempotently appended
provenance.jsonl entries for the synth netlist, routed.def, and the SPEF
(#509/#590), but NOT for the sign-off DRC report (klayout), the LVS report
(netgen/magic), or the streamout GDS. flow_compliance Step 31 (Physical
Verification) runs `provenance_check --output reports/phase3/drc_signoff.rpt`;
with no provenance entry declaring that path, the gate FAILed even when sign-off
DRC = 0 violations and LVS = "Circuits match uniquely". A genuinely clean
sign-off was reported FAIL purely on missing provenance bookkeeping.

OBSERVED (a datapath multiplier IC reached Step 38, real 444MB GDS, signoff DRC
0 violations, LVS match-uniquely): provenance.jsonl had only 3 entries
(synth/pnr-bundle/spef); none declared reports/phase3/drc_signoff.rpt.

Fix: `_v1_6_620_append_pv_signoff_provenance` idempotently declares the PV
sign-off outputs (DRC/LVS/GDS) keyed on canonical paths, each with its REAL
sha256 + tool attribution, mirroring the SPEF append.

POSITIVE (#620): provenance_check --output reports/phase3/drc_signoff.rpt goes
FAIL → PASS after the append.

NEGATIVE no-leak (anti-fabrication):
  - a report that does NOT exist on disk is NOT declared (no fabrication);
    provenance.jsonl is not even created when there is nothing real.
  - the declared sha256 is the file's REAL hash (not a placeholder).
  - idempotent: a second invocation declares nothing new.

chip-AGNOSTIC: canonical PV paths + real sha256, no chip name.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase3_one_shot_runner as P  # noqa: E402

PROVCHK = str(PLUGIN / "programs" / "provenance_check.py")


def _sha(p):
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return "sha256:" + h.hexdigest()


def _mk(tmp_path, with_drc=True, with_lvs=True, with_gds=True):
    (tmp_path / "provenance.jsonl").write_text(
        json.dumps({"tool": "openroad", "exit_code": 0,
                    "outputs": {"phase3/stage3/pnr/routed.def": "sha256:bb"}}) + "\n")
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    if with_drc:
        # A real, clean KLayout report database. It used to be the one-line
        # stub `"<klayout drc-rdb> total 0 violations"`, which was fine while
        # the declarer hardcoded `tool: "klayout"` for whatever sat at this
        # path — and that hardcoding is exactly the defect the sign-off
        # producer work closes. The attribution is now derived from the
        # artefact, so the fixture has to BE the thing it stands for. Same
        # subject (provenance bookkeeping), honest input.
        (tmp_path / "reports/phase3/drc_signoff.rpt").write_text(
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<report-database>\n"
            "  <generator>drc: script='/pdk/tech/klayout/drc/deck.lydrc'"
            "</generator>\n"
            "  <top-cell>chip_top</top-cell>\n"
            "  <items></items>\n"
            "</report-database>\n")
    if with_lvs:
        (tmp_path / "reports/phase3/lvs.rpt").write_text(
            "Circuits match uniquely.\n")
    if with_gds:
        (tmp_path / "phase3/stage4/gds").mkdir(parents=True)
        (tmp_path / "phase3/stage4/gds/chip_top.gds").write_text("GDS\n")
    return tmp_path


def _declared_paths(tmp_path):
    out = set()
    for line in (tmp_path / "provenance.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        for k in (json.loads(line).get("outputs") or {}):
            out.add(k)
    return out


def test_pv_signoff_outputs_declared_with_real_sha(tmp_path):
    _mk(tmp_path)
    declared = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert set(declared) == {
        "reports/phase3/drc_signoff.rpt", "reports/phase3/lvs.rpt",
        "phase3/stage4/gds/chip_top.gds"}
    paths = _declared_paths(tmp_path)
    assert "reports/phase3/drc_signoff.rpt" in paths
    # the declared sha256 must be the file's REAL hash
    for line in (tmp_path / "provenance.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        for k, v in (json.loads(line).get("outputs") or {}).items():
            if k == "reports/phase3/drc_signoff.rpt":
                assert v == _sha(tmp_path / k)


def test_provenance_check_fail_then_pass(tmp_path):
    _mk(tmp_path)

    def gate():
        return subprocess.run(
            [sys.executable, PROVCHK, str(tmp_path),
             "--output", "reports/phase3/drc_signoff.rpt", "--tool", "klayout"],
            capture_output=True, text=True).returncode
    assert gate() != 0, "before the append the gate must FAIL (#620 現象)"
    P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert gate() == 0, "after the append the gate must PASS"


def test_idempotent(tmp_path):
    _mk(tmp_path)
    first = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert first
    second = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert second == [], "a second invocation must declare nothing new"


def test_anti_fabrication_missing_report_not_declared(tmp_path):
    # no PV outputs on disk at all → nothing declared, no provenance created.
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    declared = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert declared == []
    assert not (tmp_path / "provenance.jsonl").exists()


def test_partial_only_declares_existing(tmp_path):
    # only the DRC report exists → only it is declared (LVS/GDS absent).
    _mk(tmp_path, with_lvs=False, with_gds=False)
    declared = P._v1_6_620_append_pv_signoff_provenance(tmp_path, "chip_top")
    assert declared == ["reports/phase3/drc_signoff.rpt"]
