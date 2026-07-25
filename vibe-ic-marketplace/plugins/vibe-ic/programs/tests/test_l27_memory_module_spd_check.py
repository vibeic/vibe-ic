#!/usr/bin/env python3
"""Smoke tests for l27_memory_module_spd_check.py.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. For every rule R1-R6 there is a
pair: a deliberately-gutted layer that MUST FAIL, and a well-formed layer that
MUST PASS. A test that cannot fail proves nothing, so both directions are
asserted explicitly.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied,
and no design name / PDK name / vendor part number appears here.
"""
from __future__ import annotations

import ast
import importlib
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest


def _executable_source(path: Path) -> str:
    """Return `path`'s source with comments and every docstring removed, so a
    test can assert about code rather than about prose."""
    src = path.read_text()

    # 1. blank every docstring span (module / class / function)
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            for i in range(first.lineno - 1,
                           min(first.end_lineno, len(lines))):
                lines[i] = ""
    no_docstrings = "\n".join(lines)

    # 2. drop comment tokens from what remains
    kept = [tok for tok in tokenize.generate_tokens(
        io.StringIO(no_docstrings).readline)
        if tok.type != tokenize.COMMENT]
    return tokenize.untokenize(kept)

PROG = Path(__file__).resolve().parent.parent / "l27_memory_module_spd_check.py"
mod = importlib.import_module("l27_memory_module_spd_check")
tx = importlib.import_module("l_doc_taxonomy")


# ---------------------------------------------------------------------------
# fixtures — synthesized, neutral
# ---------------------------------------------------------------------------
def _mkproj(tmp_path, l27=None, l4=None, inputs=None, waivers=None,
            name="p"):
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l27 is not None:
        (gd / "L27_MEMORY_MODULE_SPD.json").write_text(json.dumps(l27))
    if l4 is not None:
        (gd / "L4_REGMAP.json").write_text(json.dumps(l4))
    if inputs:
        idoc = proj / "phase1" / "input_doc"
        idoc.mkdir(parents=True, exist_ok=True)
        for fn, body in inputs.items():
            (idoc / fn).write_text(body)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def _run(project):
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


# The well-formed N/A stub, matching the shape real runs emit.
def _good_na_stub():
    return {
        "doc_id": "L27",
        "doc_name": "L27_MEMORY_MODULE_SPD",
        "applicability": "N/A",
        "ic_class": "generic_digital_block_class",
        "rationale": "Not a JEDEC memory module (no SPD EEPROM)",
        "extraction_evidence": {},
        "emitted_by": "l_doc_taxonomy.na_stub",
        "extraction_strategy": {},
    }


# The other real not-applicable shape (AI-track resolver, no ic_class key).
def _good_not_applicable_fields():
    return {
        "doc_id": "L27",
        "doc_name": "L27_MEMORY_MODULE_SPD",
        "applicability": "NOT_APPLICABLE",
        "fields": {
            "reason": ("On-chip SRAM only (no external module SPD device). "
                       "On-chip storage is detailed in L4/L9."),
            "onchip_sram_total_kb": 64,
        },
        "schema_version": 2,
        "ic_name": "synthetic_block",
        "extraction_evidence": {},
    }


def _good_applicable():
    """A well-formed OPT-IN L27: standard + bus address + distinct byte map."""
    std = mod._spd_standard_tokens()[0]
    return {
        "doc_id": "L27",
        "doc_name": "L27_MEMORY_MODULE_SPD",
        "applicability": "APPLICABLE",
        "ic_class": "synthetic_memory_module_class",
        "spd_standard": std,
        "spd_bus_address": "0b1010_AAA (module select-address encoded)",
        "spd_bytes": [
            {"name": "spd_revision", "byte": 1, "value": "0x10"},
            {"name": "module_density_banks", "byte": 4, "value": "0x45"},
            {"name": "module_organization", "byte": 12, "value": "0x0A"},
            {"name": "module_serial_number", "byte": "325..328"},
        ],
    }


def _l4_regmap(names):
    return {"registers": [{"name": n, "offset": f"0x{i:02X}"}
                          for i, n in enumerate(names)]}


