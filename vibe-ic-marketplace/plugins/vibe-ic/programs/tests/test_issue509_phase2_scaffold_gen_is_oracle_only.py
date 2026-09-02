#!/usr/bin/env python3
"""vibe-ic#509 — `phase2_scaffold_gen` is ORACLE-ONLY, and stays that way.

WHAT #509 MEASURED
==================
`programs/phase2_scaffold_gen.py` has no production caller. No runner names
it at any version, `flow/phase1_phase2_phase3.yaml` does not name it, nothing
invokes it as a subprocess, and nothing else writes a `<top>_fsm.v`. Phase 2
authors RTL through `design_one_shot_runner.step_rtl_gen`. The module's real
role is a CONTRACT ORACLE: the executable specification of what a conforming
Phase 2 must be able to produce from the L docs, which the L1/L4/L6/L17/…
layer gates import and drive.

That is a legitimate design. What was not legitimate was five-plus gates —
one of them BLOCKING Phase 1 — justifying their requirements with a sentence
about a consequence that never occurs ("so phase 2 receives a state enum with
no transition information at all"). Those now read counterfactually.

WHY A TEST AND NOT ONLY A DOCSTRING
===================================
The wording is only true while the measurement holds. If someone later wires
this module into a runner or a flow step, every counterfactual sentence in
those gates silently becomes an understatement, and nothing would say so.
These tests make wiring it a DELIBERATE ACT that reddens a named test rather
than a silent change of meaning in eight other files.

Everything below is DERIVED FROM THE REAL TREE — globs and AST walks over
whatever `programs/` and `flow/` actually contain. Nothing here is a
hardcoded file list that goes stale when a program is added or renamed.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

import pytest

from _plugin_tree import plugin_path

ORACLE_STEM = "phase2_scaffold_gen"
ORACLE_FILE = f"{ORACLE_STEM}.py"

#: Names that only this module owns. A reference to any of them is a
#: reference to the oracle even when the module name itself is absent.
ORACLE_TOKENS = (ORACLE_STEM, "emit_fsm_v", "derive_fsm_states")

PROGRAMS = plugin_path("programs")
FLOW = plugin_path("flow")
ORACLE_PATH = PROGRAMS / ORACLE_FILE


# ---------------------------------------------------------------------------
# Tree walkers — the population is measured, never listed.
# ---------------------------------------------------------------------------

def _production_programs() -> List[Path]:
    """Every shipped `programs/*.py` except the oracle and the test tree."""
    return sorted(p for p in PROGRAMS.glob("*.py") if p.name != ORACLE_FILE)


def _runner_programs() -> List[Path]:
    """Every program the repo's own naming convention calls a runner."""
    return sorted(p for p in PROGRAMS.glob("*runner*.py"))


def _flow_specs() -> List[Path]:
    """Every flow specification file, whatever its extension."""
    if not FLOW.is_dir():
        return []
    return sorted(p for p in FLOW.rglob("*") if p.is_file())


def _mentions_oracle(text: str) -> List[str]:
    return [t for t in ORACLE_TOKENS if t in text]


#: The flow-spec keys whose scalars the flow LOADER ACTUALLY EXECUTES.
#: Read off `flow/phase1_phase2_phase3.yaml`'s own shape, not invented here:
#: a gate clause is either a bare command string or a mapping whose `command`
#: is run and whose `condition_files_exist` paths are evaluated; a step's
#: `programs:` is a list of program names; a `program_outputs` entry names the
#: `program` that writes a `path`.
_FLOW_CLAUSE_KEYS = ("program_exit_zero", "advisory_program_exit_zero",
                     "optional_program_exit_zero")
_FLOW_CLAUSE_EXECUTED = ("command", "condition_files_exist")
_FLOW_OUTPUT_EXECUTED = ("program", "path")


