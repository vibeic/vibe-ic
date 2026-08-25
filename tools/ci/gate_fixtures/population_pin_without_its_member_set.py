"""`population pin without its member set` — a live population pinned by SIZE
and never by IDENTITY.

THE MUTATION IS THE MEASURED DEFECT ITSELF. The gate's docstring records a
count pin that stayed green while the population it named became a DIFFERENT
SET, because one arrival and one departure landing together leave the number
identical. The only repair it names is a member pin standing beside the count.
So the mutation here is exactly that repair being absent: one module keeps its
count pin, keeps its live re-derivation, keeps its place in the corpus, and
loses the assertion that names WHICH members produced the number.

THE DENOMINATOR IS THE SAME IN BOTH ARMS
========================================
Both subjects contain the same test modules, and every one of them carries the
same count pin over the same live re-derivation. The gate prints its
denominators, and they are byte-identical across the pair:

    test modules parsed:       15      (both arms)
    modules with a count pin:  15      (both arms)
    count pins, no member pin: 14 -> 15

Nothing is added to the corpus and nothing is removed from it. What moves is
the ANSWER for ONE module — whether the identities behind its number are
pinned — which is the question the gate exists to ask.

WHY THE SUBJECT IS BUILT FROM THE SHIPPED INVENTORY
===================================================
The gate reads its inventory from beside its own executable, and `$PG` is the
REAL programs tree, so the inventory in play is the shipped one. An inventory
row matching nothing is rc 1 by design — "a row that matches nothing is a lie
about what the tree contains" — so a subject that ignored the inventory would
be refused for STALE ROWS in both directions, and the pair would prove the
gate can notice a missing file rather than a missing member pin.

The subject therefore MATERIALISES EVERY INVENTORIED KEY, read from the
shipped inventory at run time and never copied into this directory. Each such
module is written count-only, which is what the row asserts about it. `seen`
then equals `known`, no row is stale, and the pair's only moving part is the
one module this fixture owns. When a row is repaired out of the real
inventory, the subject stops materialising it on the next run — the fixture
tracks the file it is judged against instead of pinning a copy that would
drift.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "population pin without its member set"

#: Where `scan()` looks. A flat `<root>/programs/` is parsed as 0 modules.
_TESTS = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests")

#: Read from the tree under test at run time; never vendored here.
_INVENTORY = F.PROGRAMS / "population_pin_member_set_inventory.json"

#: A LIVE re-derivation (rglob off a `__file__` anchor) whose SIZE is pinned.
#: `_repo_anchors` refuses anything read out of a fixture the test just built,
#: so the anchor is what makes this a population pin at all.
_COUNT_ONLY = '''\
"""A module that pins a live population's size."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
ITEMS = sorted(ROOT.rglob("*.marker"))


def test_population_size():
    assert len(ITEMS) == 3
'''

#: The remedy the gate names: the identities pinned beside the count and
#: compared as a set, so a missing member and an extra member differ.
_MEMBER_PIN = '''

def test_population_members():
    got = {p.name for p in ITEMS}
    expected = {"one.marker", "two.marker", "three.marker"}
    assert got == expected
'''

_SUBJECT_MODULE = "test_fixture_population_pin.py"


def _inventoried_keys():
    """Every key the SHIPPED inventory excuses, in the tree's own words."""
    if not _INVENTORY.is_file():
        return []
    try:
        rows = json.loads(_INVENTORY.read_text(encoding="utf-8")).get("known", [])
    except (OSError, ValueError):
        return []
    return [r["key"] for r in rows if isinstance(r, dict) and r.get("key")]


def _tree(work: Path, member_pin: bool) -> Path:
    root = work / "subject"
    tests = root.joinpath(*_TESTS)
    tests.mkdir(parents=True)
    # Every inventoried row, materialised count-only so no row goes stale.
    for key in _inventoried_keys():
        p = root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_COUNT_ONLY, encoding="utf-8")
    body = _COUNT_ONLY + (_MEMBER_PIN if member_pin else "")
    (tests / _SUBJECT_MODULE).write_text(body, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The count pin carries its member set. Nothing is new, no row is stale."""
    return _tree(work, member_pin=True)


def can_fail(work: Path):
    """The same module, the same count pin, the same live re-derivation — and
    the identities behind the number are no longer stated anywhere."""
    return (_tree(work, member_pin=False),
            "pin a live population's SIZE and never its MEMBERS")
