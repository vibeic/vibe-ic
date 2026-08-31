"""test_hamming_synth.py — the DETERMINISTIC CVDP Hamming/ECC-family solver.

hamming_synth.solve(record) recognizes a stand-alone Hamming encoder
(transmitter) or decoder/corrector (receiver), PARSES the stated geometry
(k data bits / p parity bits / n encoded width, even-parity convention, the
power-of-two-positional layout with a redundant LSB), DERIVES the standard
Hamming parity coverage from k/p (never reading a golden body), and emits the
XOR-tree encoder or the syndrome single-error-correcting decoder. It is
CVDP-COMPLIANT: the module NAME and the port INTERFACE both come from
`input.prompt`/`input.context` via `record_prompt_context_bridge` (exactly like `crc_synth`),
NEVER from the OFF-LIMITS cocotb harness / `.env` TOPLEVEL.

POSITIVE: the real-shaped (7,4) encoder and decoder records PARSE, EMIT, and the
emit is FUNCTIONALLY correct — the encoder matches the golden codeword for all
16 data words, and the decoder corrects EVERY single-bit error in EVERY codeword
(16 words x 8 positions + no-error), both in Python (encode/decode) and via
iverilog when the binary is present. The parameterized forms are verified at a
SECOND geometry (DATA_WIDTH=11 -> Hamming(15,11)).

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None — a wrong ECC is far worse than
an honest skip):
  * a foreign ECC (Reed-Solomon / BCH / CRC / convolutional)  -> SKIP;
  * parity convention (even/odd) not stated                   -> SKIP;
  * the power-of-two layout / redundant bit not stated        -> SKIP;
  * a stated parity count that contradicts the formula        -> SKIP;
  * a COMPOSITE split-and-concatenate top (NUM_MODULES)       -> SKIP;
  * a non-Hamming prompt                                      -> SKIP.

CHIP-AGNOSTIC: the solver keys only on Hamming semantics, never on a design name.
A renamed copy of the positive solves identically; the guards fire on the
SEMANTICS, and the emitted RTL stays functionally correct under the rename.

The iverilog functional check is GATED on the iverilog binary; the parse / emit /
SKIP / Python-cross-check assertions run anywhere.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import hamming_synth as H  # noqa: E402
import record_prompt_context_bridge as CB  # noqa: E402  compliant name+interface source
from _hostpaths import corpus_path  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


# --------------------------------------------------------------------------- #
# fixtures — CVDP-COMPLIANT records (name + interface in input.prompt; harness
# .env + cocotb retained as OFF-LIMITS oracle the solver never reads)
# --------------------------------------------------------------------------- #
def _record(prompt: str, top: str, in_sig: str = "data_in",
            out_sig: str = "data_out", in_w: int = 4, out_w: int = 8,
            params=None, tb_name: str = "tx_test") -> dict:
    """A CVDP-COMPLIANT record: the module NAME and the port INTERFACE both live in
    `input.prompt` — the ONLY model-visible surface. `hamming_synth.solve` recovers
    the name via `record_prompt_context_bridge.toplevel_name` (prompt/context) and the ports via
    `record_prompt_context_bridge.extract_interface` (a prompt `### Inputs:`/`### Outputs:`
    block, prose, or a test-case table) — NEVER the cocotb `dut.<sig>` harness or the
    `.env` TOPLEVEL, which are the hidden test HARNESS = OFF-LIMITS oracle. Mirrors
    the compliant `crc_synth.solve` interface-source pattern.

    (1) Guarantee the module name is STATED in the prompt so `toplevel_name` can
        recover it without the harness — prepend a `module `<top>`` designation when
        the prompt does not already name it.
    (2) Relocate the port NAMES + WIDTHS into a legal prompt-side
        `### Inputs:`/`### Outputs:` block. The widths are the Hamming shape the
        design already implies (encoder: k-bit data in / n-bit codeword out; decoder:
        n-bit codeword in / k-bit data out) — the SAME single-in/single-out interface
        the removed cocotb `dut.<sig>` harness bound, merely stated on a legal surface.
    """
    if f"`{top}`" not in prompt:
        prompt = f"Design the Verilog module `{top}`.\n\n" + prompt
    if "### Inputs:" not in prompt:
        prompt = prompt + textwrap.dedent(f"""

            ### Inputs:
            - `{in_sig}` ([{in_w-1}:0], {in_w}-bit): the single data/codeword input.

            ### Outputs:
            - `{out_sig}` ([{out_w-1}:0], {out_w}-bit): the single data/codeword output.
        """)
    # OFF-LIMITS oracle harness (retained for record-shape fidelity; solver ignores).
    extra = ""
    if params:
        extra = "\n".join(f"    _{p} = int(dut.{p}.value)" for p in params) + "\n"
    tb_py = textwrap.dedent(f"""\
        import cocotb
        @cocotb.test()
        async def {tb_name}(dut):
        {extra}    dut.{in_sig}.value = 0
            await Timer(1)
            got = int(dut.{out_sig}.value)
    """)
    return {
        "input": {"prompt": prompt},
        "harness": {"files": {
            "src/.env": f"TOPLEVEL = {top}\nMODULE = {tb_name}\n",
            f"src/{tb_name}.py": tb_py,
        }},
        "output": {"context": {f"rtl/{top}.sv": ""}},
    }


# A real-shaped, fully-stated (7,4) Hamming ENCODER (transmitter): 4 data bits,
# 3 parity bits, 8-bit encoded output, even parity, parity at powers of two,
# redundant LSB. This is the canonical positive.
_ENC_PROMPT = textwrap.dedent("""\
    Design a transmitter module that encodes 4-bit input data (data_in) into an
    8-bit output (data_out) using Hamming code principles for error detection.

    For 4 data bits, 3 parity bits are required, resulting in a total of 7 bits
    (3 parity + 4 data). An extra redundant bit is added to pad the output 8 bits.

    The parity bits are calculated using XOR operations to ensure even parity.
    These parity bit positions correspond to powers of 2 in the output structure
    (positions 1, 2, and 4). data_out[0] is a redundant bit fixed to 0. The data
    bits are placed sequentially at the non-power-of-two positions.

    The module outputs the final 8-bit encoded signal for transmission.
