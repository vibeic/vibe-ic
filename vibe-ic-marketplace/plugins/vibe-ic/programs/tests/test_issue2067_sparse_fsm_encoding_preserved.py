#!/usr/bin/env python3
"""Regression for #2067 — `synth` flattened the design's SPARSE FSM encodings.

MEASURED on 8HD-8, image sha256:06537f7e8d3c (label 0.3.46), yosys 0.68+,
against the opentitan_aes corpus cell's OWN RTL (`aes_ctr_fsm`, design INPUT
only — §4.05) and a 3-state d_min=3 reproducer:

  BEFORE (shipped script)   `wire [2:0] u_state_regs.u_state_flop.q_o`
                            fsm_encoding.enc:  .fsm aes_ctr_fsm
                                               u_state_regs.u_state_flop.q_o
                                               .map 01110 --1 / 11000 -1- /
                                               00001 1--
                            -> the RTL's 5-bit Hamming-3 codes are one-hot
  AFTER  (this fix)         `wire [4:0] u_state_regs.u_state_flop.q_o`
                            reset bits PN0/PN1/PN1/PN0 = 5'b01110 = CTR_IDLE,
                            the RTL constant; fsm_encoding.enc EMPTY

The netlist was functionally equivalent BOTH ways — that is exactly why no
existing gate could see this: port equivalence says the FUNCTION is preserved,
not the fault-injection property the sparse encoding exists for. Keeping the
encoding cost no proofs; it gained one. Shipped `lec_run.py`, unchanged, on
`aes_ctr_fsm` in the same container:

    with the fix     compared 32, unproven 0   verdict PASS
    without it       compared 31, unproven 1   verdict INCONCLUSIVE

The state register `fsm_recode` actually re-encodes is the SPARSE FLOP's own
output (`u_state_regs.u_state_flop.q_o`), NOT the name the RTL gives the state
(`aes_ctr_cs`) — so both the injection and the audit have to be anchored on
the flop INSTANCE as well as on the declared register name, and the attribute
has to be set AFTER `flatten` (before it, the instance-path wire does not
exist). Each of those three facts is pinned by a test below; each was a real
red while this was measured.
"""
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import sparse_fsm_detect as det              # noqa: E402
import sparse_fsm_encoding_check as chk      # noqa: E402

# A 3-state, 5-bit, minimum-Hamming-3 encoding — the shape OpenTitan's
# sparse-fsm-encode.py emits. These ARE the opentitan_aes `aes_ctr_e` codes,
# read from the design INPUT (`input/vendor_rtl/aes/aes_pkg.sv`).
SPARSE_RTL = """
module sparse_fsm (input clk, input rst_n, input go, output reg done);
  localparam [4:0] S_IDLE  = 5'b01110;
  localparam [4:0] S_INCR  = 5'b11000;
  localparam [4:0] S_ERROR = 5'b00001;
  reg [4:0] state_q, state_d;
  always @(*) case (state_q)
      S_IDLE:  state_d = go ? S_INCR : S_IDLE;
      S_INCR:  state_d = S_IDLE;
      default: state_d = S_ERROR;
    endcase
  always @(posedge clk or negedge rst_n)
    if (!rst_n) state_q <= S_IDLE; else state_q <= state_d;
  always @(*) done = (state_q == S_INCR);
endmodule
"""

# A dense binary-count encoding: d_min = 1. The NEGATIVE control — nothing
# here may be reported sparse, or the fix would disable `fsm_recode`'s normal
# and correct optimisation for ordinary designs.
DENSE_RTL = """
module dense_fsm (input clk, input rst_n, input go, output reg done);
  localparam [1:0] A = 2'b00, B = 2'b01, C = 2'b10;
  reg [1:0] st;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) st <= A; else case (st) A: st <= go ? B : A;
                                       B: st <= C; default: st <= A; endcase
  always @(*) done = (st == C);
endmodule
"""

# The OpenTitan spelling: the state register is a macro argument and the flop
# is an instance. Matching only the module name `prim_sparse_fsm_flop` finds
# the macro DEFINITION and nothing else — measured on the corpus cell, 2 files
# name the module and 7 use the macro.
MACRO_RTL = """
module aes_ctr_fsm (input clk_i, input rst_ni);
  aes_ctr_e aes_ctr_ns, aes_ctr_cs;
  `PRIM_FLOP_SPARSE_FSM(u_state_regs, aes_ctr_ns, aes_ctr_cs, aes_ctr_e,
                        CTR_IDLE)
endmodule
"""

