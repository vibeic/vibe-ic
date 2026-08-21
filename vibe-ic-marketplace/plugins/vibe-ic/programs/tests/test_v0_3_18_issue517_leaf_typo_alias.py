"""v0.3.18 — #517: promote the #506 misspelled-leaf alias-wrapper from SKILL
PROSE to a DETERMINISTIC PROGRAM so it fires every time, not only when a fresh
clean-room author remembers the lesson.

A leaf module name that is a probable misspelling of a canonical hardware term
(`substractor`→`subtractor`, `multipler`→`multiplier`) must auto-emit a thin
canonical-spelling alias wrapper so the design elaborates whichever spelling a
hidden testbench instantiates. Corpus-sweep: a correct leaf, a leaf far from any
term, an ambiguous leaf, and short abbreviations must NOT false-fire.

chip-AGNOSTIC: only generic hardware-term roots are baked in; no chip literal.
"""
import shutil
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import leaf_typo_alias_emit as L  # noqa: E402


# ── detection: positive (typo) cases ────────────────────────────────────

def test_detect_whole_name_typos():
    assert L.detect_leaf_typo("substractor") == "subtractor"
    assert L.detect_leaf_typo("multipler") == "multiplier"
    assert L.detect_leaf_typo("accumulater") == "accumulator"
    assert L.detect_leaf_typo("comparater") == "comparator"


def test_detect_token_typo_in_compound():
    # exactly one token is a typo → corrected, other tokens preserved.
    assert L.detect_leaf_typo("fast_multipler") == "fast_multiplier"
    assert L.detect_leaf_typo("pipelined_substractor") == "pipelined_subtractor"


# ── detection: corpus-sweep — must NOT false-fire ───────────────────────

def test_correct_canonical_leaf_does_not_fire():
    for good in ("counter", "multiplier", "divider", "register", "shifter",
                 "decoder", "fast_multiplier", "pipelined_subtractor"):
        assert L.detect_leaf_typo(good) is None, good


def test_far_and_short_leaves_do_not_fire():
    # novel / unrelated names and short abbreviations stay untouched.
    for novel in ("my_block", "fifo", "alu", "mux", "ram", "addr", "spi_core",
                  "frobnicator", "widget", "top", "dut", "uart_tx"):
        assert L.detect_leaf_typo(novel) is None, novel


def test_legitimate_english_word_forms_do_not_fire():
    # ADVERSARIAL-REVIEW REGRESSION (#517): inflected real words sit at
    # edit-distance 1 from canonical -er/-or terms but are NOT typos — they are
    # ordinary RTL signal/module names (past-tense, plural, gerund). None may
    # be aliased.
    legit = [
        "shifted",     # vs shifter   (d1, -ed)
        "encoded",     # vs encoder   (d1, -ed)
        "decoded",     # vs decoder   (d1, -ed)
        "scheduled",   # vs scheduler (d1, -ed)
        "counters",    # vs counter   (d1, plural)
        "registers",   # vs register  (d1, plural)
        "decoders",    # plural
        "encoders",    # plural
        "shifting",    # gerund
        "counting",    # gerund
        "recorder",    # real word, d2 from decoder/encoder
        "resister",    # real word, d1 from register
        "reminder",    # real word
    ]
    for w in legit:
        assert L.detect_leaf_typo(w) is None, f"false-fire on legit word {w!r}"


def test_distance_two_typos_are_not_auto_aliased():
    # honest limit: a distance-2 (transposition / double) typo is NOT rescued
    # — the single-edit restriction trades that coverage for false-fire safety.
    # `recorder` (d2 from decoder) must NOT alias to a HW term.
    assert L.detect_leaf_typo("recorder") is None


def test_british_spelling_variants_do_not_fire():
    # RE-REVIEW REGRESSION (#517 round-2): British -iser spelling is an
    # intentional variant, not a typo — handled as a CLASS (s↔z), not one word.
    for brit in ("normaliser", "serialiser", "deserialiser"):
        assert L.detect_leaf_typo(brit) is None, brit


def test_real_agent_noun_collisions_do_not_fire():
    # RE-REVIEW REGRESSION (#517 round-2): real verb+er agent nouns at d1.
    for word in ("diviner", "deceiver", "resister"):
        assert L.detect_leaf_typo(word) is None, word


