#!/usr/bin/env python3
"""A finished protocol synth that nothing can ever call is not a feature.

`phase1_doc_one_shot_runner` [14e2b/15] already has a generic auto-dispatch: it
globs `*_protocol_synth.py`, imports each, and fires the ones that opt in with
`AUTO_DISPATCH = True` and export `is_<base>()` + `apply_<base>_synth()`. The
opt-in is what makes a module reachable in a real Phase-1 run.

MEASURED before this guard existed: of 86 protocol synths, 59 were hand-wired
into the runner and 6 carried the opt-in flag — leaving 22 modules, ~36k lines,
whose interface was complete and whose detector passed the no-misfire sweep, but
which no production path could ever reach. Their detectors were exercised (the
misfire matrix imports every module by glob) so they looked covered; only the
SYNTH half was dead. That is the failure mode this file exists to stop: a
module can be tested, audited, and still be unreachable.

The rule pinned here: if a `*_protocol_synth.py` exports the full dispatch
interface, it must be reachable — hand-wired in the runner, or opted in. A
module that is deliberately withheld records itself in `_WITHHELD` with a
reason, so "unreachable" is always a stated decision rather than an oversight.
"""
from __future__ import annotations

import re
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_RUNNER = _PROGRAMS / "phase1_doc_one_shot_runner.py"

# base -> why this one is deliberately NOT reachable. Empty is the healthy
# state. An entry here is a decision on the record, not a silent gap.
_WITHHELD: dict[str, str] = {
    "ethercat":
        "Detector mis-fires. `protocol_detector_no_misfire_matrix --blob "
        "generated` reports is_ethercat foreign_fires=['ethernet'] — it fires "
        "on a plain Ethernet design's generated L1-L3. Reproduces identically "
        "on origin/main, so it predates the opt-in sweep; wiring it would "
        "promote a latent detector bug into a live one that corrupts the "
        "L-docs of any Ethernet design. The runner's blob is input_doc + "
        "generated L1-L3, so a project with no input_doc/ sees exactly the "
        "blob that mis-fires. Fix the detector (it needs the subject-dominance "
        "check its siblings use, so EtherCAT fires only when EtherCAT is the "
        "document's subject rather than a protocol it mentions), re-run the "
        "matrix on all three blobs, then remove this entry.",
}


def _modules():
    for p in sorted(_PROGRAMS.glob("*_protocol_synth.py")):
        yield p.stem[: -len("_protocol_synth")], p


def _src(p: Path) -> str:
    return p.read_text(errors="replace")


def _exports_full_interface(base: str, src: str) -> bool:
    return bool(re.search(rf"^def is_{re.escape(base)}\s*\(", src, re.M)
                and re.search(rf"^def apply_{re.escape(base)}_synth\s*\(",
                              src, re.M))


def _opted_in(src: str) -> bool:
    return bool(re.search(r"^AUTO_DISPATCH\s*=\s*True", src, re.M))


def test_every_complete_protocol_synth_is_reachable():
    runner = _src(_RUNNER)
    unreachable = []
    for base, p in _modules():
        src = _src(p)
        if not _exports_full_interface(base, src):
            continue                      # not a dispatchable module
        if base in _WITHHELD:
            continue
        hand_wired = p.stem in runner
        if not hand_wired and not _opted_in(src):
            unreachable.append(base)
    assert not unreachable, (
        "protocol synths with a complete dispatch interface that NO production "
        f"path can reach: {unreachable}. Add `AUTO_DISPATCH = True` (after "
        "confirming the detector passes protocol_detector_no_misfire_matrix), "
        "hand-wire it in the runner, or record it in _WITHHELD with a reason.")


def test_withheld_entries_carry_a_reason():
    bad = [k for k, v in _WITHHELD.items() if not str(v).strip()]
    assert not bad, f"_WITHHELD entries with no stated reason: {bad}"


def test_withheld_entries_still_exist():
    """A stale _WITHHELD key would silently stop guarding anything."""
    bases = {b for b, _ in _modules()}
    assert not (set(_WITHHELD) - bases), (
        f"_WITHHELD names a module that no longer exists: "
        f"{sorted(set(_WITHHELD) - bases)}")


def test_opted_in_modules_export_what_the_dispatcher_calls():
    """The dispatcher looks up `is_<base>` and `apply_<base>_synth` by name and
    silently `continue`s when either is absent — so a module that sets the flag
    without the interface is opted in and still never fires."""
    broken = []
    for base, p in _modules():
        src = _src(p)
        if _opted_in(src) and not _exports_full_interface(base, src):
            broken.append(base)
    assert not broken, (
        f"AUTO_DISPATCH=True but missing is_<base>/apply_<base>_synth: {broken}"
        " — the dispatcher would skip these silently")


def test_the_guard_can_actually_fail():
    """Direction check on the guard itself: the predicate must be falsifiable.
    A module with the full interface, no hand-wiring and no flag IS reported."""
    src = "def is_x(b): return False\ndef apply_x_synth(d, f, n): pass\n"
    assert _exports_full_interface("x", src)
    assert not _opted_in(src)
