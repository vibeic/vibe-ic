"""`provenance value is resolved not constant` — a typed source path standing
beside a resolved one.

WHAT THE GATE IS ASKING, in its own words: an artefact says where its numbers
came from by RESOLVING it, never by typing it. Its narrow population is a single
artefact write that emits BOTH claims at once — a resolved subject block, and
beside it a run-relative path typed into the emitter's own format string. Where
the two coexist one of them must be redundant, and only the typed one can go on
looking correct after the read failed, after the layout moved, or when the
artefact is about a different design entirely.

THE SUBJECT IS ONE EMITTER, AND BOTH ARMS CARRY IT. The gate prints its
denominator — `examined N resolved-subject artefact write(s)` — and returns rc 2
NOT CHECKED when N is 0. A fixture that reached red by deleting the emitter, or
by handing the gate a tree with no `_measured_subject_lines` call in it, would
prove only that the gate notices an empty corpus. Both arms here examine exactly
ONE resolved-subject write. The denominator does not move; the ANSWER inside it
does.

THE MUTATION IS ONE CONCATENATED STRING. The emitter keeps resolving its subject
and keeps rendering it the same way — the resolved claim is untouched, which is
what makes the finding about COEXISTENCE rather than about a missing resolve.
What the mutation adds is a second source claim, `# Source:` followed by a fixed
run-relative report path, in the same `write_text` call. That is the shape the
gate was written for: the measured defect was a 487-byte report published
byte-identical across two designs, citing a source path neither of them
contains.

chip-AGNOSTIC: the emitter below measures nothing and names no IC, vendor or
process — it exists to be read by an AST walk and never to be run.
"""
from pathlib import Path

GATE = "provenance value is resolved not constant"

#: The gate walks the plugin's programs tree, so the subject is laid out the way
#: the repository lays it out rather than flat under the root.
_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/artefact_emitter.py"

_HEAD = '''#!/usr/bin/env python3
"""An artefact emitter, in the shape this rule polices. Synthetic fixture
input: it is parsed, never executed, and measures nothing."""
from pathlib import Path


def _measured_subject_lines(subject: dict) -> str:
    """The RESOLVED identity of what was measured, rendered from the run."""
    return "".join("# %s: %s\\n" % kv for kv in sorted(subject.items()))


def emit(out_path: Path, subject: dict, rows) -> None:
    body = "".join("%s\\n" % r for r in rows)
'''

#: The accepted write: one resolved subject block, and no source path typed
#: anywhere inside the call.
_GOOD_WRITE = '''    out_path.write_text(_measured_subject_lines(subject) + body,
                        encoding="utf-8")
'''

#: The same write, same resolved block, plus a second source claim the emitter
#: never resolved. The path is assembled here rather than spelled in one piece
#: so that this fixture file cannot itself read as the defect it describes.
_TYPED_PATH = "reports/" + "phase3/" + "antenna" + ".rpt"

_BAD_WRITE = ('''    out_path.write_text(_measured_subject_lines(subject) + body
                        + "# Source: ''' + _TYPED_PATH + '''\\n",
                        encoding="utf-8")
''')


def _tree(work: Path, write_body: str) -> Path:
    root = work / "subject"
    target = root / _REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_HEAD + write_body, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One resolved-subject write, examined and accepted: rc 0."""
    return _tree(work, _GOOD_WRITE)


def can_fail(work: Path):
    """The same one write, now carrying a typed source path beside the resolved
    block. Same denominator, opposite answer."""
    root = _tree(work, _BAD_WRITE)
    # The literal has to appear in the refusal, which is how the pair test knows
    # the gate refused for THIS mutation rather than by coincidence.
    return root, "types the source path '%s'" % _TYPED_PATH
