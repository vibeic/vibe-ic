#!/usr/bin/env python3
"""A looser gate's PASS was read as clearance by a file it never applied its rule to.

THE DEFECT, MEASURED, and it has already cost a batch a red.

`source_chip_agnostic_check` PERMITS open-PDK names — 508 programs carry one
legitimately and banning them repo-wide would redden every one. FIVE programs
carry their OWN, stricter rule, asserted only by their own test file. Nothing
connected the two. So an author edits one of those five, runs the repo-wide gate,
reads

    PASS (1544 file(s) scanned): no forbidden chip / vendor / SKU tokens ...

and concludes the file is clear. It is not. On 2026-08-21 a docstring paragraph
naming two open PDKs went into `area_total_vs_budget_check` exactly that way; the
batch that carried it recorded the red as
`c5c2e22824` in `bb2db3381` and had to fix it downstream.

THE POPULATION IS MEASURED FROM THE TESTS, NOT LISTED HERE. A hand-written list
of five program names would be wrong the first time somebody adds a sixth, and
its failure mode is the quiet one: "no stricter rule here" when there is. So the
discovery below reads the TEST files and finds the bans structurally, and a
control asserts the discoverer is still live — a discoverer that finds nothing
would make every assertion in this file vacuously true.

AND THE SCOPES ARE NOT THE SAME RULE, which is the part that actually bit:

    strict        the test reads the WHOLE file — a DOCSTRING naming a PDK is red
    strict-logic  the test splits the source on a triple quote and keeps the
                  tail, so the module docstring MAY name one and only the
                  logic may not

Both are stricter than the repo-wide gate. Only `strict` can be broken by a
comment, and the file that broke was a `strict` one. A declaration that got the
scope wrong would be worse than none, so the scope is asserted against what each
test ACTUALLY does, not against what its name suggests.

WHAT THIS CHANGE DOES NOT DO, deliberately: it does not make the repo-wide gate
ENFORCE the stricter rule. Each program's own test is the lane that can refuse,
and a second enforcement of one rule is two lanes that can disagree. This half is
a CENSUS — it discloses, and the disclosure is what the exit code never carried.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
_GATE = _PROGRAMS / "source_chip_agnostic_check.py"

#: Commercial-vendor names. A program-local ban NAMES SEVERAL of them; an
#: unrelated `for tok in (...)` loop does not. Two is the discriminator that
#: separates this class from the 152 assertion loops a shape-only match finds.
_VENDOR = {"tsmc", "samsung", "globalfound", "globalfoundries", "umc",
           "smic", "intel"}
#: Open PDK names. Their presence in a ban is what makes it STRICTER than the
#: repo-wide gate, which permits them.
_OPEN = {"sky130", "gf180", "sg13g2", "sg13", "asap7", "nangate", "ihp"}

def _gate_mod():
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the gate this file measures."""
    spec = importlib.util.spec_from_file_location("_scac_strict", _GATE)
    mod = importlib.util.module_from_spec(spec)
    # REGISTERED under its private name before exec: `@dataclass` resolves its
    # own annotations via `sys.modules[cls.__module__]`, so a module that is
    # not there raises AttributeError out of dataclasses at import time. The
    # private NAME is what keeps this a private copy; the registration does not
    # give a sibling test a way to reach the shipped module under its own name.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _bans_in(test_path: Path):
    """Every program-local vendor ban in one test file, with the scope it
    enforces and the program it guards.

    Structural, never a grep for a test NAME: two of the five are named
    `test_the_library_is_chip_and_pdk_and_vendor_agnostic` and
    `test_the_checker_is_chip_and_pdk_agnostic`, so a name-based search finds
    three of five and silently calls that the population. (It did. That
    undercount is why this reads the AST.)
    """
    try:
        tree = ast.parse(test_path.read_text(errors="replace"))
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(
                node.iter, (ast.Tuple, ast.List)):
            continue
        toks = {e.value.lower() for e in node.iter.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if len(toks & _VENDOR) < 2:
            continue
        if not any(isinstance(a, ast.Assert) and isinstance(a.test, ast.Compare)
                   and any(isinstance(o, ast.NotIn) for o in a.test.ops)
                   for a in ast.walk(node)):
            continue
        # SCOPE, read from what the test DOES: a `split('\"\"\"', 2)` anywhere in
        # the enclosing function means the module docstring is stripped first.
        fn = _enclosing_function(tree, node)
        scope = "strict-logic" if _strips_docstring(fn) else "strict"
        out.append({"test": test_path.name,
                    "function": getattr(fn, "name", "?"),
                    "scope": scope,
                    "bans_open_pdks": sorted(toks & _OPEN)})
    return out


def _enclosing_function(tree, target):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
                n is target for n in ast.walk(node)):
            best = node
    return best