""")

# A real-shaped, fully-stated (7,4) Hamming DECODER (receiver/corrector).
_DEC_PROMPT = textwrap.dedent("""\
    Design a receiver module that decodes an 8-bit input signal (data_in) and
    detects single-bit errors using Hamming code principles, and provides
    corrected 4-bit data to output port data_out.

    The transmitted data includes 4 data bits and 3 parity bits plus 1 redundant
    bit. Parity bits are placed at positions that are powers of 2 in data_in
    (positions 1, 2, 4). The receiver performs even parity checks (XOR) to compute
    the syndrome, which directly indicates the position of any single-bit error.
    If an error is detected the erroneous bit is inverted; the redundant bit at
    position 0 is not corrected. The corrected data bits are assigned to data_out.
""")

# Parameterized encoder / decoder (DATA_WIDTH / PARITY_BIT defaults 4 / 3).
_PARAM_ENC_PROMPT = textwrap.dedent("""\
    Convert the Hamming code transmitter into a parameterized Hamming code
    transmitter using SystemVerilog, named hamming_tx.

    - DATA_WIDTH: Specifies the width of the data input, configurable by the user.
      The default is 4 and should be greater than 0.
    - PARITY_BIT: Specifies the number of parity bits, also configurable by the
      user. The default is 3.
    - ENCODED_DATA = PARITY_BIT + DATA_WIDTH + 1, the total output width.

    Parity bits use even parity (XOR) and are placed at indices corresponding to
    powers of two (1, 2, 4, 8). data_out[0] is a redundant bit set to 1'b0. The
    data bits fill the remaining non-power-of-two positions sequentially. The
    design outputs the encoded data_out.