MACRO_DEFINITION_RTL = """
`define PRIM_FLOP_SPARSE_FSM(__name, __d, __q, __type, __resval) \\
    prim_sparse_fsm_flop #(.Width($bits(__type))) __name (        \\
      .clk_i(clk_i), .rst_ni(rst_ni), .state_i(__d), .state_o());
"""


def _write(tmp_path, name, text):
    d = tmp_path / name
    d.mkdir()
    (d / (name + ".v" if "macro" not in name else name + ".sv")).write_text(text)
    return d


# --------------------------------------------------------------------------
# 1. DETECTION — from the design INPUT, and BOTH directions.
# --------------------------------------------------------------------------
def test_hamming_separated_localparams_are_detected(tmp_path):
    d = _write(tmp_path, "sparse", SPARSE_RTL)
    rep = det.detect_paths([d])
    assert rep["declares_sparse_fsm"] is True
    assert "state_q" in rep["register_names"], rep["register_names"]


def test_a_dense_encoding_is_not_reported_sparse(tmp_path):
    """THE CONTROL. A checker that says yes to everything is not a checker,
    and a fix that disabled fsm_recode design-wide would be a PPA regression
    for every ordinary design."""
    d = _write(tmp_path, "dense", DENSE_RTL)
    rep = det.detect_paths([d])
    assert rep["declares_sparse_fsm"] is False
    assert rep["register_names"] == []


def test_minimum_pairwise_hamming_is_undefined_not_zero():
    assert det.min_pairwise_hamming(["01110", "11000", "00001"]) == 3
    assert det.min_pairwise_hamming(["00", "01", "10"]) == 1
    # Undefined must never read as "densely packed".
    assert det.min_pairwise_hamming(["0101"]) is None
    assert det.min_pairwise_hamming(["010", "0101"]) is None


def test_the_macro_use_is_detected_and_the_macro_definition_is_not(tmp_path):
    d = tmp_path / "ot"
    d.mkdir()
    (d / "aes_ctr_fsm.sv").write_text(MACRO_RTL)
    (d / "prim_flop_macros.sv").write_text(MACRO_DEFINITION_RTL)
    rep = det.detect_paths([d])
    assert "aes_ctr_cs" in rep["register_names"]
    assert "u_state_regs" in rep["flop_instances"]
    # The definition's formal arguments are not state registers of any module.
    assert not [n for n in rep["register_names"] if n.startswith("__")], rep


# --------------------------------------------------------------------------
# 2. THE INJECTION the synth step emits.
# --------------------------------------------------------------------------
def test_no_sparse_fsm_means_a_byte_identical_script():
    """NO-LEAK. A design that declares no sparse FSM must get exactly the
    yosys script it got before this change."""
    assert det.yosys_setattr_cmd([], []) is None
    assert det.yosys_encoding_preserve_cmds([], [], top="anything") == []


def test_the_injection_is_per_register_and_instance_anchored():
    cmd = det.yosys_setattr_cmd(["aes_ctr_cs"], ["u_state_regs"])
    assert cmd.startswith('setattr -set fsm_encoding "none" ')
    assert "w:aes_ctr_cs" in cmd
    # MEASURED: the register fsm_recode really re-encodes is
    # `u_state_regs.u_state_flop.q_o`, so the declared name alone selects
    # nothing and the fix would be inert.
    assert "w:*u_state_regs*" in cmd
    # ...and NOT a bare wildcard that would cover every flop in the design.
    assert "w:*q_o*" not in cmd


def test_the_attribute_is_set_after_flatten():
    """Before `flatten` the instance-path wire does not exist yet. Measured:
    setting the attribute pre-flatten left the encfile non-empty."""
    cmds = det.yosys_encoding_preserve_cmds(["state_q"], ["u_state_regs"],
                                            top="t")
    assert cmds[:3] == ["hierarchy -top t", "proc", "flatten"]
    assert cmds[3].startswith("setattr -set fsm_encoding")