def _strips_docstring(fn) -> bool:
    """True when the function splits on a triple quote before checking — the
    `src.split('\"\"\"', 2)[-1]` idiom that makes a ban logic-only."""
    if fn is None:
        return False
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "split" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and '"""' in node.args[0].value):
            return True
    return False


def _discovered():
    """Every program-local vendor ban in the shipped test suite."""
    rows = []
    for f in sorted(_TESTS.glob("test_*.py")):
        rows.extend(_bans_in(f))
    return rows


# ───────────────────────────────────────────── the discoverer must be LIVE

def test_the_discoverer_still_finds_the_class_at_all():
    """EVERY assertion below is of the form "each discovered ban is declared".
    That family is satisfied completely by a discoverer that finds nothing, so
    this is the assertion the rest of the file rests on. Measured on
    origin/main a4caccefe: 5 bans across 5 test files, 4 of them stricter than
    the repo-wide gate."""
    rows = _discovered()
    assert len(rows) >= 5, (
        f"the discoverer found {len(rows)} program-local vendor ban(s); it "
        f"found 5 when this was written. A discoverer that has gone blind "
        f"makes every other assertion here vacuously true — fix the "
        f"discovery, never the bound")
    stricter = [r for r in rows if r["bans_open_pdks"]]
    assert len(stricter) >= 4, (
        f"only {len(stricter)} of {len(rows)} ban(s) forbid an open PDK; 4 did")


def test_both_scopes_are_present_so_the_distinction_is_not_theoretical():
    """The two scopes are different rules and only one can be broken by a
    comment. If the corpus ever carried just one of them, a declaration that
    got the scope wrong would never be caught by anything here."""
    scopes = {r["scope"] for r in _discovered()}
    assert scopes == {"strict", "strict-logic"}, (
        f"scopes present: {sorted(scopes)}; both were present when this was "
        f"written, and the assertions below distinguish them")


# ─────────────────────────────────────── the gate can READ a declaration

@pytest.mark.parametrize("scope", ["strict", "strict-logic"])
def test_the_gate_reads_a_declaration_of_each_scope(scope):
    """RETURNED VALUE, not a grep: `declared_strictness` is the exact function
    the gate calls, so this cannot pass on a declaration the gate would not
    see — one past the 4000-character window, or one that does not open its
    line."""
    mod = _gate_mod()
    assert mod.declared_strictness(
        f'"""a program.\n\nCHIP_AGNOSTIC: {scope} — because.\n"""\n') == scope


def test_strict_is_not_swallowed_by_being_a_prefix_of_strict_logic():
    """`strict` is a prefix of `strict-logic`, so an alternation in the wrong
    order reports the WHOLE-FILE scope for a file that declared the weaker one
    — telling an author their docstring is dangerous when it is not, and the
    reverse for the next reader. Asserted because the ordering is invisible."""
    mod = _gate_mod()
    assert mod.declared_strictness(
        '"""x\n\nCHIP_AGNOSTIC: strict-logic — only the logic.\n"""') == \
        "strict-logic"


def test_a_declaration_below_the_window_is_not_read():
    """The window is the point: a declaration a reader never meets is not one.
    This pins that the gate agrees with that, rather than quietly reading the
    whole file and disagreeing with its own documented contract."""
    mod = _gate_mod()
    buried = '"""x\n\n' + ("filler line\n" * 900) + \
             "CHIP_AGNOSTIC: strict — too late.\n\"\"\"\n"
    assert len(buried) > mod._STRICTNESS_WINDOW
    assert mod.declared_strictness(buried) is None


def test_prose_about_the_token_is_not_a_declaration():
    """Several files discuss this rule. A mention inside a sentence must not be
    read as the file declaring one — the identical defect vibe-ic#886 fixed for
    `ENFORCEMENT:`, one gate over."""
    mod = _gate_mod()
    assert mod.declared_strictness(
        '"""we set CHIP_AGNOSTIC: strict on two programs elsewhere."""') is None


