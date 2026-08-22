"""`upstream pins still resolve` — an anchor that is no longer in the file.

THE PROPERTY. A pin names an upstream artefact and a fragment of EXACT TEXT
inside it that fixes the quantity we re-derive. The pin is worth something only
while that text is still there: if upstream rewrites the line, our
re-implementation stops being known to agree with anything, and nothing else in
the tree would say so.

WHY THE SUBJECT CARRIES ITS OWN UPSTREAM TREE. The dispatcher declares this gate
with `--upstream-root "$ROOT"`, i.e. an upstream tree VENDORED INSIDE THE
CHECKOUT is probed before the installed system roots. That clause is what makes
the gate's input choosable at all — every other root it probes is an absolute
system path no fixture may write into — and it is not a fixture-only argument:
on a real host it is one stat per pin against a directory the repository is free
to start carrying.

THE MUTATION EDITS THE UPSTREAM FILE AND NOTHING ELSE. The pin is untouched, the
file is still there and is still READ, and the gate still resolves it — the
line that fixed the quantity is simply not in it any more. Deleting the artefact
instead would reach rc 2 NOT DETERMINED, which is this gate's honest "I could not
look" and is the opposite of the finding under test.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "upstream pins still resolve"

_UPSTREAM_REL = "vendored_upstream/scripts/place_ring.tcl"
_ANCHOR = "set extent [$master width]"

_MODULE = '''"""A synthetic step pinned to the upstream computation it re-derives."""

UPSTREAM_PINS = [
    {
        "upstream": "%s",
        "anchor": "%s",
        "quantity": "the along-the-row extent one cell consumes",
        "why": "ours takes the master width; a footprint-derived extent is a "
               "different number on a rotated side",
    },
]


def side_extent(cells):
    return sum(c["master_width"] for c in cells)
''' % (_UPSTREAM_REL, _ANCHOR)

#: The upstream artefact, carrying the anchor.
_UPSTREAM_WITH_ANCHOR = """# synthetic upstream placement script
proc place_one {master} {
    %s
    return $extent
}
""" % _ANCHOR

#: The same artefact after an upstream rewrite: same file, same procedure, and
#: the line the pin fixes the quantity to is gone.
_UPSTREAM_REWRITTEN = """# synthetic upstream placement script
proc place_one {master} {
    set extent [lindex [$master footprint] 0]
    return $extent
}
"""


def _tree(work: Path, upstream_text: str) -> Path:
    root = work / "subject"
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_row_extent.py").write_text(_MODULE, encoding="utf-8")
    art = root / _UPSTREAM_REL
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(upstream_text, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One pin, resolved under the checkout, anchor present."""
    return _tree(work, _UPSTREAM_WITH_ANCHOR)


def can_fail(work: Path):
    """The same pin, the same file, read — and the anchor rewritten away."""
    root = _tree(work, _UPSTREAM_REWRITTEN)
    return root, "UPSTREAM_ANCHOR_ABSENT"
