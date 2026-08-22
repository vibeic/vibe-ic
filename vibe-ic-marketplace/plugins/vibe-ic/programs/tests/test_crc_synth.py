"""test_crc_synth.py — the DETERMINISTIC CVDP CRC-family solver.

crc_synth.solve(record) recognizes a stand-alone CRC generator/checker,
PARSES the stated convention (width / polynomial / init / reflect-in / reflect-out
/ final-XOR), and emits the deterministic shift-register CRC datapath (module
named per the harness TOPLEVEL, ports from the shipped cvdp_atomic_bridge).

POSITIVE: a real-shaped CRC record (width=8, POLY=0xAA, init=0, no reflect, the
serial MSB-first `crc_reg=(crc_reg<<1)^POLY if MSB^data_in[i]` algorithm) PARSES,
EMITS, and the emit is FUNCTIONALLY correct — its crc_out(0x5123) == 0x42 (the
prompt's own worked example), both in Python (`python_crc`) and via iverilog when
the binary is present.

§4.05 / NO-CHEAT NEGATIVES (each MUST SKIP -> None — a wrong CRC is far worse than
an honest skip):
  * no polynomial stated                          -> SKIP (never guess a poly);
  * no width stated / not derivable               -> SKIP (never guess a width);
  * reflect MENTIONED but not pinned to a value   -> SKIP (ambiguous convention);
  * the CRC is one sub-module of a COMPOSITE top  -> SKIP (ECC/SIPO/FSM co-resident);
  * a non-CRC prompt                              -> SKIP.

CHIP-AGNOSTIC: the solver keys only on CRC semantics, never on a design name. A
renamed copy of the positive solves identically; the guards fire on the SEMANTICS.

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

import crc_synth as C  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures — CVDP-COMPLIANT records (name + interface in input.prompt; harness
# .env + cocotb retained as OFF-LIMITS oracle the solver never reads)
# --------------------------------------------------------------------------- #
def _record(prompt: str, top: str = "crc_generator",
            in_sig: str = "data_in", out_sig: str = "crc_out") -> dict:
    """A CVDP-COMPLIANT record: the module NAME and the port INTERFACE both live in
    `input.prompt` — the ONLY model-visible surface. The harness `.env` TOPLEVEL and
    the cocotb testbench are RETAINED for shape fidelity but are OFF-LIMITS oracle the
    refactored `cvdp_atomic_bridge` never reads (name from prompt/context only,
    interface from a prompt `### Inputs:`/`### Outputs:` block, prose, or a
    test-case table — never from `dut.<sig>` or `.env`).

    (1) Guarantee the module name is STATED in the prompt so `toplevel_name` can
        recover it without the harness — prepend a `module `<top>`` designation when
        the prompt does not already name it (the CRC prompts already say
        "`crc_generator` module", so no prepend fires there).
    (2) Relocate the cocotb `dut.<in_sig>` / `dut.<out_sig>` port NAMES into a legal
        prompt-side `### Inputs:`/`### Outputs:` block. NAMES only — the port WIDTHS
        stay wherever the prompt prose already states them (e.g. `data_in [15:0]`,
        `crc_out [7:0]`), so no width is invented, merely a legal fact relocated.
    """
    if f"`{top}`" not in prompt:
        prompt = f"Design the Verilog module `{top}`.\n\n" + prompt
    if "### Inputs:" not in prompt:
        prompt = prompt + textwrap.dedent(f"""

            ### Inputs:
            - `{in_sig}`

            ### Outputs:
            - `{out_sig}`
        """)
    # OFF-LIMITS oracle harness (retained for record-shape fidelity; solver ignores).
    tb_py = textwrap.dedent(f"""\
        import cocotb
        @cocotb.test()
        async def t(dut):
            dut.{in_sig}.value = 0x5123
            await Timer(1)
            got = int(dut.{out_sig}.value)
    """)
    return {
        "input": {"prompt": prompt},
        "harness": {"files": {
            "src/.env": f"TOPLEVEL = {top}\nMODULE = test_crc\n",
            "src/test_crc.py": tb_py,
        }},
        "output": {"context": {f"rtl/{top}.sv": ""}},
    }


# A real-shaped, fully-stated, STAND-ALONE CRC generator (the sipo CRC sub-module's
# convention lifted into its own top): width 8, POLY 0xAA, init 0, MSB-first,
# no reflect, no final-XOR. The prompt cites the worked example 0x5123 -> 0x42.
_POS_PROMPT = textwrap.dedent("""\
    Design a `crc_generator` module that computes the CRC for a 16-bit input
    data_in [15:0] and produces an 8-bit crc_out [7:0].

    Parameters:
    - CRC_WIDTH: 8.
    - POLY: 8'b10101010.

    Behaviour: compute the CRC for data_in using the generator polynomial POLY.
    The crc_reg starts at 0 (when reset crc_out will be zero). For each input bit,
    MSB first:
        crc_reg = (crc_reg << 1) ^ POLY   if (crc_reg[MSB] ^ data_in[i])
        crc_reg = crc_reg << 1            otherwise

    Example: data_in = 16'h5123 -> crc_out = 8'b01000010 = 0x42
