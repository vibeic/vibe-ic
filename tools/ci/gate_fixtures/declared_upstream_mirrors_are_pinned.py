"""`declared upstream mirrors are pinned` — a pin that does not read upstream.

THE MUTATION IS THE MEASURED DEFECT, in the gate's own words: OUR half of a
mirrored invariant was pinned by a test and THEIRS was not, so "upstream does it
this way" was true when it was typed and unchecked from then on.

WHAT THE CAN-FAIL DELIBERATELY DOES NOT DO. It does not delete the pin file and
it does not delete the test function inside it — both of those are shapes this
gate also refuses, and either would let the pair pass while proving nothing
about the property the gate is FOR. The pin stays present and keeps its name;
what changes is that it stops mentioning the artefact it is pinned to, which is
the exact state "pinned in name only" describes.

THE DECLARED MIRROR IS UNTOUCHED IN BOTH DIRECTIONS, so the gate's population is
identical either way: one file parsed, one mirror declared. A subject declaring
NO mirror is rc 2 by this gate's own zero-denominator rule, so an empty tree
could never have exercised the predicate under test.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "declared upstream mirrors are pinned"

_UPSTREAM = "libreflow/scripts/place_ring.tcl"
_PIN_REL = "tests/test_synthetic_row_extent_pin.py"

_MODULE = '''"""A synthetic step that mirrors an upstream placement contract."""

UPSTREAM_MIRROR = {
    "upstream": "%s",
    "mirrors": "the order in which the four sides are walked, and the "
               "quantity each side sums",
    "pinned_by": "%s::test_the_side_extent_matches_upstream",
}


def side_extent(cells):
    return sum(c["master_width"] for c in cells)
''' % (_UPSTREAM, _PIN_REL)

#: A pin that READS upstream: it opens the declared artefact by the path the
#: declaration names, which is what makes it able to see upstream change.
_PIN_READS_UPSTREAM = '''"""Pins the synthetic step against the upstream script it mirrors."""

from pathlib import Path

_ARTEFACT = "%s"


def test_the_side_extent_matches_upstream(tmp_path):
    text = Path(_ARTEFACT).read_text() if Path(_ARTEFACT).is_file() else ""
    assert "master" in text or text == ""
''' % _UPSTREAM

#: The same test, still present and still named, now asserting only our own
#: constant. It mentions neither the declared artefact nor the declaration.
_PIN_READS_ONLY_US = '''"""Pins the synthetic step against a constant of our own."""


def test_the_side_extent_matches_upstream(tmp_path):
    assert 4 == 4
'''


def _tree(work: Path, pin_source: str) -> Path:
    root = work / "subject"
    programs = root / "programs"
    (programs / "tests").mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_row_extent.py").write_text(_MODULE, encoding="utf-8")
    (programs / _PIN_REL).write_text(pin_source, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One declared mirror whose named test reads the artefact it mirrors."""
    return _tree(work, _PIN_READS_UPSTREAM)


def can_fail(work: Path):
    """The same declaration; the pin now reads nothing but our own side."""
    root = _tree(work, _PIN_READS_ONLY_US)
    return root, "declared mirror(s) are not pinned to what they mirror"
