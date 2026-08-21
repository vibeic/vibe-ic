"""`_analog_producer_common` — the exit-code contract and the provenance binding.

Added by the gatekeeper on landing #632: the module shipped with no test of its
own, and D1 (program-test coverage) named it. It is a SHARED module — all three
A-track producers route their exit codes and their provenance through it — so an
untested one is the widest possible blast radius for the smallest possible diff.

The two defects it exists for, from its own docstring:

  1. rc 2 MEANT TWO THINGS. Every producer returned 2 for an honest gap, and
     `argparse` returns 2 for a usage error. Measured on all three, same tree,
     same invocation except one unknown flag: honest gap wrote a gap file and a
     `--json` report; the usage error wrote neither — and the caller that maps
     rc 2 to a deferral read a producer that never ran as one that ran and stood
     down for a stated reason.

  2. A DIGEST PUBLISHED AS PROOF NAMED NEITHER THE ARTEFACT NOR THE RUN. The
     netlist header quoted `sha256=` of two inputs that embed a wall-clock stamp
     and an absolute path, so it changed on every run even when the design
     content was byte-identical — six sibling trees of the same inputs, six
     different digests, none of them saying which tree it came from.

CONTENT IDENTITY AND RUN IDENTITY ARE TWO JOBS, and the tests below are mostly
about keeping them two.
"""
from __future__ import annotations

import importlib

P = importlib.import_module("_analog_producer_common")


# ── the exit-code contract ─────────────────────────────────────────────────
def test_the_two_rc_2_meanings_are_now_different_codes():
    """LOAD-BEARING. If these ever collide again, a producer that never ran is
    reported as one that ran and declined."""
    assert P.RC_HONEST_GAP != P.EX_USAGE


def test_a_usage_error_does_not_take_the_honest_gap_code(capsys):
    ap = P.ProducerArgumentParser(prog="analog_x_emit")
    ap.add_argument("--known")
    try:
        ap.parse_args(["--nope"])
    except SystemExit as exc:
        assert exc.code == P.EX_USAGE, exc.code
    else:
        raise AssertionError("a usage error must exit")


def test_a_usage_error_says_which_tier_it_is_NOT(capsys):
    """The rc is the discriminator, but a caller that reads text must not be
    able to confuse them either — so the usage path names the code it is not
    using."""
    ap = P.ProducerArgumentParser(prog="analog_x_emit")
    try:
        ap.parse_args(["--nope"])
    except SystemExit:
        pass
    err = capsys.readouterr().err
    assert str(P.RC_HONEST_GAP) in err, err


def test_the_honest_gap_line_is_token_first():
    """A caller that greps the transcript needs the token at line start; buried
    mid-sentence it cannot be matched without matching prose too."""
    line = P.honest_gap_line("analog_a1_spec_emit", "no attributed spec")
    assert line.startswith(P.HONEST_GAP_TOKEN)
    assert "analog_a1_spec_emit" in line and "no attributed spec" in line


# ── content identity: stable across runs of the same inputs ────────────────
_BODY = "* a netlist\n.subckt blk a b\nM1 a b 0 0 nch W=1u L=1u\n.ends\n"

#: The stamp line a producer writes, in the module's OWN format. Spelling it
#: from `PROVENANCE_COMMENT_PREFIX` rather than typing `* run_ref=` — which is
#: what the first version of this file guessed, and four tests failed on the
#: guess — keeps the fixture and the parser from drifting.
def _stamped(ref: str, body: str = _BODY) -> str:
    return f"{P.PROVENANCE_COMMENT_PREFIX} run_ref={ref}\n" + body


def test_content_digest_ignores_the_provenance_comments():
    """THE WHOLE POINT of (2): the artefact carries a per-run stamp, and a
    digest that includes it changes every run while the design is identical."""
    assert P.content_digest(_stamped("aaaaaaaaaaaa")) \
        == P.content_digest(_stamped("bbbbbbbbbbbb"))


def test_content_digest_still_moves_when_the_DESIGN_moves():
    """A digest stable against everything is not an identity. This is the
    accept case that keeps the stripping from going too far."""
    assert P.content_digest(_BODY) != P.content_digest(
        _BODY.replace("W=1u", "W=2u"))


def test_a_missing_file_digests_to_None_not_to_a_hash_of_nothing():
    """`sha256("")` is a real, quotable hash — publishing it for an absent file
    states a content identity for content that does not exist."""
    assert P.file_digest("/nonexistent/analog/does-not-exist.sp") is None


# ── run identity: one emission, checked by agreement ───────────────────────
def test_two_emissions_get_different_run_refs():
    assert P.new_run_ref() != P.new_run_ref()


def test_a_run_ref_round_trips_through_the_artefact():
    ref = P.new_run_ref()
    assert P.stamped_run_ref(_stamped(ref)) == ref


def test_an_unstamped_artefact_has_no_run_ref():
    """None, not a derived-from-the-path answer: deriving run identity from
    where the file happens to sit means a copied tree claims to be the run it
    was copied from."""
    assert P.stamped_run_ref(_BODY) is None


# ── the one token a report quotes, and its check ───────────────────────────
def test_the_ref_carries_run_artefact_and_content():
    tok = P.provenance_ref("abc123abc123", "phase3/analog/blk/blk.sp",
                           "0" * 64)
    assert "abc123abc123" in tok
    assert "phase3/analog/blk/blk.sp" in tok
    assert tok.endswith("0" * 12), tok


def test_a_matching_ref_verifies():
    text = _stamped("deadbeefcafe")
    tok = P.provenance_ref("deadbeefcafe", "blk.sp", P.content_digest(text))
    assert P.verify_provenance_ref(tok, "blk.sp", text) is None


def test_a_ref_lifted_from_ANOTHER_RUN_is_rejected():
    """LOAD-BEARING, and the failure (2) describes: a digest quoted from a
    different run must be self-evidently from a different run."""
    text = _stamped("deadbeefcafe")
    other = P.provenance_ref("0123456789ab", "blk.sp", P.content_digest(text))
    assert P.verify_provenance_ref(other, "blk.sp", text) is not None


def test_a_ref_naming_ANOTHER_ARTEFACT_is_rejected():
    text = _stamped("deadbeefcafe")
    tok = P.provenance_ref("deadbeefcafe", "other.sp", P.content_digest(text))
    assert P.verify_provenance_ref(tok, "blk.sp", text) is not None


def test_a_ref_whose_CONTENT_moved_is_rejected():
    text = _stamped("deadbeefcafe")
    tok = P.provenance_ref("deadbeefcafe", "blk.sp", P.content_digest(text))
    edited = text.replace("W=1u", "W=9u")
    assert P.verify_provenance_ref(tok, "blk.sp", edited) is not None


def test_an_absent_or_malformed_ref_is_rejected_not_ignored():
    """A verifier that returns "fine" for a ref it could not parse is the
    absence-rendering-as-a-pass shape, inside the thing that exists to stop it.
    """
    text = _stamped("deadbeefcafe")
    for bad in (None, "", "not-a-ref", 12345, {"a": 1}):
        assert P.verify_provenance_ref(bad, "blk.sp", text) is not None, bad


def test_a_copied_run_directory_still_verifies():
    """The stated design goal: the check reads bytes that travel WITH the tree,
    so an intact copy verifies and only a record lifted between runs does not.
    """
    text = _stamped("deadbeefcafe")
    tok = P.provenance_ref("deadbeefcafe", "blk.sp", P.content_digest(text))
    copied = text                      # a byte-for-byte copy of the artefact
    assert P.verify_provenance_ref(tok, "blk.sp", copied) is None