def test_emit_skips_when_canonical_module_already_exists(tmp_path):
    # residual-harm mitigation: if the design already defines `module divider`,
    # a leaf that merely LOOKS like a divider-typo must NOT emit a duplicate
    # module (would be a compile error). Here `divder` is a real d1 typo of
    # `divider`, but a divider module already exists → skip the emit.
    rtl = tmp_path / "design.v"
    rtl.write_text(
        "module divder (input clk, output y);\n  assign y = clk;\nendmodule\n")
    (tmp_path / "divider.v").write_text(
        "module divider (input clk, output y);\n  assign y = ~clk;\nendmodule\n")
    assert L.detect_leaf_typo("divder") == "divider"   # detector still fires
    rc = L.main(["--rtl", str(rtl), "--leaf", "divder"])
    assert rc == 0
    # but no NEW divider.v wrapper clobbered/duplicated the existing module:
    # the pre-existing divider.v is untouched (still the real module).
    assert "assign y = ~clk" in (tmp_path / "divider.v").read_text()


def test_two_typo_tokens_is_ambiguous_no_fire():
    # more than one typo token → do not guess.
    assert L.detect_leaf_typo("substractor_multipler") is None


def test_empty_and_garbage():
    assert L.detect_leaf_typo("") is None
    assert L.detect_leaf_typo("   ") is None


# ── emit + elaborate BOTH spellings ─────────────────────────────────────

def _leaf_rtl(leaf: str) -> str:
    return (f"module {leaf} (\n"
            f"    input clk,\n"
            f"    input [7:0] a,\n"
            f"    input [7:0] b,\n"
            f"    output [7:0] y\n"
            f");\n"
            f"    assign y = a - b;\n"
            f"endmodule\n")