# ──────────────────────────── every discovered ban is DECLARED by its program

def test_every_program_local_ban_is_declared_by_the_program_it_guards():
    """THE FIX ITSELF. A rule asserted only in a test file is invisible to the
    person editing the program, which is how the red got in."""
    mod = _gate_mod()
    declared = {}
    for f in list(_PROGRAMS.rglob("*.py")):
        try:
            s = mod.declared_strictness(f.read_text(errors="replace"))
        except OSError:
            continue
        if s:
            declared[f.name] = s
    # ONLY the stricter ones. The fifth discovered ban
    # (`test_step32_resizer_area_ceiling`) forbids the same set the repo-wide
    # gate already covers, so its program has no rule of its own to declare and
    # demanding one would be ceremony. `bans_open_pdks` is the discriminator,
    # read from the ban itself rather than from a list of names here.
    rows = [r for r in _discovered() if r["bans_open_pdks"]]
    assert rows, "no STRICTER ban discovered; see the discoverer control above"
    missing = []
    for r in rows:
        # The guarded program is named by the test; resolve it from the test's
        # own source rather than from its filename, because two of the five
        # guard a module under `_ppa/` whose name the test filename never says.
        src = (_TESTS / r["test"]).read_text(errors="replace")
        guarded = [n for n in declared if n in src]
        if not guarded:
            missing.append(r)
    assert not missing, (
        "these program-local bans are asserted by a test but DECLARED by no "
        "program, so an author editing the program cannot see the rule:\n  "
        + "\n  ".join(f"{m['test']}::{m['function']}" for m in missing))


def test_the_two_whole_file_programs_declare_the_whole_file_scope():
    """The sub-class that can be broken by a comment. Named explicitly because
    getting the SCOPE wrong here is the failure this whole file is about, and
    a generic "something is declared" assertion would not catch it."""
    mod = _gate_mod()
    for name in ("area_total_vs_budget_check.py", "closed_loop_edge_check.py"):
        p = _PROGRAMS / name
        assert p.is_file(), f"{name} is gone; re-derive the population"
        assert mod.declared_strictness(p.read_text()) == "strict", (
            f"{name}'s own test reads the WHOLE file, docstring included, so a "
            f"comment naming a PDK reddens it. It must declare `strict`")


def test_a_declaring_program_names_no_forbidden_token_in_the_declaration():
    """A declaration that itself names a PDK would redden the very test it
    exists to warn about — the joke version of this bug."""
    for name in ("area_total_vs_budget_check.py", "closed_loop_edge_check.py"):
        low = (_PROGRAMS / name).read_text().lower()
        for tok in ("sky130", "gf180", "sg13g2", "tsmc", "samsung",
                    "globalfound", "intel", "umc", "smic"):
            assert tok not in low, f"{name} names {tok!r}"


# ─────────────────────────────────────── the PASS stops claiming clearance

def test_the_gate_discloses_them_on_the_pass_path(tmp_path):
    """END TO END, on the CONSOLE and in the JSON.

    The PASS line is what gets mistaken for a clean bill, so the disclosure has
    to be on the PASS path — not only in a report nobody opens, and not only on
    the FAIL path, which already sends the reader to a file."""
    out = tmp_path / "r.json"
    cp = _pr.run(
        [sys.executable, str(_GATE), str(_PLUGIN), "--json", str(out)],
        capture_output=True, text=True)
    assert cp.returncode == 0, (cp.stdout[-3000:], cp.stderr[-2000:])
    assert "DISCLOSURE" in cp.stdout, cp.stdout[-2000:]
    assert "is not their verdict" in cp.stdout, cp.stdout[-2000:]
    for name in ("area_total_vs_budget_check.py", "closed_loop_edge_check.py"):
        assert name in cp.stdout, (name, cp.stdout[-2000:])
    rep = json.loads(out.read_text())
    declared = rep["declared_stricter_than_this_gate"]
    assert len(declared) >= 5, declared
    assert declared["programs/area_total_vs_budget_check.py"] == "strict"


# ═════════════════════════════════════════════════════════════ THE CONTROLS
#
# Every assertion above says the gate REPORTS something. That is satisfiable by
# a gate that reports the same thing about everything, so the controls drive the
# same `audit()` over synthetic trees and prove it discriminates.