# ===========================================================================
# POSITIVE CONTROLS — a well-formed layer must PASS
# ===========================================================================
class TestWellFormedPasses:
    def test_pass_real_shape_na_stub(self, tmp_path):
        proj = _mkproj(tmp_path, l27=_good_na_stub())
        r = _run(proj)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout

    def test_pass_real_shape_not_applicable_fields_reason(self, tmp_path):
        """The AI-track shape carries its reason in fields.reason, not
        rationale, and has no ic_class key. It must still PASS."""
        proj = _mkproj(tmp_path, l27=_good_not_applicable_fields())
        r = _run(proj)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout

    def test_pass_well_formed_applicable_layer(self, tmp_path):
        proj = _mkproj(tmp_path, l27=_good_applicable(),
                       l4=_l4_regmap(["ctrl", "status", "irq_mask"]))
        r = _run(proj)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "actionable" in r.stdout

    def test_pass_na_when_input_negates_the_module(self, tmp_path):
        """A spec that explicitly DENIES having a module must not trip R4."""
        proj = _mkproj(
            tmp_path, l27=_good_na_stub(),
            inputs={"L2_architecture.txt": (
                "The device uses on-chip SRAM only.\n"
                "There is no DIMM and no serial presence detect EEPROM.\n")})
        r = _run(proj)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout

    def test_pass_na_when_only_one_axis_present(self, tmp_path):
        """One axis alone (a controller that merely reads someone else's SPD,
        or a passing form-factor mention) must NOT flag. Requires both."""
        one_axis = {"L2_architecture.txt": (
            "The controller reads serial presence detect data at boot "
            "over the config bus.\n")}
        proj = _mkproj(tmp_path, l27=_good_na_stub(), inputs=one_axis)
        r = _run(proj)
        assert r.returncode == 0, r.stdout + r.stderr

        other_axis = {"L2_architecture.txt": (
            "The host board accepts a DIMM in the adjacent socket.\n")}
        proj2 = _mkproj(tmp_path, l27=_good_na_stub(), inputs=other_axis,
                        name="p2")
        r2 = _run(proj2)
        assert r2.returncode == 0, r2.stdout + r2.stderr


