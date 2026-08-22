"""Unit tests for `crosslayer_rewrite_equivalence.py`.

The gate's whole job is to reject a rewritten candidate that is not the
baseline. These tests pin the parts that decide that, and every "measured"
case below records a behaviour observed on a real Yosys run rather than an
assumption about what Yosys prints.
"""
import importlib
import json

mod = importlib.import_module("crosslayer_rewrite_equivalence")


class TestParseEvidence:
    def test_wellformed_citation(self):
        assert mod.parse_evidence("input/docs/L2.md:64") == {
            "path": "input/docs/L2.md", "line": 64}

    def test_no_citation_is_none(self):
        assert mod.parse_evidence(None) is None
        assert mod.parse_evidence("") is None

    def test_a_path_with_no_line_is_not_close_enough(self):
        # The entire value of the citation is that a reader can go and look at
        # that line, so there is deliberately no lenient parse.
        assert mod.parse_evidence("input/docs/L2.md") is None

    def test_a_line_that_is_not_a_number_is_refused(self):
        assert mod.parse_evidence("input/docs/L2.md:sixty-four") is None


class TestModulePorts:
    ANSI = """
module spm #(parameter size = 32) (
    input  wire            clk,
    input  wire            rst,
    input  wire [size-1:0] x,
    input  wire            y,
    output wire            p
);
endmodule
"""
    NON_ANSI = """
module m (a, b, q);
  input [7:0] a;
  input b;
  output q;
endmodule
"""

    def test_ansi_header(self):
        ports = mod.module_ports(self.ANSI, "spm")
        assert [n for _d, _r, n in ports] == ["clk", "rst", "x", "y", "p"]
        assert [d for d, _r, _n in ports].count("output") == 1

    def test_non_ansi_header(self):
        ports = mod.module_ports(self.NON_ANSI, "m")
        assert [(d, n) for d, _r, n in ports] == [
            ("input", "a"), ("input", "b"), ("output", "q")]

    def test_unknown_module_is_empty_not_a_guess(self):
        assert mod.module_ports(self.ANSI, "not_here") == []

    def test_params_are_captured(self):
        assert "size" in mod.module_params(self.ANSI, "spm")
        assert mod.param_names(mod.module_params(self.ANSI, "spm")) == ["size"]

    def test_a_module_without_params_has_no_param_header(self):
        assert mod.module_params(self.NON_ANSI, "m") == ""


class TestDelayWrapper:
    PORTS = [("input", "", "clk"), ("input", "", "rst"),
             ("input", "[size-1:0]", "x"), ("input", "", "y"),
             ("output", "", "p")]

    def test_measured_parameterised_range_needs_the_parameter_header(self):
        # MEASURED: a wrapper that copied `[size-1:0]` without the parameter was
        # rejected by the frontend ("Non-constant range in declaration"), which
        # turned the whole latency-offset mode into a silent 0-points-compared
        # NOT_MEASURED.
        v = mod.build_delay_wrapper("spm", self.PORTS, "spm", "spm__d1", 1,
                                    "clk", params_txt="parameter size = 32")
        assert "#(parameter size = 32)" in v
        assert "spm #(.size(size)) u_inner" in v
        assert "[size-1:0] x" in v          # a space, not `[size-1:0]x`

    def test_every_output_is_delayed_by_the_same_depth(self):
        ports = self.PORTS + [("output", "[3:0]", "q")]
        v = mod.build_delay_wrapper("m", ports, "m", "m__d2", 2, "clk")
        for name in ("p", "q"):
            assert f"{name}__d0" in v and f"{name}__d1" in v
            assert f"assign {name} = {name}__d1;" in v

    def test_measured_declared_reset_flushes_the_alignment_chain(self):
        # MEASURED: a +1-latency rewrite of a synchronous-reset design, aligned
        # by an UNRESET chain, was refuted at the reset edge and nowhere else.
        v = mod.build_delay_wrapper("spm", self.PORTS, "spm", "spm__d1", 1,
                                    "clk", reset="rst")
        assert "if (rst) begin" in v
        assert "p__d0 <= 0;" in v

    def test_active_low_reset_is_inverted(self):
        v = mod.build_delay_wrapper("spm", self.PORTS, "spm", "spm__d1", 1,
                                    "clk", reset="rst_n",
                                    reset_active_low=True)
        assert "if (!rst_n) begin" in v

    def test_no_reset_declared_means_no_reset_in_the_chain(self):
        v = mod.build_delay_wrapper("spm", self.PORTS, "spm", "spm__d1", 1,
                                    "clk")
        assert "if (" not in v


