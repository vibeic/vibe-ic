"""#1119 — the three states of "are these bytes the bytes THIS RUN produced?".

`_run_evidence_binding` answers one question and answers it in three ways, and
collapsing any two of them is the defect it exists to prevent:

    BOUND       a register names this relpath and the bytes agree
    MISMATCH    a register names it and the bytes DISAGREE — somebody replaced
                the evidence after the run recorded it
    UNRECORDED  no register names it. NOTHING IS CLAIMED, and the disclosure
                says so, because a gate that quietly found no register must not
                read the same as a gate that checked and was happy.

These are the module's own tests. The GATE behaviour built on it — and the
adversarial attacks that motivated it — are in
`test_signoff_evidence_belongs_to_this_run.py`.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_evidence_binding as reb  # noqa: E402
import _published_corpus as _pc  # noqa: E402

# --------------------------------------------------------------------------- #
# fixtures — two runs that are both HONEST and both CLEAN
# --------------------------------------------------------------------------- #
#: A clean antenna report. Tool-signed and above the size floor, so every
#: pre-existing content check in `--mode antenna` passes on it.
_ANTENNA = (
    "# openroad antenna check (gate-oxide protection)\n"
    "# Tool: openroad / check_antennas (ANT).\n"
    "# Emitted by the flow's routing step; the counts below are the\n"
    "# post-repair measurement of the realized routing.\n"
    "antenna check: 0 net violations, 0 pin violations\n"
    "antenna clean: YES\n"
    "[INFO ANT-0002] Found 0 net violations.\n"
    "[INFO ANT-0001] Found 0 pin violations.\n"
    "routing complete: YES\n"
    "# run marker: {marker}\n"
)

def _density(marker: str) -> str:
    """A clean density artefact for `erc_density_check`. Row utilization, in
    range, tool-signed — everything the gate's own content checks want."""
    return json.dumps({
        "tool": "openroad",
        "check": "filler_placement",
        "row_utilization_pct": 42.0,
        "run_marker": marker,
    }, indent=2) + "\n"

_ERC = (
    "# openroad ERC report\n"
    "# Tool: openroad.\n"
    "ERC floating nets: 0\n"
    "ERC clean: YES\n"
    "# run marker: {marker}\n"
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _build_run(root: Path, marker: str, register: str = "both") -> Path:
    """A complete, honest, self-consistent run tree.

    `register` selects which run-evidence register the tree carries, so a test
    can prove each one binds on its own rather than relying on the union.
    """
    root.mkdir(parents=True, exist_ok=True)
    rels = {
        "reports/phase3/antenna.rpt": _ANTENNA.format(marker=marker),
        "reports/density.json": _density(marker),
        "reports/phase3/erc.rpt": _ERC.format(marker=marker),
    }
    written = {rel: _write(root, rel, text) for rel, text in rels.items()}
    digests = {rel: _sha(p) for rel, p in written.items()}

    if register in ("both", "step_record"):
        _write(root, "steps/phase3/stage3/26_antenna/STEP_RECORD.json",
               json.dumps({
                   "id": "26", "status": "pass",
                   "declared_outputs": [
                       {"rel": rel, "sha256": digests[rel], "in_cell": True}
                       for rel in rels],
               }, indent=2) + "\n")
    if register in ("both", "provenance"):
        _write(root, "provenance.jsonl", "".join(
            json.dumps({"tool": "openroad", "exit_code": 0,
                        "outputs": {rel: "sha256:" + digests[rel]}}) + "\n"
            for rel in rels))
    return root


def _run(program: str, project: Path, *argv: str):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / f"{program}.py"), str(project), *argv],
        capture_output=True, text=True, timeout=300)


def _substitute(target: Path, donor: Path, rel: str) -> None:
    """The attack, reduced to one file: donor's bytes at the target's path."""
    shutil.copy2(donor / rel, target / rel)