# ===========================================================================
# NEGATIVE CONTROLS — a gutted layer must FAIL
# ===========================================================================
class TestGuttedLayerFails:
    def test_r1_fail_no_applicability_verdict(self, tmp_path):
        """GUTTED: the applicability verdict removed entirely."""
        doc = _good_na_stub()
        doc.pop("applicability")
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R1" in r.stdout

    def test_r1_fail_unrecognised_verdict(self, tmp_path):
        doc = _good_na_stub()
        doc["applicability"] = "maybe"
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R1" in r.stdout

    def test_r2_fail_na_with_empty_rationale(self, tmp_path):
        """GUTTED: N/A claimed, rationale emptied."""
        doc = _good_na_stub()
        doc["rationale"] = ""
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R2" in r.stdout

    def test_r2_fail_na_with_placeholder_rationale(self, tmp_path):
        doc = _good_na_stub()
        doc["rationale"] = "N/A"
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R2" in r.stdout

    def test_r2_fail_not_applicable_shape_with_gutted_reason(self, tmp_path):
        doc = _good_not_applicable_fields()
        doc["fields"]["reason"] = "none"
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R2" in r.stdout

    def test_r4_fail_false_na_against_designs_own_input(self, tmp_path):
        """THE MOTIVATING DEFECT SHAPE. The design's own input declares a
        self-describing memory module on BOTH axes; L27 says not-applicable
        and carries zero payload. The requirement is in the input and 0 times
        in the consuming layer."""
        std = mod._spd_standard_tokens()[0]
        proj = _mkproj(
            tmp_path, l27=_good_na_stub(),
            inputs={
                "L1_product_metadata.txt": (
                    "This product is a memory module assembly.\n"),
                "L2_architecture.txt": (
                    f"The module carries a {std} serial presence detect "
                    f"EEPROM addressed over the sideband bus.\n"
                    "Form factor: SO-DIMM.\n"),
            })
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R4" in r.stdout
        assert "0 times in the consuming layer" in r.stdout

    def test_r5_fail_applicable_but_empty_skeleton(self, tmp_path):
        """GUTTED: opt-in claimed, all SPD content removed."""
        proj = _mkproj(tmp_path, l27={
            "doc_id": "L27",
            "doc_name": "L27_MEMORY_MODULE_SPD",
            "applicability": "APPLICABLE",
            "ic_class": "synthetic_memory_module_class",
        })
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R5" in r.stdout
        assert "empty skeleton" in r.stdout

    def test_r5_fail_applicable_missing_bus_address(self, tmp_path):
        doc = _good_applicable()
        doc.pop("spd_bus_address")
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R5" in r.stdout

    def test_r5_fail_applicable_with_unrecognised_standard(self, tmp_path):
        """A `spd_standard` that names no JEDEC standard the taxonomy knows
        is a free-text placeholder, not an actionable device identifier."""
        doc = _good_applicable()
        doc["spd_standard"] = "see datasheet"
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R5" in r.stdout

    def test_r5_fail_applicable_with_empty_byte_map(self, tmp_path):
        doc = _good_applicable()
        doc["spd_bytes"] = []
        proj = _mkproj(tmp_path, l27=doc)
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R5" in r.stdout

    def test_r6_fail_l27_merely_restates_the_on_die_regmap(self, tmp_path):
        """GUTTED: the byte map replaced by a copy of the L4 register map, so
        L27 carries no module-level information."""
        doc = _good_applicable()
        names = ["ctrl", "status", "irq_mask"]
        doc["spd_bytes"] = [{"name": n, "byte": i}
                            for i, n in enumerate(names)]
        proj = _mkproj(tmp_path, l27=doc, l4=_l4_regmap(names))
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "R6" in r.stdout
        assert "distinct from the on-die register map" in r.stdout


# ===========================================================================
# R3 — taxonomy contradiction. No ic_class opts into L27 today (by design),
# so this branch is exercised by monkeypatching a hypothetical opt-in class.
# Both directions asserted.
# ===========================================================================
class TestTaxonomyContradictionR3:
    def test_r3_fail_na_while_taxonomy_says_applicable(
            self, tmp_path, monkeypatch):
        """GUTTED premise: the class DOES opt in, but L27 says N/A."""
        monkeypatch.setattr(mod, "_taxonomy_says_applicable",
                            lambda ic: ic == "synthetic_memory_module_class")
        doc = _good_na_stub()
        doc["ic_class"] = "synthetic_memory_module_class"
        proj = _mkproj(tmp_path, l27=doc)
        code, lines = mod.evaluate_l27(proj)
        out = "\n".join(lines)
        assert code == 1, out
        assert "R3" in out

    def test_r3_pass_na_when_taxonomy_agrees_not_applicable(
            self, tmp_path, monkeypatch):
        """Same fixture, honest premise: taxonomy agrees → PASS."""
        monkeypatch.setattr(mod, "_taxonomy_says_applicable", lambda ic: False)
        doc = _good_na_stub()
        doc["ic_class"] = "synthetic_memory_module_class"
        proj = _mkproj(tmp_path, l27=doc)
        code, lines = mod.evaluate_l27(proj)
        assert code == 0, "\n".join(lines)

    def test_no_current_class_opts_into_l27(self):
        """Guard the premise the gate rests on: L27 is opt-in-only and no
        shipped ic_class claims it. If this ever changes, R3/R5 go live and
        the change must be deliberate."""
        for cls in tx.IC_CLASS_APPLICABILITY:
            assert not tx.is_applicable(cls, "L27"), cls
        assert not tx.is_applicable("some_unrecognised_class", "L27")


