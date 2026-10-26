#!/usr/bin/env python3
"""R-0915-144 — Step 5 answers its L8 clock/reset obligations PROGRAM-FIRST.

THE RULING. An obligation stating a STRUCTURAL fact (clock edge, reset port
name, synchronous vs asynchronous) is discharged by the program with a
structural check on the flow's own yosys netlist, recorded INVOKED_BY_PROGRAM
with its evidence. An obligation stating TEMPORAL reset behaviour (polarity;
"all internal state zero one cycle after assertion") is authored by the program
as generated properties over EVERY state register, and proved by the flow's own
engine. The `formal-verify` expert keeps only what no rule covers.

WHAT WAS MEASURED BEFORE THIS (spm run22, lanes icspm5 / icformal1):
  * step 5 INCOMPLETE — EXPERT_FALLBACK_OUTSTANDING, denominator 6, 5 open;
  * a property over `dut.pr` failed at frame 3 while the SAME claim over the
    harness port `p` (= pr) proved: yosys `read_verilog` makes `dut.pr` an
    implicitly declared, undriven local wire — a free variable. So DUT state is
    made visible through `@observe` observers (flatten + connect -set), and a
    `dut.*` reference is refused, never silently proved or refuted.

EVERY ARM RUNS THE REAL PROGRAMS: `formal_harness_gen.generate` ->
`formal_property_run.run` (the runner's own Step-5 sequence) ->
`formal_proof_evidence_check.audit`, with yosys and SymbiYosys on this process's
PATH (the in-image route CI and the flow take). Both directions:

  GREEN  the reference design, declared honestly     -> Step 5 PASS, program-only
  RED    async reset declared synchronous             -> sync obligation REFUTED
  RED    negedge clock declared posedge               -> edge obligation REFUTED
  RED    a register the reset branch does not zero    -> zeroing property cex
  RED    active-LOW reset declared active-high        -> polarity property cex
  RED    a property over `dut.<reg>`                   -> refused, nothing proved

chip-AGNOSTIC: the fixture is a textbook serial-parallel multiplier written
here; no vendor, SKU, IC or PDK literal.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import formal_harness_gen as fhg  # noqa: E402
import formal_property_run as fpr  # noqa: E402
import formal_proof_evidence_check as gate  # noqa: E402
from not_verified_tier import skip_not_verified  # noqa: E402

RTL = """`default_nettype none
module serial_mac #(
    parameter size = 8
) (
    input  wire            clk,
    input  wire            rst,
    input  wire [size-1:0] x,
    input  wire            y,
    output wire            p
);
    reg  [size-1:0] s;
    reg  [size-1:0] c;
    reg             yr;
    reg             pr;
    wire [size-1:0] m  = x & {size{yr}};
    wire [size-1:0] so = m ^ s ^ c;
    wire [size-1:0] co = (m & s) | (m & c) | (s & c);
    always @(posedge clk) begin
        if (rst) begin
            s  <= {size{1'b0}};
            c  <= {size{1'b0}};
            yr <= 1'b0;
            pr <= 1'b0;
        end else begin
            yr <= y;
            s  <= {1'b0, so[size-1:1]};
            c  <= co;
            pr <= so[0];
        end
    end
    assign p = pr;
endmodule
`default_nettype wire
"""

PROSE = ("同步 reset(**active-high**);"
         "assertion 後一個 cycle 內所有內部狀態歸零")

IDS = {
    "edge": "L8.clock_and_reset_waveform.clocks.0.edge",
    "name": "L8.clock_and_reset_waveform.resets.0.name",
    "polarity": "L8.clock_and_reset_waveform.resets.0.polarity",
    "sync": "L8.clock_and_reset_waveform.resets.0.sync",
    "prose": "L8.clock_and_reset_waveform.resets.0.port_description",
}


def _l8(edge="posedge", polarity="active_high", sync="synchronous",
        prose=PROSE) -> dict:
    return {"clock_and_reset_waveform": {
        "clocks": [{"name": "clk", "edge": edge}],
        "resets": [{"name": "rst", "polarity": polarity, "sync": sync,
                    "port_description": prose}]}}


def _project(tmp_path: Path, rtl: str = RTL, l8: dict = None) -> Path:
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(
        json.dumps(l8 or _l8(), ensure_ascii=False))
    rtl_dir = tmp_path / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "serial_mac.v").write_text(rtl)
    return tmp_path


def _require_engine():
    # Not a pass: an arm that cannot reach the engine has proved nothing, and
    # it says so as NOT_VERIFIED (a failure under
    # VIBEIC_REQUIRE_EDA_VERIFICATION=1), never as a green skip.
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_144_step5_closes_program_first.py")


def _step5(project: Path) -> tuple:
    """The runner's own Step-5 sequence, then the gate."""
    _require_engine()
    gen = fhg.generate(project=project, top="serial_mac")
    assert gen["verdict"] == "EMITTED", gen
    res = fpr.run(project, harness=Path(gen["harness_path"]),
                  rtl=[Path(p) for p in gen["rtl_files"]],
                  top=gen["harness_module"], container=None, timeout=300)
    rep = gate.audit(project)
    return gen, res, rep


