#!/usr/bin/env python3
"""A parameter is not a constant, and must not be judged by a constant's schema.

MEASURED 2026-08-29 on subservient/gf180mcuD at v1.12.65: `constants_validation`
exited 1 on `phase1/generated_docs/L8_RTL_CONSTANTS.json` with six errors --
`constants[0..2]: missing or null 'value'` and `constants[0..2]: missing 'width'
or 'bits' field` -- against a file whose only entry list is `parameters`, whose
emitted schema is `{name, default, type, description, source,
extraction_strategy}`. It carries no `value` and no `width` because a PARAMETER
has neither: its value lives in `default`, and a Verilog parameter is routinely
unsized. Every L8 the emitter writes has that shape, so the gate refused a shape
no producer in the tree emits, for every design.

The fix is NOT to stop reading `parameters` -- narrowing the population so a
gate stops finding things is the wrong repair. It is to require of each shape
the fields that shape actually carries, so a parameter with no value at all is
still a finding.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "constants_validation.py"


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _project(tmp_path: Path, name: str, doc: dict) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "rtl_constants.json").write_text(json.dumps(doc), encoding="utf-8")
    return proj


#: The L8 emitter's real parameter schema, verbatim in shape.
_L8_PARAMETERS = {"parameters": [
    {"name": "memsize", "default": "1024", "type": "256 / 512 / 1024 / 2048",
     "description": "", "source": "L3_external_interface.md",
     "extraction_strategy": "rst_param_grid_table_anchorless_v1_6_400"},
    {"name": "RESET_PC", "default": "`0x00000000`", "type": "`0x0` ~ `0xFFFFFFFC`",
     "description": "", "source": "L3_external_interface.md",
     "extraction_strategy": "rst_param_grid_table_anchorless_v1_6_400"},
]}


def test_l8_parameter_shape_is_accepted(tmp_path):
    """THE DEFECT. Pre-fix this exits 1 demanding 'value' and 'width'."""
    proj = _project(tmp_path, "l8shape", _L8_PARAMETERS)
    res = _run(proj)
    assert res.returncode == 0, (
        "a parameter list carrying the L8 emitter's own schema must not be "
        f"refused for lacking a constant's fields; got rc={res.returncode}\n"
        f"{res.stdout}")


def test_parameter_message_names_a_parameter(tmp_path):
    """A refusal that says `constants[0]` about a parameter misnames it."""
    proj = _project(tmp_path, "naming", {"parameters": [{"name": "P"}]})
    res = _run(proj)
    assert res.returncode == 1, f"a parameter with no value at all must fail; {res.stdout}"
    assert "parameters[0]" in res.stdout, (
        f"the finding must name the shape it read; got:\n{res.stdout}")
    assert "constants[0]" not in res.stdout


def test_parameter_with_no_value_at_all_is_still_a_finding(tmp_path):
    """The population is NOT narrowed: the gate still refuses a real defect."""
    proj = _project(tmp_path, "novalue", {"parameters": [
        {"name": "memsize", "type": "int", "source": "L3.md"}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "missing or null 'default' or 'value'" in res.stdout


def test_parameter_may_spell_its_value_as_value(tmp_path):
    """An emitter that spells it `value` is accepted too -- this only widens."""
    proj = _project(tmp_path, "valuekey", {"parameters": [
        {"name": "memsize", "value": "1024"}]})
    assert _run(proj).returncode == 0


def test_parameter_declaring_a_bad_width_is_still_refused(tmp_path):
    """Unsized is fine; sized-and-wrong is a finding whatever the shape."""
    proj = _project(tmp_path, "badwidth", {"parameters": [
        {"name": "memsize", "default": "1024", "width": 0}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "must be > 0" in res.stdout


# --------------------------------------------------------------------------
# CONTROLS -- green in BOTH arms. The fix must not change these answers.
# --------------------------------------------------------------------------
def test_control_wellformed_constants_still_pass(tmp_path):
    proj = _project(tmp_path, "ctl_good", {"constants": [
        {"name": "CRC_POLY", "value": "0x07", "width": 8, "comment": "poly"},
        {"name": "FIFO_DEPTH", "value": 16, "bits": 5, "comment": "depth"}]})
    assert _run(proj).returncode == 0


def test_control_constant_missing_value_still_refused(tmp_path):
    """A CONSTANT still owes a `value`. The fix must not relax this."""
    proj = _project(tmp_path, "ctl_noval", {"constants": [
        {"name": "CRC_POLY", "width": 8, "comment": "poly"}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "constants[0]: missing or null 'value'" in res.stdout


def test_control_constant_missing_width_still_refused(tmp_path):
    """A CONSTANT still owes a width. Only a PARAMETER is exempt."""
    proj = _project(tmp_path, "ctl_nowidth", {"constants": [
        {"name": "CRC_POLY", "value": "0x07", "comment": "poly"}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "missing 'width' or 'bits' field" in res.stdout


def test_control_duplicate_name_still_refused(tmp_path):
    proj = _project(tmp_path, "ctl_dup", {"constants": [
        {"name": "A", "value": 1, "width": 8, "comment": "x"},
        {"name": "A", "value": 2, "width": 8, "comment": "y"}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "DUPLICATE_NAME" in res.stdout


def test_control_bare_toplevel_list_still_judged_as_constants(tmp_path):
    """An unkeyed list keeps the stricter shape -- widening would lose findings."""
    proj = _project(tmp_path, "ctl_bare", [{"name": "A", "value": 1}])
    res = _run(proj)
    assert res.returncode == 1
    assert "constants[0]: missing 'width' or 'bits' field" in res.stdout


def test_control_explicit_constants_key_wins_over_parameters(tmp_path):
    """A file carrying both is judged on `constants`, as it always was."""
    proj = _project(tmp_path, "ctl_both", {
        "constants": [{"name": "C", "width": 8, "comment": "c"}],
        "parameters": [{"name": "P", "default": "1"}]})
    res = _run(proj)
    assert res.returncode == 1
    assert "constants[0]: missing or null 'value'" in res.stdout
