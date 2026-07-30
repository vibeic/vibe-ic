"""The phase-2 non-measurement must not outlive the phase-3 measurement.

Before v1.8.51, canonical Step 11 ran in phase 2 against a netlist the phase-3
runner had not written yet, gave up, renamed its artefacts to `*.unmeasured.*`
and wrote `dft_atpg_not_run.json` disclosing a CAPABILITY GAP. v1.8.51 made
phase 3 re-measure, so a real `coverage.json` now lands — but the phase-2
records stayed on disk beside it.

Both statements were true at the instant they were written and are false once
the measurement lands. Leaving them is how a later audit, or a human, quotes a
non-measurement as the result.

The cleanup is deliberately conservative: it fires ONLY on the success path, and
ONLY for a sibling whose canonical counterpart now exists and is non-empty. The
second test is the one that matters — an unmeasured record that is still the only
evidence must SURVIVE, because deleting it would erase the disclosure rather than
supersede it.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _dft(tmp_path: Path) -> Path:
    d = tmp_path / "phase2" / "stage2" / "dft"
    d.mkdir(parents=True)
    return d


def _seed_unmeasured(d: Path):
    (d / "atpg_coverage.unmeasured.rpt").write_text("no measurement\n")
    (d / "coverage.unmeasured.json").write_text(json.dumps({"measured": False}))
    (d / "coverage.unmeasured.yml").write_text("measured: false\n")
    (d / "dft_atpg_not_run.json").write_text(json.dumps(
        {"capability_flag": "cap:atpg_signoff_coverage",
         "reason": "OSS ATPG engine-limited (pdk=generic)"}))


def test_superseded_non_measurements_are_cleared(tmp_path):
    """A real coverage.json landed: the stale siblings must go."""
    d = _seed_unmeasured(tmp_path) or _dft(tmp_path)
    d = _dft(tmp_path) if not (tmp_path / "phase2").exists() else d
    _seed_unmeasured(d)
    (d / "coverage.json").write_text(json.dumps({"measured": True, "coverage": 97.0}))
    (d / "atpg_coverage.rpt").write_text("coverage 97.0\n")
    (d / "coverage.yml").write_text("coverage: 97.0\n")
    R._clear_superseded_dft_nonmeasurements(d)
    assert not (d / "coverage.unmeasured.json").exists()
    assert not (d / "atpg_coverage.unmeasured.rpt").exists()
    assert not (d / "coverage.unmeasured.yml").exists()
    assert not (d / "dft_atpg_not_run.json").exists()
    # the real measurement is untouched
    assert json.loads((d / "coverage.json").read_text())["coverage"] == 97.0


def test_unmeasured_record_survives_when_it_is_the_only_evidence(tmp_path):
    """CONTROL. No coverage.json => the disclosure is still the truth. Keep it.

    Deleting here would erase a disclosure instead of superseding it, which is
    strictly worse than the stale-artefact problem this fix exists to solve.
    """
    d = _dft(tmp_path)
    _seed_unmeasured(d)
    R._clear_superseded_dft_nonmeasurements(d)
    assert (d / "coverage.unmeasured.json").exists()
    assert (d / "dft_atpg_not_run.json").exists()


def test_empty_canonical_artefact_does_not_supersede(tmp_path):
    """CONTROL. A 0-byte coverage.json is not a measurement (D4)."""
    d = _dft(tmp_path)
    _seed_unmeasured(d)
    (d / "coverage.json").write_text("")
    R._clear_superseded_dft_nonmeasurements(d)
    assert (d / "coverage.unmeasured.json").exists()