def _flow_values(path: Path) -> List[str]:
    """Every scalar the flow WIRES — prose about the flow excluded.

    vibe-ic#1012 IN THIS FILE. `test_no_flow_step_names_the_scaffold_oracle`
    read the yaml as raw TEXT and asked whether the token appeared anywhere in
    it, so a program named in a `#` COMMENT counted as a flow step naming it.
    #1012 moved the population from raw text to `yaml.safe_load` scalars, which
    drops comments by construction.

    THAT WAS HALF THE POPULATION. MEASURED on live main 7903c1972305
    (2026-09-03, host load 6.5, pinned image sha256:66c33ff2...): the sole
    remaining hit in the whole `flow/` tree is

        steps[0].gate.all_of[22].advisory_program_exit_zero.advisory_reason

    — a PROSE key. It quotes, verbatim, `cross_layer_reference_check`'s own
    notch output from a real spm run on 2026-08-31 ("... phase2_scaffold_gen
    .derive_signals — the derivation that would consume it — yields width").
    The clause's `command` is `cross_layer_reference_check .`; the flow wires
    the oracle NOWHERE. #1012 excluded comments and did not exclude prose
    KEYS, and a YAML string value is a scalar just as much as a wired one.

    Two ways to get this wrong, both rejected. Editing that `advisory_reason`
    to drop the program name would ERASE A MEASURED READING to make a guard
    green — and the ratchet doctrine keeps that notch precisely so the next
    reader knows it was measured. Hand-listing "skip these prose keys" would
    be an allow-list, blind to the next prose key anyone adds and silently
    expiring.

    So the population is defined by BEHAVIOUR: the scalars the loader runs or
    evaluates — a clause's command and its `condition_files_exist` paths, a
    step's `programs:`, a `program_outputs` entry's `program` and `path`. A
    file this reader recognises no executed scalar in falls back to its RAW
    TEXT, and so does a file that is not yaml or does not parse: a reader that
    silently skipped what it could not understand would turn a real wiring
    into a pass, which is the opposite failure and the worse one.

    `test_the_flow_reader_still_sees_every_wiring_shape` pins that the
    narrowing did not blind the guard.
    """
    try:
        import yaml  # noqa: PLC0415
        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                                   # noqa: BLE001
        return [path.read_text(encoding="utf-8", errors="replace")]
    if doc is None:
        return []
    out: List[str] = []

    def emit(node: object) -> None:
        """Every scalar under an EXECUTED node, whatever its nesting."""
        if isinstance(node, dict):
            for v in node.values():
                emit(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                emit(v)
        elif node is not None:
            out.append(str(node))

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                if key in _FLOW_CLAUSE_KEYS:
                    if isinstance(v, dict):
                        for ek in _FLOW_CLAUSE_EXECUTED:
                            emit(v.get(ek))
                    else:
                        emit(v)
                elif key == "programs":
                    emit(v)
                elif key == "program_outputs":
                    for entry in (v if isinstance(v, list) else []):
                        if isinstance(entry, dict):
                            for ek in _FLOW_OUTPUT_EXECUTED:
                                emit(entry.get(ek))
                        else:
                            emit(entry)
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)

    walk(doc)
    if not out:
        # Nothing this reader recognises as wiring. Do not call that clean.
        return [path.read_text(encoding="utf-8", errors="replace")]
    return out


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"))