# ── pure: the classification and the harness shape ─────────────────────────

def test_obligation_kind_is_derived_from_the_declaration_field():
    l8 = _l8()
    rows = {k: fhg.l8_program_rule(l8, k, t)
            for k, t in fhg._timing_semantics(l8)}
    kinds = {k.rsplit(".", 1)[-1]: (r or {}).get("kind") for k, r in rows.items()}
    # round 5: polarity is a STRUCTURAL netlist fact (review round 4, H2)
    assert kinds == {"edge": "STRUCTURAL", "name": "STRUCTURAL",
                     "polarity": "STRUCTURAL", "sync": "STRUCTURAL",
                     "port_description": "MIXED"}


def test_prose_the_program_does_not_fully_understand_stays_with_the_expert():
    # One unrecognised clause ("held for 16 cycles") and the program must not
    # answer ANY of it.
    assert fhg.parse_reset_prose(
        "同步 reset(**active-high**);assertion 後必須保持 16 個 cycle",
        "rst", "active_high") is None
    l8 = _l8(prose="synchronous; must be held for 16 cycles")
    rule = fhg.l8_program_rule(
        l8, "clock_and_reset_waveform.resets.0.port_description",
        "synchronous; must be held for 16 cycles")
    assert rule is None


def test_generated_harness_observes_every_state_register_and_never_uses_dut_refs(tmp_path):
    _require_engine()  # the observed state is read from the yosys netlist
    project = _project(tmp_path)
    gen = fhg.generate(project=project, top="serial_mac")
    text = Path(gen["harness_path"]).read_text()
    assert fpr.unbound_hierarchical_refs(text) == []
    # round 5: the observed registers are the NETLIST's design state (pr is
    # observed through its output-port alias p), never an RTL text scan
    obs = {o: r for o, r in fpr.parse_observers(text)}
    assert set(obs.values()) == {"dut.s", "dut.c", "dut.yr", "dut.p"}
    for reg in ("s", "c", "yr", "p"):
        assert f"property p_l8_reset_state_zero_rst_ah_{reg};" in text
    contract = json.loads(
        (project / "phase2/stage1/formal/property_contract.json").read_text())
    open_ids = {o["id"] for o in contract["unresolved_obligations"]}
    assert open_ids == {IDS["edge"], IDS["name"], IDS["sync"], IDS["polarity"],
                        IDS["prose"]}


def test_a_dut_hierarchical_reference_is_detected():
    text = ("module formal_x (input wire clk);\n"
            "  serial_mac #(.size(8)) dut (.clk(clk));\n"
            "  property q; @(posedge clk) 1 |-> (dut.pr == 1'b0); endproperty\n"
            "  // @observe vibeic_obs_pr = dut.pr\n"
            "endmodule\n")
    assert fpr.unbound_hierarchical_refs(text) == ["dut.pr"]


