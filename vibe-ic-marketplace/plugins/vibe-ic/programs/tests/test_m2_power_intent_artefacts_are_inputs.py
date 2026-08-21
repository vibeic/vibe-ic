#!/usr/bin/env python3
"""M2-d4 — direction-1 guard on the shape of the KNOWN power-intent gap.

M2 declares three ``required_outputs``::

    reports/analog/mixed_signal/power_domain.json
    reports/analog/mixed_signal/level_shifter.json
    reports/analog/mixed_signal/isolation.json

and no program in this plugin writes any of them: every occurrence across the
tree is a consumer, a checker or a test fixture.  They are INPUTS — the power
intent plus the protection cells the UPF-driven implementation flow actually
inserted.  The gap is real and is deliberately left declared and RED (see the
M2 block in the flow yaml); closing it needs a real emitter reading the UPF
*and* the post-PnR netlist, which is an owner decision, not a declaration edit.

What this file guards is the TWO CHEAP WAYS the red could be made to go away
without the substance ever being established:

  1. a checker that supplies its own input — writing a power_domain.json (or
     either sidecar) when it finds none.  An empty ``crossings`` list makes
     ``power_domain_crossing_check`` report "0 crossings audited; all required
     cells present" — a PASS carrying no information at all.
  2. a checker that treats absent power intent as a clean result instead of a
     disclosed skip.

Both must stay impossible whether or not an emitter is ever shipped, so these
assertions are about OBSERVED behaviour on an empty project and hold equally
well the day a real producer lands.

chip-AGNOSTIC: synthetic fixtures only.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

_DIR = "reports/analog/mixed_signal"
_SIDECARS = ("power_domain.json", "level_shifter.json", "isolation.json")

# The four programs M2's gate runs, with the --json evidence path each is
# invoked with in the flow yaml.
_M2_GATES = (
    ("power_domain_crossing_check", f"{_DIR}/power_domain_crossing_audit.json"),
    ("level_shifter_required_check", f"{_DIR}/level_shifter_audit.json"),
    ("isolation_cell_required_check", f"{_DIR}/isolation_audit.json"),
    ("power_domain_signal_crossing_check",
     "reports/phase2/gates/power_domain_signal_crossing.json"),
)

# Where a relative --json actually lands. These programs do
# `Path(args.json).parent.mkdir(...)` with no project-dir join, so a RELATIVE
# --json resolves against the CALLER's cwd, which under pytest is the
# `programs/` source directory. Snapshotted so this file can prove it does not
# write there — an earlier revision of it did, on every suite run, and the
# files were not gitignored.
_CWD_SPILL_DIR = PROGRAMS / "reports" / "analog" / "mixed_signal"


def _spill_snapshot():
    """Names under the cwd-relative spill dir, or None if it does not exist."""
    if not _CWD_SPILL_DIR.is_dir():
        return None
    return sorted(p.name for p in _CWD_SPILL_DIR.iterdir())


def _run_gate(name: str, proj: Path, evidence: str) -> int:
    """Invoke a gate with an ABSOLUTE --json under the project.

    Relative would be a silent no-op for this file's purpose: these programs
    resolve --json against the process cwd, so the report — and any sidecar a
    misbehaving gate wrote next to it — would land outside `proj` entirely and
    every assertion below would be checking a directory that cannot exist."""
    out = proj / evidence
    assert out.is_absolute()
    mod = __import__(name)
    try:
        return mod.main([str(proj), "--json", str(out)])
    except SystemExit as exc:                      # pragma: no cover - defensive
        return int(exc.code or 0)


def test_no_m2_gate_supplies_its_own_power_intent(tmp_path):
    """Run every M2 gate on a project with NO power intent at all. None of them
    may leave a power_domain.json / level_shifter.json / isolation.json behind:
    a checker that writes its own input can only ever audit itself.

    The search is the WHOLE project subtree, not one guessed directory, so a
    gate that drops its input somewhere other than beside its own report is
    caught too."""
    for name, evidence in _M2_GATES:
        proj = tmp_path / name
        proj.mkdir()
        _run_gate(name, proj, evidence)

        # The report must exist where we asked for it — otherwise the gate
        # never ran far enough to have written anything, and "no sidecar
        # found" would prove nothing.
        assert (proj / evidence).is_file(), (
            f"{name} wrote no report at the --json path it was given; the "
            "sidecar assertions below would be vacuous.")

        written = sorted(p.relative_to(proj).as_posix()
                         for p in proj.rglob("*") if p.is_file())
        offenders = [w for w in written
                     if Path(w).name in _SIDECARS]
        assert not offenders, (
            f"{name} wrote {offenders} — the artefact it is supposed to be "
            "auditing. A gate that supplies its own evidence measures "
            f"nothing. (files it did write: {written})")


def test_the_m2_gates_write_nothing_into_the_plugin_source_tree(tmp_path):
    """Regression guard on THIS FILE's own past defect, and on the programs'
    cwd-relative --json resolution generally.

    Running the M2 gates must not create anything under `programs/`. When this
    file passed a RELATIVE --json, every suite run left three untracked JSON
    files in `programs/reports/analog/mixed_signal/` — not gitignored
    (`git check-ignore` rc=1) — and, worse, made
    `test_no_m2_gate_supplies_its_own_power_intent` assert on a project
    directory the gates never touched, so it would have passed even if a gate
    DID emit the sidecar it audits."""
    before = _spill_snapshot()
    for name, evidence in _M2_GATES:
        proj = tmp_path / f"nospill_{name}"
        proj.mkdir()
        _run_gate(name, proj, evidence)
    assert _spill_snapshot() == before, (
        f"an M2 gate wrote into {_CWD_SPILL_DIR} — the plugin SOURCE tree — "
        "instead of the project it was given. The --json path handed to these "
        "programs must be absolute.")


def test_absent_power_intent_is_a_disclosed_skip_not_a_clean_result(tmp_path):
    """The three sidecar auditors must SKIP (rc=2), never exit 0, when the
    power intent they audit is absent — that is what keeps the M2 gap visible
    instead of reading as 'audited and found clean'."""
    for name, evidence in _M2_GATES[:3]:
        proj = tmp_path / f"skip_{name}"
        proj.mkdir()
        rc = _run_gate(name, proj, evidence)
        assert rc == 2, (
            f"{name} returned rc={rc} on a project with no power intent; the "
            "input-missing convention is rc=2 (disclosed skip). rc=0 would "
            "make 'nothing to look at' indistinguishable from 'looked and "
            "found it clean'.")
