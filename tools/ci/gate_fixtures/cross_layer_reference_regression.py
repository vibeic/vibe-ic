"""`cross-layer reference regression` — a reference that addresses nothing.

THE GATE'S OWN CLAIM, as `repo_hygiene_gates.sh` declares it, is that the repo
"cannot grow a NEW instance of the class silently": it sweeps
`$ROOT/benchmark-data/ic`, resolves every declared row of
`programs/cross_layer_references.json` across each published cell's L-docs, and
ratchets the resulting `row/code` counts against
`programs/cross_layer_reference_baseline.json`.

The one shipped row, `port_width_symbolic_to_parameter`, resolves in three legs
per element: PARSE the `width_symbolic` value under the `symbolic_range`
grammar, RESOLVE its identifier to a `parameters[]` entry inside the row's
declared `target.scope_layers` (`L8`, `L9`) and read a usable `default`, then
OBSERVE what `phase2_scaffold_gen.derive_signals` — the consuming derivation —
yields for the same port.

THE SUBJECT IS A CORPUS, BUT ONE CELL DOES THE WORK. The declaration's argv is
the only argv a fixture may drive (`gate_mutation_fixtures`, "the fixture may
choose the INPUT and never the ARGV"), so the subject is a git checkout whose
`benchmark-data/ic/` carries one published project tree. Everything below is a
statement about the L-docs of that project.

WHAT THE PASSING SPECIMEN PRESENTS — AND ITS DENOMINATOR
========================================================
Three ports, each declared in `L1.pin_table`, `L9.top_ports` and `L9.ports`, so
the sweep reports

    1 cell(s), 9 producer record(s) carrying a declared reference
    (3 distinct element(s)), 0 finding(s)

9 is not an arbitrary number. `cross_layer_reference_baseline.json` records
`examined: {port_width_symbolic_to_parameter: 9}`, and `compare_denominator`
FAILs any sweep that reaches fewer records than that — so a specimen presenting
8 would be refused for LOST REACH and would prove nothing about whether the
resolver resolves. This one presents exactly the recorded denominator.

It is also NON-VACUOUS in the sense this repo means: each of the three elements
carries a real `width_symbolic` (`WIDTH_A-1:0`, `WIDTH_B-1:0`, `WIDTH_C-1:0`),
each identifier resolves to an `L8_RTL_CONSTANTS.parameters[]` entry whose
`default` is an integer, and each `L9` port also states the matching integer
`width`, which is what `derive_signals` needs in order to reach the same number
(it refuses to resolve `width_symbolic` itself, by design — see its docstring).
So the gate accepts this subject because all three legs of three references
succeeded, never because it found nothing to judge.

THE FAILING SPECIMEN BREAKS EXACTLY ONE CONDITION
=================================================
`port_c`'s `width_symbolic` is rewritten from `WIDTH_C-1:0` to
`UNDECLARED_W-1:0` in the three records that carry that one element. Nothing
else moves. Broken: leg 2, RESOLVE, for one element — `UNDECLARED_W` is
declared by no `parameters[]` collection in any layer of the cell, so the
reference addresses nothing and the finding is `DANGLING_REFERENCE`.

Left deliberately intact, and each of them is a way this refusal could have
been mis-attributed:

  * THE DENOMINATOR. The field is rewritten, never removed, so the sweep still
    examines 9 producer records and `compare_denominator` stays silent. The
    refusal is a NEW break, not the LOST-REACH complaint the same gate emits
    when an emitter renames a field or the corpus shrinks — two failures that
    exit 1 through different branches and mean opposite things.
  * THE GRAMMAR. `UNDECLARED_W-1:0` is still a well-formed `symbolic_range`, so
    leg 1 parses and the finding is not `UNPARSEABLE_REFERENCE`.
  * THE SCOPE. `L8` still declares `WIDTH_A`, `WIDTH_B` and `WIDTH_C`, and no
    layer declares `UNDECLARED_W` anywhere, so the resolver reports
    "nothing declares this name" (`DANGLING_REFERENCE`) rather than "something
    declares it, outside the scoping namespace" (`OUT_OF_SCOPE_REFERENCE`).
  * THE OTHER TWO ELEMENTS. `port_a` and `port_b` still resolve, still read a
    usable `default`, and still agree with the consuming derivation, in the
    SAME run. So the refusal cannot be read as the mechanism having stopped
    working; two thirds of it demonstrably still works while it refuses.
  * THE REGISTER. `cross_layer_reference_baseline.json` is untouched, so its
    seal verifies and neither specimen goes near the `[FAIL] the debt register
    was EDITED` branch.

WHY `DANGLING_REFERENCE` AND NOT MORE OF `CONSUMER_CANNOT_REACH`. The baseline
already RECORDS 3 `CONSUMER_CANNOT_REACH`, so a fourth would have to out-count
a recorded number to be NEW, which makes the specimen's refusal depend on a
count the corpus repository owns rather than on the condition this fixture
broke. `DANGLING_REFERENCE` has never been recorded for this row, so `0 -> 1`
is unambiguously the mutation's own doing.

chip-AGNOSTIC / PDK-AGNOSTIC: the cell, its ports and its parameters are named
for their role in this fixture. No foundry, process node, vendor, SKU, tool or
design codename appears in the subject or in this file.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "cross-layer reference regression"

#: Where the declaration points `--corpus`, and the one cell under it.
CORPUS_REL = Path("benchmark-data/ic")
CELL = "reference_bearing_cell"

#: port name -> (parameter identifier, its declared default = the width the
#: reference resolves to). Three of them, carried by three collections each,
#: is the 9 producer records the baseline's `examined` denominator records.
PORTS = (("port_a", "WIDTH_A", 8),
         ("port_b", "WIDTH_B", 16),
         ("port_c", "WIDTH_C", 4))

#: The element the can-fail specimen breaks, and the identifier it is made to
#: address. Declared by no `parameters[]` collection in any layer of the cell.
BROKEN_PORT = "port_c"
UNDECLARED = "UNDECLARED_W"


def _symbolic(param: str) -> str:
    """A `symbolic_range` address: the row's grammar, well formed."""
    return f"{param}-1:0"