# ===========================================================================
# Derivation — the SPD vocabulary must come from the taxonomy, not a literal
# ===========================================================================
class TestVocabularyIsDerived:
    def test_standards_are_parsed_from_taxonomy_description(self):
        toks = mod._spd_standard_tokens()
        desc = tx.l_doc_spec("L27").description
        designators = [t for t in toks if t != "serial presence detect"]
        assert designators, "no SPD standard designator derived"
        for t in designators:
            assert t in desc, f"{t} not derived from the taxonomy description"

    def test_executable_source_helper_can_actually_catch_a_literal(
            self, tmp_path):
        """META-CONTROL: prove the anti-hardcoding test above is capable of
        failing. `_executable_source` must DROP docstring/comment prose but
        KEEP a literal that real code matches against — otherwise the test
        would pass vacuously no matter what the gate did."""
        probe = tmp_path / "probe.py"
        probe.write_text(
            '"""Docstring mentioning DESIGNATOR_X as illustration."""\n'
            "# comment mentioning DESIGNATOR_Y\n"
            "def f():\n"
            '    """Inner docstring mentioning DESIGNATOR_Z."""\n'
            '    return "DESIGNATOR_W" in "abc"\n')
        code = _executable_source(probe)
        assert "DESIGNATOR_X" not in code, "module docstring not stripped"
        assert "DESIGNATOR_Y" not in code, "comment not stripped"
        assert "DESIGNATOR_Z" not in code, "inner docstring not stripped"
        assert "DESIGNATOR_W" in code, (
            "a real code literal was stripped — the anti-hardcoding test "
            "would pass vacuously")

    def test_gate_source_does_not_hardcode_standard_designators(self):
        """The designators must not appear in the gate's EXECUTABLE code.

        Docstrings and comments may quote the taxonomy text as illustration —
        that is documentation, not a hardcoded rule. What must not exist is a
        literal designator the gate actually matches against, because such a
        literal would silently stop tracking the taxonomy.
        """
        code = _executable_source(PROG)
        for t in mod._spd_standard_tokens():
            if t == "serial presence detect":
                continue
            assert t not in code, (
                f"{t} is hardcoded in the gate's executable code; it must be "
                f"derived from l_doc_taxonomy at runtime")


# ===========================================================================
# Skips + waiver
# ===========================================================================
class TestSkipAndWaiver:
    def test_skip_when_l27_absent(self, tmp_path):
        proj = tmp_path / "p"
        (proj / "phase1" / "generated_docs").mkdir(parents=True)
        r = _run(proj)
        assert r.returncode == 2
        assert "SKIP" in r.stdout

    def test_skip_when_project_dir_missing(self, tmp_path):
        r = _run(tmp_path / "nope")
        assert r.returncode == 2

    def test_fail_on_unparseable_l27(self, tmp_path):
        proj = tmp_path / "p"
        gd = proj / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L27_MEMORY_MODULE_SPD.json").write_text("{not json")
        r = _run(proj)
        assert r.returncode == 1

    def test_waiver_converts_fail_to_pass(self, tmp_path):
        doc = _good_na_stub()
        doc["rationale"] = ""
        proj = _mkproj(tmp_path, l27=doc, waivers={
            "waivers": [{
                "id": "l27_memory_module_spd_intentional",
                "justification": (
                    "Synthesized fixture: the N/A rationale is supplied "
                    "out-of-band by the module datasheet under review."),
            }]})
        r = _run(proj)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WAIVED" in r.stdout

    def test_short_waiver_does_not_convert_fail(self, tmp_path):
        """Negative control on the waiver itself: a stub justification must
        NOT be able to switch the gate off."""
        doc = _good_na_stub()
        doc["rationale"] = ""
        proj = _mkproj(tmp_path, l27=doc, waivers={
            "waivers": [{"id": "l27_memory_module_spd_intentional",
                         "justification": "n/a"}]})
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr


# ===========================================================================
# Blocking posture — the gate must NOT be informational-only.
# ===========================================================================
def test_gate_is_registered_as_blocking():
    fcc = importlib.import_module("flow_compliance_check")
    assert "l27_memory_module_spd_check" in fcc._STRUCTURAL_RTL_GATES
    assert "l27_memory_module_spd_check" not in fcc.INFORMATIONAL_GATES


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