def _tree(root: Path, files: dict) -> Path:
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        p = progs / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return root


def test_the_control_an_undeclared_program_is_not_disclosed(tmp_path):
    """The gate must not credit a file that declared nothing — otherwise the
    disclosure is noise and a reader learns to skip it."""
    mod = _gate_mod()
    root = _tree(tmp_path / "t", {
        "quiet.py": '"""says nothing about its strictness."""\n',
        "loud.py": '"""x\n\nCHIP_AGNOSTIC: strict — whole file.\n"""\n',
    })
    verdict, findings = mod.audit(root)
    assert verdict == "PASS", (verdict, findings)
    assert dict(mod.DECLARED_STRICT) == {"programs/loud.py": "strict"}, \
        dict(mod.DECLARED_STRICT)


def test_the_control_the_disclosure_does_not_fire_when_nothing_declares(
        tmp_path):
    """A tree with no declaration must print no disclosure at all, or the line
    stops carrying information."""
    mod = _gate_mod()
    root = _tree(tmp_path / "t", {"quiet.py": '"""nothing."""\n'})
    verdict, _ = mod.audit(root)
    assert verdict == "PASS"
    assert dict(mod.DECLARED_STRICT) == {}
    cp = _pr.run([sys.executable, str(_GATE), str(root)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "DISCLOSURE" not in cp.stdout, cp.stdout


def test_the_control_state_does_not_leak_between_runs(tmp_path):
    """`DECLARED_STRICT` is module-level, so a second `audit()` that forgot to
    clear it would report the FIRST tree's declarations about the second — a
    disclosure about files the run never saw."""
    mod = _gate_mod()
    a = _tree(tmp_path / "a",
              {"loud.py": '"""x\n\nCHIP_AGNOSTIC: strict — whole file.\n"""\n'})
    b = _tree(tmp_path / "b", {"quiet.py": '"""nothing."""\n'})
    mod.audit(a)
    assert dict(mod.DECLARED_STRICT)
    mod.audit(b)
    assert dict(mod.DECLARED_STRICT) == {}, (
        "the previous run's declarations survived into this one")


def test_the_control_the_disclosure_never_changes_the_verdict(tmp_path):
    """THE RULING THIS CHANGE OBEYS: the program's own test is the lane that can
    refuse; this half is a CENSUS. A declaring file that DOES carry a forbidden
    token must still fail for the token — on the repo-wide rule, by the normal
    path — and a declaring file that is clean must still pass. The declaration
    must move the verdict in neither direction."""
    mod = _gate_mod()
    clean = _tree(tmp_path / "c",
                  {"d.py": '"""x\n\nCHIP_AGNOSTIC: strict — whole file.\n"""\n'})
    v1, f1 = mod.audit(clean)
    assert v1 == "PASS" and not f1, (v1, f1)
    # The token is taken from the gate's OWN list rather than guessed. The
    # first guess here was a commercial foundry name and the control failed
    # GREEN, which sent me to measure what actually bans what:
    #
    #   source_chip_agnostic_check._FORBIDDEN_TOKENS   8 tokens, no vendor name
    #   source_chip_agnostic_check._NDA_TOKENS         8 tokens, no vendor name
    #   nda_diff_scan_check --diff-file <adds a vendor name>          rc 0, PASS
    #
    # So NO repo-wide guard bans a public foundry name, and that is CORRECT
    # rather than a hole: those 8 tokens are confidential chip / customer
    # identifiers, and naming a public company is not a leak. Keeping a vendor
    # name out of a GATE'S LOGIC is a different concern with a different owner —
    # and its owner is exactly the five program-local bans this file makes
    # discoverable. For those five programs the local ban is the ONLY thing
    # standing between the tree and a vendor literal, which is why a PASS from
    # the repo-wide gate must stop reading as their verdict.
    tok = sorted(mod._FORBIDDEN_TOKENS)[0]
    dirty = _tree(tmp_path / "d", {
        "d.py": '"""x\n\nCHIP_AGNOSTIC: strict — whole file.\n"""\n'
                f'V = "{tok}"\n'})
    v2, f2 = mod.audit(dirty)
    assert v2 == "FAIL" and f2, (
        f"a declared-strict file carrying {tok!r} must still FAIL on the "
        f"repo-wide rule; declaring is not an exemption")


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
