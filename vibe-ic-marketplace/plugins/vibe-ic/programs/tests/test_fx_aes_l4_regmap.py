"""FX_AES_L4_REGMAP: phase 1 judged a register map that was not yet final, and
named a multireg's element 0 by its family.

MEASURED on opentitan_aes x main 7fac744e1 (lane rvp2):
`l4_regmap_declared_register_coverage_check` FAILed "7 of 35 register(s)
covered". The layergate-2 loop ran right after `gen_l4_regmap`, 17 s before the
post-emit passes (register-table rows, the G19 offset backfill) grew L4 to its
final rows. And behind it: the register-table pass deduped `<FAMILY>_0` against
the collapsed family row at the same address, so L4 carried the family and
elements 1..n but no register by element 0's declared name.

The design input decides which side is wrong: its register summary names every
element `<FAMILY>_<i>`, element 0 included, at its own offset. So the emitter is
fixed (the dedupe recognises an element), and the gate order is fixed (the
layer gates run after every producer of their layers). No design name appears
here; the fixtures use a generic `FIFO` family.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
for _p in (str(PROGRAMS), str(PROGRAMS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase1_doc_one_shot_runner as R  # noqa: E402

RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def _family(name="FIFO", base=0x10, n=4, stride=4):
    return {"name": name, "offset": hex(base), "address": hex(base),
            "element_offsets": [{"index": i, "offset": hex(base + i * stride)}
                                for i in range(n)]}


# ── the element rule ──────────────────────────────────────────────────────

@pytest.mark.parametrize("row_name, addr, expect", [
    ("FIFO_0", "0x10", True),     # element 0 at the family's own address
    ("FIFO_2", "0x18", True),     # any element at its own listed offset
    ("FIFO_1", "0x10", False),    # an index the family places elsewhere
    ("OTHER", "0x10", False),     # a second name for the register: a duplicate
    ("FIFO_X", "0x10", False),    # not an index
    ("FIFOX_0", "0x10", False),   # not this family's name
])
def test_an_element_is_told_from_a_duplicate(row_name, addr, expect):
    assert R._multireg_element_of(_family(), {"name": row_name}, addr) is expect


def test_a_family_already_named_by_its_element_is_not_renamed_twice():
    fam = dict(_family(), name="FIFO_0", multireg_family="FIFO")
    assert R._multireg_element_of(fam, {"name": "FIFO_0"}, "0x10") is False


def test_a_row_without_element_offsets_has_no_elements():
    fam = {"name": "FIFO", "address": "0x10"}
    assert R._multireg_element_of(fam, {"name": "FIFO_0"}, "0x10") is False
    assert R._multireg_element_of(None, {"name": "FIFO_0"}, "0x10") is False


# ── the real register-table pass, on a generic multireg ───────────────────

_TABLE = """# Registers

