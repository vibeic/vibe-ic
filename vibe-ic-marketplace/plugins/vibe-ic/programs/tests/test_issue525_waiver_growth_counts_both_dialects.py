from __future__ import annotations


import sys


from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(PROGRAMS))


def test_roles_sharing_one_canonical_step_do_not_collide(tmp_path):
    """The corpus shape, and the hardest collision to avoid.

    A project separately defers two physical-verification roles that resolve to
    the SAME canonical flow step, under ONE ticket, in one phase — so the two
    entries differ in exactly one field, the step name as written. Two things
    would fuse them into a single counted waiver and hide half the deferred
    work: resolving the step name through the many-to-one step map before
    comparing, or keying on the ticket, which is the field that most looks like
    an identifier."""
    import _waiver_entries as _we
    assert _we.resolve_step_name("drc") == _we.resolve_step_name("lvs"), (
        "premise moved: these role names no longer share a canonical step, so "
        "this test no longer exercises the collision it was written for")