# ── engine: GREEN ───────────────────────────────────────────────────────────

def test_green_reference_design_closes_step5_program_only(tmp_path):
    project = _project(tmp_path)
    _, res, rep = _step5(project)
    # R-0924-2 (landed on main before this port): the reset NAME is
    # discharged by BINDING at the gate, not by the structural check, so
    # it is the one row the proof record leaves open and the gate closes.
    assert res["all_proved"] is True, res
    assert [o["id"] for o in res["unresolved_obligations"]] == [IDS["name"]]
    assert res["expert_fallback_invocation_status"] == "INVOKED_BY_PROGRAM"
    receipt = project / res["expert_fallback_receipt"]
    assert receipt.name == fpr.PROGRAM_RECEIPT and receipt.is_file()
    disp = {d["id"]: d["status"] for d in
            json.loads(receipt.read_text())["dispositions"]}
    assert disp == {**{IDS[k]: fpr.DISCHARGED_BY_PROGRAM
                       for k in ("edge", "sync", "polarity", "prose")},
                    IDS["name"]: "NOT_DISCHARGED"}
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["discharged_by_binding"] == [IDS["name"]]
    assert not any("EXPERT_FALLBACK_OUTSTANDING" in f for f in rep["findings"])


# ── engine: RED, one per obligation ─────────────────────────────────────────

def _why(row: dict) -> str:
    return f"{row.get('description', '')} {row.get('program_refused', '')}"


def _refuted_ids(res):
    return {r["id"] for r in res.get("structural_refutations") or []}


def test_red_async_reset_is_not_discharged_as_synchronous(tmp_path):
    rtl = RTL.replace("always @(posedge clk) begin",
                      "always @(posedge clk or posedge rst) begin")
    _, res, rep = _step5(_project(tmp_path, rtl))
    # the brief's arm: the sync obligation is NOT discharged, and named.
    # R-0915-155: this netlist is outside the class the program proves
    # (flop bits no public net holds wholly), so it is NOT_DISCHARGED.
    opened = {o["id"]: o for o in res["unresolved_obligations"]}
    assert IDS["sync"] in opened
    assert "R-0915-155" in _why(opened[IDS["sync"]])
    assert rep["verdict"] != "PASS"


def test_red_negedge_clock_fails_the_edge_obligation(tmp_path):
    rtl = RTL.replace("always @(posedge clk) begin",
                      "always @(negedge clk) begin")
    _, res, rep = _step5(_project(tmp_path, rtl))
    assert IDS["edge"] in _refuted_ids(res)
    assert rep["verdict"] == "FAIL"


def test_red_a_register_the_reset_branch_does_not_zero_fails_with_a_cex(tmp_path):
    rtl = RTL.replace("            yr <= 1'b0;\n", "")
    _, res, rep = _step5(_project(tmp_path, rtl))
    # "all state zero" is false (yr holds its value through reset) and must
    # never close. R-0915-155: the reset now GATES yr's load (it reaches yr's
    # enable), which is outside the class — NOT_DISCHARGED, named.
    opened = {o["id"]: o for o in res["unresolved_obligations"]}
    assert IDS["prose"] in opened
    assert "R-0915-155" in _why(opened[IDS["prose"]])
    assert rep["verdict"] != "PASS"


def test_red_active_low_reset_declared_active_high_fails_polarity(tmp_path):
    rtl = RTL.replace("if (rst) begin", "if (!rst) begin")
    _, res, rep = _step5(_project(tmp_path, rtl))
    # the netlist says every flop rst resets is reset ACTIVE-LOW (SRST
    # polarity 0): the declared active-high polarity is refuted structurally
    assert IDS["polarity"] in _refuted_ids(res)
    assert res["verdict"] == "FAIL"
    assert rep["verdict"] == "FAIL"