| Name                      | Offset   |   Length | Description        |
|:--------------------------|:---------|---------:|:-------------------|
| blk.[`CTRL`](#ctrl)       | 0x0      |        4 | Control Register.  |
| blk.[`FIFO_0`](#fifo)     | 0x10     |        4 | FIFO word.         |
| blk.[`FIFO_1`](#fifo)     | 0x14     |        4 | FIFO word.         |
| blk.[`FIFO_2`](#fifo)     | 0x18     |        4 | FIFO word.         |
| blk.[`FIFO_3`](#fifo)     | 0x1c     |        4 | FIFO word.         |
| blk.[`ALIAS`](#alias)     | 0x0      |        4 | Control, aliased.  |
"""


def _project(tmp_path: Path) -> Path:
    import _path_layout as _pl
    p = tmp_path / "proj"
    gd = _pl.generated_docs_dir(p)
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"class_path": "x"}))
    (gd / "L4_REGMAP.json").write_text(json.dumps({"registers": [
        {"name": "CTRL", "offset": "0x0", "address": "0x0"}, _family()]}))
    ind = _pl.input_doc_dir(p)
    ind.mkdir(parents=True)
    (ind / "blk_registers.md").write_text(_TABLE)
    return p


def test_the_table_pass_names_element_zero_by_its_declared_name(tmp_path):
    import _path_layout as _pl
    p = _project(tmp_path)
    # the per-register table repeats element 0 (as register docs do)
    ind = _pl.input_doc_dir(p)
    (ind / "blk_fifo.md").write_text(
        "| Name   | Offset |\n|:-------|:-------|\n| FIFO_0 | 0x10   |\n"
        "| FIFO_1 | 0x14   |\n")
    R._post_emit_pdf_regmap_table_rows(p)
    regs = json.loads((_pl.generated_docs_dir(p) / "L4_REGMAP.json")
                      .read_text())["registers"]
    names = [r["name"] for r in regs]
    by = {r["name"]: r for r in regs}
    for i, addr in enumerate(("0x10", "0x14", "0x18", "0x1c")):
        assert names.count(f"FIFO_{i}") == 1, names
        r = by[f"FIFO_{i}"]
        assert int(str(r.get("address") or r.get("addr_hex")), 16) == int(addr, 16)
    # element 0 IS the family row: one record per address, family recorded
    assert "FIFO" not in by
    assert by["FIFO_0"]["multireg_family"] == "FIFO"
    assert len(by["FIFO_0"]["element_offsets"]) == 4
    addrs = [int(str(r.get("address") or r.get("addr_hex")), 16) for r in regs]
    assert len(addrs) == len(set(addrs)), addrs
    # a genuine second name at an occupied address is still a duplicate:
    # absorbed as an alias, not appended
    assert "ALIAS" not in by
    assert "ALIAS" in (by["CTRL"].get("also_named") or [])


def test_the_phase2_emitter_builds_the_named_map(tmp_path):
    """The phase-2 emitter emits one register per L4 row: after the pass the
    map has unique identifiers and addresses (the contract gate's rule)."""
    import _path_layout as _pl
    import phase2_scaffold_gen as G
    p = _project(tmp_path)
    R._post_emit_pdf_regmap_table_rows(p)
    l4 = json.loads((_pl.generated_docs_dir(p) / "L4_REGMAP.json").read_text())
    regs = G.derive_registers(l4, {})
    names = [r["name"] for r in regs]
    assert len(names) == len(set(names)), names
    assert {"FIFO_0", "FIFO_1", "FIFO_2", "FIFO_3", "CTRL"} <= set(names)


def _typed_family_project(tmp_path):
    import _path_layout as layout
    project = _project(tmp_path)
    path = layout.generated_docs_dir(project)/'L4_REGMAP.json'
    doc = json.loads(path.read_text())
    doc['registers'][1].update(access='WO', reset_value='0x0', length=4,
        fields=[{'field_name':'PAYLOAD','bits':'31:0','msb':31,'lsb':0,'access':'WO'}])
    path.write_text(json.dumps(doc))
    return project, path


def test_array_elements_keep_family_attributes_in_the_phase2_consumer(tmp_path):
    import phase2_scaffold_gen as consumer
    project, path = _typed_family_project(tmp_path)
    R._post_emit_pdf_regmap_table_rows(project)
    doc = json.loads(path.read_text())
    rows = {r['name']:r for r in consumer.derive_registers(doc,{})}
    for i in range(4):
        row = rows[f'FIFO_{i}']
        assert row['width'] == 32
        assert row['access'] == 'wo'
        assert row['fields'][0]['field_name'] == 'PAYLOAD'
        original = next(r for r in doc['registers'] if r['name'] == f'FIFO_{i}')
        assert original['reset_value'] == '0x0'
        assert original['length'] == 4


def test_array_attributes_require_both_declared_index_and_address(tmp_path):
    import _path_layout as layout
    for i,(name,addr) in enumerate([('FIFO_1','0x28'),('OTHER_1','0x14')]):
        project, path = _typed_family_project(tmp_path/str(i))
        (layout.input_doc_dir(project)/'blk_registers.md').write_text(
            '| Name | Offset |\n|---|---|\n'
            '| FIFO_0 | 0x10 |\n'+f'| {name} | {addr} |\n')
        R._post_emit_pdf_regmap_table_rows(project)
        row = next(r for r in json.loads(path.read_text())['registers'] if r['name']==name)
        assert not row.get('fields')
        assert row.get('access') != 'WO'
        assert 'reset_value' not in row


# ── the order: layer gates judge the final layers ─────────────────────────
#
# DERIVED FROM THE WRITES, not from names (review wave 8): a producer is any
# function that both names a judged document (L4_REGMAP / L5_ADI_SPEC /
# L6_CONTROL_LOGIC) and writes a file, directly or through its callees -- in
# the runner, or in a program module `main` imports it from (the protocol-synth
# overlays) -- plus any statement in `main` that does both in line.

def _main():
    tree = ast.parse(RUNNER.read_text())
    return next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")


def _layergate2_loop(fn):
    """The one place `main` runs the layergate-2 gates."""
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_run_layergate2"]
    if len(calls) != 1:
        raise AssertionError(f"main runs the layergate-2 gates {len(calls)} times")
    return calls[0]


_JUDGED = ("L4_REGMAP", "L5_ADI_SPEC", "L6_CONTROL_LOGIC")
_WRITES = ("dump", "write_text", "write_json", "write_bytes")


def _names_doc(node) -> bool:
    return any(isinstance(c, ast.Constant) and isinstance(c.value, str)
               and any(j in c.value for j in _JUDGED) for c in ast.walk(node))


def _writes(node) -> bool:
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and c.func.attr in _WRITES for c in ast.walk(node))


def _producers(tree) -> set:
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def calls(f):
        return {c.func.id for c in ast.walk(f)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    doc = {n for n, f in funcs.items() if _names_doc(f)}
    wr = {n for n, f in funcs.items() if _writes(f)}
    for grow in (doc, wr):
        changed = True
        while changed:
            changed = False
            for n, f in funcs.items():
                if n not in grow and calls(f) & grow:
                    grow.add(n)
                    changed = True
    return {n for n in doc & wr if n != "main"}


def _late_producers(source: str) -> tuple:
    tree = ast.parse(source)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    loop = _layergate2_loop(main)
    prod = _producers(tree)
    for n in ast.walk(main):
        if isinstance(n, ast.ImportFrom) and n.module \
                and (PROGRAMS / f"{n.module}.py").is_file():
            mod = _producers(ast.parse((PROGRAMS / f"{n.module}.py").read_text()))
            prod |= {a.asname or a.name for a in n.names if a.name in mod}
    late = [f"{n.func.id}@{n.lineno}" for n in ast.walk(main)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in prod and n.lineno > loop.end_lineno]
    late += [f"inline@{st.lineno}" for st in main.body
             if st.lineno > loop.end_lineno and _names_doc(st) and _writes(st)]
    return prod, late


def test_the_layer_gates_run_after_every_producer_of_their_layers():
    prod, late = _late_producers(RUNNER.read_text())
    # the population is real: the unprefixed writers and the overlays are in it
    assert {"gen_l4_regmap", "_v1_6_295_propagate_class_path_to_layer_docs",
            "_v1_6_350_post_emit_spice_metadata",
            "_g19_post_emit_backfill_register_offsets"} <= prod, sorted(prod)
    assert "_apply_can" in prod
    assert late == [], f"producers of the judged layers after the gate loop: {late}"


@pytest.mark.parametrize("call", [
    "_v1_6_350_post_emit_spice_metadata(project)",
    "_v1_6_295_propagate_class_path_to_layer_docs(project)",
])
def test_the_order_guard_sees_a_producer_with_no_prefix(call):
    """Self-mutation: move an unprefixed producer below the loop; the guard
    must report it."""
    src = RUNNER.read_text()
    line = f"    {call}\n"
    assert src.count(line) == 1, call
    src = src.replace(line, "", 1)
    anchor = '    print(f"[15/15] coverage report ...")\n'
    src = src.replace(anchor, line + anchor, 1)
    _prod, late = _late_producers(src)
    assert any(l.startswith(call.split("(")[0]) for l in late), late


_FAKE_ENUM = """import sys
print("[FAIL] l4_regmap_enumerated_values_typed_check: 1 field lacks codes")
sys.exit(1)
"""
_FAKE_JSON = """import json, sys
out = sys.argv[sys.argv.index("--json") + 1]
open(out, "w").write(json.dumps({"verdict": "FAIL"}))
print("[FAIL] fake_json_check: a real finding")
sys.exit(1)
"""


def test_every_blocking_line_cites_a_report_that_exists(tmp_path, capsys):
    """Behaviour, not a source string (review wave 8): a gate with no --json
    of its own still gets a report at the path its FAIL line cites."""
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "l4_regmap_enumerated_values_typed_check.py").write_text(_FAKE_ENUM)
    (gates / "fake_json_check.py").write_text(_FAKE_JSON)
    proj = tmp_path / "proj"
    proj.mkdir()
    failed = R._run_layergate2(
        proj, gates=(("l4_regmap_enumerated_values_typed_check", "l4_enum"),
                     ("fake_json_check", "fake_json")), gate_dir=gates)
    out = capsys.readouterr().out
    assert failed == ["l4_regmap_enumerated_values_typed_check",
                      "fake_json_check"]
    cited = [l.split("(see ", 1)[1].rstrip(")") for l in out.splitlines()
             if "FAIL — blocks phase1" in l]
    assert len(cited) == 2, out
    for rel in cited:
        assert (proj / rel).is_file(), rel
    enum = json.loads((proj / cited[0]).read_text())
    assert "lacks codes" in enum["stdout"] and enum["returncode"] == 1


def test_a_stalled_gate_is_not_measured_not_skipped(tmp_path, capsys,
                                                    monkeypatch):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fake_json_check.py").write_text(_FAKE_JSON)
    proj = tmp_path / "proj"
    proj.mkdir()

    def stall(*a, **kw):
        raise R._pr.Stalled(["gate"], 3, 1.0, 9.0, {"cpu": 0})
    monkeypatch.setattr(R._pr, "run", stall)
    failed = R._run_layergate2(proj, gates=(("fake_json_check", "fake"),),
                               gate_dir=gates)
    out = capsys.readouterr().out
    assert failed == ["fake_json_check"]
    assert failed.failed == [] and failed.not_measured == ["fake_json_check"]
    assert "NOT_MEASURED — stalled, the layer is NOT judged" in out
    receipt = json.loads(R._pl.report_path(proj, "phase1/fake.run.json").read_text())
    assert receipt["verdict"] == "NOT_MEASURED" and receipt["reason"] == "stalled"
    assert "SKIP" not in out


@pytest.mark.parametrize("failure", ["missing_script", "launch_error"])
def test_an_unrun_selected_gate_blocks_and_has_a_typed_receipt(
        tmp_path, monkeypatch, failure):
    gates = tmp_path / "gates"
    gates.mkdir()
    if failure == "launch_error":
        (gates / "fake_json_check.py").write_text(_FAKE_JSON)

        def cannot_launch(*args, **kwargs):
            raise OSError("synthetic launch refusal")

        monkeypatch.setattr(R._pr, "run", cannot_launch)
    proj = tmp_path / "proj"
    proj.mkdir()
    stale = R._pl.report_path(proj, "phase1/fake.run.json")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"verdict": "PASS"}')
    result = R._run_layergate2(
        proj, gates=(("fake_json_check", "fake"),), gate_dir=gates)
    assert result == ["fake_json_check"], (
        "an unrun required gate must block Phase 1")
    assert result.failed == [] and result.not_measured == ["fake_json_check"]
    report = R._pl.report_path(proj, "phase1/fake.run.json")
    payload = json.loads(report.read_text())
    assert payload["gate"] == "fake_json_check"
    assert payload["verdict"] == "NOT_MEASURED"
    assert payload["reason"] == failure
    assert payload["gate_report"] is None


@pytest.mark.parametrize("line, expected", [
    ("[SKIP] no register map applies", "NOT_APPLICABLE"),
    ("", "NOT_MEASURED"),
    ("rc2 without a terminal classification", "NOT_MEASURED"),
])
def test_rc2_needs_an_explicit_nonapplicable_verdict(tmp_path, line, expected):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fake_json_check.py").write_text(
        f"import sys\nprint({line!r})\nsys.exit(2)\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    result = R._run_layergate2(
        proj, gates=(("fake_json_check", "fake"),), gate_dir=gates)
    receipt = json.loads(
        R._pl.report_path(proj, "phase1/fake.run.json").read_text())
    assert receipt["verdict"] == expected
    assert result == ([] if expected == "NOT_APPLICABLE" else ["fake_json_check"])


def test_a_gate_failure_without_own_json_cites_the_run_receipt(tmp_path, capsys):
    gates = tmp_path / "gates"
    gates.mkdir()
    (gates / "fake_json_check.py").write_text(
        'import sys\nprint("[FAIL] no report")\nsys.exit(1)\n')
    proj = tmp_path / "proj"
    proj.mkdir()
    result = R._run_layergate2(
        proj, gates=(("fake_json_check", "fake"),), gate_dir=gates)
    assert result == ["fake_json_check"]
    assert result.failed == ["fake_json_check"]
    out = capsys.readouterr().out
    cited = out.split("FAIL — blocks phase1 (see ", 1)[1].split(")", 1)[0]
    assert (proj / cited).is_file(), cited
    assert json.loads((proj / cited).read_text())["verdict"] == "FAIL"


def test_the_tail_failure_line_names_the_report_directory():
    src = RUNNER.read_text()
    assert "— see reports/phase1/\")" not in src
    assert "and reports/phase1/*.json" not in src


@pytest.mark.parametrize("case, expected_rc, expected_verdict", [
    ("one_bit", 2, "NOT_APPLICABLE"),
    ("typed_enum", 0, "PASS"),
    ("missing_enum", 1, "FAIL"),
])
def test_actual_enum_layergate_terminal_verdict(
        tmp_path, case, expected_rc, expected_verdict):
    """The real enum producer's measured N/A is terminal, never a PASS."""
    project = tmp_path / "project"
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    field = ({"name": "ENABLE", "bits": "0:0"} if case == "one_bit" else
             {"name": "MODE", "bits": "1:0"})
    if case == "typed_enum":
        field["enumerated_values"] = [
            {"code": 0, "meaning": "Idle"},
            {"code": 1, "meaning": "Run"},
        ]
    (docs / "L4_REGMAP.json").write_text(json.dumps({
        "registers": [{"name": "CTRL", "fields": [field]}]}))
    gate = "l4_regmap_enumerated_values_typed_check"
    result = R._run_layergate2(
        project, gates=((gate, "l4_regmap_enumerated_values"),))
    receipt = json.loads(R._pl.report_path(
        project, "phase1/l4_regmap_enumerated_values.run.json").read_text())
    gate_report = json.loads(R._pl.report_path(
        project, "phase1/l4_regmap_enumerated_values.json").read_text())
    observed = {
        "blocking": list(result), "failed": result.failed,
        "not_measured": result.not_measured,
        "not_applicable": result.not_applicable,
        "receipt": receipt, "gate_report": gate_report,
    }
    (tmp_path / "TERMINAL_OBSERVATION.json").write_text(
        json.dumps(observed, indent=2) + "\n")
    assert receipt["returncode"] == expected_rc
    assert gate_report["stdout"] == receipt["stdout"]
    assert gate_report["stderr"] == receipt["stderr"]
    if case == "one_bit":
        assert receipt["stdout"].startswith("[NOT_APPLICABLE_BY_STRUCTURE]")
        assert "enumerated 1 register field(s) L4 carries and found 0" in receipt["stdout"]
        assert "examined 0" in receipt["stdout"]
        assert "of 1 considered" in receipt["stdout"]
    expected = ([gate], [gate], [], []) if expected_verdict == "FAIL" else (
        [], [], [], [gate] if expected_verdict == "NOT_APPLICABLE" else [])
    assert (list(result), result.failed, result.not_measured,
            result.not_applicable) == expected
    assert receipt["verdict"] == expected_verdict
    if expected_verdict == "NOT_APPLICABLE":
        assert receipt["reason"] == "gate_declared_not_applicable_by_structure"
