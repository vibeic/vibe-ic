"""`generated values state read or defaulted` — a caller that takes the value
and drops the provenance.

WHAT THE GATE IS ASKING, in its own words: a value that could have been READ
from the design's own documents or DEFAULTED by the generator's fallback must
say which. `declared_clock_period` already returns the disclosure —
`matched_key`, `source`, `line`, `note` — beside the number. The rule this gate
adds is about the CALLER: a module that reads the value and references no
disclosure field anywhere in code re-creates the original defect one layer up,
and the artefact is once again byte-identical whether the input was read or
defaulted.

THE HELPER IS RECOGNISED BY SHAPE, NOT BY NAME, so the fixture does not have to
name a real program: any non-test function returning a mapping that carries at
least three of the four disclosure fields alongside a value key is a
read-or-default helper. Both arms below define exactly one, in
`resolver.py`, and exactly one caller in a DIFFERENT module — the gate skips the
helper's own file, so a single-module subject would have no population at all.

BOTH ARMS CARRY THE SAME DENOMINATOR. The gate prints `examined N call site(s)
of M read-or-default helper(s)` and returns rc 2 NOT CHECKED when either is 0.
`can_pass` and `can_fail` are both 1 site of 1 helper: the helper is untouched,
the call is untouched, the value is used identically. What moves is whether the
emitter references the disclosure.

THE MUTATION IS THE GATE'S OWN DOCUMENTED FALSE PASS. Its `_carries_disclosure`
docstring records the exact text that used to satisfy this check —

    rep = declared_period_ns(docs, c)
    # we deliberately ignore matched_key / source / line here
    out.write_text(...)

— a COMMENT stating that the provenance is discarded, counted as carrying it.
That is what `can_fail` writes: the disclosure reference is replaced by the
comment announcing its absence, which is the defect certifying itself. A gate
that still passed here would be reading text rather than code.

chip-AGNOSTIC: the modules below name no IC, vendor, PDK or process — they are
parsed by an AST walk and never executed, and the "documents" they mention are
a synthetic dict.
"""
from pathlib import Path

GATE = "generated values state read or defaulted"

#: The gate walks every non-test .py under the subject, so the layout only has
#: to keep the two modules apart and out of a `tests/` directory.
_PKG = "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: The read-or-default helper. Three disclosure fields plus a value key whose
#: name carries a value hint (`period`, `_ns`) is what makes it recognisable.
_RESOLVER = '''#!/usr/bin/env python3
"""A read-or-default resolver, in the shape this rule recognises. Synthetic
fixture input: parsed, never executed."""

_TABLE = {"lib-a": (24.0, "declared in the timing section")}
_FALLBACK = 20.0


def declared_period_ns(documents, cell_library):
    """The period, and WHERE it came from, in one mapping."""
    hit = _TABLE.get(cell_library)
    if hit is None:
        return {"period_ns": _FALLBACK, "matched_key": None,
                "source": "generator fallback", "line": 0,
                "note": "no declaration matched this cell library"}
    value, where = hit
    return {"period_ns": value, "matched_key": cell_library,
            "source": "design documents", "line": 117, "note": where}
'''

_HEAD = '''#!/usr/bin/env python3
"""The emitter that turns the resolved value into an artefact. Synthetic
fixture input: parsed, never executed."""
from pathlib import Path

from resolver import declared_period_ns


def emit(out_path, documents, cell_library):
    report = declared_period_ns(documents, cell_library)
'''

#: Accepted: the disclosure travels with the value into the artefact.
_GOOD_TAIL = '''    Path(out_path).write_text(
        "create_clock -period %s\\n" % report["period_ns"]
        + "# resolved from %s (%s)\\n" % (report["source"], report["matched_key"]),
        encoding="utf-8")
'''

#: Refused: the same call, the same value, and the provenance announced as
#: discarded in a COMMENT — the gate's own recorded false pass.
_BAD_TAIL = '''    # we deliberately ignore matched_key / source / line here
    Path(out_path).write_text(
        "create_clock -period %s\\n" % report["period_ns"],
        encoding="utf-8")
'''


def _tree(work: Path, tail: str, leaf: str) -> Path:
    root = work / leaf
    pkg = root / _PKG
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "resolver.py").write_text(_RESOLVER, encoding="utf-8")
    (pkg / "sdc_emitter.py").write_text(_HEAD + tail, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One helper, one call site, and the emitter carries the disclosure: rc 0."""
    return _tree(work, _GOOD_TAIL, "accepted")


def can_fail(work: Path):
    """The same helper and the same one call site, with the disclosure reference
    replaced by a comment saying it was dropped. Same denominator, opposite
    answer."""
    root = _tree(work, _BAD_TAIL, "refused")
    return root, "calls declared_period_ns() and uses its value without carrying"