def _dotted(node: ast.AST) -> str:
    """`a.b.c` for an Attribute/Name chain; "" for anything else."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return ""
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _string_constants(node: ast.AST) -> Iterator[str]:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.value


# ---------------------------------------------------------------------------
# 1 — no runner references the oracle
# ---------------------------------------------------------------------------

def _wires_oracle(path: Path) -> List[Tuple[int, str]]:
    """(lineno, what) for every place `path` actually WIRES the oracle.

    Wiring is an import of the module, a call to something the module owns, or
    a process spawn naming it. NAMING it is not wiring: a comment that explains
    how the oracle ranks a field is documentation of the contract, which is the
    oracle's whole job.

    This is the standard `_subprocess_invocations_of_oracle` already states two
    tests below — "AST-based, so a mention in a comment, a docstring or an
    `import` is not confused with an invocation". This test was the one that
    did not follow it: it read the file as bytes and reported "a runner now
    references it" on any occurrence of the name. MEASURED on the shipped tree:
    `phase1_doc_one_shot_runner.py:63104`, a comment reading
    `# phase2_scaffold_gen.derive_top_module_name ranks L9.top_module above ...`
    turned this guard red, so the suite failed while nothing was wired and the
    counterfactual wording in the eight other files was still exactly true.

    A guard that fires on its subject being DISCUSSED cannot be left armed, and
    a green one that fires on nothing would be worse — so the population moves
    to the syntax, not away from the question.
    """
    try:
        tree = _parse(path)
    except SyntaxError:
        return []
    out: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == ORACLE_STEM or a.name.endswith(f".{ORACLE_STEM}"):
                    out.append((node.lineno, f"import {a.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == ORACLE_STEM
                                or node.module.endswith(f".{ORACLE_STEM}")):
                out.append((node.lineno,
                            f"from {node.module} import "
                            + ", ".join(a.name for a in node.names)))
        elif isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee and any(tok in callee.split(".")
                              for tok in ORACLE_TOKENS):
                out.append((node.lineno, f"call {callee}()"))
    out.extend((ln, f"spawn via {callee}")
               for ln, callee in _subprocess_invocations_of_oracle(path))
    return sorted(set(out))


def test_no_runner_references_the_scaffold_oracle():
    """The measurement #509 turned on: `git log -S` over `programs/*runner*.py`
    across all refs returns nothing. Pinned here on the current tree."""
    runners = _runner_programs()
    assert runners, (
        f"no *runner*.py found under {PROGRAMS} — the glob that defines this "
        f"test's population is broken, so a PASS would be vacuous"
    )
    offenders: Dict[str, List[Tuple[int, str]]] = {}
    for r in runners:
        hits = _wires_oracle(r)
        if hits:
            offenders[r.name] = hits
    assert not offenders, (
        f"{ORACLE_STEM} is ORACLE-ONLY (#509) and a runner now wires it: "
        f"{offenders}. Every gate that cites this module states its "
        f"requirement counterfactually ('a conforming phase 2 WOULD receive'). "
        f"Wiring it is a legitimate decision — but the gates' wording, this "
        f"module's docstring and INDEX.md all have to change with it."
    )


def test_this_guard_still_catches_a_runner_that_really_wires_it(tmp_path):
    """The reverse case. Moving from "the name appears" to "the syntax wires
    it" narrows the guard, so the narrowing has to be shown not to have blinded
    it — each of the three wiring shapes must still be caught, and a comment
    that merely names the oracle must not be."""
    shapes = {
        "import": f"import {ORACLE_STEM}\n",
        "from-import": f"from {ORACLE_STEM} import emit_fsm_v\n",
        "call": f"import x\nx.{ORACLE_STEM}.emit_fsm_v(1)\n",
        "spawn": ("import subprocess\n"
                  f"subprocess.run(['python3', '{ORACLE_STEM}.py'])\n"),
    }
    for label, src in shapes.items():
        p = tmp_path / f"{label}_runner.py"
        p.write_text(src)
        assert _wires_oracle(p), f"{label} wiring went undetected"

    innocent = tmp_path / "comment_runner.py"
    innocent.write_text(
        f"# {ORACLE_STEM}.derive_top_module_name ranks L9.top_module above\n"
        f'"""{ORACLE_STEM} is the contract oracle for phase 2."""\n'
        f'NOTE = "see {ORACLE_STEM} for the conforming shape"\n')
    assert not _wires_oracle(innocent), (
        "a comment/docstring/string that names the oracle is documentation of "
        "the contract, not wiring")


# ---------------------------------------------------------------------------
# 2 — no flow step names the oracle
# ---------------------------------------------------------------------------

def test_no_flow_step_names_the_scaffold_oracle():
    specs = _flow_specs()
    assert specs, (
        f"no flow specification files under {FLOW} — this test's population "
        f"is empty, so a PASS would be vacuous"
    )
    offenders: Dict[str, List[str]] = {}
    for s in specs:
        try:
            values = _flow_values(s)
        except OSError:
            continue
        hits = sorted({t for v in values for t in _mentions_oracle(v)})
        if hits:
            offenders[str(s.relative_to(FLOW))] = hits
    assert not offenders, (
        f"{ORACLE_STEM} is ORACLE-ONLY (#509) and a flow specification now "
        f"names it: {offenders}. See the module docstring before landing it."
    )


def test_the_flow_reader_still_sees_every_wiring_shape(tmp_path):
    """CONTROL for the narrowing above — the direction that must stay RED.

    Moving the flow population from "every parsed scalar" to "every EXECUTED
    scalar" narrows the guard, so the narrowing has to be shown not to have
    blinded it. Every shape the live spec actually uses to wire a program is
    planted here with the oracle's name in it, and each must still be seen;
    a prose key carrying the same name must not be.

    The wiring shapes are not re-typed from memory — they are the keys this
    module declares it reads, so a shape added to `_FLOW_CLAUSE_KEYS` or
    `_FLOW_OUTPUT_EXECUTED` and not covered here fails the last assertion.
    """
    seen_clause_keys, seen_output_keys = set(), set()
    wiring = {
        "clause-as-string": {
            "steps": [{"gate": {"all_of": [
                {"program_exit_zero": f"{ORACLE_STEM} ."}]}}]},
        "clause-as-mapping-command": {
            "steps": [{"gate": {"all_of": [
                {"advisory_program_exit_zero": {
                    "command": f"{ORACLE_STEM} .",
                    "advisory_reason": "why"}}]}}]},
        "clause-optional-command": {
            "steps": [{"gate": {"all_of": [
                {"optional_program_exit_zero": {
                    "command": f"{ORACLE_STEM} ."}}]}}]},
        "clause-condition-files": {
            "steps": [{"gate": {"all_of": [
                {"program_exit_zero": {
                    "command": "something_else .",
                    "condition_files_exist": [f"programs/{ORACLE_FILE}"]}}]}}]},
        "step-programs-list": {
            "steps": [{"programs": ["a_check", ORACLE_STEM]}]},
        "program-outputs-program": {
            "steps": [{"program_outputs": [
                {"program": ORACLE_STEM, "path": "reports/x.json"}]}]},
        "program-outputs-path": {
            "steps": [{"program_outputs": [
                {"program": "a_check", "path": f"reports/{ORACLE_STEM}.json"}]}]},
        "oracle-token-not-the-module-name": {
            "steps": [{"programs": ["emit_fsm_v"]}]},
    }
    # EVERY planted doc also carries one UNRELATED executed scalar. Without it
    # a reader that stopped honouring the shape under test would emit nothing,
    # fall back to raw text, and find the token anyway — MEASURED: disabling
    # `programs:` in the reader left this control GREEN until this line existed.
    ballast = {"gate": {"all_of": [{"program_exit_zero": "unrelated_check ."}]}}
    for label, doc in wiring.items():
        doc = dict(doc)
        doc["steps"] = list(doc["steps"]) + [ballast]
        spec = tmp_path / f"{label}.yaml"
        spec.write_text(json.dumps(doc))
        values = _flow_values(spec)
        assert "unrelated_check ." in values, (
            f"{label}: the ballast scalar did not reach the reader, so this "
            f"case is being rescued by the raw-text fallback and proves "
            f"nothing about the shape it plants")
        assert _mentions_oracle(" ".join(values)), (
            f"the flow reader no longer sees the {label!r} wiring shape; the "
            f"narrowing blinded the guard it was meant to sharpen")
        for k in _FLOW_CLAUSE_KEYS:
            if k in json.dumps(doc):
                seen_clause_keys.add(k)
        for k in _FLOW_OUTPUT_EXECUTED:
            if label.startswith("program-outputs"):
                seen_output_keys.add(k)

    # ...and the measured false positive this narrowing removes.
    prose = tmp_path / "prose.yaml"
    prose.write_text(json.dumps({"steps": [{"gate": {"all_of": [
        {"advisory_program_exit_zero": {
            "command": "cross_layer_reference_check .",
            "advisory_reason": (
                "Notch measured rc 1 on a real spm run (2026-08-31). It "
                f"reported: {ORACLE_STEM}.derive_signals — the derivation "
                "that would consume it — yields width"),
            "absent_condition_reason": f"{ORACLE_STEM} is not wired here"}}]}}]}))
    assert not _mentions_oracle(" ".join(_flow_values(prose))), (
        "prose ABOUT the oracle was read as the flow WIRING it — the #1012 "
        "shape, one layer in")

    # A shape this module says it reads but nothing above exercises would make
    # the control weaker than the reader.
    assert seen_clause_keys == set(_FLOW_CLAUSE_KEYS), (
        f"clause keys the reader honours but this control never plants: "
        f"{sorted(set(_FLOW_CLAUSE_KEYS) - seen_clause_keys)}")
    assert seen_output_keys == set(_FLOW_OUTPUT_EXECUTED), (
        f"program_outputs keys the reader honours but this control never "
        f"plants: {sorted(set(_FLOW_OUTPUT_EXECUTED) - seen_output_keys)}")


def test_a_flow_file_the_reader_cannot_read_is_scanned_whole(tmp_path):
    """The safe direction, kept. An unparseable spec, and a parseable one with
    no wiring the reader recognises, both fall back to RAW TEXT — silently
    skipping what it cannot understand would turn a real wiring into a pass."""
    broken = tmp_path / "broken.yaml"
    broken.write_text(f"steps: [ {{ unbalanced: '{ORACLE_STEM}'\n")
    assert _mentions_oracle(" ".join(_flow_values(broken)))

    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"some_future_key": ORACLE_STEM}))
    assert _mentions_oracle(" ".join(_flow_values(unknown))), (
        "a flow file whose shape this reader does not know was reported "
        "clean; 'I could not read it' is not 'there is nothing there'")


# ---------------------------------------------------------------------------
# 3 — nothing invokes the oracle as a subprocess / CLI
# ---------------------------------------------------------------------------

_SUBPROCESS_PREFIXES = ("subprocess.",)
_EXEC_CALLS = {
    "os.system", "os.popen", "os.spawnl", "os.spawnv", "os.spawnlp",
    "os.spawnvp", "os.execv", "os.execvp", "os.execl", "os.execlp",
}


def _subprocess_invocations_of_oracle(path: Path) -> List[Tuple[int, str]]:
    """(lineno, callee) for every process-spawning call in `path` whose
    arguments mention the oracle. AST-based, so a mention in a comment, a
    docstring or an `import` is not confused with an invocation."""
    try:
        tree = _parse(path)
    except SyntaxError:
        return []
    out: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _dotted(node.func)
        if not callee:
            continue
        spawns = (callee in _EXEC_CALLS
                  or any(callee.startswith(p) for p in _SUBPROCESS_PREFIXES))
        if not spawns:
            continue
        if any(ORACLE_STEM in s for s in _string_constants(node)):
            out.append((node.lineno, callee))
    return out


def test_nothing_invokes_the_scaffold_oracle_as_a_subprocess():
    programs = _production_programs()
    assert len(programs) > 100, (
        f"only {len(programs)} programs found under {PROGRAMS}; the "
        f"population this test scans looks wrong"
    )
    offenders: Dict[str, List[Tuple[int, str]]] = {}
    for p in programs:
        hits = _subprocess_invocations_of_oracle(p)
        if hits:
            offenders[p.name] = hits
    assert not offenders, (
        f"{ORACLE_STEM} is ORACLE-ONLY (#509) and is now spawned as a "
        f"process: {offenders}. A gate reading it as a library is the "
        f"oracle role; running it is production wiring."
    )


# ---------------------------------------------------------------------------
# 4 — nothing calls the oracle's main()
# ---------------------------------------------------------------------------

def _oracle_aliases(tree: ast.Module) -> Set[str]:
    """Every local name bound to the oracle module by an import in `tree`."""
    aliases: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == ORACLE_STEM:
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == ORACLE_STEM:
                for a in node.names:
                    if a.name == "main":
                        aliases.add(f"::{a.asname or a.name}")
    return aliases


def test_nothing_calls_the_scaffold_oracles_main():
    """`main()` is what turns the specification into files on disk. A gate
    drives `derive_*` / `emit_*` in memory and writes nothing; a caller of
    `main()` is production wiring by another name."""
    offenders: Dict[str, List[int]] = {}
    for p in _production_programs():
        try:
            tree = _parse(p)
        except SyntaxError:
            continue
        aliases = _oracle_aliases(tree)
        if not aliases:
            continue
        bare = {a[2:] for a in aliases if a.startswith("::")}
        mods = {a for a in aliases if not a.startswith("::")}
        hits: List[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _dotted(node.func)
            if not callee:
                continue
            if callee in bare:
                hits.append(node.lineno)
            elif "." in callee:
                head, _, tail = callee.rpartition(".")
                if tail == "main" and head in mods:
                    hits.append(node.lineno)
        if hits:
            offenders[p.name] = hits
    assert not offenders, (
        f"{ORACLE_STEM}.main() is now called from production code: "
        f"{offenders}. That writes phase2/stage1/scaffold/ into a real "
        f"project, which is exactly the wiring #509 measured absent."
    )


def test_importing_the_oracle_writes_nothing():
    """Its own `main()` must be reachable only through the `__main__` guard,
    so every gate that imports it gets a pure library."""
    tree = _parse(ORACLE_PATH)
    guarded: Set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if "__name__" not in {
            n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)
        }:
            continue
        for sub in ast.walk(node):
            guarded.add(id(sub))
    unguarded: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _dotted(node.func) != "main":
            continue
        if id(node) not in guarded:
            unguarded.append(node.lineno)
    assert not unguarded, (
        f"{ORACLE_FILE} calls main() outside the `if __name__ == '__main__'` "
        f"guard at line(s) {unguarded}; importing it would then write files "
        f"into whatever project a gate is judging."
    )


# ---------------------------------------------------------------------------
# 5 — the oracle role is REAL: the opposite drift is pinned too
# ---------------------------------------------------------------------------

def test_the_oracle_still_has_gate_readers():
    """Guard against the mirror-image regression: if every gate stopped
    importing it, the module would be dead code and #509's answer — "it is a
    reference implementation the gates read" — would no longer be true."""
    readers: List[str] = []
    for p in _production_programs():
        try:
            tree = _parse(p)
        except SyntaxError:
            continue
        if _oracle_aliases(tree):
            readers.append(p.name)
            continue
        # importlib file-path loads count too: that is how the L6 gate and
        # cross_layer_reference_check reach it without a package import.
        text = p.read_text(encoding="utf-8", errors="replace")
        if ORACLE_FILE in text and "spec_from_file_location" in text:
            readers.append(p.name)
    assert len(readers) >= 3, (
        f"only {readers} still read {ORACLE_STEM} as a contract oracle. "
        f"#509 recorded its role as 'the executable specification the layer "
        f"gates drive'; if the gates stopped driving it, that record is "
        f"stale and the module has no role at all."
    )


