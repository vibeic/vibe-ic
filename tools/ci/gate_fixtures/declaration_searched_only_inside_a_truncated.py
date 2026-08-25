"""`declaration searched only inside a truncated` — a window that decides a verdict.

THE MUTATION IS THE GATE'S OWN DISTINCTION, in its own words: "A slice that
only feeds OUTPUT — a `print`, a report field, an f-string in a message — is a
display bound and is correct. The rule turns on the slice reaching a SEARCH,
which is the only place a window can change a verdict."

So both trees carry the SAME file, with the SAME variable sliced to the SAME
constant bound. The only thing that moves is where the sliced value goes: into
an f-string that is printed (can_pass) or into an `in` membership test that
decides a boolean (can_fail). Nothing is added, nothing is deleted:

    modules parsed          identical in both arms
    constant-size windows   identical in both arms
    slice-then-search sites 9 -> 10        <- the ANSWER, and only the answer

A subject with no `.py` under the nested layout gives "modules parsed: 0", and
this gate happens to print that and still exit 0 — which is exactly why the
empty tree is worthless as a can_fail. The refusal here has to come from a
window that reaches a search.

WHY THE SHIPPED INVENTORY IS REPRODUCED INTO THE SUBJECT
========================================================
The declaration passes no `--inventory`, so the gate reads the REAL
`truncated_window_search_inventory.json` beside its own executable — and that
file's rows may only shrink: a row matching nothing is rc 1 all by itself. A
subject that carried none of them would be rejected for STALE ROWS, which is a
refusal about the inventory and not about the predicate, and the can_pass arm
would be permanently stuck.

The rows are therefore SYNTHESISED from the inventory at fixture time rather
than transcribed: each key is `file::sliced::side::size`, which is precisely
enough to re-emit a slice-then-search site the gate will re-derive that same
key from. A row deleted upstream stops being generated here on the next run, so
the fixture tracks the repair instead of pinning the debt.

chip-AGNOSTIC: nothing here names any IC, vendor, SKU or process.
"""
from pathlib import Path
import ast
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "declaration searched only inside a truncated"

#: The nested layout the gate walks. A flat `<root>/programs/` gives 0.
_PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: The inventory the gate itself will read, since the declaration names none.
_INVENTORY = F.PROGRAMS / "truncated_window_search_inventory.json"

#: The one file the mutation moves. Its name must not collide with any file the
#: inventory names, or its key would be excused by a row and the mutation would
#: be invisible.
_PIVOT = "synthetic_declaration_window_probe.py"

_PIVOT_HEAD = '''"""A constant-size window over ingested text. Synthetic fixture subject."""


def summarise(text):
    """The window feeds OUTPUT only — a display bound, which the rule allows."""
    print(f"  head of the ingested text: {text[:4000]}")
'''

_PIVOT_SEARCHED = '''"""A constant-size window over ingested text. Synthetic fixture subject."""


def summarise(text):
    """The SAME window, now deciding a verdict: a miss reads as absence."""
    return "REQUIRED-DECLARATION-MARKER" in text[:4000]
'''


def _rows():
    """(file, sliced-expression, side, size) for every shipped inventory row."""
    if not _INVENTORY.is_file():
        return []
    known = json.loads(_INVENTORY.read_text(encoding="utf-8")).get("known", [])
    out = []
    for row in known:
        key = row.get("key", "")
        parts = key.rsplit("::", 3)
        if len(parts) != 4:
            raise RuntimeError(
                f"inventory row {key!r} is not file::sliced::side::size; the "
                f"fixture cannot re-emit a site it cannot read")
        rel, sliced, side, size = parts
        if side not in ("head", "tail") or not size.isdigit():
            raise RuntimeError(f"inventory row {key!r} names no window")
        try:
            ast.parse(sliced, mode="eval")
        except SyntaxError as exc:
            raise RuntimeError(
                f"inventory row {key!r} carries a sliced expression this "
                f"fixture cannot re-emit as source ({exc}); the row's `sliced` "
                f"field is truncated at 48 chars by the gate") from None
        out.append((rel, sliced, side, int(size)))
    return out


def _module_source(sites) -> str:
    """A parseable module whose slice-then-search sites are exactly `sites`.

    The gate only ever `ast.parse`s this file, so the free names in the probe
    bodies never have to resolve — and giving them a binding would be inventing
    a shape the inventory never described.
    """
    lines = ['"""Synthetic re-emission of a shipped inventory row. Never run."""',
             "", ""]
    for i, (sliced, side, size) in enumerate(sites):
        window = f"{sliced}[:{size}]" if side == "head" else \
                 f"{sliced}[-{size}:]"
        lines += [f"def _probe_{i}():",
                  f'    return "DECLARATION-MARKER" in {window}',
                  "", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _tree(work: Path, pivot_source: str) -> Path:
    root = work / "subject"
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)

    by_file = {}
    for rel, sliced, side, size in _rows():
        by_file.setdefault(rel, []).append((sliced, side, size))
    for rel, sites in by_file.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_module_source(sites), encoding="utf-8")

    (programs / _PIVOT).write_text(pivot_source, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Every inventory row is present, and the one extra window only prints."""
    return _tree(work, _PIVOT_HEAD)


def can_fail(work: Path):
    """The same window, same bound, same variable — now read by a search."""
    root = _tree(work, _PIVOT_SEARCHED)
    return root, "search(es) run over a fixed-size slice"
