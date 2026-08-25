"""`PPA actuator registry bindings` — an EXECUTABLE claim over a program that
is not in the tree.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT. `_ppa.closure.verify_bindings`
says it in one line: "An unverified claim of executability is the same defect
one level up as an unexecuted `closed_loop`: a promise nothing checks." So the
mutation renames the program ONE EXECUTABLE actuator names, to a name that does
not exist under `programs/`. The entry keeps `binding: EXECUTABLE`; what changes
is whether that permission resolves to anything.

WHY THE PROGRAM NAME AND NOT THE BINDING. Flipping `DECLARED_ONLY` ->
`EXECUTABLE` would also refuse, but for a different rule (a DECLARED_ONLY entry
that names a program), and it would be refused by the shape of the entry rather
than by the state of the tree. Renaming keeps the registry perfectly
well-formed and moves only the fact the gate exists to check.

THE DENOMINATOR IS IDENTICAL IN BOTH ARMS, and the gate prints it: both print
`actuators 6 (1 EXECUTABLE)`, `domains 9 (2 EXECUTABLE)`, `controllers 1`. The
CAN-FAIL arm does not shrink the registry, so its refusal cannot be the empty-
population path — it is a verdict about a claim that is still there.

WHY `$PG` MATTERS HERE MORE THAN USUAL. The resolution the gate performs is
`programs/<name>.py` under the REAL programs directory (`_ppa.closure`
resolves it from its own `__file__`, not from the subject). That is exactly
what the protocol's `$PG`-stays-real rule preserves, and it is why the mutant
name carries a suffix that no shipped program can plausibly acquire.

The registry is written back through `yaml.safe_dump`, so both arms differ in
one scalar and in nothing else — including the CAN-PASS arm, which is round-
tripped identically rather than copied, so the two subjects cannot differ by
serialisation.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process; the
actuator it touches is selected by its `binding`, never by its name.
"""
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "PPA actuator registry bindings"

#: Byte-for-byte the path the declaration passes to `--registry`, relative to
#: `$PLUGIN` — which the engine redirects at the subject root.
_REL = Path("config") / "ppa_actuator_registry.yaml"

#: The real file, under the real plugin. `$PLUGIN` in the declaration is the
#: INPUT and is redirected; this is where the known-good input is read from.
_SOURCE = (F.REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / _REL)

#: A suffix no shipped program can acquire, so the CAN-FAIL arm cannot go green
#: by someone later adding a file with the mutant's name.
_ABSENT = "_absent_from_tree__gate_fixture"


def _write(work: Path, doc: dict) -> Path:
    root = work / "subject"
    (root / _REL).parent.mkdir(parents=True, exist_ok=True)
    (root / _REL).write_text(
        yaml.safe_dump(doc, sort_keys=False, default_flow_style=False,
                       allow_unicode=True),
        encoding="utf-8")
    return root


def _doc() -> dict:
    if not _SOURCE.is_file():
        raise AssertionError(
            f"the actuator registry is not at {_SOURCE}. This fixture cannot "
            f"build a subject for a gate whose input has moved; fix the "
            f"declaration rather than letting the fixture answer over a tree "
            f"with no registry in it.")
    return yaml.safe_load(_SOURCE.read_text(encoding="utf-8"))


def can_pass(work: Path) -> Path:
    """The shipped registry: every EXECUTABLE claim resolves, rc 0."""
    return _write(work, _doc())


def can_fail(work: Path):
    """One EXECUTABLE actuator pointed at a program that is not in the tree."""
    doc = _doc()
    renamed = None
    for aid, actuator in (doc.get("actuators") or {}).items():
        if not isinstance(actuator, dict):
            continue
        if actuator.get("binding") != "EXECUTABLE":
            continue
        wrapper = actuator.get("wrapper")
        if not isinstance(wrapper, dict) or not wrapper.get("program"):
            continue
        wrapper["program"] = str(wrapper["program"]) + _ABSENT
        renamed = aid
        break
    if renamed is None:
        raise AssertionError(
            "the registry declares no EXECUTABLE actuator naming a program, "
            "so this mutation has nothing to break. The fixture would "
            "otherwise hand the gate a CLEAN subject and call its rc 0 a "
            "discrimination.")
    # The token the refusal must carry, so the pair test knows the gate refused
    # for THIS mutation and not by coincidence.
    return _write(work, doc), "claims EXECUTABLE but"