def test_both_phase2_synth_call_sites_preserve_the_encoding():
    """The netlist can come from either synth call-site (built-in
    read_verilog, or the read_slang/sv2v fallback a modern-SV design such as
    an OpenTitan-class IP takes). Both must inject, or the fix is live on one
    of them only. Read as TEXT: importing the runner drags in the whole
    runner."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text()
    assert src.count("import sparse_fsm_detect as _sfd") == 2, src.count(
        "import sparse_fsm_detect as _sfd")
    # the SV-frontend site: the attribute lands after that script's flatten
    assert src.count("proc; flatten; {_sparse_post}") == 1
    assert src.count('f"{_sparse_post}"') == 1
    # the built-in site: the prelude is spliced into the command list
    assert "_sparse_fsm_preserve_cmds(rtl_files)" in src


# --------------------------------------------------------------------------
# 3. THE AUDIT — it must be able to go RED, by name.
# --------------------------------------------------------------------------
def _proj(tmp_path, enc_text, netlist_text):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "sparse.v").write_text(SPARSE_RTL)
    enc = tmp_path / "fsm_encoding.enc"
    enc.write_text(enc_text)
    net = tmp_path / "netlist.v"
    net.write_text(netlist_text)
    return [d], enc, net


# The exact table `synth -encfile` wrote for the reproducer, and the exact
# one-hot state declaration its netlist carried.
RECODED_ENC = ".fsm sparse_fsm state_q\n.map 11000 -1-\n.map 01110 --1\n" \
              ".map 00001 1--\n"
RECODED_NET = "module sparse_fsm(clk, rst_n, go, done);\n" \
              "  wire [2:0] state_q;\nendmodule\n"
KEPT_NET = "module sparse_fsm(clk, rst_n, go, done);\n" \
           "  wire [4:0] state_q;\nendmodule\n"


def test_the_audit_names_the_registers_whose_encoding_was_lost(tmp_path):
    rtl, enc, net = _proj(tmp_path, RECODED_ENC, RECODED_NET)
    rep = chk.check(rtl, enc, net)
    assert rep["verdict"] == "FAIL"
    assert rep["refusal"] == "FSM_SPARSE_ENCODING_LOST"
    assert [r["register"] for r in rep["fsm_recoded"]] == ["state_q"]


def test_the_audit_reports_an_empty_list_when_the_encoding_survived(tmp_path):
    rtl, enc, net = _proj(tmp_path, "", KEPT_NET)
    rep = chk.check(rtl, enc, net)
    assert rep["verdict"] == "PASS"
    assert rep["fsm_recoded"] == []


def test_the_netlist_width_alone_can_redden_it(tmp_path):
    """The second, independent observable: an absent encoding table must not
    be able to hide a re-encoding."""
    rtl, _enc, net = _proj(tmp_path, "", RECODED_NET)
    rep = chk.check(rtl, None, net)
    assert rep["verdict"] == "FAIL"
    assert rep["fsm_recoded"][0]["rtl_width"] == 5
    assert rep["fsm_recoded"][0]["netlist_width"] == 3


def test_an_encfile_entry_named_by_the_flop_instance_still_reddens(tmp_path):
    """MEASURED on opentitan_aes: the entry names
    `u_state_regs.u_state_flop.q_o`, not `aes_ctr_cs`. Matching only the
    declared register name would have reported a clean sweep over the exact
    defect this issue is about."""
    d = tmp_path / "ot"
    d.mkdir()
    (d / "aes_ctr_fsm.sv").write_text(MACRO_RTL)
    (d / "aes_pkg.sv").write_text(
        "typedef enum logic [4:0] { CTR_IDLE = 5'b01110,"
        " CTR_INCR = 5'b11000, CTR_ERROR = 5'b00001 } aes_ctr_e;\n")
    enc = tmp_path / "fsm_encoding.enc"
    enc.write_text(".fsm aes_ctr_fsm u_state_regs.u_state_flop.q_o\n"
                   ".map 01110 --1\n")
    rep = chk.check([d], enc, None)
    assert rep["verdict"] == "FAIL"
    assert rep["refusal"] == "FSM_SPARSE_ENCODING_LOST"
    assert rep["fsm_recoded"][0]["register"].endswith("q_o")


def test_unreadable_is_not_clean(tmp_path):
    """"Could not read it" is never "read it and it was clean"."""
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "sparse.v").write_text(SPARSE_RTL)
    rep = chk.check([d], None, None)
    assert rep["verdict"] == "NOT_MEASURED"
    assert rep["fsm_recoded"] == []


def test_a_design_with_no_sparse_fsm_passes(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "dense.v").write_text(DENSE_RTL)
    rep = chk.check([d], None, None)
    assert rep["verdict"] == "PASS"


def test_the_cli_exit_codes_separate_fail_from_not_measured(tmp_path):
    rtl, enc, net = _proj(tmp_path, RECODED_ENC, RECODED_NET)
    base = [sys.executable, str(_PROGRAMS / "sparse_fsm_encoding_check.py"),
            "--rtl-dir", str(rtl[0]), "--json", str(tmp_path / "r.json")]
    r = subprocess.run(base + ["--encfile", str(enc), "--netlist", str(net)],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stderr
    assert json.loads((tmp_path / "r.json").read_text())["refusal"] == \
        "FSM_SPARSE_ENCODING_LOST"
    r2 = subprocess.run(base, capture_output=True, text=True)
    assert r2.returncode == 2, r2.stderr


def test_the_audit_has_a_runner():
    """An audit nothing runs is inert. The producer runs it beside the netlist
    it judges and writes reports/sparse_fsm_encoding.json; the standalone CLI
    is the gate that can exit non-zero."""
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text()
    assert "import sparse_fsm_encoding_check as _sfec" in src
    assert "reports\" / \"sparse_fsm_encoding.json" in src or \
        '"sparse_fsm_encoding.json"' in src, "the report path must be written"
    assert "_sfec.check(" in src


# --------------------------------------------------------------------------
# 4. THE `_NOT_PROSE` CLAIM — its falsifier.
# --------------------------------------------------------------------------
# `prose_polarity_consulted_check._NOT_PROSE` classifies
# `sparse_fsm_detect::_sparse_enum_types` as reading a formal grammar rather
# than prose, so it is exempt from consulting the polarity vocabulary. That is
# a CLASSIFICATION, not an allowlist, and it has to be checkable: OpenTitan
# documents its Hamming histogram in a COMMENT directly above the enum, which
# is the one place natural language appears in this input. If a sentence there
# could change what the reader publishes, the classification is false and the
# instruction is to DELETE THE ENTRY — never to relax the assertion below.
_ENUM_WITH_A_DENYING_COMMENT = """
// Minimum Hamming distance: 3
typedef enum logic [4:0] {
  CTR_IDLE  = 5'b01110,
  // This state is NOT part of the encoding and is REMOVED, not translated:
  // CTR_FAKE = 5'b01111,
  CTR_INCR  = 5'b11000,
  CTR_ERROR = 5'b00001
} aes_ctr_e;
"""

_ENUM_PLAIN = """
typedef enum logic [4:0] {
  CTR_IDLE  = 5'b01110,
  CTR_INCR  = 5'b11000,
  CTR_ERROR = 5'b00001
} aes_ctr_e;
"""


def test_the_not_prose_claim_for_the_enum_reader_is_falsifiable():
    """No sentence reaches these regexes: the function strips comments itself,
    so the denial and its absence answer alike — which is exactly why the
    polarity question has no referent here. The claim is NOT that the prose is
    read and correctly overruled; it is that it is never read.

    THE FIXTURE IS CHOSEN SO THE CLAIM CARRIES THE RESULT. `CTR_FAKE =
    5'b01111` sits inside the enum body, commented out and explicitly denied.
    Read as a declaration it is 1 bit from CTR_IDLE, which drops the group's
    minimum pairwise Hamming distance to 1 and the whole enum stops being
    reported sparse — i.e. a denied constant would silently withdraw the
    encoding this issue exists to preserve. MEASURED: with the strip removed
    this test goes red, which is what makes it a falsifier rather than a
    restatement."""
    denied = det._sparse_enum_types(_ENUM_WITH_A_DENYING_COMMENT)
    plain = det._sparse_enum_types(_ENUM_PLAIN)
    assert denied == plain, (
        "a comment changed what the enum reader published; the `_NOT_PROSE` "
        "entry for sparse_fsm_detect::_sparse_enum_types claims no prose "
        "reaches it, and that claim is now false — delete the entry rather "
        "than this assertion")
    # ...and the grammar half of the claim: what it publishes is the DECLARED
    # constants, keyed by the declared type.
    assert plain["aes_ctr_e"]["min_hamming"] == 3
    assert plain["aes_ctr_e"]["states"]["CTR_IDLE"] == "01110"
    assert "CTR_FAKE" not in denied["aes_ctr_e"]["states"]


def test_the_enum_reader_strips_comments_itself_not_via_its_callers():
    """The claim must be a property of the FUNCTION. Called directly, with no
    caller to pre-strip, a commented-out constant inside the body must not
    reach the match."""
    got = det._sparse_enum_types(_ENUM_WITH_A_DENYING_COMMENT)
    assert list(got["aes_ctr_e"]["states"]) == ["CTR_IDLE", "CTR_INCR",
                                                "CTR_ERROR"]
