"""FX_405 — the DEFAULT-flow design-input readers never open an oracle file.

§4.05 is the first binding rule: a run reads ONLY the design input, never an
oracle, harness or golden. The flag path (llv1 W21) applies the repo's one
authority before it opens a staged tool config; the default-flow readers did
not. MEASURED on origin/main 7fac744e1 with an audit hook, on a project that
stages an oracle tree next to its design input:

  * `phase3_one_shot_runner._rf_pnr_scan` opened `golden/flow.mk`,
    `score/cfg.mk`, `golden.mk` and `expected_results.tcl` under
    `input/reference_flow/` and ADOPTED their values (CORE_UTILIZATION 33,
    TNS_END_PERCENT 7, CTS_CLUSTER_SIZE 9, PLACE_DENSITY 0.61);
  * `sdc_constraints.collect_sdc_files` returned
    `input/constraints/golden_timing.sdc` FIRST, so the resolved clock was the
    golden one (2.5 ns) and not the design's (10 ns);
  * `l4_regmap_declared_register_coverage_check.find_staged_hdl` keyed its
    result by file name and read `input/golden/top.v` before
    `input/rtl/top.v`, so the golden module REPLACED the design's;
  * and thirteen more readers opened golden/, expected/, score/,
    canonical_samples/ or `_ref.` / `verified_` files.

The oracle list below is written out here, NOT computed from the authority the
fix uses: a test that asked the fix which files are oracle would pass whatever
the fix decided. Every entry is one the repo's authority already denies
(`step_input_scope.oracle_reason`), or a staged tool-config file whose name
says it records a result (`_reference_flow_boundary.is_oracle_name`, the rule
llv1 W21 applies to the same trees).

The design input is still read: every reader is also held to the design files
it opened on main, and where the oracle changed a value the design's own value
is pinned. `input/docs/L1_product_metadata.md` is the over-match control — a
genuine design document with an oracle WORD in its name, of the kind the corpus
stages; applying the word rule to all of `input/` would drop it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent

ORACLE = {
    "input/reference_flow/golden/flow.mk":
        "export CORE_UTILIZATION = 33\nexport VERILOG_INCLUDE_DIRS = ginc\n",
    "input/reference_flow/golden/ginc/g.vh": "`define GOLDEN 1\n",
    "input/reference_flow/score/cfg.mk": "export TNS_END_PERCENT = 7\n",
    "input/reference_flow/golden.mk":
        "export CTS_CLUSTER_SIZE = 9\nexport REMOVE_ABC_BUFFERS = 1\n",
    "input/reference_flow/expected_results.tcl":
        "set ::env(PLACE_DENSITY) 0.61\n"
        "set ::env(DIE_AREA) \"0 0 200 200\"\n"
        "# using the lib_b library\nset gold_clk_input gclk\n"
        "set gold_clk_period 2500\n",
    "input/reference_flow/golden/golden.sdc":
        "create_clock -name clk -period 1.234 [get_ports clk]\n",
    "input/constraints/golden_timing.sdc":
        "create_clock -name clk -period 2.5 [get_ports clk]\n",
    "input/constraints/oracle.sdc":
        "create_clock -name clk -period 2.5 [get_ports clk]\n",
    "input/golden/top.v":
        "module top(\n  input wire clk,\n  output wire q\n);\n"
        "parameter GOLDEN_P = 1;\nendmodule\n",
    "input/expected/out.txt":
        "| Address | Name |\n|---|---|\n| 0x10 | GOLD_A |\n"
        "| 0x14 | GOLD_B |\n| 0x18 | GOLD_C |\n",
    "input/score/score.py": "x = 1\n",
    "input/canonical_samples/s.v":
        "module s(input wire a);\nparameter SAMPLE_P = 2;\nendmodule\n",
    "input/rtl/top_ref.v":
        "module top_ref(input wire a);\nparameter REF_P = 3;\nendmodule\n",
    "input/rtl/verified_top.v":
        "module verified_top(input wire a);\nparameter VERIFIED_P = 4;\n"
        "endmodule\n",
    # Outside the staged trees: a RESULT-named config file (review 405).
    "input/flow/expected_results.tcl": "set ::env(DIE_AREA) \"0 0 300 300\"\n",
    "input/docs/regmap_ref.md":
        "| Address | Name |\n|---|---|\n| 0x20 | REF_REG |\n",
}

LEGIT = {
    "input/reference_flow/flow.mk":
        "export CTS_CLUSTER_DIAMETER = 40\nexport SWAP_ARITH_OPERATORS = 1\n"
        "export VERILOG_INCLUDE_DIRS = inc\n",
    "input/reference_flow/inc/defs.vh": "`define DESIGN 1\n",
    "input/reference_flow/config.tcl":
        "set ::env(DIE_AREA) \"0 0 100 100\"\n"
        "# using the lib_a library\nset core_clk_input clk\n"
        "set core_clk_period 10000\n",
    "input/reference_flow/design.sdc":
        "create_clock -name clk -period 10 [get_ports clk]\n",
    "input/constraints/top.sdc":
        "create_clock -name clk -period 10 [get_ports clk]\n",
    # Over-match control: SDC's "design rule constraints" are genuine input.
    "input/constraints/top_design_rules.sdc": "set_max_fanout 16 [current_design]\n",
    "input/docs/L1_product.md":
        "# Product\n\n| Address | Name |\n|---|---|\n| 0x0 | CTRL |\n"
        "| 0x4 | STATUS |\n",
    "input/docs/L1_product_metadata.md": "# Product metadata\n\nA counter.\n",
    "input/rtl/top.v": "module top;\nparameter WIDTH = 8;\nendmodule\n",
    "phase1/generated_docs/L8_RTL_CONSTANTS.json": '{"clock_domains": []}',
}

#: reader -> (module, expression over `m` (module) and `P` (project Path),
#:            the design-input files it must still open).
READERS = {
    "collect_sdc_files": (
        "sdc_constraints",
        "sorted(str(p.relative_to(P)) for p in m.collect_sdc_files(P))",
        set()),  # it globs and returns paths; its value is pinned below
    "_iter_input_files": (
        "floorplan_contract", "[r for r, _p, _t in m._iter_input_files(P)]",
        {"input/docs/L1_product.md"}),
    "find_staged_hdl": (
        "l4_regmap_declared_register_coverage_check", "m.find_staged_hdl(P)",
        {"input/rtl/top.v"}),
    "documentary_declarations": (
        "l4_regmap_declared_register_coverage_check",
        "sorted(n for d in m.documentary_declarations(P) for n in d['names'])",
        {"input/docs/L1_product.md"}),
    "_v1_14_50_declared_rtl_parameters": (
        "phase1_doc_one_shot_runner",
        "sorted(m._v1_14_50_declared_rtl_parameters(P))",
        {"input/rtl/top.v"}),
    "_v1_14_50_present_but_never_ingested": (
        "phase1_doc_one_shot_runner",
        "sorted(r['path'] for r in m._v1_14_50_present_but_never_ingested(P))",
        {"input/docs/L1_product.md"}),
    "_post_emit_reference_clock_config": (
        "phase1_doc_one_shot_runner",
        "(m._post_emit_reference_clock_config(P), sorted("
        "d['source_pin'] for d in json.loads((P / 'phase1' / 'generated_docs'"
        " / 'L8_RTL_CONSTANTS.json').read_text())['clock_domains']))[1]",
        {"input/reference_flow/config.tcl"}),
    "input_text_report": (
        "phase1_expert_parse_track",
        "{k: m.input_text_report(P)[k] for k in ('files_read',)}",
        {"input/docs/L1_product.md", "input/docs/L1_product_metadata.md"}),
    # Review 405: two readers the first sweep missed, and the census.
    "clock_target_provenance.resolve": (
        "clock_target_provenance",
        "(lambda r: [r['period_ns'], r['tier']])(m.resolve(P, applied_period_ns=10))",
        {"input/constraints/top.sdc"}),
    "_clock_target_record": (
        "l19_constraint_token_emit",
        "(lambda r: [r['status'], r['period_ns'], r['evidence']])"
        "(m._clock_target_record(P, {}))",
        {"input/constraints/top.sdc"}),
    "documentary_census": (
        "l4_regmap_declared_register_coverage_check",
        "(lambda c: [c['opened_count'], c.get('excluded_oracle_count')])"
        "(m.documentary_census(P))",
        set()),  # it counts; nothing is opened
}

_CHILD = r'''
import json, shutil, sys, tempfile, importlib
from pathlib import Path
programs, template, spec = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3])
sys.path.insert(0, programs)
state = {"root": None, "opened": []}
def _hook(event, args):
    root = state["root"]
    if root and event == "open" and isinstance(args[0], str) \
            and args[0].startswith(root + "/"):
        state["opened"].append(args[0][len(root) + 1:])
sys.addaudithook(_hook)
out = {}
for name, (mod, expr) in spec.items():
    m = importlib.import_module(mod)
    P = Path(tempfile.mkdtemp(prefix="fx405_")) / "proj"
    shutil.copytree(template, P)
    state["opened"], state["root"] = [], str(P)
    try:
        value = eval(expr, {"m": m, "P": P, "Path": Path, "json": json})
        err = None
    except BaseException as exc:          # noqa: BLE001 - reported, asserted
        value, err = None, f"{type(exc).__name__}: {exc}"
    state["root"] = None
    try:
        json.dumps(value)
    except TypeError:
        value = repr(value)
    out[name] = {"opened": sorted(set(state["opened"])), "value": value,
                 "error": err}
print("FX405" + json.dumps(out))
'''


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    template = tmp_path_factory.mktemp("fx405_template")
    for rel, body in {**ORACLE, **LEGIT}.items():
        p = template / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    spec = {name: [mod, expr] for name, (mod, expr, _l) in READERS.items()}
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, str(PROGRAMS), str(template),
         json.dumps(spec)],
        capture_output=True, text=True, timeout=900)
    line = next((ln for ln in done.stdout.splitlines()
                 if ln.startswith("FX405")), None)
    assert line, (done.returncode, done.stderr[-3000:])
    return json.loads(line[len("FX405"):])


@pytest.mark.parametrize("reader", sorted(READERS))
def test_reader_opens_no_oracle_file(observed, reader):
    got = observed[reader]
    assert got["error"] is None, got["error"]
    leaked = sorted(set(got["opened"]) & set(ORACLE))
    assert leaked == [], f"{reader} opened oracle files {leaked}"


@pytest.mark.parametrize("reader", sorted(READERS))
def test_reader_still_opens_the_design_input(observed, reader):
    """Non-vacuity: a reader that opened nothing would pass the test above."""
    must = READERS[reader][2]
    missing = sorted(must - set(observed[reader]["opened"]))
    assert missing == [], f"{reader} no longer opens {missing}"


def test_sdc_collector_returns_only_the_design_constraints(observed):
    assert observed["collect_sdc_files"]["value"] == [
        "input/constraints/top.sdc", "input/constraints/top_design_rules.sdc",
        "input/reference_flow/design.sdc"]


def test_staged_hdl_is_the_design_module_not_the_golden_one(observed):
    assert observed["find_staged_hdl"]["value"] == {
        "top.v": LEGIT["input/rtl/top.v"],
        "defs.vh": LEGIT["input/reference_flow/inc/defs.vh"]}


def test_register_declarations_are_the_design_ones(observed):
    assert observed["documentary_declarations"]["value"] == ["CTRL", "STATUS"]


def test_rtl_parameters_are_the_design_ones(observed):
    assert observed["_v1_14_50_declared_rtl_parameters"]["value"] == [
        "WIDTH"]


def test_never_ingested_census_does_not_list_oracle_files(observed):
    rows = observed["_v1_14_50_present_but_never_ingested"]["value"]
    assert not set(rows) & set(ORACLE)
    assert "input/docs/L1_product.md" in rows


def test_reference_clock_is_the_design_one(observed):
    assert observed["_post_emit_reference_clock_config"]["value"] == ["clk"]


def test_input_text_reads_design_docs_including_the_word_control(observed):
    read = observed["input_text_report"]["value"]["files_read"]
    assert not {f"input/{r}" for r in read} & set(ORACLE)
    assert "docs/L1_product_metadata.md" in read


def test_sign_off_provenance_and_l19_cite_the_design_clock(observed):
    # main: 2.5 ns, citing input/constraints/golden_timing.sdc, while STA signed
    # off at 10 ns (review 405, clock_target_provenance's own SDC collector).
    assert observed["clock_target_provenance.resolve"]["value"] == [10.0, "staged_sdc"]
    assert observed["_clock_target_record"]["value"] == [
        "DECLARED", 10.0, "input/constraints/top.sdc:1"]


def test_register_census_counts_an_excluded_doc_as_excluded_not_read(observed):
    assert observed["documentary_census"]["value"] == [2, 1]


def test_register_census_pins_excluded_member_and_scope_disclosure(tmp_path):
    import sys
    sys.path.insert(0, str(PROGRAMS))
    import l4_regmap_declared_register_coverage_check as l4
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "regmap_ref.md").write_text(
        "| Address | Name |\n|---|---|\n| 0x20 | REF_REG |\n")
    census = l4.documentary_census(tmp_path)
    assert [entry.split(" (")[0] for entry in census["excluded_oracle"]] == [
        "input/docs/regmap_ref.md"]
    assert all(entry.split(" (", 1)[1].startswith("§4.05")
               for entry in census["excluded_oracle"])
    _, summary = l4.evaluate(tmp_path)
    reason = summary["denominator"]["not_applicable_reason"]
    assert "deliberately did not read 1 file(s)" in reason
    assert "input/docs/regmap_ref.md" in reason