# ---------------------------------------------------------------------------
# 6 — the decision is recorded where the next reader hits it
# ---------------------------------------------------------------------------

def test_the_module_declares_itself_oracle_only():
    doc = ast.get_docstring(_parse(ORACLE_PATH)) or ""
    assert doc, f"{ORACLE_FILE} lost its module docstring"
    first = doc.splitlines()[0]
    assert "ORACLE" in first.upper(), (
        f"{ORACLE_FILE}'s first docstring line no longer says it is an "
        f"oracle: {first!r}. That line is what `tools/gen_programs_index.py` "
        f"renders into INDEX.md, so it is where the next reader hits the "
        f"question #509 answered."
    )


def test_index_md_does_not_describe_the_oracle_as_a_live_path():
    index = PROGRAMS / "INDEX.md"
    if not index.is_file():
        pytest.skip("INDEX.md not present in this tree")
    rows = [ln for ln in index.read_text(encoding="utf-8").splitlines()
            if f"`{ORACLE_STEM}`" in ln]
    assert rows, f"{ORACLE_STEM} has no entry in INDEX.md"
    for row in rows:
        assert "ORACLE" in row.upper(), (
            f"INDEX.md still describes {ORACLE_STEM} as a live path: "
            f"{row.strip()!r}. Re-run `python3 tools/gen_programs_index.py` "
            f"after the module docstring, or say plainly that it now runs."
        )
