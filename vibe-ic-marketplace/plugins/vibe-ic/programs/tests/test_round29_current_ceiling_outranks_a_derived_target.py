"""When two declarations cannot both be met, the design's own outranks mine.

MEASURED (round 29, on the whole block rather than the buffer bench,
v1.16.60 / fa43da5df107). Round 28 sized the common-mode buffer's output
stage to 512u/32u because that met the 360 ohm R_out this analysis had
back-derived from the switched charge. On the block:

    output stage     R_out (bench)   modulator Idd
      512u / 32u        357 ohm        1.037 mA      <- over the CEILING
      512u / 28u        388 ohm        0.947 mA
      512u / 24u        427 ohm        ~0.88 mA
     1024u / 24u        416 ohm        ~0.88 mA      <- that axis converged

This design declares Iout 0.5 mA target and 1.0 mA MAXIMUM (L5, L22). At
512/32 the modulator draws 1.037 mA -- past the ceiling, not merely past the
target. The two numbers do not both fit in this topology, and widening the
pull-up further does not buy the impedance back.

512/28 is chosen. The current ceiling is a number the DESIGN declares; 360 ohm
is an intermediate target this analysis derived. Breaking the design's own
stated maximum is worse than missing one I wrote down myself, so the derived
one gives way -- out loud, with the shortfall stated (388 ohm, 7.8% over).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_a2_topology_emit as m  # noqa: E402


def _entry():
    for name in dir(m):
        v = getattr(m, name)
        if isinstance(v, dict) and "delta_sigma" in v:
            c = v["delta_sigma"]
            if isinstance(c, dict) and "circuit_class_citation" in c:
                return c
    raise AssertionError("delta_sigma entry not found")


def _dev(n):
    for d in _entry()["devices"]:
        if d.get("name") == n:
            return d
    return None


def test_the_output_stage_sits_at_the_chosen_compromise():
    assert _dev("mp_cmo")["w"] == 512.0
    assert _dev("mn_cmo")["w"] == 28.0, (
        "32u meets the derived impedance target and breaks the design's "
        "declared current ceiling")


def test_the_conflict_is_recorded_where_the_size_is_chosen():
    src = Path(m.__file__).read_text()
    i = src.index('"name": "mp_cmo"')
    head = src[max(0, i - 4000):i]
    # the measured total, the ceiling it broke, and the shortfall accepted
    assert "1.037 mA" in head, "the measurement that forced the choice is gone"
    assert "1.0 mA" in head and "MAXIMUM" in head
    assert "388 ohm" in head and "7.8%" in head, (
        "the target that was missed, and by how much, must be stated")


def test_the_precedence_is_stated_not_assumed():
    src = Path(m.__file__).read_text()
    i = src.index('"name": "mp_cmo"')
    head = src[max(0, i - 4000):i]
    assert "outranks" in head or "worse than" in head, (
        "which declaration wins, and why, has to be written down -- a silent "
        "choice between two specs is the one nobody can review")


def test_the_shipped_library_still_holds_its_own_invariants():
    assert m.library_invariants() == []
