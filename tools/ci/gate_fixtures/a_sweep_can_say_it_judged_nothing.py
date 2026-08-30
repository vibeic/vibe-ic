"""`a sweep can say it judged nothing` — a sweep that read the corpus and went quiet.

THE DEFECT, IN THE SURVEY'S OWN WORDS: a sweep driven against a corpus it can
READ IN FULL but whose rule applies to NOTHING in it exits 0 with no `VACUOUS_PASS:`
sentinel and no rc 2, so an automated reader — `flow_compliance_check` consumes
exactly those two signals — cannot tell "I looked and it was clean" from "I never
reached the check". That is the shape a 756-pair corpus sweep reported as
`exit 0, clean`.

THE MUTATION IS THAT ONE ANSWER AND NOTHING ELSE. Both arms ship the SAME number
of sweep-shaped programs, all of them driven to a zero-reach run, so the survey's
denominator is identical either way (`driven` is printed and can be read back off
both runs). The can-fail arm deletes the DISCLOSURE from exactly one of them —
the sentinel line, leaving the sweep otherwise byte-identical: it still reads
every probe file, still judges none, still exits 0. What changes is whether it can
say so.

WHY THE CORPUS IS NOT SHRUNK TO ZERO. A can-fail that removed the sweeps would
drive `discovered` to 0, the survey would return rc 2 through `_sweep_reach`
("surveyed nothing") rather than a ratio, and the red would prove the vacuity
path instead of the predicate. The population is held constant on purpose.

THE MUTATION IS A SWAP, AND THE TOTAL DOES NOT MOVE. The bound is the NAMED SET
in the register the declaration points `--silent-set` at, so the case worth
proving is the one no count can reach: one registered sweep starts disclosing
and one UNREGISTERED sweep goes silent, in the same commit. `silent` is 3 before
and 3 after — a count bound of any value accepts both trees identically — and the
set refuses, because a name it never sanctioned is now silent.

WHY THE FIXTURE SHIPS ITS OWN REGISTER. `$PLUGIN` resolves to the fixture's
subject tree, so `--silent-set "$PLUGIN/programs/sweep_silence_register.json"`
reads the register written HERE and never the shipped one. A fixture whose
subject the gate could not move would prove nothing about the gate.

WHAT THIS FIXTURE DELIBERATELY DOES NOT PROVE: that a SHRINKING register passes.
The engine's contract is one accept and one refuse, and a shrink is a third tree
that must be ACCEPTED — it is proven in
`programs/tests/test_sweep_silence_register.py`, which asserts the exact exit
code on all three trees, because a ratchet that punishes tightening is the
defect this bound was written to remove and it must be pinned somewhere that can
assert a PASS.
"""
from pathlib import Path
import json
import re
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "a sweep can say it judged nothing"

#: The sweep body, in the shape `sweep_reach_survey` discovers: an argparse CLI
#: whose positional takes a SET of targets (`nargs="+"`). It reads every probe
#: file it is handed and judges none of them, because the token it looks for
#: appears in no valid Verilog module — a genuine zero-reach run, not a crash and
#: not a refusal.
_SWEEP = '''#!/usr/bin/env python3
"""A probe sweep over a set of sources. Fixture-only; describes nothing real."""
import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", help="files or directories to sweep")
    a = ap.parse_args(argv)
    examined = judged = 0
    for t in a.targets:
        p = Path(t)
        for f in (sorted(p.rglob("*.v")) if p.is_dir() else [p]):
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            examined += 1
            if "a_token_no_valid_module_carries" in text:
                judged += 1
    if judged == 0:
{disclosure}
        return 0
    print("findings: %d of %d" % (judged, examined))
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''

#: The disclosure. `VACUOUS_PASS:` at line-start is one of the two signals the
#: consumer reads; without it the same run is indistinguishable from a clean one.
_DISCLOSES = ('        print("VACUOUS_PASS: examined %d file(s), '
              'judged none" % examined)')
#: The mutation: the sweep still returns 0 having judged nothing, and says nothing.
_SILENT = "        pass"


def _register_path(subject_root: Path) -> Path:
    """Where the DECLARATION tells the gate to read its register.

    Derived from the declared argv rather than assumed, so a fixture cannot
    write its register somewhere the gate does not look and then read the
    resulting refusal as the predicate firing.
    """
    decl = next(d for d in F.declarations() if d.label == GATE)
    toks = shlex.split(decl.cmd)
    i = toks.index("--silent-set")
    rel = re.sub(r"^\$\{?(ROOT|PLUGIN)\}?/", "", toks[i + 1])
    return subject_root / rel


def _write_register(root: Path, permitted: "list[str]") -> None:
    """A register naming exactly `permitted`, each with the argument the loader
    demands. An entry with no written justification is REFUSED by the loader, so
    the fixture cannot accidentally prove the bound with a nameless blessing."""
    path = _register_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "register": "sweep_silence_register",
        "permitted": {
            n: {"why_permitted": "fixture-only probe sweep; describes nothing "
                                 "real and is registered so that the tree "
                                 "under test starts from an accepted state"}
            for n in permitted},
        "known_silent_untriaged": {},
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


#: How many silent probe sweeps the subject carries. Small and FIXED: with a set
#: bound there is no declared N to size the population from, and the swap below
#: is decisive at any size.
_N_SILENT = 3


def _tree(work: Path) -> Path:
    """`_N_SILENT` silent sweeps, all registered, plus one that discloses."""
    root = F.git_init(work / "subject")
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    quiet = []
    for i in range(_N_SILENT):
        name = f"probe_quiet_sweep_{i:03d}.py"
        (progs / name).write_text(_SWEEP.format(disclosure=_SILENT),
                                  encoding="utf-8")
        quiet.append(name)
    (progs / "probe_loud_sweep_000.py").write_text(
        _SWEEP.format(disclosure=_DISCLOSES), encoding="utf-8")
    _write_register(root, quiet)
    return root


def can_pass(work: Path) -> Path:
    """Every silent sweep is named in the register, so the gate must accept."""
    root = _tree(work)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    """A SWAP: the total stays at `_N_SILENT` and an unsanctioned name is silent.

    One registered sweep gains the disclosure it lacked; the sweep that had it
    loses it and is in no list. `silent` is `_N_SILENT` before and after, so a
    count bound of any value cannot separate these two trees. The set can.
    """
    root = _tree(work)
    F.git_commit(root)
    progs = root / "programs"
    registered = progs / "probe_quiet_sweep_000.py"
    unregistered = progs / "probe_loud_sweep_000.py"
    assert _DISCLOSES in unregistered.read_text(encoding="utf-8")
    registered.write_text(_SWEEP.format(disclosure=_DISCLOSES), encoding="utf-8")
    unregistered.write_text(_SWEEP.format(disclosure=_SILENT), encoding="utf-8")
    F.git_commit(root, "swap")
    return root, "named in NEITHER list"
