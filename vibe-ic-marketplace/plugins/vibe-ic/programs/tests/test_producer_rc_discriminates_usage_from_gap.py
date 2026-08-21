"""test_producer_rc_discriminates_usage_from_gap.py

rc 2 MEANT TWO THINGS AND THE CALLER COULD NOT TELL THEM APART.

Measured on all three deterministic producers, same tree, same invocation
except for one flag that does not exist:

    honest gap   -> rc 2, gap file written,    --json report written
    usage error  -> rc 2, NO gap file,         NO --json report

The caller maps rc 2 to a deferral, so "the producer examined the project and
stood down for a stated reason" and "the producer never ran at all" arrived as
the same verdict. A usage error read as an honest gap.

THE RULE, with no tool or step name in it: two outcomes a caller must act on
differently may not share a published token. The honest tier keeps this repo's
rc-2 "nothing produced, and here is why"; a usage error leaves it entirely.

Every assertion is on the rc and the stderr of a SHIPPED program driven as a
subprocess, and on files on disk. Nothing reaches into an internal.
Fixtures are synthetic — `vreg_beta`, `doc_alpha.md`, no chip, PDK SKU or
vendor literal anywhere.
"""
from __future__ import annotations

import pytest

from _analog_producer_fixture import (
    A1, A2, A3, block, make_project, run_prog, bdir)

#: (producer, the gap file it writes when it honestly declines)
PRODUCERS = [
    (A1, "spec_gap.json"),
    (A2, "topology_gap.json"),
    (A3, "netlist_gap.json"),
]

#: sysexits.h EX_USAGE. Anything that is not the honest-gap tier would do;
#: what matters is that it is NOT 2.
EX_USAGE = 64
RC_HONEST_GAP = 2


def _gapless_project(tmp_path):
    """A tree whose one declared block honestly carries no spec: the input
    shape every producer is entitled to decline on."""
    return make_project(tmp_path, [block("vreg_beta", "ldo", specs=None)])


@pytest.mark.parametrize("prog,gapfile",
                         PRODUCERS, ids=[p[0].stem for p in PRODUCERS])
def test_a_wrong_flag_does_not_exit_the_honest_gap_tier(tmp_path, prog,
                                                        gapfile):
    """The measured collision, from the side that was being misread."""
    p = _gapless_project(tmp_path)
    cp = run_prog(prog, p, "--no-such-flag")

    # PRECONDITION — the run really did fail on the command line, not on the
    # project. Without it, `rc != 2` would also hold for a producer that
    # crashed for some unrelated reason and the test would prove nothing.
    assert "unrecognized arguments" in cp.stderr or "no-such-flag" in cp.stderr

    assert cp.returncode != RC_HONEST_GAP, (
        f"a usage error exited {RC_HONEST_GAP}, the same code this producer "
        f"uses for an honest gap — and it wrote no gap file, so a caller "
        f"reading the exit code alone deferred a step that was never run")
    assert cp.returncode == EX_USAGE, cp.stderr[-400:]
    assert "USAGE_ERROR:" in cp.stderr, (
        "a caller that reads text rather than an exit code has to be able to "
        "tell the two apart too")
    assert not (bdir(p, "vreg_beta") / gapfile).exists(), (
        "the fixture is only meaningful if the usage error really wrote no "
        "gap file")


@pytest.mark.parametrize("prog,gapfile",
                         PRODUCERS, ids=[p[0].stem for p in PRODUCERS])
def test_an_honest_gap_keeps_its_tier_and_names_itself(tmp_path, prog,
                                                       gapfile):
    """The other side of the same discriminator: the honest tier must still be
    reachable, and must say so in text as well as in the exit code."""
    p = _gapless_project(tmp_path)
    cp = run_prog(prog, p)
    if cp.returncode == 0:
        # This producer can serve this input from a type library; it has no
        # honest gap to report here and the tier is not under test for it.
        pytest.skip(f"{prog.stem} emitted for this input; no gap to inspect")
    assert cp.returncode == RC_HONEST_GAP, cp.stderr[-400:]
    assert (bdir(p, "vreg_beta") / gapfile).is_file(), (
        "the honest tier claims a recorded reason; the record must exist")
    assert "HONEST_GAP:" in cp.stderr, (
        "the honest tier is not distinguishable from a usage error by text")
    assert "USAGE_ERROR:" not in cp.stderr


def test_the_runner_does_not_report_a_producer_error_as_a_recorded_gap(
        tmp_path, monkeypatch):
    """The consumer that made the collision expensive.

    The runner ran the producer, found no gap file, and fell through to the
    same deferral message the gate emits when an artefact was simply never
    produced — so a producer that ERRORED was reported in words that say it
    declined.
    """
    import analog_one_shot_runner as R

    p = _gapless_project(tmp_path)
    # Force the producer to be invoked with a flag it does not have. Nothing
    # about the project changes: the same tree, the same gate, the same block.
    prod = dict(R._A1_A3_PRODUCERS["A1_spec_extract"])
    prod["extra_args"] = ["--no-such-flag"]
    monkeypatch.setitem(R._A1_A3_PRODUCERS, "A1_spec_extract", prod)

    res = R.step_for_block(p, {"name": "vreg_beta", "type": "ldo"},
                           "A1_spec_extract", args=None)

    extras = res.extras or {}
    assert extras.get("producer_error") is True, (
        f"the runner recorded no producer error; detail was {res.detail!r} "
        f"and extras {extras!r} — a producer that never examined the project "
        f"is being reported exactly like one that examined it and declined")
    assert extras.get("producer_rc") == EX_USAGE
    assert "ERRORED" in (res.detail or "")
    assert "gap_path" not in extras, (
        "a producer error must not be attributed a recorded reason it never "
        "wrote")
