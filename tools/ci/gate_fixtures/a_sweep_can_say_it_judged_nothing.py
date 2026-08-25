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

WHY N IS READ FROM THE DECLARATION. The gate lands as a RATCHET
(`--max-silent N`) and N is expected to shrink as sweeps are fixed. A fixture
that hard-coded today's N would go red the day the ratchet tightened — for the
gate improving, which is the one direction a fixture must never punish. The
population is sized from the declared N at run time: N silent sweeps plus one
that discloses is exactly at the limit, and the mutation puts it one over.
"""
from pathlib import Path
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


def _declared_max_silent() -> int:
    """The `--max-silent N` the dispatcher declares for this gate."""
    decl = next(d for d in F.declarations() if d.label == GATE)
    toks = shlex.split(decl.cmd)
    i = toks.index("--max-silent")
    return int(toks[i + 1])


def _tree(work: Path, disclosing_sweeps: int) -> Path:
    """N silent sweeps + `disclosing_sweeps` that disclose. N is the ratchet."""
    root = F.git_init(work / "subject")
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    n = _declared_max_silent()
    for i in range(n):
        (progs / f"probe_quiet_sweep_{i:03d}.py").write_text(
            _SWEEP.format(disclosure=_SILENT), encoding="utf-8")
    for i in range(disclosing_sweeps):
        (progs / f"probe_loud_sweep_{i:03d}.py").write_text(
            _SWEEP.format(disclosure=_DISCLOSES), encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """N silent + 1 disclosing: exactly at the ratchet, and it must be accepted."""
    root = _tree(work, disclosing_sweeps=1)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    """The same population; the one sweep that could disclose no longer can."""
    root = _tree(work, disclosing_sweeps=1)
    F.git_commit(root)
    loud = root / "programs" / "probe_loud_sweep_000.py"
    assert _DISCLOSES in loud.read_text(encoding="utf-8")
    loud.write_text(_SWEEP.format(disclosure=_SILENT), encoding="utf-8")
    F.git_commit(root, "mutate")
    return root, "driven sweep(s) are SILENT"