class TestEquivScript:
    def test_both_sides_get_the_identical_normalisation(self):
        s = mod.build_rewrite_equiv_script(["/a/base.v"], ["/a/cand.v"], "top")
        # Asymmetry is how a filter stops discriminating.
        for p in ("memory_map", "flatten", "async2sync", "opt_clean",
                  "splitnets -ports"):
            assert s.count(p) == 2, p

    def test_the_unbounded_proof_stages_are_all_present(self):
        s = mod.build_rewrite_equiv_script(["/a/base.v"], ["/a/cand.v"], "top")
        for p in ("equiv_make gold gate equiv", "equiv_struct", "equiv_simple",
                  "equiv_induct -seq 4", "equiv_induct -seq 16",
                  "equiv_induct -seq 64", "equiv_status"):
            assert p in s, p

    def test_refutation_script_pins_the_initial_state(self):
        # MEASURED: without -set-init-zero the solver "refutes" a correct
        # candidate by starting the two designs in different states.
        s = mod.build_refutation_script(["/a/base.v"], ["/a/cand.v"], "top", 12)
        assert "-set-init-zero" in s
        assert "sat -seq 12" in s
        assert "miter -equiv -flatten -make_assert" in s


class TestParseRefutation:
    def test_model_found_is_a_refutation(self):
        assert mod.parse_refutation(
            "SAT proof finished - model found: FAIL!") is True

    def test_no_model_within_the_bound_is_not_a_proof_and_not_a_refutation(self):
        assert mod.parse_refutation(
            "SAT proof finished - no model found: SUCCESS!") is False

    def test_a_run_that_said_neither_is_no_evidence_at_all(self):
        assert mod.parse_refutation("yosys crashed") is None
        assert mod.parse_refutation("") is None


class TestClassify:
    def test_all_points_proven_is_the_only_pass(self):
        st, rc, _ = mod.classify(
            {"total": 162, "proven": 162, "unproven": 0, "equivalent": True})
        assert (st, rc) == (mod.STATUS_PASS, 0)

    def test_zero_points_compared_is_NOT_MEASURED_never_a_pass(self):
        st, rc, why = mod.classify(
            {"total": 0, "proven": 0, "unproven": 0, "equivalent": True})
        assert (st, rc) == (mod.STATUS_NOT_MEASURED, 2)
        assert "ZERO points" in why

    def test_unproven_with_a_counterexample_is_a_measured_difference(self):
        st, rc, _ = mod.classify(
            {"total": 162, "proven": 131, "unproven": 31, "equivalent": False},
            refuted=True)
        assert (st, rc) == (mod.STATUS_FAIL, 1)

    def test_unproven_without_a_counterexample_is_not_reported_as_wrong(self):
        # "the engine could not decide" and "the design is wrong" are different
        # findings; both block, neither borrows the other's words.
        st, rc, why = mod.classify(
            {"total": 162, "proven": 131, "unproven": 31, "equivalent": False},
            refuted=False)
        assert (st, rc) == (mod.STATUS_NOT_PROVEN, 2)
        assert "NOT a report that it is wrong" in why

    def test_no_refutation_verdict_is_treated_as_no_evidence(self):
        st, rc, _ = mod.classify(
            {"total": 10, "proven": 9, "unproven": 1, "equivalent": False},
            refuted=None)
        assert (st, rc) == (mod.STATUS_NOT_PROVEN, 2)

    def test_points_proven_but_yosys_never_said_equivalent(self):
        st, rc, _ = mod.classify(
            {"total": 10, "proven": 10, "unproven": 0, "equivalent": False})
        assert (st, rc) == (mod.STATUS_NOT_MEASURED, 2)


class TestLatencyOffsetAuthorisation:
    def test_an_offset_with_no_evidence_is_refused_before_any_tool_runs(
            self, tmp_path):
        (tmp_path / "base").mkdir()
        (tmp_path / "cand").mkdir()
        rc = mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                       "--candidate-rtl-dir", "cand", "--top", "m",
                       "--latency-offset", "3",
                       "--json", "reports/re.json"])
        assert rc == 2
        rep = json.loads((tmp_path / "reports/re.json").read_text())
        assert rep["status"] == mod.STATUS_NOT_MEASURED
        assert "nobody authorised" in rep["explanation"]

    def test_an_evidence_citation_that_cannot_be_read_is_refused(self, tmp_path):
        (tmp_path / "base").mkdir()
        (tmp_path / "cand").mkdir()
        rc = mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                       "--candidate-rtl-dir", "cand", "--top", "m",
                       "--latency-offset", "1",
                       "--latency-free-evidence", "nowhere.md:3",
                       "--json", "reports/re.json"])
        assert rc == 2
        rep = json.loads((tmp_path / "reports/re.json").read_text())
        assert "not a citation" in rep["explanation"]

    def test_a_citation_past_the_end_of_the_file_is_refused(self, tmp_path):
        (tmp_path / "base").mkdir()
        (tmp_path / "cand").mkdir()
        (tmp_path / "spec.md").write_text("one line\n", encoding="utf-8")
        rc = mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                       "--candidate-rtl-dir", "cand", "--top", "m",
                       "--latency-offset", "1",
                       "--latency-free-evidence", "spec.md:99",
                       "--json", "reports/re.json"])
        assert rc == 2