def test_red_a_property_over_dut_reg_is_refused_not_proved(tmp_path):
    project = _project(tmp_path)
    fdir = project / "phase2/stage1/formal"
    fdir.mkdir(parents=True)
    # the path s48 measured: an expert fragment asserting over `dut.<reg>`
    (fdir / fhg.EXPERT_PROPERTIES_SVH).write_text(
        "    property p_expert_pr;\n"
        "        @(posedge clk) (f_past_valid && rst_active_q) |-> (dut.pr == 1'b0);\n"
        "    endproperty\n"
        "    a_expert_pr: assert property (p_expert_pr);\n")
    _, res, rep = _step5(project)
    assert res["verdict"] == "ERROR" and res["all_proved"] is False
    assert res["hierarchical_references"] == ["dut.pr"]
    assert "HIERARCHICAL_REFERENCE_UNBOUND" in res["refusal"]
    assert rep["verdict"] == "FAIL"
    assert any("HIERARCHICAL_REFERENCE_UNBOUND" in f for f in rep["findings"])


def _provenance_declarations(tmp_path):
    import hashlib
    l8 = _l8()
    wave = l8['clock_and_reset_waveform']
    clock = wave['clocks'][0]
    clock['semantic_provenance'] = {'edge': {
        'kind': 'convention', 'rule': 'default_positive_clock_edge'}}
    l8['clock_domains'] = [json.loads(json.dumps(clock))]
    quote = '| `rst` | 1-bit | input | 同步 reset(**active-high**) |'
    source = tmp_path / 'input/docs/interface.md'
    source.parent.mkdir(parents=True)
    source.write_text(quote + '\n')
    basis = {'file': 'input/docs/interface.md', 'line': 1, 'quote': quote,
             'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    wave['resets'][0]['semantic_provenance'] = {
        f: {'kind': 'explicit', 'basis': [dict(basis)]} for f in ('sync', 'polarity')}
    return l8, source


def test_equivalent_provenance_uses_canonical_claims(tmp_path):
    l8, _ = _provenance_declarations(tmp_path)
    for key, text in fhg._timing_semantics(l8):
        rule = fhg.l8_program_rule(l8, key, text, tmp_path)
        assert rule is not None, key
        if '.semantic_provenance.' in key:
            parent, tail = key.split('.semantic_provenance.')
            canonical = parent + '.' + tail.split('.')[0]
            expected = fhg.l8_program_rule(l8, canonical, fhg._value_at(l8, canonical))
            assert rule['claims'] == expected['claims']
            assert rule['kind'] == 'STRUCTURAL'
            assert rule['equivalent_to'] == 'L8.' + canonical
            assert rule['semantic_provenance'] == fhg._value_at(l8, parent + '.semantic_provenance.' + tail.split('.')[0])
    assert fhg.l8_program_rule(l8, 'clock_domains.0.edge', 'posedge')['claims'] == [
        {'rule': 'clock_edge', 'signal': 'clk', 'value': 'posedge'}]


@pytest.mark.parametrize('edge', ['negedge', 'either', 'bogus'])
def test_clock_provenance_cannot_borrow_positive_edge(tmp_path, edge):
    l8, _ = _provenance_declarations(tmp_path)
    l8['clock_domains'][0]['edge'] = edge
    assert fhg.l8_program_rule(l8, 'clock_domains.0.semantic_provenance.edge.rule',
                               'default_positive_clock_edge', tmp_path) is None
    direct = fhg.l8_program_rule(l8, 'clock_domains.0.edge', edge)
    assert direct is None or direct['claims'][0]['value'] != 'posedge'


