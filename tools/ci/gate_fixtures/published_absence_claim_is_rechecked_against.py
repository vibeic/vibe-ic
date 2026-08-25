"""`published absence claim is rechecked against` — a literal absence claim
that the tree has since contradicted.

THE MUTATION IS THE DEFECT THE GATE NAMES, NOT AN INVENTED ONE
==============================================================
The gate's docstring states it exactly: a placeholder carries a published
reason string naming a module as not yet present, "the named thing lands
later, in a different change, and the string is never revisited". So the
mutation is the LANDING. Both arms ship the identical `programs/` corpus and
the identical reason string; the can-fail arm additionally contains the file
that string says is absent.

SAME DENOMINATOR, BOTH ARMS
===========================
The gate prints three population figures before its verdict, and the mutation
moves none of them:

    modules parsed              3   (the file it lands is `docs/*.md`, not
                                     `*.py`, and `docs/` is populated in both
                                     arms so neither is the empty-corpus path)
    absence-shaped strings      2   (the literal claim, plus the CORRECT
                                     interpolated form `f"no such file: {p}"`
                                     which is population and never a finding)
    claims ATTACHED to a path   1   (same string, same sentence, same window)

Only the last line moves: `of those, false against the tree` goes 0 -> 1. A
can-fail that emptied the corpus would drive `modules parsed: 0` and the rc-2
CANNOT-DETERMINE branch, which proves the gate notices an empty tree and
nothing about whether it can read a claim.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path

GATE = "published absence claim is rechecked against"

#: The claim, byte-for-byte in both arms. Verb and path share one sentence and
#: sit 27 characters apart, inside the gate's 60-character attachment window.
_CLAIMED_PATH = "docs/pending_module_note.md"
_REASON_LINE = (
    'REASON = "docs/pending_module_note.md does not exist, so there is '
    'nothing to summarise."\n'
)

#: The placeholder that publishes it. The string is a module-level assignment,
#: not a docstring, because the gate excludes docstrings by construction.
_PLACEHOLDER = (
    '"""Emit a placeholder record when the analysis cannot be run."""\n'
    "\n"
    + _REASON_LINE +
    "\n"
    "\n"
    "def emit():\n"
    '    return {"status": "placeholder", "why": REASON}\n'
)

#: The pattern the gate exists to leave alone: the path is interpolated at the
#: moment of publication, so the sentence cannot go stale. It is absence-shaped
#: — it counts in the population — and carries no literal path, so it is never
#: a finding. Present in BOTH arms.
_CORRECT = (
    '"""The correct shape: the path is resolved when the reason is written."""\n'
    "\n"
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def why(p: Path):\n"
    "    if not p.is_file():\n"
    '        return f"no such file: {p}"\n'
    "    return None\n"
)

_INERT = (
    '"""A program with no published reason string at all."""\n'
    "\n"
    "\n"
    "def add(a, b):\n"
    "    return a + b\n"
)


def _tree(work: Path) -> Path:
    root = work / "subject"
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    (progs / "placeholder_emitter.py").write_text(_PLACEHOLDER, encoding="utf-8")
    (progs / "correct_emitter.py").write_text(_CORRECT, encoding="utf-8")
    (progs / "inert_helper.py").write_text(_INERT, encoding="utf-8")
    # `docs/` exists in both arms. The mutation is one FILE inside it landing,
    # never the directory appearing.
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.md").write_text("# fixture docs\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The claim is TRUE: nothing in the tree resolves the named path."""
    root = _tree(work)
    assert not (root / _CLAIMED_PATH).exists()
    return root


def can_fail(work: Path):
    """The named thing lands in a later change; the string is never revisited."""
    root = _tree(work)
    (root / _CLAIMED_PATH).write_text(
        "# the module the published reason still calls absent\n", encoding="utf-8")
    return root, "say a path is absent and it exists"
