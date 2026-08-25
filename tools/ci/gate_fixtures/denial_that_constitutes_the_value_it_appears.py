"""`denial that constitutes the value it appears` — a blanket denial check on
an extractor whose subject IS the denial.

THE MUTATION IS THE DEFECT THE GATE WAS WRITTEN FOR
===================================================
Both arms ship the SAME two modules and the SAME two constitutive extractors.
The mutation replaces one extractor's `classify_denial(<concept>, span)` — the
table lookup that tests constitutive FIRST — with the blanket `is_denied`
check, which reads "not stated" as a withholding when the sentence is granting
a freedom. Nothing is added and nothing is removed:

    modules parsed:             2 -> 2
    constitutive extractors:    2 -> 2
    blanket-checked among them: 1 -> 2      <- the only figure that moves

That is the whole point of the pair. If the can-fail arm were red because the
corpus shrank, it would prove the empty-corpus refusal (`modules parsed: 0`,
rc 2) and nothing about the predicate.

WHY THE DEBT ROW IS SYNTHESISED FROM THE REAL INVENTORY
=======================================================
The declaration passes no `--inventory`, so the gate reads
`$PG/constitutive_denial_inventory.json` — the REAL one — against whatever
subject it is pointed at. A row that matches nothing is `stale`, which is rc 1
on its own. So a can-pass subject is not merely "a clean tree": it must
REPRODUCE every recorded row, or the gate refuses the good input for a reason
the fixture never intended and the can-pass arm becomes untrustworthy.

The rows are therefore read at run time and rendered back into source, the same
way a name-scanning fixture synthesises its forbidden token from the gate's own
deny-list rather than storing one. The concept spelling is taken from the
gate's own `_CONCEPT_ALIASES`, so a future row keyed on a concept this fixture
never heard of still lands in the subject with the right classification.

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "denial that constitutes the value it appears"

_PROGRAMS = "vibe-ic-marketplace/plugins/vibe-ic/programs"
_GATE_PY = F.PROGRAMS / "denial_that_constitutes_the_value_it_appears_to_negate.py"
_INVENTORY = F.PROGRAMS / "constitutive_denial_inventory.json"

#: Where the mutation lands. Deliberately NOT any path the inventory records:
#: a mutation inside a recorded row would be absorbed as known debt and the
#: gate would stay green, which is the one thing a can-fail arm may not do.
_MUTABLE = _PROGRAMS + "/freedom_span_reader.py"

#: The extractor the mutation flips, and the concept it extracts. `unspecified`
#: is one of the gate's own `freedom` aliases, so the classification is the
#: gate's, not this fixture's opinion of it.
_FN = "_unspecified_bound"
_CONCEPT = "freedom"

_CLEAN = '''"""A reader for the freedom a specification grants by declining to fix a value."""


def {fn}(span):
    """Consults the shared table, which tests constitutive FIRST."""
    kind, word = classify_denial("{concept}", span)
    if kind == "constitutive":
        return word
    return None
'''

_BLANKET = '''"""A reader for the freedom a specification grants by declining to fix a value."""


def {fn}(span):
    """Reads every denial as a withholding, and drops the freedom granted."""
    if is_denied(span):
        return None
    return span
'''


def _gate_module():
    """The gate's OWN concept table, read at run time rather than copied."""
    spec = importlib.util.spec_from_file_location(
        "vibeic_fixture_subject_denial_gate", _GATE_PY)
    if spec is None or spec.loader is None:      # pragma: no cover - install bug
        raise ImportError(f"cannot load the gate under test: {_GATE_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _debt_rows():
    """`file -> [(function, concept)]` for every row the real inventory keeps."""
    if not _INVENTORY.is_file():
        return {}
    out = {}
    for row in json.loads(_INVENTORY.read_text(encoding="utf-8")).get("known", []):
        rel, fn, concept = row["key"].split("::")
        out.setdefault(rel, []).append((fn, concept))
    return out


def _debt_source(gate, entries) -> str:
    """Source reproducing each recorded row: constitutive, and blanket-checked.

    A row is only matched when the gate classifies the function the SAME way
    the inventory key spells it, so the concept is asserted here rather than
    assumed — a silently mis-rendered row would go stale and turn the can-pass
    arm red for the wrong reason.
    """
    parts = ['"""Recorded debt, reproduced so the real inventory has a match."""\n']
    for fn, concept in entries:
        by_name = gate._concept_of(fn)
        lines = [f"\n\ndef {fn}(sentence):",
                 f'    """Its subject IS the {concept}; it carries a private grammar."""']
        if by_name != concept:
            if by_name is not None:
                raise AssertionError(
                    f"inventory row {fn}::{concept} cannot be reproduced: the "
                    f"gate reads that name as {by_name!r}")
            alias = gate._CONCEPT_ALIASES[concept][0]
            lines.append("    out = {}")
            lines.append(f"    out[{alias!r}] = sentence")
        lines += ["    if is_denied(sentence):",
                  "        return True",
                  "    return False"]
        parts.append("\n".join(lines) + "\n")
    return "".join(parts)


def _tree(work: Path) -> Path:
    """The subject both arms share: the recorded debt, plus one clean reader."""
    root = work / "subject"
    gate = _gate_module()
    for rel, entries in _debt_rows().items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_debt_source(gate, entries), encoding="utf-8")
    mut = root / _MUTABLE
    mut.parent.mkdir(parents=True, exist_ok=True)
    mut.write_text(_CLEAN.format(fn=_FN, concept=_CONCEPT), encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    return _tree(work)


def can_fail(work: Path):
    root = _tree(work)
    # Same module, same function, same concept — only the ANSWER changes.
    (root / _MUTABLE).write_text(_BLANKET.format(fn=_FN), encoding="utf-8")
    return root, f"{_FN}() extracts '{_CONCEPT}'"
