"""#1119 — a sign-off gate must not certify a design from another run's reports.

WHAT WAS MEASURED, AND WHY THESE ASSERTIONS ARE SHAPED THIS WAY
===============================================================
`adversarial_agent` run against the published corpus with the gates' own CLIs
produced THIRTEEN forged greens: six gates certified a design after its reports
were replaced with a DIFFERENT design's (`A3_CROSS_DESIGN`), the same six
certified it after they were replaced with an EARLIER run of the same design's
(`A2_STALE_REPLAY`), and one stayed green after its reports were destroyed
outright (`A1_TAMPER_DESTRUCTIVE`, `--mode ir_drop`, rescued by a companion
JSON the attack did not touch).

The substituted reports were CLEAN and WELL-FORMED. Every content check the
gates already run — tool signature, size floor, violation count, verdict token
— passed on them, because they are real reports; they are just not this run's.
So a test that feeds a gate a MALFORMED report proves nothing about this
defect. Every fixture below is a report that would legitimately PASS, and the
only thing separating the two arms is WHOSE RUN produced it.

BIDIRECTIONAL, AND THE `clears` HALF IS NEVER PRESENTED ALONE
=============================================================
`flow-change-acceptance` §1: each `..._is_refused` test ships beside a
`..._is_accepted` sibling over the SAME tree, so a change that made the gate
refuse everything would fail here rather than look like progress.
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
# the gates — bidirectional, over the SAME tree
# --------------------------------------------------------------------------- #
_GATES = [
    ("antenna_report_check", ("--mode", "antenna"), "reports/phase3/antenna.rpt"),
    ("erc_density_check", (), "reports/density.json"),
    ("erc_density_check", (), "reports/phase3/erc.rpt"),
]


@pytest.mark.parametrize("program,argv,rel", _GATES)
def test_the_untouched_run_is_ACCEPTED(tmp_path, program, argv, rel):
    """The `clears` half. Never read alone — its sibling below is the control."""
    run = _build_run(tmp_path / "run", "A")
    r = _run(program, run, *argv)
    assert r.returncode == 0, r.stdout[-3000:]
    assert reb.RULE not in r.stdout


@pytest.mark.parametrize("program,argv,rel", _GATES)
def test_another_runs_report_is_REFUSED(tmp_path, program, argv, rel):
    """THE DEFECT. The donor's report is clean and well-formed: the ONLY thing
    that differs is which run produced it."""
    run = _build_run(tmp_path / "run", "A")
    other = _build_run(tmp_path / "other", "B")
    assert _run(program, run, *argv).returncode == 0, "arm setup: not green first"
    _substitute(run, other, rel)
    r = _run(program, run, *argv)
    assert r.returncode == 1, r.stdout[-3000:]
    assert reb.RULE in r.stdout
    assert rel in r.stdout


def test_the_donors_report_would_have_passed_on_its_OWN_tree(tmp_path):
    """The discrimination control: proves the refusal above is about RUN
    IDENTITY and not about the donor's bytes being defective in some way the
    content checks would have caught anyway."""
    other = _build_run(tmp_path / "other", "B")
    assert _run("antenna_report_check", other, "--mode", "antenna").returncode == 0
    assert _run("erc_density_check", other).returncode == 0


def test_a_run_with_no_register_is_still_accepted_and_says_so(tmp_path):
    """UNRECORDED must not become a failure — that would redden every local run
    and every imported tree."""
    run = tmp_path / "bare"
    _write(run, "reports/phase3/antenna.rpt", _ANTENNA.format(marker="A"))
    r = _run("antenna_report_check", run, "--mode", "antenna")
    assert r.returncode == 0, r.stdout[-2000:]
    doc = json.loads(r.stdout)
    binding = doc["summary"]["evidence_binding"]
    assert binding["registers_read"] == 0
    assert "NOTHING was verified" in binding["disclosure"]


def test_every_gate_verdict_carries_the_binding_disclosure(tmp_path):
    """§6 degrade-loudly: a gate that did not verify provenance must SAY so in
    its own verdict document, not merely omit the claim."""
    run = _build_run(tmp_path / "run", "A")
    r = _run("antenna_report_check", run, "--mode", "antenna")
    doc = json.loads(r.stdout)
    assert "evidence_binding" in doc["summary"]
    assert doc["summary"]["evidence_binding"]["disclosure"]
    r2 = _run("erc_density_check", run)
    doc2 = json.loads(r2.stdout)
    assert doc2["summary"]["evidence_binding"]["disclosure"]


# --------------------------------------------------------------------------- #
# REAL ARTEFACTS — §4: a suite made only of its own fixtures cannot tell itself
# from its own absence.
# --------------------------------------------------------------------------- #
@_pc.needs_corpus
def test_no_published_cell_disagrees_with_its_own_ledger():
    """The corpus sweep, as an assertion rather than a claim in a report.

    If this ever fires it is EITHER a real tampering finding OR proof the gate
    is a false-positive machine — and either way somebody must look, which is
    exactly what a gate is for."""
    cells = _pc.cell_dirs()
    assert cells, _pc.SKIP_REASON
    checked = 0
    for cell in cells:
        led = reb.load_ledger(cell)
        if not led.entries:
            continue
        a = reb.assess(cell, [cell / rel for rel in led.entries], led)
        assert a.summary()["mismatched"] == 0, (
            f"{cell.name}: {a.summary()['mismatched_paths']}")
        checked += a.summary()["bound"]
    assert checked > 0, "no published cell carried a readable ledger entry"


@_pc.needs_corpus
def test_a_real_cells_report_swapped_for_another_real_cells_is_caught():
    """Driven end to end by checked-in artefacts, not by fixtures authored in
    this commit. Two published cells, one real report path, one copy."""
    cells = [c for c in _pc.cell_dirs() if reb.load_ledger(c).entries]
    if len(cells) < 2:
        pytest.skip("fewer than two published cells carry a run-evidence "
                    "register here; this needs a donor and a target")
    target = cells[0]
    led = reb.load_ledger(target)
    donor = next((c for c in cells[1:]
                  if any((c / rel).is_file() and
                         _sha(c / rel) not in led.entries[rel]
                         for rel in led.entries if (target / rel).is_file())),
                 None)
    if donor is None:
        pytest.skip("no second published cell shares a recorded artefact path "
                    "with the first")
    rel = next(rel for rel in led.entries
               if (target / rel).is_file() and (donor / rel).is_file()
               and _sha(donor / rel) not in led.entries[rel])
    a = reb.assess(target, [donor / rel], led)
    # `assess` keys on the project-relative path, so handing it the donor's
    # file at the target's recorded relpath is the substitution, without
    # writing a byte into the published tree.
    assert a.bindings and a.bindings[0].state in (reb.MISMATCH, reb.UNRECORDED)