# --------------------------------------------------------------------------- #
# the module's own three states
# --------------------------------------------------------------------------- #
def test_an_artefact_this_run_recorded_is_BOUND(tmp_path):
    run = _build_run(tmp_path / "run", "A")
    a = reb.assess(run, [run / "reports/phase3/antenna.rpt"])
    assert [b.state for b in a.bindings] == [reb.BOUND]
    assert a.summary()["mismatched"] == 0


def test_another_runs_bytes_at_the_same_path_are_MISMATCH(tmp_path):
    run = _build_run(tmp_path / "run", "A")
    other = _build_run(tmp_path / "other", "B")
    _substitute(run, other, "reports/phase3/antenna.rpt")
    a = reb.assess(run, [run / "reports/phase3/antenna.rpt"])
    assert [b.state for b in a.bindings] == [reb.MISMATCH]
    assert a.summary()["mismatched_paths"] == ["reports/phase3/antenna.rpt"]


def test_an_artefact_no_register_names_is_UNRECORDED_not_a_failure(tmp_path):
    run = _build_run(tmp_path / "run", "A")
    _write(run, "reports/phase3/extra.rpt", "# openroad\nsomething\n")
    a = reb.assess(run, [run / "reports/phase3/extra.rpt"])
    assert [b.state for b in a.bindings] == [reb.UNRECORDED]
    assert a.summary()["mismatched"] == 0
    assert "UNVERIFIED" in a.disclosure()


@pytest.mark.parametrize("register", ["provenance", "step_record"])
def test_either_register_binds_on_its_own(tmp_path, register):
    run = _build_run(tmp_path / register, "A", register=register)
    other = _build_run(tmp_path / (register + "_other"), "B", register=register)
    rel = "reports/phase3/antenna.rpt"
    clean = reb.assess(run, [run / rel])
    assert clean.summary()["bound"] == 1, clean.disclosure()
    _substitute(run, other, rel)
    dirty = reb.assess(run, [run / rel])
    assert dirty.summary()["mismatched"] == 1, dirty.disclosure()


def test_a_path_recorded_twice_binds_to_EITHER_recorded_value(tmp_path):
    """A run that writes one path twice records two digests for it. Both are
    values THIS RUN produced; refusing the earlier one would fire on an honest
    tree, which is the false-positive shape §2 forbids."""
    run = _build_run(tmp_path / "run", "A")
    rel = "reports/phase3/antenna.rpt"
    first = _sha(run / rel)
    (run / rel).write_text(_ANTENNA.format(marker="A-second-write"),
                           encoding="utf-8")
    second = _sha(run / rel)
    assert first != second
    _write(run, "steps/phase3/stage3/26_antenna/STEP_RECORD.json",
           json.dumps({"id": "26", "declared_outputs": [
               {"rel": rel, "sha256": first}, {"rel": rel, "sha256": second}]}))
    (run / "provenance.jsonl").unlink()
    a = reb.assess(run, [run / rel])
    assert [b.state for b in a.bindings] == [reb.BOUND]
    assert a.summary()["ambiguous_ledger_paths"] == 1


def test_a_truncated_register_line_degrades_to_UNRECORDED_never_to_MISMATCH(tmp_path):
    """provenance.jsonl is append-only; a run killed mid-append leaves half a
    line. That must cost coverage, never manufacture a forgery finding."""
    run = _build_run(tmp_path / "run", "A", register="provenance")
    prov = run / "provenance.jsonl"
    prov.write_text(prov.read_text(encoding="utf-8").rstrip("\n")[:-25],
                    encoding="utf-8")
    a = reb.assess(run, [run / "reports/phase3/antenna.rpt"])
    assert a.summary()["mismatched"] == 0
    assert [b.state for b in a.bindings] in ([reb.BOUND], [reb.UNRECORDED])


def test_no_register_at_all_is_DISCLOSED_and_never_silent(tmp_path):
    run = tmp_path / "bare"
    _write(run, "reports/phase3/antenna.rpt", _ANTENNA.format(marker="A"))
    a = reb.assess(run, [run / "reports/phase3/antenna.rpt"])
    assert a.summary()["registers_read"] == 0
    assert "NOTHING was verified" in a.disclosure()


