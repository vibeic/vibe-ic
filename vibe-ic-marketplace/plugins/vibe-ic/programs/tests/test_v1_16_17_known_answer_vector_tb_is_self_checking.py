"""The expected value is a comparison, not a comment.

`testbench_gen.emit_unit_tb` wrote a case's expected value into a `//` line and
told a human to add the compare. This emitter drives the vector's typed inputs
onto the DUT's own ports, compares the sampled outputs against a typed literal,
increments `errors` and ends `$fatal(1)`.

Fail-closed is the load-bearing property: a vector whose fields do not bind to
ports of this DUT at the value's own width emits NOTHING, so a case nobody can
drive still fails Step 4 honestly instead of getting a testbench that prints a
PASS it never checked.
"""
import shutil
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

DIGEST = ("ba7816bf8f01cfea414140de5dae2223"
          "b00361a396177a9cb410ff61f20015ad")
CASE = {
    "name": "kav_sha256_abc",
    "kind": "known_answer_vector",
    "algorithm": "sha2",
    "inputs": {"message": "616263"},
    "expected_outputs": {"digest": DIGEST},
    "parameters": {"digest_len": 256},
    "citation": "FIPS-180-4 SHA-256 one-block example",
    "source": "named_public_standard",
    "evidence": "FIPS-180-4",
    "transport": {"kind": "port_mapped"},
}
# (DIRECTION, WIDTH, NAME) — the order `testbench_gen.resolve_dut` yields and
# `_classify` reads. This fixture had it as (name, width, direction), which is
# why every test here passed while every REAL port surface bound nothing.
PORTS = [("input", "", "clk"), ("input", "", "rst_n"),
         ("input", "[23:0]", "message"), ("output", "[255:0]", "digest")]

DUT = """module sha_core(input clk, input rst_n, input [23:0] message,
                output [255:0] digest);
  assign digest = 256'h%s;
endmodule
"""


def _emit(case=None, ports=None):
    import known_answer_vector_tb_gen as T
    return T.emit_case_oracle_from_ports(case or CASE, "sha_core",
                                         ports or PORTS)


def test_the_expected_value_is_a_comparison_not_a_comment():
    """The load-bearing red."""
    text, why = _emit()
    assert text, why
    body = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
    joined = "\n".join(body)
    assert f"256'h{DIGEST}" in joined, "the expected value is not a literal"
    assert "errors = errors + 1;" in joined
    assert "$fatal(1);" in joined
    assert "!==" in joined, "nothing is compared"
    # and the DUT is instantiated live, not stubbed
    assert "sha_core dut (" in joined


def test_a_vector_that_does_not_bind_emits_nothing():
    """Over-reach control: partial binding is the failure mode that would
    compare a value against a port the TB never drove."""
    no_output = [p for p in PORTS if p[2] != "digest"]
    text, why = _emit(ports=no_output)
    assert text is None
    assert "binds to no output port" in why, why
    wrong_width = [("input", "", "clk"), ("input", "[23:0]", "message"),
                   ("output", "[127:0]", "digest")]
    text2, why2 = _emit(ports=wrong_width)
    assert text2 is None, "a 256-bit vector must not drive a 128-bit port"
    assert "128" not in (text2 or ""), why2


def test_a_prose_expected_never_reaches_the_emitter():
    prose = dict(CASE, expected_outputs={"digest": "the SHA-256 of the block"})
    text, why = _emit(case=prose)
    assert text is None
    assert why, why


def test_perturbing_one_byte_turns_the_testbench_red(tmp_path):
    """The acceptance control. A correct DUT exits 0; one byte changed in the
    DUT's output makes the simulator exit non-zero.

    Skipped only when no simulator is on PATH — and the skip is loud, because a
    green that never ran a simulator would be exactly the kind of evidence this
    capture exists to remove."""
    import pytest
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not (iverilog and vvp):
        pytest.skip("NOT MEASURED HERE: no iverilog/vvp on PATH — this control "
                    "was measured in the container; see the commit message")
    text, why = _emit()
    assert text, why
    (tmp_path / "tb.v").write_text(text)
    results = {}
    for tag, digest in (("good", DIGEST), ("bad", DIGEST[:-1] + "e")):
        (tmp_path / "dut.v").write_text(DUT % digest)
        subprocess.run([iverilog, "-g2012", "-o", "sim.vvp", "tb.v", "dut.v"],
                       cwd=tmp_path, check=True, capture_output=True)
        r = subprocess.run([vvp, "sim.vvp"], cwd=tmp_path,
                           capture_output=True, text=True)
        results[tag] = (r.returncode, r.stdout)
    assert results["good"][0] == 0, results["good"]
    assert "PASS" in results["good"][1]
    assert results["bad"][0] != 0, results["bad"]
    assert "FAIL" in results["bad"][1]
