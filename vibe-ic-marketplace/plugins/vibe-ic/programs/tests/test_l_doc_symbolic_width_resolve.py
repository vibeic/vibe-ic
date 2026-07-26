#!/usr/bin/env python3
"""Bidirectional tests for l_doc_symbolic_width_resolve.py.

WHY BOTH DIRECTIONS, ALWAYS
---------------------------
The headline test drives the EXISTING gate
`l1_pin_bus_width_actionable_check` twice around the resolver:

    defect state  -> gate rc 1 (FAIL)
    resolver      -> gate rc 0 (PASS, verdict "PASS", no waiver file)

Either assertion ALONE is a rubber stamp. "It PASSes after the fix" alone
proves nothing — a gate that can never FAIL passes everything, and this whole
class of defect was discovered because presence-shaped checks reported
CAPTURED on a prose string. "It FAILs on the defect" alone proves nothing
either — it does not show the resolver produced the RIGHT width rather than
merely SOME width. Only the pair says the resolver moved a real gate from red
to green by supplying the correct number.

And the third direction, which is the one a resolver can get catastrophically
wrong: when an identifier is NOT resolvable, the document must come back
BYTE-IDENTICAL and the gate must still FAIL. A resolver that guesses turns a
true FAIL into a false PASS, which is strictly worse than not having run.

The measured original: ONE cell, THIRTEEN independent runs
(campaign_v1544..v1578; recorded in
`l1_pin_bus_width_actionable_check.py:31`) carried
`{"width": "N-bit(`[size-1:0]`, parameter `size` ...)", "msb": null,
"lsb": null}` in L1 while the SAME corpus declared that parameter's default
in L8/L9 `parameters[]`. Everything needed was present; nobody joined it.

FIXTURES ARE SYNTHESIZED neutral data — invented parameter and port names on
an invented block. No real design's files are copied, and no design name, PDK
name or vendor part number appears anywhere.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_RESOLVER = _PROGRAMS / "l_doc_symbolic_width_resolve.py"
_L1_GATE = _PROGRAMS / "l1_pin_bus_width_actionable_check.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


res = _load(_RESOLVER, "l_doc_symbolic_width_resolve")
gate = _load(_L1_GATE, "l1_pin_bus_width_actionable_check")


# ---------------------------------------------------------------- fixtures
def _docs_dir(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_doc(project: Path, name: str, payload: dict) -> Path:
    p = _docs_dir(project) / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


def _write_input(project: Path, relpath: str, text: str) -> None:
    p = project / "input" / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _defect_project(tmp_path: Path, *, param_default="16",
                    expr="WORD_W-1:0") -> Path:
    """The measured shape, synthesized: the symbolic width lives in L1, the
    parameter default lives in a DIFFERENT L-doc of the same corpus, and
    nothing joins them."""
    project = tmp_path / "proj"
    _write_doc(project, "L1_DATASHEET.json", {
        "ic_name": "synth_block",
        "pin_table": [
            {"name": "clk_in", "mode": "input",
             "width": 1, "msb": 0, "lsb": 0},
            {"name": "accum_bus", "mode": "output",
             "width": f"N-bit(`[{expr}]`, parameter `WORD_W` default "
                      f"{param_default})",
             "width_symbolic": expr},
        ],
    })
    _write_doc(project, "L8_RTL_CONSTANTS.json", {
        "ic_name": "synth_block",
        "parameters": [
            {"name": "WORD_W", "default": param_default,
             "source": "synthesized_fixture"},
        ],
    })
    # The design's own input declares the parameterised bus, which is what
    # makes the L1 gate treat the pin as bus-confirmed rather than skipping it.
    _write_input(project, "docs/iface.md",
                 f"| accum_bus[{expr}] | output | N-bit | accumulator |\n")
    return project


def _run_gate(project: Path):
    out = project / "l1_verdict.json"
    rc = gate.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _run_resolver(project: Path, *, apply: bool):
    out = project / "resolve.json"
    argv = [str(project), "--json", str(out)]
    if apply:
        argv.append("--apply")
    rc = res.main(argv)
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _bytes_of(project: Path) -> dict:
    return {p.name: p.read_bytes()
            for p in sorted(_docs_dir(project).glob("L*.json"))}


# ------------------------------------------------- (1) the bidirectional pair
def test_defect_fails_gate_then_resolver_turns_the_same_gate_green(tmp_path):
    """THE acceptance evidence, asserted in both directions.

    Neither half stands alone: the FAIL half alone does not show the resolver
    produced the CORRECT width, and the PASS half alone does not show the gate
    was ever capable of failing. Asserted together, and with the exact number
    checked (16, from the corpus' own declared default), they say the resolver
    performed the join rather than merely writing something.
    """
    project = _defect_project(tmp_path)

    # -- direction 1: the defect state FAILs the existing gate --------------
    rc_before, rep_before = _run_gate(project)
    assert rc_before == 1, rep_before
    assert rep_before["verdict"] == "FAIL"
    assert rep_before["violations"][0]["pin"] == "accum_bus"

    # -- the join ----------------------------------------------------------
    rc_res, rep_res = _run_resolver(project, apply=True)
    assert rc_res == 0, rep_res
    assert rep_res["verdict"] == "RESOLVED"
    assert rep_res["parameter_env"] == {"WORD_W": 16}
    assert len(rep_res["resolved"]) == 1
    got = rep_res["resolved"][0]
    assert (got["width"], got["msb"], got["lsb"]) == (16, 15, 0)
    assert got["parameters_used"] == {"WORD_W": 16}

    pin = json.loads(
        (_docs_dir(project) / "L1_DATASHEET.json").read_text()
    )["pin_table"][1]
    assert pin["width"] == 16 and pin["msb"] == 15 and pin["lsb"] == 0
    # the audit trail survives: the expression that was joined, the parameter
    # value used, and which sibling L-doc supplied it.
    prov = pin["width_resolution"]
    assert prov["resolver"] == "l_doc_symbolic_width_resolve"
    assert prov["expression"] == "WORD_W-1:0"
    assert prov["parameters_used"] == {"WORD_W": 16}
    assert prov["parameter_sources"] == ["L8_RTL_CONSTANTS.json"]
    assert pin["width_symbolic"] == "WORD_W-1:0"   # never destroyed

    # -- direction 2: the same gate now PASSes, on its own merits -----------
    rc_after, rep_after = _run_gate(project)
    assert rc_after == 0, rep_after
    # a genuine PASS: not VACUOUS_PASS (nothing to assert) and not
    # PASS_WITH_WAIVER (asserted, failed, forgiven).
    assert rep_after["verdict"] == "PASS", rep_after
    assert rep_after["bus_confirmed"] == 1
    assert rep_after["violations"] == []
    assert not (project / "waivers.json").exists()


# --------------------------------------- (2) the no-guess direction (byte-eq)
def test_unresolvable_identifier_leaves_documents_byte_identical(tmp_path):
    """When the corpus does NOT declare the identifier, the resolver must be a
    strict no-op AND the gate must still FAIL.

    This is the direction that matters most for a resolver: guessing a
    plausible width would convert a true FAIL into a false PASS, which is
    strictly worse than never running. `WIDTH_UNKNOWN` semantics — unknown is
    UNKNOWN, never a literal 1 and never a plausible number.
    """
    project = _defect_project(tmp_path)
    # remove the only declaration of the parameter
    _write_doc(project, "L8_RTL_CONSTANTS.json",
               {"ic_name": "synth_block", "parameters": []})

    before = _bytes_of(project)
    rc, rep = _run_resolver(project, apply=True)
    assert rc == 0
    assert rep["verdict"] == "NO_OP"
    assert rep["resolved"] == []
    assert rep["skipped"][0]["unresolved_identifiers"] == ["WORD_W"]
    assert _bytes_of(project) == before, "a no-op must not even re-serialise"

    rc_gate, rep_gate = _run_gate(project)
    assert rc_gate == 1, "an unresolved width must stay a FAIL, never a false green"
    assert rep_gate["verdict"] == "FAIL"


def test_conflicting_defaults_are_ambiguous_and_nothing_is_written(tmp_path):
    """The corpus contradicts itself about the parameter's default. There is
    no correct value to pick, so the resolver picks none."""
    project = _defect_project(tmp_path)
    _write_doc(project, "L9_INTEGRATION_SPEC.json", {
        "ic_name": "synth_block",
        "parameters": [{"name": "WORD_W", "default": "8"}],
    })
    before = _bytes_of(project)
    rc, rep = _run_resolver(project, apply=True)
    assert rc == 0
    assert rep["verdict"] == "NO_OP"
    assert "WORD_W" in rep["ambiguous_parameters"]
    assert rep["ambiguous_parameters"]["WORD_W"]["values"] == {
        "8": ["L9_INTEGRATION_SPEC.json"], "16": ["L8_RTL_CONSTANTS.json"]}
    assert rep["parameter_env"] == {}
    # the report must say WHICH failure this is: contradicted, not absent.
    assert "CONFLICTING" in rep["skipped"][0]["reason"]
    assert _bytes_of(project) == before


def test_a_conflict_that_only_becomes_visible_late_still_wins(tmp_path):
    """A contradiction must not be able to hide behind resolution ORDER.

    Here one declaration (`16`) is evaluable immediately and the other
    (`BASE*2` = 8) only becomes evaluable after `BASE` resolves. Testing for
    conflicts mid-fixpoint would let `16` win simply by arriving first and
    silently write a 16-bit port for a corpus that also says 8. The conflict
    test therefore runs against the CONVERGED environment.
    """
    project = _defect_project(tmp_path)
    _write_doc(project, "L9_INTEGRATION_SPEC.json", {
        "ic_name": "synth_block",
        "parameters": [{"name": "WORD_W", "default": "BASE*2"},
                       {"name": "BASE", "default": "4"}],
    })
    before = _bytes_of(project)
    rc, rep = _run_resolver(project, apply=True)
    assert rc == 0 and rep["verdict"] == "NO_OP", rep
    assert "WORD_W" in rep["ambiguous_parameters"]
    assert sorted(rep["ambiguous_parameters"]["WORD_W"]["values"]) == ["16", "8"]
    # BASE was never contradicted, so it survives — only the ambiguity is dropped.
    assert rep["parameter_env"] == {"BASE": 4}
    assert _bytes_of(project) == before


def test_existing_integer_width_is_never_overwritten(tmp_path):
    """An entry that already carries an actionable width is not this
    program's business, even when a symbolic expression sits beside it."""
    project = _defect_project(tmp_path)
    d = _docs_dir(project) / "L1_DATASHEET.json"
    doc = json.loads(d.read_text())
    doc["pin_table"][1].update({"width": 24, "msb": 23, "lsb": 0})
    d.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    before = _bytes_of(project)
    rc, rep = _run_resolver(project, apply=True)
    assert rc == 0 and rep["verdict"] == "NO_OP"
    assert "already carries an actionable integer width" in \
        rep["skipped"][0]["reason"]
    assert _bytes_of(project) == before


def test_non_span_and_negative_bound_expressions_are_untouched(tmp_path):
    """`hi:lo` is the ONE shape joined. A bare identifier has no unique width;
    a negative bound is not a bus. Both are left alone."""
    for expr, default in (("WORD_W", "16"), ("WORD_W-1:0", "0")):
        project = _defect_project(tmp_path / expr.replace(":", "_"),
                                  param_default=default, expr=expr)
        before = _bytes_of(project)
        rc, rep = _run_resolver(project, apply=True)
        assert rc == 0 and rep["verdict"] == "NO_OP", (expr, rep)
        assert _bytes_of(project) == before


def test_clog2_and_parameter_chain_resolve(tmp_path):
    """The shipped evaluator's reach is the resolver's reach: `$clog2` and a
    parameter whose default references an earlier parameter both join."""
    project = tmp_path / "proj"
    _write_doc(project, "L1_DATASHEET.json", {
        "ic_name": "synth_block",
        "pin_table": [
            {"name": "addr_bus", "mode": "input",
             "width": "N-bit(`[$clog2(DEPTH)-1:0]`)",
             "width_symbolic": "$clog2(DEPTH)-1:0"},
            {"name": "wide_bus", "mode": "input",
             "width": "N-bit(`[DOUBLE_W-1:0]`)",
             "width_symbolic": "DOUBLE_W-1:0"},
        ],
    })
    _write_doc(project, "L8_RTL_CONSTANTS.json", {
        "ic_name": "synth_block",
        "parameters": [
            {"name": "DEPTH", "default": "1024"},
            {"name": "BASE_W", "default": "12"},
            {"name": "DOUBLE_W", "default": "BASE_W*2"},
        ],
    })
    rc, rep = _run_resolver(project, apply=True)
    assert rc == 0 and rep["verdict"] == "RESOLVED", rep
    by_name = {r["name"]: r for r in rep["resolved"]}
    assert (by_name["addr_bus"]["width"], by_name["addr_bus"]["msb"]) == (10, 9)
    assert (by_name["wide_bus"]["width"], by_name["wide_bus"]["msb"]) == (24, 23)


def test_dry_run_plans_but_writes_nothing(tmp_path):
    """Default is a dry run — the plan is reported, the corpus is untouched."""
    project = _defect_project(tmp_path)
    before = _bytes_of(project)
    rc, rep = _run_resolver(project, apply=False)
    assert rc == 0 and rep["verdict"] == "RESOLVED"
    assert rep["applied"] is False
    assert _bytes_of(project) == before
    assert _run_gate(project)[0] == 1, "dry run must not silence the gate"


def test_missing_corpus_is_rc2_not_a_silent_success(tmp_path):
    project = tmp_path / "empty"
    project.mkdir()
    rc, rep = _run_resolver(project, apply=True)
    assert rc == 2 and rep["verdict"] == "SILENT_SKIP"


def test_cli_endstate_via_subprocess(tmp_path):
    """END-STATE through the real CLI: returncode asserted, artefact on disk."""
    project = _defect_project(tmp_path)
    out = tmp_path / "cli.json"
    proc = subprocess.run(
        [sys.executable, str(_RESOLVER), str(project),
         "--apply", "--json", str(out)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "RESOLVED" in proc.stdout
    rep = json.loads(out.read_text())
    assert rep["applied"] is True
    assert rep["documents_written"] == ["L1_DATASHEET.json"]

    proc_gate = subprocess.run(
        [sys.executable, str(_L1_GATE), str(project)],
        capture_output=True, text=True, timeout=120)
    assert proc_gate.returncode == 0, proc_gate.stderr
    assert proc_gate.stdout.startswith("PASS:"), proc_gate.stdout