""")


# --------------------------------------------------------------------------- #
# spec parsing
# --------------------------------------------------------------------------- #
def test_parse_pos_spec():
    spec = C.parse_crc_spec(_POS_PROMPT)
    assert spec is not None
    assert spec.width == 8
    assert spec.poly == 0xAA
    assert spec.init == 0
    assert spec.reflect_in is False
    assert spec.reflect_out is False
    assert spec.xor_out == 0


def test_parse_poly_power_form():
    # x^16 + x^12 + x^5 + 1 -> CRC-16-CCITT generator 0x1021, degree 16.
    pp = C._parse_poly("generator polynomial x^16 + x^12 + x^5 + 1")
    assert pp is not None
    val, width = pp
    assert width == 16
    assert val == 0x1021


def test_parse_poly_hex_form():
    pp = C._parse_poly("polynomial 0x04C11DB7")
    assert pp is not None
    assert pp[0] == 0x04C11DB7


# --------------------------------------------------------------------------- #
# Python golden cross-check — the parsed poly/init reproduces the worked example
# --------------------------------------------------------------------------- #
def test_python_crc_matches_worked_example():
    spec = C.parse_crc_spec(_POS_PROMPT)
    assert spec is not None
    # the prompt's own iteration table: data_in=0x5123 (16-bit) -> 0x42
    assert C.python_crc(spec, 0x5123, 16) == 0x42
    # all-zero data -> init (0) shifted, no poly XORs -> 0
    assert C.python_crc(spec, 0x0000, 16) == 0x00


def test_python_crc_reflect_and_xor_paths_exercised():
    # a reflect-out + final-xor spec must produce a value distinct from the plain
    # one — proves the reflect/xor code paths are real, not dead. Use a data value
    # whose plain CRC is NOT a bit-palindrome so reflect-out is observably distinct.
    plain = C.CrcSpec(8, 0x07, 0xFF, False, False, 0)
    refl = C.CrcSpec(8, 0x07, 0xFF, False, True, 0)
    xored = C.CrcSpec(8, 0x07, 0xFF, False, False, 0xFF)
    base = C.python_crc(plain, 0x1234, 16)          # 0x26 (not a palindrome)
    assert C._reflect(base, 8) != base, "pick a non-palindrome base for this test"
    assert C.python_crc(refl, 0x1234, 16) == C._reflect(base, 8)
    assert C.python_crc(xored, 0x1234, 16) == (base ^ 0xFF) & 0xFF


# --------------------------------------------------------------------------- #
# POSITIVE solve + emit
# --------------------------------------------------------------------------- #
def test_positive_solve_emits_named_module():
    rtl = C.solve(_record(_POS_PROMPT, top="crc_generator"))
    assert rtl is not None
    assert "module crc_generator" in rtl
    assert "8'haa" in rtl.lower()          # the stated poly, low 8 bits
    assert "data_in" in rtl and "crc_out" in rtl


def test_chip_agnostic_rename_solves_identically():
    a = C.solve(_record(_POS_PROMPT, top="crc_generator"))
    # rename the top everywhere it appears (module name + .env TOPLEVEL).
    renamed_prompt = _POS_PROMPT.replace("crc_generator", "frame_check_unit")
    b = C.solve(_record(renamed_prompt, top="frame_check_unit"))
    assert a is not None and b is not None
    # the only textual difference is the module name; the datapath is identical.
    assert a.replace("crc_generator", "X") == b.replace("frame_check_unit", "X")


# --------------------------------------------------------------------------- #
# §4.05 / NO-CHEAT negatives — each MUST SKIP
# --------------------------------------------------------------------------- #
def test_skip_no_polynomial():
    # names CRC + width, but never states the polynomial -> never guess -> SKIP.
    p = textwrap.dedent("""\
        Design a `crc_generator` for a 16-bit input data_in [15:0] producing an
        8-bit crc_out [7:0]. CRC_WIDTH: 8. Compute the CRC of data_in.
    """)
    assert C.parse_crc_spec(p) is None
    assert C.solve(_record(p)) is None


def test_skip_no_width():
    # names CRC + cites a polynomial, but the polynomial token is an unsized
    # parameter name (POLY) with no numeric literal and no CRC width -> width not
    # derivable, poly not numeric -> SKIP (never guess a width).
    p = textwrap.dedent("""\
        Design a CRC generator `crc_generator`. data_in [15:0] -> crc_out. Use the
        generator polynomial POLY. The crc_reg is shifted left and XORed with POLY.
    """)
    assert C.parse_crc_spec(p) is None
    assert C.solve(_record(p)) is None


def test_skip_ambiguous_reflect():
    # reflect MENTIONED but not pinned to a definite value -> ambiguous -> SKIP.
    p = textwrap.dedent("""\
        Design a `crc_generator` for data_in [15:0] -> crc_out [7:0].
        CRC_WIDTH: 8. POLY: 8'b10101010. init = 0.
        The input bits may be reflected depending on the configuration; the CRC
        register starts at 0 and shifts left, XORing with POLY when the MSB is set.
    """)
    assert C.parse_crc_spec(p) is None
    assert C.solve(_record(p)) is None


def test_skip_composite_crc_submodule():
    # the CRC is ONE sub-module of a SIPO+ECC composite top -> not stand-alone.
    p = textwrap.dedent("""\
        Modify the `sipo_top` module to incorporate the crc generation. The design
        consists of 3 modules: serial_in_parallel_out_8bit (SIPO), onebit_ecc
        which generates hamming code and a syndrome, and crc_generator.
        CRC_WIDTH: 8. POLY: 8'b10101010. crc_reg starts at 0.
        data_in [15:0] -> crc_out [7:0].
    """)
    # spec itself parses (poly+width+init stated) but the COMPOSITE guard SKIPs.
    assert C.solve(_record(p, top="sipo_top")) is None


def test_skip_non_crc():
    p = "Design a 32-bit adder: sum = a + b + carry_in. a [31:0], b [31:0]."
    assert C.parse_crc_spec(p) is None
    assert C.solve(_record(p, top="adder")) is None


def test_width_derived_from_hex_poly():
    # 0x.. hex IS sized (its hex digits imply a width): a CRC with no explicit
    # CRC_WIDTH but a 2-hex-digit 0xAA polynomial derives width 8. Note the
    # prompt MUST mention "CRC" as a word (real CRC prompts always do) for the
    # solver to engage at all.
    p = textwrap.dedent("""\
        Design a CRC generator `crc_generator`. data_in [15:0] -> crc_out [7:0].
        The generator polynomial is 0xAA, init = 0. The crc_reg shifts left and
        XORs with the polynomial.
    """)
    spec = C.parse_crc_spec(p)
    # 0xAA implies width 8 -> spec resolves; this is the documented derive path.
    assert spec is not None and spec.width == 8 and spec.poly == 0xAA


# --------------------------------------------------------------------------- #
# iverilog functional check (gated) — emit compiles and matches the worked value
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("iverilog") is None or shutil.which("vvp") is None,
                    reason="iverilog/vvp not installed")
def test_iverilog_functional_table_check():
    rtl = C.solve(_record(_POS_PROMPT))
    assert rtl is not None
    tb = textwrap.dedent("""\
        module tb;
          reg [15:0] data_in; wire [7:0] crc_out;
          crc_generator dut(.data_in(data_in), .crc_out(crc_out));
          integer errors = 0;
          initial begin
            data_in = 16'h5123; #1;
            if (crc_out !== 8'h42) begin errors = errors + 1;
              $display("FAIL 5123 -> %h exp 42", crc_out); end
            data_in = 16'h0000; #1;
            if (crc_out !== 8'h00) begin errors = errors + 1;
              $display("FAIL 0000 -> %h exp 00", crc_out); end
            if (errors == 0) $display("ALL_PASS"); else $display("ERRORS=%0d", errors);
            $finish;
          end
        endmodule
    """)
    d = Path(tempfile.mkdtemp())
    (d / "dut.v").write_text(rtl)
    (d / "tb.v").write_text(tb)
    comp = subprocess.run(
        ["iverilog", "-g2012", "-o", str(d / "sim"), str(d / "dut.v"), str(d / "tb.v")],
        capture_output=True, text=True)
    assert comp.returncode == 0, f"compile failed:\n{comp.stderr}"
    run = subprocess.run(["vvp", str(d / "sim")], capture_output=True, text=True)
    assert "ALL_PASS" in run.stdout, f"TB did not pass:\n{run.stdout}\n{run.stderr}"


# --------------------------------------------------------------------------- #
# bad input
# --------------------------------------------------------------------------- #
def test_non_dict_and_empty():
    assert C.solve(None) is None
    assert C.solve({}) is None
    assert C.solve({"input": {"prompt": ""}}) is None


# ── polarity: a prompt retires a polynomial as readily as it states one ─────
#
# Found by a census of functions fed a `prompt`. A CRC built on the retired
# polynomial computes a different remainder and will not interoperate.

def _poly(prompt):
    import crc_synth as M
    return M._parse_poly(prompt)


def test_a_retired_polynomial_is_not_read_as_stated():
    assert _poly("The polynomial 0x04C11DB7 is no longer used.") is None


def test_the_live_polynomial_beside_a_retired_one_is_taken():
    """`finditer`, not `search`: a denied statement must not end the search, or
    a prompt that retires one polynomial and gives another yields nothing."""
    assert _poly("The polynomial 0x04C11DB7 is no longer used.\n"
                 "Use polynomial 0x1021.") == (0x1021, 16)


def test_a_plainly_stated_polynomial_is_still_read():
    """The control arm: a fix that read nothing would pass the rest."""
    assert _poly("The CRC polynomial is 0x04C11DB7.") == (0x04C11DB7, 32)


def test_a_retired_init_value_is_not_read_as_stated():
    """The polynomial was guarded first and its siblings were not -- two readers
    of one document disagreeing about a denial, in one file."""
    import crc_synth as M
    assert M._parse_init("The init value 0xFFFFFFFF is no longer used.\n"
                         "Use init = 0x0000.") == 0


def test_a_retired_reflect_setting_is_not_read_as_stated():
    import crc_synth as M
    assert M._parse_reflect_xor(
        "reflect_in = true is no longer used.\n"
        "reflect_in = false and reflect_out = false, xor_out = 0."
    ) == (False, False, 0)


def test_the_plainly_stated_convention_is_still_read():
    """The control arm for both siblings."""
    import crc_synth as M
    assert M._parse_init("init = 0xFFFFFFFF") == 0xFFFFFFFF
    assert M._parse_reflect_xor(
        "reflect_in = true and reflect_out = true, xor_out = 0xFFFFFFFF."
    ) == (True, True, 0xFFFFFFFF)
