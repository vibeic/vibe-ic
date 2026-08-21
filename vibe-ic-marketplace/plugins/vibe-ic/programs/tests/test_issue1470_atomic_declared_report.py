"""The atomic-artefact ratchet is GREEN on main again — vibe-ic#1470.

WHAT #1470 IS ACTUALLY ABOUT
===========================
The issue was filed as "a ratchet shipped without its baseline file". That
reading is refuted by the tree: `programs/_atomic_artefact_residual.json` is
committed, `tools/ci/repo_hygiene_gates.sh` wires the check at top level and
unconditionally, and `gate_red_since.json` carries no acknowledgement row that
would soften it. So the baseline exists and is honoured.

What is REAL is the consequence the issue predicted from the other end: the
gate is a hard failure on main, and it was failing. Not on the 576 phantom
regressions an absent baseline would have manufactured — on a handful of
GENUINE post-baseline ones. Two programs landed after the residual was measured
and wrote their declared report destination with `Path(...).write_text(...)`:

    generated_artifact_conflict_resolve.py:391  .write_text(...)
    hygiene_finding_delta.py:420  .write_text(...)

Both are verdict-bearing. `generated_artifact_conflict_resolve` writes a
RESOLVED/REFUSED/UNMEASURABLE verdict a landing acts on; `hygiene_finding_delta`
writes the subset comparison that BLOCKS a landing. A truncated one of those is
read downstream as the step's own evidence — exactly the lie #1082 exists to
remove — so the fix is to convert them, never to widen the register.

WHY THE REGISTER IS NOT TOUCHED, AND WHY THAT IS ASSERTED HERE
==============================================================
Adding these two names to `_atomic_artefact_residual.json` would also have made
the gate exit 0. It would have bought the green by making the rule smaller,
which is worse than the failure it hides: the residual "may only ever shrink"
is the whole ratchet. `test_the_green_was_not_bought_by_widening_the_register`
is the assertion that pins that, so the cheap fix cannot be reintroduced later
and still look like this one.

AND THE PROPERTY IS CHECKED AT RUNTIME, NOT ONLY AS A SHAPE
===========================================================
Every other test around #1082 checks the SHAPE of the source — that no
`.write_text` reaches a declared destination. A shape assertion cannot tell a
converted program from one whose writer no longer runs. So the two runtime
tests below drive both real programs end to end and check the invariant the
issue is actually about, in both directions:

    the write succeeds  -> the declared destination exists and parses
    the write dies      -> the declared destination DOES NOT EXIST at all,
                           and no temp sibling is left behind

The second is only a measurement because the first exists: a program that wrote
nothing under any circumstances would satisfy "absent after a death" for free.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _atomic_artefact as A  # noqa: E402
import atomic_artifact_write_check as G  # noqa: E402
import generated_artifact_conflict_resolve as RESOLVER  # noqa: E402
import hygiene_finding_delta as DELTA  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
BASELINE = PROGRAMS / "_atomic_artefact_residual.json"

#: The two programs #1470 is about, pinned BY NAME. A count alone would also be
#: satisfied by deleting them, and by any later pair regressing in their place.
CONVERTED = ["generated_artifact_conflict_resolve", "hygiene_finding_delta"]

#: The register's size at the tranche that last pulled it down (#1082's
#: `open(..., 'w')` closure). It may SHRINK below this; growing past it is the
#: ratchet slipping.
REGISTER_CEILING = 515

_SYNTHETIC_OFFENDER = '''\
import argparse
import json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    Path(a.json_out).write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
'''


def _argv_resolver(dest: Path, repo: Path):
    return ["--repo", str(repo), "--dry-run", "--json", str(dest)]


def _argv_delta(dest: Path, repo: Path):
    # Both records are deliberately absent: the program REFUSES, and a refusal
    # is still a verdict it must write whole. Nothing here needs a real hygiene
    # run, which keeps this test far inside the 60s inner bound.
    return ["--base", str(repo / "absent_base.json"),
            "--candidate", str(repo / "absent_candidate.json"),
            "--base-host", "host-a", "--candidate-host", "host-a",
            "--json", str(dest)]


#: (label, module, argv-builder). Driven end to end in both runtime tests.
DRIVEN = [
    ("generated_artifact_conflict_resolve", RESOLVER, _argv_resolver),
    ("hygiene_finding_delta", DELTA, _argv_delta),
]


def test_the_detector_still_finds_this_shape(tmp_path):
    """POSITIVE CONTROL, and it is load-bearing.

    `test_the_two_programs_are_converted` asserts `scan_program` returns
    nothing. That passes vacuously against a broken detector — `return []`
    kills none of it. Hand the detector a program that plainly has the defect
    and require it to say so, so "nothing found" is a measurement.
    """
    p = tmp_path / "synthetic_offender.py"
    p.write_text(_SYNTHETIC_OFFENDER, encoding="utf-8")
    sites = G.scan_program(p) or []
    assert sites, "the detector found nothing in a program that plainly offends"
    assert any(s["form"] == ".write_text(...)" for s in sites), sites


def test_the_two_programs_are_converted():
    """Neither writes its declared report destination directly any more."""
    missing = [s for s in CONVERTED if not (PROGRAMS / f"{s}.py").is_file()]
    assert not missing, f"program(s) vanished rather than being converted: {missing}"
    still = {s: G.scan_program(PROGRAMS / f"{s}.py") for s in CONVERTED}
    assert not any(still.values()), {k: v for k, v in still.items() if v}


def test_the_gate_is_green_and_the_ratchet_holds():
    """The failure #1470 reports, gone — measured the way CI measures it.

    `--strict` only, deliberately: it is the plain verdict PLUS the growth
    check, so one invocation subsumes both, and each invocation is a full AST
    sweep of ~1170 programs. Two of them exceeded the harness's 180s bound on a
    loaded host, which would make this file flaky for a reason that has nothing
    to do with the property under test.
    """
    assert G.main([str(PROGRAMS), "--strict"]) == 0


def test_the_green_was_not_bought_by_widening_the_register():
    """Adding these two names to the residual would ALSO have exited 0.

    That is the failure mode this repo keeps paying for: a gate turned green by
    shrinking the rule. The register must not name them, and must not have
    grown to make room for them.
    """
    recorded = set(json.loads(BASELINE.read_text(encoding="utf-8"))["offenders"])
    assert len(recorded) <= REGISTER_CEILING, len(recorded)
    for s in CONVERTED:
        assert f"{s}.py" not in recorded, (
            f"{s} was excused into the residual instead of converted")


def test_the_declared_report_is_written_on_success(tmp_path):
    """The writers still write. Without this, the death test below is free."""
    for label, mod, argv in DRIVEN:
        dest = tmp_path / f"{label}.json"
        mod.main(argv(dest, tmp_path))
        assert dest.is_file(), f"{label} produced no declared report"
        doc = json.loads(dest.read_text(encoding="utf-8"))
        assert isinstance(doc, dict) and doc, f"{label} wrote an empty record"


def test_the_declared_report_appears_only_when_complete(tmp_path, monkeypatch):
    """THE INVARIANT, at runtime: a write that dies leaves NO final name.

    The death is injected at `os.fsync`, which `_atomic_artefact.writing` calls
    after the last byte and before the rename — i.e. inside the exact window
    `Path.write_text` cannot protect, where the old form would already have
    created and truncated the destination. `monkeypatch` restores it, so the
    blast radius is this test.
    """
    def _die(*_a, **_k):
        raise OSError("simulated death between the last byte and the rename")

    monkeypatch.setattr(A.os, "fsync", _die)
    for label, mod, argv in DRIVEN:
        dest = tmp_path / f"{label}.json"
        try:
            mod.main(argv(dest, tmp_path))
        except OSError:
            pass          # some writers report the failure, some propagate it
        assert not dest.exists(), (
            f"{label} left a declared report under its final name after the "
            f"write died — a consumer cannot tell it from a complete one")
    litter = [p.name for p in tmp_path.iterdir() if A.is_temp_artefact(p)]
    assert not litter, f"temp artefact(s) left behind: {litter}"


def test_the_form_this_replaced_really_did_leave_a_file(tmp_path):
    """The CONTRAST, so the test above is a difference and not a tautology.

    Same failure, same payload, the two forms side by side on a real
    filesystem. `Path.write_text` creates the final name and fills it second,
    so the name survives the failure with incomplete contents; the helper
    leaves nothing. `_atomic_artefact`'s own docstring names this: a 0-byte
    file and a finished report are the same answer to `required_outputs`.
    """
    # Encodable prefix, then one code point utf-8 cannot emit: the encoder
    # raises with the destination already opened.
    payload = "x" * 200_000 + "\udcff"

    old = tmp_path / "old_form.json"
    try:
        old.write_text(payload, encoding="utf-8")
    except UnicodeEncodeError:
        pass
    assert old.exists(), (
        "the pre-fix form no longer leaves a file under the final name — this "
        "control no longer models the defect and must be re-derived")
    assert old.stat().st_size < len(payload), "expected an INCOMPLETE artefact"

    new = tmp_path / "new_form.json"
    try:
        A.write_text(new, payload)
    except UnicodeEncodeError:
        pass
    assert not new.exists(), "the helper left a final name after a failed write"
    assert not [p for p in tmp_path.iterdir() if A.is_temp_artefact(p)]
