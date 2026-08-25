"""`printed remedy runs as printed` — one printed remedy, with its command on
the wrong side of the entry point's own option.

WHAT THE GATE IS ASKING, in its own words: a refusal that prints "run this to
fix it" makes a promise, and a printed line that omits an argument the entry
point requires fails WITHOUT EVER RUNNING THE COMMAND. The composed EDA image
has an entry point that parses the arguments after the image reference, so
`--skip` must reach it BEFORE the command; put the command first and the entry
point takes it for one of its own options and answers
`[ERROR] Unexpected option`. The exit is non-zero, so this is not a silent
failure — it is a confident wrong answer about a tool that was never invoked.

THE SUBJECT IS ONE PRINTED REMEDY, AND BOTH ARMS CARRY IT. The gate prints its
denominator — `examined N printed string(s) naming docker` — and returns rc 2
NOT CHECKED when N is 0. A fixture that reached red by removing the remedy, or
by handing the gate a tree with no `docker` in it, would prove only that the
gate notices an empty population. Both arms here examine exactly ONE printed
string naming docker. The denominator does not move; the ANSWER inside it does.

THE MUTATION IS TOKEN ORDER, AND NOTHING ELSE. Same `print`, same image
reference held in the same module-level constant (the shape the gate's own
`_str_constants` fold exists for), same command, same flag. The accepted arm
puts `--skip` immediately after the image; the refused arm puts the command
there and leaves `--skip` trailing behind it, which is the defect recorded
verbatim in `container_image_provenance.py`:

    docker logs: [ERROR] Unexpected option "sleep"

DIRECTION. The gate flags a remedy whose FIRST token after the image reference
is not `--skip`; it is therefore tripped by MOVING that token, never by deleting
the remedy or the flag. Deleting `--skip` from the accepted arm would also go
red, but for a reason indistinguishable from "the author wrote a different
command", and the fixture would then be about absence rather than about order.

chip-AGNOSTIC: the module below names no IC, vendor, SKU or process. It is
parsed, never executed, and measures nothing.
"""
from pathlib import Path

GATE = "printed remedy runs as printed"

#: Anywhere under the root that is not a test path — `_skip` drops `tests/`
#: components and `test_*` basenames, and `docs/capture/` wholesale.
_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/synthetic_refusal.py"

#: The image reference lives in a module-level constant, which is how the real
#: refusals in this repository write it, and is the fold the gate performs
#: before deciding. Assembled from parts so this fixture file's own source can
#: never be read as a printed remedy by the gate that scans the tree.
_IMAGE = '"ghcr.io/vibeic/' + 'vibeic-eda' + ':0.3.16"'

_HEAD = '''#!/usr/bin/env python3
"""A refusal that prints a remedy. Synthetic fixture input: it is parsed,
never executed, and measures nothing."""
IMAGE = ''' + _IMAGE + '''


def refuse(name):
'''

#: ACCEPTED: `--skip` is the first token after the image reference, so the
#: entry point consumes it and hands the rest of the line to the shell.
_GOOD = '''    print("Remedy: docker run --rm " + IMAGE + " --skip yosys -V")
    return 1
'''

#: REFUSED: the same tokens, with the command where the entry point expects its
#: own option. `--skip` is still present, one position too late.
_BAD = '''    print("Remedy: docker run --rm " + IMAGE + " yosys -V --skip")
    return 1
'''


def _tree(work: Path, body: str) -> Path:
    root = work / "subject"
    target = root / _REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_HEAD + body, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One printed remedy, examined and accepted: rc 0."""
    return _tree(work, _GOOD)


def can_fail(work: Path):
    """The same one remedy, with the command moved ahead of `--skip`. Same
    denominator, opposite answer."""
    root = _tree(work, _BAD)
    # The sentence has to appear in the refusal, which is how the pair test
    # knows the gate refused for THIS mutation and not by coincidence.
    return root, "where the entry point expects `--skip`"