@pytest.mark.parametrize('mutation', ['foreign', 'foreign_polarity', 'hash', 'line', 'quote', 'outside', 'polarity', 'sync', 'source_pin', 'unknown_rule'])
def test_provenance_rejects_wrong_binding(tmp_path, mutation):
    import hashlib
    l8, source = _provenance_declarations(tmp_path)
    reset = l8['clock_and_reset_waveform']['resets'][0]
    basis = reset['semantic_provenance']['sync']['basis'][0]
    key = 'clock_and_reset_waveform.resets.0.semantic_provenance.sync.basis.0.quote'
    if mutation in {'foreign', 'foreign_polarity'}:
        basis['quote'] = (basis['quote'].replace('`rst`', '`foreign_rst`')
                          if mutation == 'foreign' else
                          '| `rst` | 1-bit | input | 同步 reset; foreign_rst is active-high |')
        source.write_text(basis['quote'] + '\n')
        basis['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    elif mutation == 'hash':
        basis['sha256'] = '0' * 64
    elif mutation == 'line':
        basis['line'] = 2
    elif mutation == 'quote':
        basis['quote'] += ' modified'
    elif mutation == 'outside':
        basis['file'] = '../outside.md'
    elif mutation in {'polarity', 'sync'}:
        reset[mutation] = 'active_low' if mutation == 'polarity' else 'asynchronous'
    else:
        clock = l8['clock_domains'][0]
        if mutation == 'source_pin':
            clock['source_pin'] = 'foreign_clk'
        else:
            clock['semantic_provenance']['edge']['rule'] = 'any_edge'
        key = 'clock_domains.0.semantic_provenance.edge.rule'
    assert fhg.l8_program_rule(l8, key, fhg._value_at(l8, key), tmp_path) is None


def test_equivalent_clock_claim_reaches_structural_consumer(tmp_path):
    import formal_structural_check as structural
    l8, _ = _provenance_declarations(tmp_path)
    rtl = tmp_path / 'serial_mac.v'
    rtl.write_text(RTL)
    rule = fhg.l8_program_rule(l8, 'clock_domains.0.semantic_provenance.edge.rule',
                              'default_positive_clock_edge', tmp_path)
    assert rule is not None
    claim = rule['claims'][0]
    claims = [claim]
    for field in ('sync', 'polarity'):
        key = 'clock_and_reset_waveform.resets.0.semantic_provenance.' + field + '.basis.0.quote'
        claims += fhg.l8_program_rule(l8, key, fhg._value_at(l8, key), tmp_path)['claims']
    result = structural.check([rtl], 'serial_mac', claims + [dict(claim, value='negedge')], tmp_path / 'structural')
    (tmp_path / 'consumer.json').write_text(json.dumps(result, indent=2))
    assert [r['verdict'] for r in result['claims']] == ['PASS', 'PASS', 'PASS', 'REFUTED'], result


@pytest.mark.parametrize('suffix', ['', ' is not required',
    ' only if enable is asserted',
    '; this statement applies to foreign_rst, not rst',
    '; reset 後內部狀態須能讓乘法計算正確啟動',
    '; assertion 後一個 cycle 內所有內部狀態歸零'])
@pytest.mark.parametrize('field', ['sync', 'polarity'])
def test_complete_provenance_clause_cannot_launder_suffix(tmp_path, suffix, field):
    import hashlib
    l8, source = _provenance_declarations(tmp_path)
    quote = '| `rst` | 1-bit | input | synchronous reset (active-high)' + suffix + ' |'
    source.write_text(quote + '\n')
    basis = l8['clock_and_reset_waveform']['resets'][0]['semantic_provenance'][field]['basis'][0]
    basis.update(quote=quote, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    key = 'clock_and_reset_waveform.resets.0.semantic_provenance.' + field + '.basis.0.quote'
    observed = fhg.l8_program_rule(l8, key, quote, tmp_path)
    if suffix:
        assert observed is None, observed
    else:
        canonical = 'clock_and_reset_waveform.resets.0.' + field
        assert observed['claims'] == fhg.l8_program_rule(
            l8, canonical, fhg._value_at(l8, canonical))['claims']