class TestMissingInputsAreNotClean:
    def test_absent_baseline_directory_is_NOT_MEASURED(self, tmp_path):
        (tmp_path / "cand").mkdir()
        rc = mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                       "--candidate-rtl-dir", "cand", "--top", "m",
                       "--json", "reports/re.json"])
        assert rc == 2
        rep = json.loads((tmp_path / "reports/re.json").read_text())
        assert "NOT a clean result" in rep["explanation"]

    def test_an_empty_rtl_directory_is_NOT_MEASURED(self, tmp_path):
        (tmp_path / "base").mkdir()
        (tmp_path / "cand").mkdir()
        rc = mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                       "--candidate-rtl-dir", "cand", "--top", "m",
                       "--json", "reports/re.json"])
        assert rc == 2

    def test_report_names_the_relation_and_disclaims_step_13(self, tmp_path):
        (tmp_path / "cand").mkdir()
        mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                  "--candidate-rtl-dir", "cand", "--top", "m",
                  "--json", "reports/re.json"])
        rep = json.loads((tmp_path / "reports/re.json").read_text())
        assert rep["relation"] == "candidate_rtl == baseline_rtl"
        assert "step 13" in rep["not_the_same_check_as"]


class TestArtefactNamingIsPerReport:
    """A search evaluates MANY candidates. MEASURED: three concurrent runs all
    wrote `<PROGRAM>.ys` and each yosys ran whichever script had last won the
    race, which is the "two artefacts wearing one name" defect this repository
    already has precedent for. Every generated file is now named from the
    report stem."""

    def test_script_and_wrapper_are_named_from_the_report_stem(self, tmp_path):
        (tmp_path / "base").mkdir()
        (tmp_path / "cand").mkdir()
        (tmp_path / "base" / "m.v").write_text(
            "module m(input clk, input rst, output p);\n"
            "  reg r; always @(posedge clk) r <= rst;\n"
            "  assign p = r;\nendmodule\n", encoding="utf-8")
        (tmp_path / "cand" / "m.v").write_text(
            (tmp_path / "base" / "m.v").read_text(encoding="utf-8"),
            encoding="utf-8")
        (tmp_path / "spec.md").write_text("latency is not specified\n",
                                          encoding="utf-8")
        # The container is absent in a unit-test environment, so the run stops
        # at NOT_MEASURED — but the wrapper is written BEFORE that check, which
        # is exactly the artefact whose name is under test.
        mod.main([str(tmp_path), "--baseline-rtl-dir", "base",
                  "--candidate-rtl-dir", "cand", "--top", "m",
                  "--latency-offset", "1",
                  "--latency-free-evidence", "spec.md:1",
                  "--container", "no-such-container-for-a-unit-test",
                  "--json", "reports/cand_0007.json"])
        assert (tmp_path / "reports" / "cand_0007_delay_wrapper.v").is_file()
        assert not (tmp_path / "reports" /
                    f"{mod.PROGRAM}_delay_wrapper.v").exists()


# ── vibe-ic#712 — the declaration scan must not read a COMMENT ──────────────
_COMMENTED_HEADER_RTL = """\
// The wrapper this file replaced was:
//   module chip_top #(parameter WIDTH = 8) (input clk, output [7:0] q);
/* An older revision, kept for the reviewer:
   module chip_top #(parameter WIDTH = 99) (input a, input b, output c);
*/
module chip_top (input wire clk, input wire rst, output wire [3:0] y);
endmodule
"""


def test_module_params_does_not_read_a_commented_out_header():
    """A `//` or `/* */` header must not supply the parameter text.

    Both commented headers above declare `module chip_top` with a parameter
    list; the REAL one has none. Without the strip, `_MODULE_RE.finditer` hits
    the line comment first and `module_params` returns `parameter WIDTH = 8`,
    so the delay wrapper is built carrying a parameter the design does not
    have.
    """
    assert mod.module_params(_COMMENTED_HEADER_RTL, "chip_top") == ""


def test_module_ports_does_not_read_a_commented_out_header():
    """Same defect on the port list, which is compared against the design."""
    ports = mod.module_ports(_COMMENTED_HEADER_RTL, "chip_top")
    names = [n for _d, _r, n in ports]
    assert names == ["clk", "rst", "y"], ports
    assert "q" not in names, "a port that exists only in a comment was read"


def test_a_module_that_exists_ONLY_in_a_comment_is_not_minted():
    """The gate's own sentence: a comment sentence matching `module\\s+(\\w+)`
    must not mint a module that does not exist."""
    only_comment = "// module ghost_top (input a);\nmodule real_top (input b);\nendmodule\n"
    assert mod.module_ports(only_comment, "ghost_top") == []
    assert [n for _d, _r, n in mod.module_ports(only_comment, "real_top")] == ["b"]
