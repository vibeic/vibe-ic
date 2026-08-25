"""`declared invocation accepted by its own pars` — a clause its program refuses.

THE MUTATION IS THE MEASURED DEFECT, in the gate's own words: "a
release-documents generator whose only declared invocation omitted two
arguments its parser marks required, exiting 2, scored as a passing tier". The
declared clause never changes here; the PARSER on the other side of the
contract does — it starts marking an argument required that the clause does not
supply, so the program exits 2 out of argparse before its check can run.

BOTH TREES DECLARE THE SAME TWO CLAUSES and ship the same two programs:

    declared clauses driven   2   identical in both arms
    of which blocking         1   identical in both arms
    refused by their parser   0 -> 1     <- the ANSWER, and only the answer

The vacuity path this deliberately avoids: a flow document with no clause in it
is "declares no invocation at all", rc 2, by the gate's own refusal — and an
absent flow document or an absent `programs/` is rc 2 as well. None of those
say anything about the predicate, so the can_fail arm keeps every clause and
every program in place and moves only what the parser accepts.

WHY BOTH TIERS ARE PRESENT. `_CLAUSE_KEYS` covers `program_exit_zero` and
`advisory_program_exit_zero`, and the gate's docstring is explicit that "an
advisory clause that cannot be invoked is advisory about nothing". The subject
carries one of each so the blocking denominator is a real subset rather than
the whole population, and the mutation lands on the blocking one.

THE INVENTORY. The declaration passes no `--inventory`, so the gate reads
`declared_invocation_parser_inventory.json` beside its own executable. That
file does not exist on this tree, and rows in it may only shrink — a row
matching nothing is rc 1 by itself. So if one is ever written, `can_pass` here
re-emits every row it holds as a clause plus a program that refuses it, exactly
as the row records; otherwise the arm would be stuck on a refusal about stale
rows rather than about the predicate.

chip-AGNOSTIC: nothing here names any IC, vendor, SKU or process.
"""
from pathlib import Path
import json
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "declared invocation accepted by its own pars"

_PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
_FLOW_REL = _PLUGIN_REL + "/flow/phase1_phase2_phase3.yaml"
_PROGRAMS_REL = _PLUGIN_REL + "/programs"

#: The inventory the gate itself will read, since the declaration names none.
_INVENTORY = F.PROGRAMS / "declared_invocation_parser_inventory.json"

_BLOCKING = "synthetic_declared_probe_a.py"
_ADVISORY = "synthetic_declared_probe_b.py"

_ACCEPTS = '''#!/usr/bin/env python3
"""A synthetic gate whose parser accepts the clause the flow declares."""
import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
{options}
    a = ap.parse_args(argv)
    print(f"[PASS] {stem}: 0 of 0 declared items examined ({{a!r}})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

#: The SAME program, whose parser now marks an argument required that the
#: unchanged clause does not supply. argparse writes its documented refusal
#: protocol — a `usage:` block plus a `<prog>: error:` line — and exits 2.
_REFUSES = '''#!/usr/bin/env python3
"""A synthetic gate whose parser refuses the clause the flow declares."""
import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
{options}
    ap.add_argument("--report", required=True,
                    help="the clause does not supply this")
    a = ap.parse_args(argv)
    print(f"[PASS] {stem}: 0 of 0 declared items examined ({{a!r}})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

#: For an inventory row: a program that is refused whatever argv it is handed,
#: writing argparse's own protocol so `classify_not_invocable` reads it under
#: Rule A. The row records that this exact invocation IS refused; re-deriving
#: the refusal from the row's argv would be inventing a parser the row never
#: described.
_INVENTORY_REFUSES = '''#!/usr/bin/env python3
"""A synthetic gate re-emitting a shipped inventory row's refusal."""
import sys

print("usage: {stem} --required-artefact PATH", file=sys.stderr)
print("{stem}: error: the following arguments are required: "
      "--required-artefact", file=sys.stderr)
sys.exit(2)
'''


def _program(path: Path, template: str, argv) -> None:
    opts = "\n".join(
        f'    ap.add_argument("{a}", default=None)'
        for a in argv if a.startswith("--"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.format(options=opts or "    pass",
                                    stem=path.stem), encoding="utf-8")


def _inventory_rows():
    """(program, argv) for every shipped inventory row, or []."""
    if not _INVENTORY.is_file():
        return []
    out = []
    for row in json.loads(_INVENTORY.read_text(encoding="utf-8")).get("known", []):
        key = row.get("key", "")
        program, _, rest = key.partition("::")
        if not program:
            raise RuntimeError(
                f"inventory row {key!r} is not program::argv; the fixture "
                f"cannot re-emit a clause it cannot read")
        out.append((program, shlex.split(rest)))
    return out


def _tree(work: Path, blocking_template: str) -> Path:
    root = work / "subject"
    programs = root / _PROGRAMS_REL
    programs.mkdir(parents=True, exist_ok=True)

    clauses = [f'      - program_exit_zero: "{_BLOCKING} --root ."',
               f'      - advisory_program_exit_zero: "{_ADVISORY} --mode quick"']
    _program(programs / _BLOCKING, blocking_template, ["--root"])
    _program(programs / _ADVISORY, _ACCEPTS, ["--mode"])

    for program, argv in _inventory_rows():
        stem = program if program.endswith(".py") else program + ".py"
        p = programs / stem
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_INVENTORY_REFUSES.format(stem=Path(stem).stem),
                     encoding="utf-8")
        declared = " ".join([program] + argv)
        clauses.append(f'      - program_exit_zero: "{declared}"')

    flow = root / _FLOW_REL
    flow.parent.mkdir(parents=True, exist_ok=True)
    flow.write_text(
        "# Synthetic flow document. Every clause below is driven for real.\n"
        "steps:\n"
        "  - id: synthetic_declared_step\n"
        "    gates:\n" + "\n".join(clauses) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two declared clauses, both accepted by the parser they name."""
    return _tree(work, _ACCEPTS)


def can_fail(work: Path):
    """The same two clauses; the blocking one's parser now refuses it."""
    root = _tree(work, _REFUSES)
    return root, "declared invocation(s) the named program refuses"