def _docs(broken: bool) -> dict:
    """The cell's L-docs. `broken` rewrites ONE port's reference value."""
    def ref(port: str, param: str) -> str:
        return _symbolic(UNDECLARED if (broken and port == BROKEN_PORT)
                         else param)

    l1 = {
        "layer": "L1",
        "pin_table": [
            {"name": port, "direction": "output",
             "width_symbolic": ref(port, p)}
            for port, p, _w in PORTS
        ],
    }
    # The TARGET namespace: unchanged between the two specimens.
    l8 = {
        "layer": "L8",
        "parameters": [{"name": p, "default": w} for _port, p, w in PORTS],
    }
    # `width` (the integer) is what `derive_signals` can use; `width_symbolic`
    # is the reference this gate resolves. Both are stated, which is what lets
    # leg 3 agree on the passing specimen.
    ports = [
        {"name": port, "direction": "output", "width": w,
         "width_symbolic": ref(port, p), "description": "a referenced bus"}
        for port, p, w in PORTS
    ]
    l9 = {
        "layer": "L9",
        "top_module": "reference_bearing_top",
        "top_ports": ports,
        "ports": [dict(x) for x in ports],
    }
    return {"L1_SYSTEM_OVERVIEW.json": l1,
            "L8_RTL_CONSTANTS.json": l8,
            "L9_INTEGRATION_SPEC.json": l9}


def _tree(work: Path, name: str, *, broken: bool) -> Path:
    """A committed checkout carrying one published cell under the corpus path.

    Committed because `corpus_cells` asks GIT what the corpus publishes — an
    untracked tree would send it to a disk walk, and the population the
    baseline was measured over is the tracked one.
    """
    root = F.git_init(work / name)
    gd = root / CORPUS_REL / CELL / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for fname, payload in _docs(broken).items():
        (gd / fname).write_text(json.dumps(payload, indent=2) + "\n",
                                encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """9 producer records, 3 elements; all resolve and are reached."""
    return _tree(work, "subject_pass", broken=False)


def can_fail(work: Path):
    """One element addresses `UNDECLARED_W`; reach and the other two hold."""
    root = _tree(work, "subject_fail", broken=True)
    return root, ("NEW cross-layer break: port_width_symbolic_to_parameter"
                  "/DANGLING_REFERENCE: 0 -> 1")