def test_emit_alias_and_both_spellings_elaborate(tmp_path):
    leaf = "substractor"
    canonical = L.detect_leaf_typo(leaf)
    assert canonical == "subtractor"
    rtl = tmp_path / "design.v"
    rtl.write_text(_leaf_rtl(leaf))
    ports = L.parse_module_ports(rtl.read_text(), leaf)
    assert [p[2] for p in ports] == ["clk", "a", "b", "y"]
    wrapper = L.emit_alias_wrapper(leaf, canonical, ports)
    # structural: wrapper module is the canonical name, instantiates the leaf,
    # passes every port 1:1.
    assert f"module {canonical} (" in wrapper
    assert f"{leaf} u_{leaf} (" in wrapper
    for nm in ("clk", "a", "b", "y"):
        assert f".{nm}({nm})" in wrapper
    wrap_f = tmp_path / f"{canonical}.v"
    wrap_f.write_text(wrapper)

    iv = shutil.which("iverilog")
    if not iv:
        import pytest
        pytest.skip("iverilog not on this host — structural checks only")
    # BOTH spellings must elaborate as a top.
    for top in (leaf, canonical):
        r = subprocess.run(
            [iv, "-g2012", "-s", top, "-o", str(tmp_path / f"{top}.out"),
             str(rtl), str(wrap_f)],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{top} failed: {r.stderr}"


def test_main_no_typo_is_success_no_wrapper(tmp_path):
    rtl = tmp_path / "d.v"
    rtl.write_text(_leaf_rtl("counter"))
    rc = L.main(["--rtl", str(rtl), "--leaf", "counter"])
    assert rc == 0
    assert not (tmp_path / "counter.v").exists() or \
        (tmp_path / "d.v").read_text()  # no canonical alias emitted
    # no other .v created besides the input
    assert sorted(p.name for p in tmp_path.glob("*.v")) == ["d.v"]


def test_main_typo_writes_wrapper(tmp_path):
    rtl = tmp_path / "design.v"
    rtl.write_text(_leaf_rtl("substractor"))
    rc = L.main(["--rtl", str(rtl), "--leaf", "substractor"])
    assert rc == 0
    assert (tmp_path / "subtractor.v").is_file()


# ── REOPEN REGRESSION (#517): parameterized ANSI module (fixed_point target) ──

def _param_leaf_rtl(leaf: str) -> str:
    return (f"module {leaf} #(parameter N = 16) (\n"
            f"    input wire [N-1:0] a,\n"
            f"    input wire [N-1:0] b,\n"
            f"    output wire [N-1:0] c\n"
            f");\n"
            f"    assign c = a - b;\n"
            f"endmodule\n")


def test_parameterized_module_parses_and_emits(tmp_path):
    # the prior regex `module <name> (` missed `module <name> #(...) (` →
    # parsed 0 ports → emit silently failed. Now ports parse + wrapper emits.
    rtl = tmp_path / "design.v"
    rtl.write_text(_param_leaf_rtl("substractor"))
    ports = L.parse_module_ports(rtl.read_text(), "substractor")
    assert [p[2] for p in ports] == ["a", "b", "c"]
    pblock, pnames = L.parse_module_params(rtl.read_text(), "substractor")
    assert pblock is not None and "parameter N" in pblock
    assert pnames == ["N"]
    rc = L.main(["--rtl", str(rtl), "--leaf", "substractor"])
    assert rc == 0
    assert (tmp_path / "subtractor.v").is_file()


def test_parameterized_wrapper_elaborates_both_spellings(tmp_path):
    # the wrapper of a parameterized leaf must INHERIT the #(...) block and
    # forward the parameter, else its `[N-1:0]` ports reference an undefined N.
    rtl = tmp_path / "design.v"
    rtl.write_text(_param_leaf_rtl("substractor"))
    L.main(["--rtl", str(rtl), "--leaf", "substractor"])
    wrap = (tmp_path / "subtractor.v")
    assert wrap.is_file()
    wtxt = wrap.read_text()
    assert "module subtractor #(" in wtxt and "parameter N" in wtxt
    assert "substractor #(.N(N)) u_substractor" in wtxt
    iv = shutil.which("iverilog")
    if not iv:
        import pytest
        pytest.skip("iverilog not on this host")
    for top in ("substractor", "subtractor"):
        r = subprocess.run(
            [iv, "-g2012", "-s", top, "-o", str(tmp_path / f"{top}.out"),
             str(rtl), str(wrap)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{top}: {r.stderr}"


def test_wired_into_phase2_runner(tmp_path):
    # REOPEN REGRESSION (#517): the program must be ACTUALLY CALLED by the
    # runner (it was dormant — referenced only by skill prose). The phase2
    # step sweeps rtl/ and auto-emits the alias.
    import sys as _sys
    _sys.path.insert(0, str(PROGRAMS))
    import design_one_shot_runner as P
    import _path_layout as _pl
    rtl_dir = _pl.rtl_dir(tmp_path)
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "substractor.v").write_text(_param_leaf_rtl("substractor"))
    r = P.step_leaf_typo_aliases(tmp_path)
    assert r.status == "PASS", (r.status, r.detail)
    assert (rtl_dir / "subtractor.v").is_file()
    # idempotent + collision-safe: re-run emits nothing new.
    r2 = P.step_leaf_typo_aliases(tmp_path)
    assert r2.status == "SKIP"


def test_step_skips_when_no_typo(tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(PROGRAMS))
    import design_one_shot_runner as P
    import _path_layout as _pl
    rtl_dir = _pl.rtl_dir(tmp_path)
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "counter.v").write_text(_leaf_rtl("counter"))
    r = P.step_leaf_typo_aliases(tmp_path)
    assert r.status == "SKIP"
    assert not (rtl_dir / "subtractor.v").exists()


# ── REOPEN ROUND-3 REGRESSIONS (#517) ───────────────────────────────────

def test_compact_verilog_syntax_parses():
    # no spaces after direction / around widths — valid Verilog.
    rtl = ("module substractor#(parameter N=16)"
           "(input[N-1:0]a,output[N-1:0]y);assign y=~a;endmodule")
    ports = L.parse_module_ports(rtl, "substractor")
    assert [p[2] for p in ports] == ["a", "y"]
    assert L.detect_leaf_typo("substractor") == "subtractor"


def test_net_type_prefix_not_swallowed_into_port_name():
    # `input wirefoo` is a port named `wirefoo`, NOT type `wire` + port `foo`.
    ports = L.parse_module_ports(
        "module m (input wirefoo, output regbar);endmodule", "m")
    assert [p[2] for p in ports] == ["wirefoo", "regbar"]


def test_string_param_with_paren_does_not_unbalance():
    # a '(' inside a string parameter default must not break the paren scan.
    rtl = ('module substractor #(parameter TAG = "err(code") '
           '(input a, output b);endmodule')
    ports = L.parse_module_ports(rtl, "substractor")
    assert [p[2] for p in ports] == ["a", "b"]


def test_signed_and_multiple_qualifiers():
    # `input signed [7:0] a` and `input wire signed [7:0] a` — the sign/net-type
    # qualifiers must not be swallowed as the port name.
    ports = L.parse_module_ports(
        "module m(input signed [7:0] a, input wire signed [3:0] b,"
        " output reg [7:0] y);endmodule", "m")
    assert [p[2] for p in ports] == ["a", "b", "y"]