""")

_PARAM_DEC_PROMPT = textwrap.dedent("""\
    Convert the Hamming code receiver into a parameterized Hamming code receiver
    named hamming_rx using SystemVerilog. The module takes an encoded signal
    data_in (data, parity, and a redundant bit), detects and corrects only
    single-bit errors, and assigns the corrected data to data_out.

    - DATA_WIDTH: configurable. The default is 4.
    - PARITY_BIT: configurable. The default is 3.
    - ENCODED_DATA = PARITY_BIT + DATA_WIDTH + 1.

    Error detection uses even parity (XOR) over indices where the n-th bit of the
    binary index is 1; parity bits sit at powers of two. The combined parity check
    is the binary index of the error location; invert that bit (the redundant bit
    at position 0 is not inverted). The corrected data bits at non-power-of-two
    positions are assigned to data_out.
""")


# --------------------------------------------------------------------------- #
# geometry derivation (pure, deterministic)
# --------------------------------------------------------------------------- #
def test_derive_p_matches_hamming_formula():
    # minimum p with 2^p >= p + k + 1
    assert H.derive_p(1) == 2          # 2^2=4 >= 1+1+1=3
    assert H.derive_p(4) == 3          # 2^3=8 >= 3+4+1=8
    assert H.derive_p(11) == 4         # 2^4=16 >= 4+11+1=16
    assert H.derive_p(26) == 5
    assert H.derive_p(57) == 6


def test_data_indices_are_non_powers_of_two():
    # n=8 -> data at 3,5,6,7 (powers 1,2,4 reserved; 0 redundant)
    assert H.data_indices(8) == [3, 5, 6, 7]
    # n=16 -> 11 data slots (Hamming(15,11) + redundant LSB)
    di = H.data_indices(16)
    assert len(di) == 11
    assert 1 not in di and 2 not in di and 4 not in di and 8 not in di and 0 not in di


def test_parity_coverage_is_the_standard_hamming_set():
    spec = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
    cov = H.parity_coverage(spec)
    assert cov[0] == [1, 3, 5, 7]
    assert cov[1] == [2, 3, 6, 7]
    assert cov[2] == [4, 5, 6, 7]


# --------------------------------------------------------------------------- #
# spec parsing
# --------------------------------------------------------------------------- #
def test_parse_encoder_spec():
    spec = H.parse_hamming_spec(_ENC_PROMPT, "hamming_code_tx_for_4bit")
    assert spec is not None
    assert (spec.k, spec.p, spec.n) == (4, 3, 8)
    assert spec.role == "encoder"
    assert spec.even_parity is True
    assert spec.redundant is True


def test_parse_decoder_spec():
    spec = H.parse_hamming_spec(_DEC_PROMPT, "hamming_code_receiver")
    assert spec is not None
    assert (spec.k, spec.p, spec.n) == (4, 3, 8)
    assert spec.role == "decoder"


def test_parse_parameterized_default_geometry():
    spec = H.parse_hamming_spec(_PARAM_ENC_PROMPT, "hamming_tx")
    assert spec is not None
    assert (spec.k, spec.p, spec.n) == (4, 3, 8)
    assert spec.role == "encoder"
    assert spec.parameterized is True


# --------------------------------------------------------------------------- #
# Python golden cross-check — encode matches the harness golden; decode corrects
# every single-bit error
# --------------------------------------------------------------------------- #
def _harness_golden_enc(d):
    """The harness's own (7,4) encoder (tx_test.calculate_data_out), independent
    of our solver — proves our encode() matches the SCORER, not just itself."""
    t = [(d >> (3 - i)) & 1 for i in range(4)]
    o = [0] * 8
    o[7] = 0
    o[6] = t[3] ^ t[2] ^ t[0]
    o[5] = t[3] ^ t[1] ^ t[0]
    o[4] = t[3]
    o[3] = t[2] ^ t[1] ^ t[0]
    o[2] = t[2]
    o[1] = t[1]
    o[0] = t[0]
    return int("".join(map(str, o)), 2)


def test_encode_matches_independent_harness_golden():
    spec = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
    for d in range(16):
        assert H.encode(spec, d) == _harness_golden_enc(d), d


def test_decode_corrects_every_single_bit_error():
    enc = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
    dec = H.HammingSpec(4, 3, 8, True, True, "decoder", False, False)
    for d in range(16):
        cw = H.encode(enc, d)
        assert H.decode(dec, cw) == d              # no error
        for b in range(8):
            assert H.decode(dec, cw ^ (1 << b)) == d, (d, b)


def test_decode_corrects_at_second_geometry():
    # Hamming(15,11): DATA_WIDTH=11 -> p=4, n=16. General, not (7,4)-specific.
    enc = H.HammingSpec(11, 4, 16, True, True, "encoder", True, False)
    dec = H.HammingSpec(11, 4, 16, True, True, "decoder", True, False)
    for d in (0, 1, (1 << 11) - 1, 0x5A5, 0x2C9, 0x7FE):
        cw = H.encode(enc, d)
        assert H.decode(dec, cw) == d
        for b in range(16):
            assert H.decode(dec, cw ^ (1 << b)) == d, (d, b)


def test_odd_parity_path_is_distinct_and_real():
    # an odd-parity spec must invert each parity bit relative to even — proves the
    # parity-polarity code path is live, not dead.
    even = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
    odd = H.HammingSpec(4, 3, 8, True, False, "encoder", False, False)
    # for some data word the codewords differ in the parity positions
    assert any(H.encode(even, d) != H.encode(odd, d) for d in range(16))
    # and the odd decoder still round-trips its own odd encoder under single error
    odd_dec = H.HammingSpec(4, 3, 8, True, False, "decoder", False, False)
    for d in range(16):
        cw = H.encode(odd, d)
        assert H.decode(odd_dec, cw) == d
        for b in range(8):
            assert H.decode(odd_dec, cw ^ (1 << b)) == d, (d, b)


# --------------------------------------------------------------------------- #
# solve() end-to-end emit
# --------------------------------------------------------------------------- #
def test_solve_emits_encoder():
    rtl = H.solve(_record(_ENC_PROMPT, "hamming_code_tx_for_4bit"))
    assert rtl is not None
    assert "module hamming_code_tx_for_4bit" in rtl
    assert "data_out[0] = 1'b0" in rtl


def test_solve_emits_decoder():
    rtl = H.solve(_record(_DEC_PROMPT, "hamming_code_receiver", in_w=8, out_w=4))
    assert rtl is not None
    assert "module hamming_code_receiver" in rtl
    assert "err_pos" in rtl


def test_solve_emits_parameterized_forms():
    enc = H.solve(_record(_PARAM_ENC_PROMPT, "hamming_tx",
                          params=["DATA_WIDTH", "PARITY_BIT"]))
    dec = H.solve(_record(_PARAM_DEC_PROMPT, "hamming_rx", in_w=8, out_w=4,
                          params=["DATA_WIDTH", "PARITY_BIT", "ENCODED_DATA"],
                          tb_name="rx_test"))
    assert enc is not None and "parameter DATA_WIDTH" in enc
    assert dec is not None and "parameter DATA_WIDTH" in dec


# --------------------------------------------------------------------------- #
# §4.05 / NO-CHEAT NEGATIVES — each MUST SKIP (None)
# --------------------------------------------------------------------------- #
def test_skip_foreign_ecc_reed_solomon():
    p = _ENC_PROMPT.replace("Hamming code", "Reed-Solomon code")
    assert H.parse_hamming_spec(p, "rs_enc") is None


def test_skip_foreign_ecc_bch_and_crc():
    for bad in ("BCH", "CRC", "convolutional", "LDPC"):
        p = _ENC_PROMPT + f"\nThis uses a {bad} algorithm.\n"
        assert H.parse_hamming_spec(p, "x") is None, bad


def test_skip_parity_convention_not_stated():
    p = _ENC_PROMPT.replace("even parity", "parity")
    assert H.parse_hamming_spec(p, "x") is None


def test_skip_contradictory_parity_convention():
    p = _ENC_PROMPT + "\nThe design uses odd parity for all bits.\n"
    assert H.parse_hamming_spec(p, "x") is None


def test_skip_layout_not_powers_of_two():
    p = _ENC_PROMPT.replace("powers of 2", "arbitrary fixed").replace(
        "(positions 1, 2, and 4)", "")
    # also strip the residual "powers of two" mention path
    p = p.replace("power", "place")
    assert H.parse_hamming_spec(p, "x") is None


def test_skip_redundant_bit_not_stated():
    p = _ENC_PROMPT.replace("redundant bit", "filler value").replace(
        "An extra redundant bit is added to pad the output 8 bits.", "")
    assert H.parse_hamming_spec(p, "x") is None


def test_skip_stated_parity_contradicts_formula():
    # 4 data bits with a claimed 5 parity bits violates the minimum-p formula.
    p = _ENC_PROMPT.replace("3 parity bits are required", "5 parity bits are required")
    assert H.parse_hamming_spec(p, "x") is None


def test_skip_composite_split_top():
    p = textwrap.dedent("""\
        Complete the partial Hamming transmitter hamming_tx. The input data_in is
        split into multiple parts processed by multiple instances of t_hamming_tx,
        each encoding a PART_WIDTH segment with parity bits using even parity at
        powers of two with a redundant bit. The encoded outputs are concatenated
        to form data_out. NUM_MODULES = DATA_WIDTH / PART_WIDTH; TOTAL_ENCODED =
        ENCODED_DATA * NUM_MODULES.
    """)
    assert H.parse_hamming_spec(p, "hamming_tx") is None
    assert H.solve(_record(p, "hamming_tx")) is None


def test_skip_non_hamming_prompt():
    assert H.solve(_record("Design a 4-bit ripple-carry adder.", "adder")) is None
    assert H.parse_hamming_spec("Design a parity generator.", "x") is None


# --------------------------------------------------------------------------- #
# CHIP-AGNOSTIC — a renamed copy solves identically and stays correct
# --------------------------------------------------------------------------- #
def test_chip_agnostic_rename_encoder():
    base = H.solve(_record(_ENC_PROMPT, "hamming_code_tx_for_4bit"))
    renamed = H.solve(_record(_ENC_PROMPT.replace("transmitter", "transmitter block"),
                              "my_custom_ecc_block_xyz"))
    assert base is not None and renamed is not None
    assert "module my_custom_ecc_block_xyz" in renamed
    # the body logic (the XOR coverage) is identical modulo the module name: strip
    # the `module <name>` token from each and the remainder must match exactly.
    import re as _re
    base_body = _re.sub(r"\bmodule\s+\w+", "module NAME", base)
    ren_body = _re.sub(r"\bmodule\s+\w+", "module NAME", renamed)
    assert base_body == ren_body


def test_chip_agnostic_solver_keys_on_semantics_only():
    # the same prose under three unrelated design names must all PARSE the same
    # geometry — the solver never keys on a name.
    for name in ("foo_bar", "weird_name_123", "Z9"):
        spec = H.parse_hamming_spec(_ENC_PROMPT, name)
        assert spec is not None and (spec.k, spec.p, spec.n) == (4, 3, 8)


# --------------------------------------------------------------------------- #
# iverilog functional verification (GATED on the iverilog binary)
# --------------------------------------------------------------------------- #
def _iverilog_run(sv: str, tb: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "dut.sv").write_text(sv)
        (dp / "tb.v").write_text(tb)
        c = subprocess.run(["iverilog", "-g2012", "-o", str(dp / "a.out"),
                            str(dp / "dut.sv"), str(dp / "tb.v")],
                           capture_output=True, text=True)
        assert c.returncode == 0, c.stderr
        r = subprocess.run(["vvp", str(dp / "a.out")], capture_output=True, text=True)
        return r.stdout


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_iverilog_encoder_matches_golden():
    rtl = H.solve(_record(_ENC_PROMPT, "hamming_code_tx_for_4bit"))
    spec = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
    checks = "\n".join(
        f'    data_in=4\'d{d}; #1; if(data_out!==8\'d{H.encode(spec,d)}) '
        f'begin errs=errs+1; end' for d in range(16))
    tb = (f"module tb; reg [3:0] data_in; wire [7:0] data_out; integer errs=0;\n"
          f"hamming_code_tx_for_4bit dut(.data_in(data_in),.data_out(data_out));\n"
          f"initial begin\n{checks}\n"
          f'  if(errs==0) $display("ENC_ALL_PASS"); else $display("ENC_ERRS=%0d",errs);\n'
          f"  $finish; end endmodule")
    assert "ENC_ALL_PASS" in _iverilog_run(rtl, tb)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_iverilog_decoder_corrects_every_single_bit_error():
    rtl = H.solve(_record(_DEC_PROMPT, "hamming_code_receiver", in_w=8, out_w=4))
    enc = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
    lines = []
    for d in range(16):
        cw = H.encode(enc, d)
        for b in range(8):
            inj = cw ^ (1 << b)
            lines.append(f'    data_in=8\'d{inj}; #1; if(data_out!==4\'d{d}) '
                         f'begin errs=errs+1; end')
        lines.append(f'    data_in=8\'d{cw}; #1; if(data_out!==4\'d{d}) '
                     f'begin errs=errs+1; end')
    checks = "\n".join(lines)
    tb = (f"module tb; reg [7:0] data_in; wire [3:0] data_out; integer errs=0;\n"
          f"hamming_code_receiver dut(.data_in(data_in),.data_out(data_out));\n"
          f"initial begin\n{checks}\n"
          f'  if(errs==0) $display("DEC_ALL_PASS"); else $display("DEC_ERRS=%0d",errs);\n'
          f"  $finish; end endmodule")
    assert "DEC_ALL_PASS" in _iverilog_run(rtl, tb)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog/vvp not installed")
def test_iverilog_parameterized_decoder_second_geometry():
    # DATA_WIDTH=11 -> Hamming(15,11). Proves the parameterized RTL is general.
    spec = H.HammingSpec(11, 4, 16, True, True, "decoder", True, False)
    rtl = H.emit_decoder_rtl(spec, "hdec", "data_in", "data_out", True)
    enc = H.HammingSpec(11, 4, 16, True, True, "encoder", True, False)
    lines = []
    for d in (0, 1, (1 << 11) - 1, 0x5A5, 0x2C9):
        cw = H.encode(enc, d)
        for b in range(16):
            inj = cw ^ (1 << b)
            lines.append(f'    data_in=16\'d{inj}; #1; if(data_out!==11\'d{d}) '
                         f'begin errs=errs+1; end')
    checks = "\n".join(lines)
    tb = (f"module tb; reg [15:0] data_in; wire [10:0] data_out; integer errs=0;\n"
          f"hdec #(.DATA_WIDTH(11),.PARITY_BIT(4)) dut(.data_in(data_in),.data_out(data_out));\n"
          f"initial begin\n{checks}\n"
          f'  if(errs==0) $display("PDEC_PASS"); else $display("PDEC_ERR=%0d",errs);\n'
          f"  $finish; end endmodule")
    assert "PDEC_PASS" in _iverilog_run(rtl, tb)


# --------------------------------------------------------------------------- #
# real-dataset compliance floor (GATED on the dataset being present).
#
# Under CVDP compliance the model sees ONLY `input.prompt` + `input.context` — the
# cocotb harness / `.env` TOPLEVEL are OFF-LIMITS oracle. So a real record solves
# iff its module NAME and its port INTERFACE are BOTH recoverable from the prompt:
#   * hamming_code_tx_and_rx_0003 — a (7,4) receiver that STATES its name
#     (`hamming_code_receiver`) and a bracketed `data_in[7:0]` / `data_out[3:0]`
#     interface in the prompt -> SOLVES, and the emitted decoder is FUNCTIONALLY
#     correct (corrects every single-bit error).
#   * hamming_code_tx_and_rx_0013 — a COMPOSITE split-and-concatenate tx/rx top
#     -> §4.05 SKIP (None).
#   * the remaining hamming records DO NOT state their module name and/or port
#     interface in the prompt (only in the harness), so under compliance they are
#     HONEST None — an interface-extraction floor, NOT a solver bug, and NEVER
#     recovered by peeking at the OFF-LIMITS harness.
# The test asserts the SOLVABLE record emits correct RTL and every other record is
# None FOR A DEMONSTRATED, PROMPT-VISIBLE REASON (missing name/interface, or the
# §4.05 composite guard) — never a count the compliant extractor cannot meet.
# --------------------------------------------------------------------------- #
_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")

_RID_SOLVABLE = "cvdp_copilot_hamming_code_tx_and_rx_0003"
_RID_COMPOSITE = "cvdp_copilot_hamming_code_tx_and_rx_0013"
_RID_FLOOR = (
    "cvdp_copilot_hamming_code_tx_and_rx_0001",
    "cvdp_copilot_hamming_code_tx_and_rx_0009",
    "cvdp_copilot_hamming_code_tx_and_rx_0011",
)


@pytest.mark.skipif(not _DATASET.exists(), reason="CVDP dataset not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_dataset_hamming_records():
    import json
    recs = {r["id"]: r for r in (json.loads(l) for l in _DATASET.open())}

    # POSITIVE — the prompt-derivable (7,4) receiver solves AND emits a correct
    # single-error-correcting decoder (never a harness/golden peek).
    if _RID_SOLVABLE in recs:
        rec = recs[_RID_SOLVABLE]
        rtl = H.solve(rec)
        assert rtl is not None, (
            f"{_RID_SOLVABLE} states its name + a bracketed interface in the prompt "
            f"-> must solve compliantly")
        assert "module hamming_code_receiver" in rtl
        assert "err_pos" in rtl
        # functional proof (gated on iverilog): the emitted (7,4) decoder corrects
        # EVERY single-bit error in EVERY codeword.
        if _HAS_IVERILOG:
            enc = H.HammingSpec(4, 3, 8, True, True, "encoder", False, False)
            lines = []
            for d in range(16):
                cw = H.encode(enc, d)
                for b in range(8):
                    inj = cw ^ (1 << b)
                    lines.append(f'    data_in=8\'d{inj}; #1; if(data_out!==4\'d{d}) '
                                 f'begin errs=errs+1; end')
                lines.append(f'    data_in=8\'d{cw}; #1; if(data_out!==4\'d{d}) '
                             f'begin errs=errs+1; end')
            checks = "\n".join(lines)
            tb = (f"module tb; reg [7:0] data_in; wire [3:0] data_out; integer errs=0;\n"
                  f"hamming_code_receiver dut(.data_in(data_in),.data_out(data_out));\n"
                  f"initial begin\n{checks}\n"
                  f'  if(errs==0) $display("DEC_ALL_PASS"); else $display("DEC_ERRS=%0d",errs);\n'
                  f"  $finish; end endmodule")
            assert "DEC_ALL_PASS" in _iverilog_run(rtl, tb)

    # §4.05 SKIP — the composite split-and-concatenate top is None.
    if _RID_COMPOSITE in recs:
        assert H.solve(recs[_RID_COMPOSITE]) is None

    # HONEST COMPLIANCE FLOOR — each remaining record is None BECAUSE its module
    # name and/or its port interface is not stated in the prompt/context (only in
    # the OFF-LIMITS harness). We PROVE the reason, then require the honest None.
    for rid in _RID_FLOOR:
        if rid not in recs:
            continue
        rec = recs[rid]
        top = CB.toplevel_name(rec)
        prompt = (rec.get("input") or {}).get("prompt") or ""
        spec = H.parse_hamming_spec(prompt, top)
        iface = CB.extract_interface(rec, top) if top else None
        # the record is genuinely NOT prompt-solvable: either the name is not
        # recoverable, the geometry does not pin, or the interface does not parse.
        assert top is None or spec is None or iface is None, (
            f"{rid} appears prompt-solvable ({top=}, spec={spec is not None}, "
            f"iface={iface is not None}) but the test expects a floor — re-check "
            f"whether the compliant solver should now emit for it")
        assert H.solve(rec) is None
