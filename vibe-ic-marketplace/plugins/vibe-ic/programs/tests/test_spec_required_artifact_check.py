"""test_spec_required_artifact_check.py — bidirectional tests.

Every control here is written to FAIL when the defect is present.  The
mutations each control is required to kill are named next to it, because the
first version of this file did not kill any of them:

  - Deleting `arith_declaration_emit.py` outright left 10 of 11 tests green.
    All three fail-closed tests asserted only `returncode != 0` and
    `not out.exists()`, which python's rc=2 "can't open file" satisfies — a
    deleted program, a syntax error and an ImportError all "proved"
    fail-closed.  Fixed by `_assert_ran_and_refused`, which demands rc EXACTLY
    1 plus the program's own stderr banner plus the SPECIFIC field key that
    could not be derived, and by `_require_program`, which fails every test
    the moment a program under test is missing.
  - The one PASS-direction test asserted only `bit_order in (LSB,MSB)` and
    `isinstance(latency_cycles, int)`.  `_derive_bit_order -> "MSB_first"`
    always and `_derive_latency_from_verify_scale -> 0` always both survived
    the whole suite — the two fields that set the oracle's bit framing, i.e.
    the exact defect this program exists to close.  Fixed by asserting the
    WHOLE derived declaration against two fixtures that disagree on every
    field (LSB/MSB, 2/5 cycles, 16/8 bits, active_high/active_low,
    signed_2c/unsigned) plus a third that pins the manifest fallback.
  - The `phase1/generated_docs/L*.json` scan is a documented capability that
    had zero coverage; disabling it kept the suite green.  Covered by
    TestGateLDocSource.
  - The English clause regex covers 3 modals x 6 verbs; only `MUST emit` was
    exercised, so narrowing the regex to `MUST emit` kept the suite green.
    Covered by the parametrised TestGateClauseForms.
  - The gate treated ANY backticked token after a MUST-verb as a filesystem
    path, so "must emit `valid`" / "MUST declare `rst_n`" failed a compliant
    run (confirmed false positive).  The fix is behavioural — a path-shape
    filter in the program — and TestGateSignalNameFalsePositive fails if the
    filter is removed, while its companion control proves the filter did not
    just switch the gate off.
  - The gate was wired into nothing, so the defect it names ("no gate
    noticed") stayed open.  TestGateWiredIntoFlow fails if it is unwired.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).parent.parent
GATE_PROGRAM = PROGRAMS_DIR / "spec_required_artifact_check.py"
EMITTER_PROGRAM = PROGRAMS_DIR / "arith_declaration_emit.py"

# The emitter prints this on its fail-closed path and nowhere else.
FAIL_CLOSED_BANNER = "arith_declaration_emit: FAIL_CLOSED"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_program(path: Path) -> None:
    """A missing program must fail the test, never satisfy it.

    Mutation control: deleting either program under test now fails EVERY test
    in this module with a named reason instead of being mistaken for a
    fail-closed refusal.
    """
    assert path.is_file(), (
        f"program under test is missing: {path} — a deleted program cannot "
        f"be evidence of anything"
    )


def _make_rundir(tmp_path: Path) -> Path:
    rd = tmp_path / "run"
    rd.mkdir()
    return rd


def _run_gate(run_dir: Path) -> subprocess.CompletedProcess:
    _require_program(GATE_PROGRAM)
    return subprocess.run(
        [sys.executable, str(GATE_PROGRAM), str(run_dir)],
        capture_output=True, text=True,
    )


def _run_emitter(run_dir: Path) -> subprocess.CompletedProcess:
    _require_program(EMITTER_PROGRAM)
    return subprocess.run(
        [sys.executable, str(EMITTER_PROGRAM), str(run_dir)],
        capture_output=True, text=True,
    )


def _gate_report(run_dir: Path) -> dict:
    return json.loads(
        (run_dir / "reports/phase2/gates/spec_required_artifacts.json").read_text()
    )


def _write_input_doc(run_dir: Path, content: str, name: str = "L7_verification_plan.md") -> None:
    docs = run_dir / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(content)


def _assert_ran_and_refused(r: subprocess.CompletedProcess, run_dir: Path,
                            *, field_keys: tuple[str, ...]) -> None:
    """Assert the emitter RAN and REFUSED — not that it merely failed.

    rc must be EXACTLY 1: python exits 2 when the script file is absent, so a
    deleted program cannot satisfy this.  The banner must be present: an
    ImportError or SyntaxError exits 1 but prints a traceback and no banner,
    so a broken program cannot satisfy this either.  And the SPECIFIC field
    keys must be named, so refusing for an unrelated reason does not count.
    """
    detail = f"\nrc={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert r.returncode == 1, (
        "fail-closed means rc EXACTLY 1 (rc=2 is python failing to open the "
        "script, which proves nothing)" + detail
    )
    assert FAIL_CLOSED_BANNER in r.stderr, (
        "the program's own fail-closed banner must be on stderr; without it "
        "the non-zero exit could be a traceback from a program that never "
        "reached its own logic" + detail
    )
    for key in field_keys:
        assert f"  - {key}:" in r.stderr, (
            f"expected the refusal to name field {key!r}" + detail
        )
    assert "No file written." in r.stderr, detail
    out = run_dir / "plugin_output" / "declaration.json"
    assert not out.exists(), "should NOT write declaration.json on failure"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — DEFECT direction (absent artifact)
# ---------------------------------------------------------------------------

class TestGateDefectAbsent:
    """Gate must FAIL when a MUST-emit artifact is absent."""

    def test_english_must_emit_absent(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            ## Requirements
            The Plugin MUST emit `plugin_output/report.json` before sign-off.
        """))
        # Artifact NOT created — defect condition
        r = _run_gate(rd)
        assert r.returncode == 1, f"expected FAIL, got {r.returncode}\n{r.stdout}\n{r.stderr}"
        report = _gate_report(rd)
        assert report["verdict"] == "FAIL"
        assert report["failed_count"] == 1
        fail = report["results"][0]
        assert fail["status"] == "FAIL_ABSENT"
        assert fail["artifact_path"] == "plugin_output/report.json"

    def test_zh_tw_must_emit_absent(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            Plugin 在開始 RTL 設計前，**必須**於 `plugin_output/declaration.json` 聲明下列項目。
        """))
        r = _run_gate(rd)
        assert r.returncode == 1
        report = _gate_report(rd)
        assert report["verdict"] == "FAIL"
        assert [res["artifact_path"] for res in report["results"]] == [
            "plugin_output/declaration.json"]
        assert report["results"][0]["status"] == "FAIL_ABSENT"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — clause-form coverage
#
# Kills: narrowing _EN_PATTERN to any single modal/verb pair, and dropping
# either Traditional-Chinese alternative.  Each case names an ABSENT
# path-shaped artifact, so the gate must FAIL on every one of them; a regex
# that stops recognising the form silently returns VACUOUS_PASS (rc=0) and the
# case fails.
# ---------------------------------------------------------------------------

_EN_MODALS = ("MUST", "shall", "is required to")
_EN_VERBS = ("emit", "produce", "declare", "generate", "write", "output")

_ZH_CLAUSE_FORMS = [
    "Plugin **必須**於 `plugin_output/zh_a.json` 聲明下列項目。",
    "Plugin 必須 `plugin_output/zh_b.json` 宣告下列項目。",
    "Plugin 必須 emit `plugin_output/zh_c.json`。",
    "Plugin 必須 produce `plugin_output/zh_d.json`。",
    "Plugin 必須 declare `plugin_output/zh_e.json`。",
    "Plugin 必須 write `plugin_output/zh_f.json`。",
    "Plugin 必須 output `plugin_output/zh_g.json`。",
    "Plugin 必須 generate `plugin_output/zh_h.json`。",
]


class TestGateClauseForms:
    """Every documented clause form must be recognised, not just `MUST emit`."""

    @pytest.mark.parametrize("modal", _EN_MODALS)
    @pytest.mark.parametrize("verb", _EN_VERBS)
    def test_english_modal_verb_matrix(self, tmp_path, modal, verb):
        rd = _make_rundir(tmp_path)
        _write_input_doc(
            rd, f"The Plugin {modal} {verb} `plugin_output/declaration.json`.\n")
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 1, (
            f"clause form {modal!r} + {verb!r} was not recognised — gate "
            f"returned {r.returncode} / {report['verdict']}"
        )
        assert report["verdict"] == "FAIL"
        assert [res["artifact_path"] for res in report["results"]] == [
            "plugin_output/declaration.json"]

    @pytest.mark.parametrize("clause", _ZH_CLAUSE_FORMS)
    def test_zh_tw_clause_forms(self, tmp_path, clause):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, clause + "\n")
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 1, (
            f"ZH clause form not recognised: {clause!r} — gate returned "
            f"{r.returncode} / {report['verdict']}"
        )
        assert report["verdict"] == "FAIL"
        assert report["results"][0]["pattern"] == "zh_tw_imperative"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — the L*.json source
#
# Kills: disabling the phase1/generated_docs/L*.json scan in _collect_clauses.
# There is deliberately NO input/docs tree here, so the clause can only be
# found by the L-doc scan.
# ---------------------------------------------------------------------------

class TestGateLDocSource:
    """A MUST-emit clause carried only by a generated L-doc must be honoured."""

    def test_clause_only_in_generated_l_doc_absent(self, tmp_path):
        rd = _make_rundir(tmp_path)
        l_dir = rd / "phase1" / "generated_docs"
        l_dir.mkdir(parents=True)
        (l_dir / "L7_VERIFICATION.json").write_text(json.dumps({
            "schema_version": 2,
            "sections": [{"content":
                          "The Plugin MUST emit `plugin_output/declaration.json` "
                          "before RTL design begins."}],
        }))
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 1, (
            "clause lives only in phase1/generated_docs/L*.json — the L-doc "
            f"scan is not running (verdict {report['verdict']})"
        )
        assert report["verdict"] == "FAIL"
        assert report["results"][0]["source"] == "phase1/generated_docs/L7_VERIFICATION.json"
        assert report["results"][0]["status"] == "FAIL_ABSENT"

    def test_clause_only_in_generated_l_doc_present(self, tmp_path):
        """Same source, artifact present → PASS (so the FAIL above is not
        just 'the L-doc path always fails')."""
        rd = _make_rundir(tmp_path)
        l_dir = rd / "phase1" / "generated_docs"
        l_dir.mkdir(parents=True)
        (l_dir / "L7_VERIFICATION.json").write_text(json.dumps({
            "sections": [{"content":
                          "The Plugin MUST emit `plugin_output/declaration.json`."}],
        }))
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert _gate_report(rd)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — DEFECT direction (empty artifact)
# ---------------------------------------------------------------------------

class TestGateDefectEmpty:
    """Gate must FAIL when the declared artifact exists but is 0 bytes."""

    def test_english_must_emit_empty_file(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            The Plugin MUST emit `plugin_output/summary.json` with results.
        """))
        # Create 0-byte file
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "summary.json").write_text("")
        r = _run_gate(rd)
        assert r.returncode == 1
        report = _gate_report(rd)
        assert report["verdict"] == "FAIL"
        statuses = [res["status"] for res in report["results"]]
        assert "FAIL_EMPTY" in statuses


# ---------------------------------------------------------------------------
# spec_required_artifact_check — FIXED direction
# ---------------------------------------------------------------------------

class TestGateFixed:
    """Gate must PASS when declared artifact is present and non-empty."""

    def test_english_artifact_present(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            The Plugin MUST emit `plugin_output/declaration.json` before sign-off.
        """))
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        assert r.returncode == 0, f"expected PASS\n{r.stdout}\n{r.stderr}"
        report = _gate_report(rd)
        assert report["verdict"] == "PASS"
        assert report["failed_count"] == 0

    def test_zh_tw_artifact_present(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            **必須**於 `plugin_output/declaration.json` 聲明下列項目
        """))
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        assert r.returncode == 0
        assert _gate_report(rd)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — CONFIRMED FALSE POSITIVE (Front B)
#
# Prose lifted verbatim from the plugin's own knowledge base
# (agents/ic-expert-agent.md, replicated in 7 generated lessons.md files).
# Before the path-shape filter this doc drove the gate to rc=1 / verdict FAIL
# with FAIL_ABSENT 'valid' and FAIL_ABSENT 'rst_n' on a run that contained
# every artifact it actually owed.  Removing `_is_path_shaped` fails these.
# ---------------------------------------------------------------------------

_SIGNAL_NAME_PROSE = textwrap.dedent("""\
    ## Handshake

    A streaming run-length counter must emit `valid` for exactly one cycle
    per completed run, and the consumer MUST declare `rst_n` in its port
    list.  The design shall produce `ready` combinationally.
    每個模組必須 emit `done` 一個 cycle。
""")


class TestGateSignalNameFalsePositive:
    """Backticked SIGNAL names after a MUST-verb are not required artifacts."""

    def test_signal_names_do_not_fail_the_gate(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, _SIGNAL_NAME_PROSE)
        # A compliant run: it owes nothing, and it emitted its declaration.
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 0, (
            "signal names read as required artifacts — false positive"
            f"\nverdict={report['verdict']} results={report['results']}"
        )
        assert report["verdict"] == "VACUOUS_PASS"
        assert report["clauses_found"] == 0
        # Narrowed, not silent: the rejected tokens are reported.
        ignored = {t["artifact_path"] for t in report["ignored_tokens"]}
        assert {"valid", "rst_n", "ready", "done"} <= ignored

    def test_filter_does_not_disable_the_gate(self, tmp_path):
        """Control for the test above: the SAME prose plus one genuine
        path-shaped clause must still FAIL on the genuine one only.

        Without this, deleting the clause regexes entirely would 'fix' the
        false positive.
        """
        rd = _make_rundir(tmp_path)
        _write_input_doc(
            rd,
            _SIGNAL_NAME_PROSE
            + "\nThe Plugin MUST emit `plugin_output/declaration.json`.\n")
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 1, f"{report['verdict']}: {report['results']}"
        assert report["verdict"] == "FAIL"
        assert [res["artifact_path"] for res in report["results"]] == [
            "plugin_output/declaration.json"]
        assert report["results"][0]["status"] == "FAIL_ABSENT"

    def test_extensionless_signal_name_with_dot_is_not_a_path(self, tmp_path):
        """`u_dut.valid` is a hierarchical signal reference, not a file."""
        rd = _make_rundir(tmp_path)
        _write_input_doc(
            rd, "The DUT MUST declare `u_dut.valid` at the top level.\n")
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 0, f"{report['verdict']}: {report['results']}"
        assert report["clauses_found"] == 0
        assert report["ignored_token_count"] == 1

    def test_bare_filename_with_artifact_extension_is_a_path(self, tmp_path):
        """A token needs a separator OR a known extension — not both."""
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, "The Plugin MUST emit `declaration.json`.\n")
        r = _run_gate(rd)
        report = _gate_report(rd)
        assert r.returncode == 1, f"{report['verdict']}"
        assert [res["artifact_path"] for res in report["results"]] == [
            "declaration.json"]


# ---------------------------------------------------------------------------
# spec_required_artifact_check — VACUOUS case
# ---------------------------------------------------------------------------

class TestGateVacuous:
    """No MUST-emit clause → VACUOUS_PASS with explicit note."""

    def test_no_must_emit_clauses(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            # Verification Plan
            This document describes timing requirements.
            All outputs are optional and may be omitted.
        """))
        r = _run_gate(rd)
        assert r.returncode == 0, f"vacuous should exit 0\n{r.stdout}\n{r.stderr}"
        report = _gate_report(rd)
        assert report["verdict"] == "VACUOUS_PASS"
        assert "nothing to assert" in report["note"].lower()
        assert report["ignored_token_count"] == 0

    def test_no_input_docs_dir(self, tmp_path):
        """No input/docs directory at all — should VACUOUS_PASS, not crash."""
        rd = _make_rundir(tmp_path)
        r = _run_gate(rd)
        assert r.returncode == 0
        assert _gate_report(rd)["verdict"] == "VACUOUS_PASS"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — WIRING
#
# The capture's premise is "the spec said MUST declare, the plugin did not,
# and NO gate noticed".  A gate that nothing invokes leaves that premise
# intact.  This control fails if the gate is dropped from the canonical
# structural-RTL tuple.
# ---------------------------------------------------------------------------

class TestGateWiredIntoFlow:

    def test_gate_is_in_structural_rtl_gates(self):
        sys.path.insert(0, str(PROGRAMS_DIR))
        import flow_compliance_check as F
        assert "spec_required_artifact_check" in F._STRUCTURAL_RTL_GATES, (
            "spec_required_artifact_check is not wired into "
            "flow_compliance_check._STRUCTURAL_RTL_GATES — nothing would run "
            "it, so the defect it names stays open"
        )

    def test_gate_program_is_discoverable_by_the_umbrella(self):
        """The umbrella resolves `<gate_name>.py` under PROGRAMS_DIR and
        silently `continue`s when the file is absent — so the wiring is only
        real if the filename matches the tuple entry exactly."""
        assert (PROGRAMS_DIR / "spec_required_artifact_check.py").is_file()

    @pytest.mark.parametrize("artifact_present,expect_fail", [
        (False, True),
        (True, False),
    ])
    def test_umbrella_reports_the_gate_both_ways(self, tmp_path, monkeypatch,
                                                 artifact_present, expect_fail):
        """Membership in a tuple is not invocation.

        This drives `_run_structural_rtl_gates` itself — the function the P0
        umbrella calls — and asserts it REPORTS the FAIL when the
        spec-declared artifact is missing and does NOT when it is present.
        The tuple is monkeypatched down to this one gate purely for runtime;
        `test_gate_is_in_structural_rtl_gates` above pins the real membership.
        """
        sys.path.insert(0, str(PROGRAMS_DIR))
        import flow_compliance_check as F
        monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                            ("spec_required_artifact_check",))

        proj = tmp_path / "proj"
        rtl = proj / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True)
        (rtl / "dut.v").write_text(
            "module dut(input wire clk, output wire q);\n"
            "  assign q = 1'b0;\nendmodule\n")
        (proj / "input" / "docs").mkdir(parents=True)
        (proj / "input" / "docs" / "L7_verification_plan.md").write_text(
            "Plugin 在開始 RTL 設計前，**必須**於 "
            "`plugin_output/declaration.json` 聲明。\n")
        if artifact_present:
            (proj / "plugin_output").mkdir(parents=True)
            (proj / "plugin_output" / "declaration.json").write_text(
                '{"bit_order": "LSB_first"}\n')

        _passed, fails, skips, _waivers = F._run_structural_rtl_gates(proj)
        named = [f for f in fails if "spec_required_artifact_check" in f]
        skipped = [s for s in skips if "spec_required_artifact_check" in s]
        assert not skipped, f"umbrella SKIPPED the gate: {skipped}"
        if expect_fail:
            assert named, (
                "the umbrella did not report spec_required_artifact_check "
                f"even though the declared artifact is absent; fails={fails}")
        else:
            assert not named, (
                f"umbrella failed a compliant project: {named}")


# ---------------------------------------------------------------------------
# arith_declaration_emit — fixtures
#
# Two fixtures that disagree on EVERY derived field, so an "always X" mutation
# of any deriver is caught by one of them.
# ---------------------------------------------------------------------------

_RTL_LSB = textwrap.dedent("""\
    `default_nettype none
    //============================================================================
    // spm — serial-parallel multiplier
    // y : serial multiplier, LSB-first
    // p : serial product, LSB-first
    // Reset    : synchronous, active-high
    // Algorithm: textbook carry-save shift-add serial-parallel multiplier.
    //============================================================================
    module spm #(parameter size = 16) (
        input wire clk, input wire rst, input wire [size-1:0] x,
        input wire y, output wire p
    );
        reg yr; reg pr;
        always @(posedge clk) begin
            if (rst) begin yr <= 0; pr <= 0; end
            else begin yr <= y; pr <= yr & x[0]; end
        end
        assign p = pr;
    endmodule
    `default_nettype wire
""")

_RTL_MSB = textwrap.dedent("""\
    `default_nettype none
    //============================================================================
    // acc — serial accumulator
    // y : serial operand, MSB-first
    // Reset    : synchronous, active-low
    // Algorithm: radix-4 booth recoded accumulate.
    //============================================================================
    module acc #(parameter size = 8) (
        input wire clk, input wire rst, input wire [size-1:0] x,
        input wire y, output wire p
    );
        reg yr; reg pr;
        always @(posedge clk) begin
            if (!rst) begin yr <= 0; pr <= 0; end
            else begin yr <= y; pr <= yr & x[0]; end
        end
        assign p = pr;
    endmodule
    `default_nettype wire
""")

_L2_SIGNED = json.dumps({
    "schema_version": 2,
    "doc_class": "frs",
    "frs_sections": [{"content": 'Plugin 須聲明 signed_2c 或 unsigned；預設 signed_2c'}],
})

_L2_UNSIGNED = json.dumps({
    "schema_version": 2,
    "doc_class": "frs",
    "integer_encoding": "unsigned",
})

_VERIFY_REPORT_2 = textwrap.dedent("""\
    # Report
    | Latency | **2 cycle** |
    CALIBRATED_LATENCY: 2  BIT_ORDER: LSB_first  SIZE: 16
""")

_GLS_REPORT_5 = textwrap.dedent("""\
    # GLS Report
    | Calibrated latency | **5 cycle** |
""")

_DECL_LSB = {
    "bit_order": "LSB_first",
    "reset_polarity": "active_high",
    "latency_cycles": 2,
    "integer_encoding": "signed_2c",
    "multiplier_algorithm": "textbook_carry_save_shift_add_serial_parallel_multiplier",
    "size_param": 16,
}

_DECL_MSB = {
    "bit_order": "MSB_first",
    "reset_polarity": "active_low",
    "latency_cycles": 5,
    "integer_encoding": "unsigned",
    "multiplier_algorithm": "radix_4_booth_recoded_accumulate",
    "size_param": 8,
}


def _build_rundir(tmp_path: Path, *, rtl: str | None, l2: str | None,
                  verify_report: str | None = None,
                  gls_report: str | None = None,
                  oracle_manifest: dict | None = None) -> Path:
    rd = tmp_path / "run"
    rd.mkdir(parents=True, exist_ok=True)
    if rtl is not None:
        rtl_dir = rd / "phase2" / "stage1" / "rtl"
        rtl_dir.mkdir(parents=True)
        (rtl_dir / "myip.v").write_text(rtl)
    if l2 is not None:
        l_dir = rd / "phase1" / "generated_docs"
        l_dir.mkdir(parents=True)
        (l_dir / "L2_FRS.json").write_text(l2)
    if verify_report is not None:
        scale_dir = rd / "_verify_scale"
        scale_dir.mkdir()
        (scale_dir / "REPORT.md").write_text(verify_report)
    if gls_report is not None:
        gls_dir = rd / "_verify_gls"
        gls_dir.mkdir()
        (gls_dir / "GLS_REPORT.md").write_text(gls_report)
    if oracle_manifest is not None:
        man_dir = rd / "phase2" / "stage1" / "sim_full_stack"
        man_dir.mkdir(parents=True, exist_ok=True)
        (man_dir / "arith_oracle_manifest.json").write_text(
            json.dumps(oracle_manifest))
    return rd


# ---------------------------------------------------------------------------
# arith_declaration_emit — PASS direction (VALUES, not shapes)
# ---------------------------------------------------------------------------

class TestEmitterPass:
    """The emitted declaration must be EXACTLY the derived one.

    Kills: `_derive_bit_order -> "MSB_first"` always, `_derive_latency_* -> 0`
    always, and any other constant-return mutation of a deriver, because the
    two fixtures disagree on every one of the six fields.
    """

    @pytest.mark.parametrize("case,expected", [
        ("lsb", _DECL_LSB),
        ("msb", _DECL_MSB),
    ])
    def test_emits_exact_declaration(self, tmp_path, case, expected):
        if case == "lsb":
            rd = _build_rundir(tmp_path, rtl=_RTL_LSB, l2=_L2_SIGNED,
                               verify_report=_VERIFY_REPORT_2)
        else:
            # No _verify_scale report → exercises the GLS fallback, and pins
            # a DIFFERENT non-zero latency.
            rd = _build_rundir(tmp_path, rtl=_RTL_MSB, l2=_L2_UNSIGNED,
                               gls_report=_GLS_REPORT_5)
        r = _run_emitter(rd)
        assert r.returncode == 0, f"expected PASS\n{r.stdout}\n{r.stderr}"
        out = rd / "plugin_output" / "declaration.json"
        assert out.exists(), "declaration.json not written"
        assert out.stat().st_size > 0
        assert json.loads(out.read_text()) == expected

    def test_latency_falls_back_to_oracle_manifest(self, tmp_path):
        """Third latency source, third distinct value — so disabling the
        manifest fallback (or constant-folding it) is caught."""
        rd = _build_rundir(
            tmp_path, rtl=_RTL_LSB, l2=_L2_SIGNED,
            oracle_manifest={"framing": "self-calibrated offset=7"})
        r = _run_emitter(rd)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        d = json.loads((rd / "plugin_output" / "declaration.json").read_text())
        assert d == {**_DECL_LSB, "latency_cycles": 7}

    def test_verify_scale_wins_over_gls(self, tmp_path):
        """Documented precedence: _verify_scale first, GLS second.  Both
        present and disagreeing — the measured scale value must win."""
        rd = _build_rundir(tmp_path, rtl=_RTL_LSB, l2=_L2_SIGNED,
                           verify_report=_VERIFY_REPORT_2,
                           gls_report=_GLS_REPORT_5)
        r = _run_emitter(rd)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        d = json.loads((rd / "plugin_output" / "declaration.json").read_text())
        assert d["latency_cycles"] == 2


# ---------------------------------------------------------------------------
# arith_declaration_emit — FAIL-CLOSED
#
# Each case asserts rc EXACTLY 1 + the fail-closed banner + the SPECIFIC
# field key.  Kills: deleting the program (rc=2), breaking its imports or
# syntax (rc=1 with no banner), and refusing for the wrong reason.
# ---------------------------------------------------------------------------

class TestEmitterFailClosed:
    """Emitter exits 1 with a named reason and writes NO file."""

    def test_missing_rtl_no_file_written(self, tmp_path):
        rd = _build_rundir(tmp_path, rtl=None, l2=_L2_SIGNED,
                           verify_report=_VERIFY_REPORT_2)
        r = _run_emitter(rd)
        _assert_ran_and_refused(
            r, rd,
            field_keys=("rtl_source", "bit_order", "reset_polarity",
                        "size_param", "multiplier_algorithm"))

    def test_missing_l2_no_file_written(self, tmp_path):
        rd = _build_rundir(tmp_path, rtl=_RTL_LSB, l2=None,
                           verify_report=_VERIFY_REPORT_2)
        r = _run_emitter(rd)
        _assert_ran_and_refused(r, rd, field_keys=("integer_encoding",))
        # Everything else WAS derivable — the refusal is specific, not blanket.
        assert "  - bit_order:" not in r.stderr
        assert "  - latency_cycles:" not in r.stderr

    def test_missing_calibration_no_file_written(self, tmp_path):
        rd = _build_rundir(tmp_path, rtl=_RTL_LSB, l2=_L2_SIGNED)
        r = _run_emitter(rd)
        _assert_ran_and_refused(r, rd, field_keys=("latency_cycles",))
        assert "  - bit_order:" not in r.stderr
        assert "  - integer_encoding:" not in r.stderr

    def test_unmarked_bit_order_no_file_written(self, tmp_path):
        """The framing field itself: RTL with no LSB/MSB marker must refuse
        rather than guess a default."""
        rtl = _RTL_LSB.replace("LSB-first", "bit-serial")
        rd = _build_rundir(tmp_path, rtl=rtl, l2=_L2_SIGNED,
                           verify_report=_VERIFY_REPORT_2)
        r = _run_emitter(rd)
        _assert_ran_and_refused(r, rd, field_keys=("bit_order",))

    def test_fail_closed_does_not_clobber_existing_declaration(self, tmp_path):
        """A refusal must leave a previously-emitted declaration untouched."""
        rd = _build_rundir(tmp_path, rtl=_RTL_LSB, l2=_L2_SIGNED)
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_emitter(rd)
        assert r.returncode == 1
        assert FAIL_CLOSED_BANNER in r.stderr
        assert json.loads((out / "declaration.json").read_text()) == {
            "bit_order": "LSB_first"}


# ---------------------------------------------------------------------------
# End-to-end: emitter closes the gate
#
# The two programs are one story — the gate names the missing artifact, the
# emitter produces it, and the gate then passes on the SAME run dir.
# ---------------------------------------------------------------------------

class TestEmitterClosesTheGate:

    def test_gate_fails_then_emitter_makes_it_pass(self, tmp_path):
        rd = _build_rundir(tmp_path, rtl=_RTL_LSB, l2=_L2_SIGNED,
                           verify_report=_VERIFY_REPORT_2)
        _write_input_doc(rd, textwrap.dedent("""\
            Plugin 在開始 RTL 設計前，**必須**於 `plugin_output/declaration.json` 聲明。
        """))

        before = _run_gate(rd)
        assert before.returncode == 1
        assert _gate_report(rd)["verdict"] == "FAIL"

        emit = _run_emitter(rd)
        assert emit.returncode == 0, f"{emit.stdout}\n{emit.stderr}"

        after = _run_gate(rd)
        assert after.returncode == 0, f"{after.stdout}\n{after.stderr}"
        assert _gate_report(rd)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# WHERE the gate looks — the canonical Path-A input-doc root
#
# The gate scanned `run_dir/input/docs/*.md` and nothing else.  Measured on
# the committed run corpus at the time of this fix:
#
#   phase1/input_doc/ : 73 dirs, 181 files, ALL `.txt`  (0 `.md`)
#   input/docs/       : 74 dirs, 163 files (.md 86, .txt 40, .rst 17,
#                                           .pdf 15, .svg 4, .sv 1)
#
# and the repo's own path API calls `phase1/input_doc/` the canonical one:
#   _path_layout.input_doc_dir()                -> project/"phase1/input_doc",
#                                                  docstring "Path A entry"
#   phase1_one_shot_runner._detect_input_mode   -> "`phase1/input_doc/`
#                                                  populated (Layout P
#                                                  canonical)" vs "input/docs/
#                                                  ... legacy phase1_engine
#                                                  inputs"
#
# So on a Path-A run the gate read a directory the layout does not populate,
# found nothing, and reported an EXECUTED VACUOUS_PASS.  Every control below
# fails if `_collect_clauses` is narrowed back to `input/docs/*.md`.
# ---------------------------------------------------------------------------

_ABSENT_CLAUSE = (
    "The Plugin MUST emit `plugin_output/declaration.json` before RTL design "
    "begins.\n")


def _write_canonical_doc(run_dir: Path, content: str,
                         name: str = "L7_verification_plan.txt") -> Path:
    d = run_dir / "phase1" / "input_doc"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(content)
    return p


class TestGateReadsCanonicalPathADocDir:
    """MUTATION killed: `_input_doc_dirs` drops the canonical root (i.e. the
    pre-fix `input/docs`-only scan)."""

    def test_clause_in_canonical_input_doc_is_seen_and_fails(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_canonical_doc(rd, _ABSENT_CLAUSE)
        r = _run_gate(rd)
        rep = _gate_report(rd)
        assert r.returncode == 1, (
            "a MUST-emit clause in the CANONICAL Path-A doc root names an "
            "absent artifact — the gate must FAIL, not report an executed "
            f"pass.\nrc={r.returncode}\n{r.stdout}\n{r.stderr}\n{rep}")
        assert rep["verdict"] == "FAIL"
        assert [x["artifact_path"] for x in rep["results"]] == [
            "plugin_output/declaration.json"]

    def test_same_clause_passes_once_the_artifact_exists(self, tmp_path):
        """PASS direction — proves the FAIL above is about the artifact, not
        about the gate simply blowing up on the canonical root."""
        rd = _make_rundir(tmp_path)
        _write_canonical_doc(rd, _ABSENT_CLAUSE)
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        rep = _gate_report(rd)
        assert rep["verdict"] == "PASS"
        assert rep["clauses_found"] == 1

    def test_report_names_the_canonical_root_it_scanned(self, tmp_path):
        rd = _make_rundir(tmp_path)
        doc = _write_canonical_doc(rd, _ABSENT_CLAUSE)
        _run_gate(rd)
        rep = _gate_report(rd)
        assert "phase1/input_doc" in rep["input_doc_dirs_scanned"], rep
        assert str(doc.relative_to(rd)) in rep["input_docs_read"], rep

    def test_canonical_root_agrees_with_the_repo_path_api(self, tmp_path):
        """If `_path_layout.input_doc_dir` ever moves, this gate must move with
        it — a hand-written literal is exactly how the drift happened."""
        sys.path.insert(0, str(PROGRAMS_DIR))
        import _path_layout as _pl
        import importlib
        gate = importlib.import_module("spec_required_artifact_check")
        rd = _make_rundir(tmp_path)
        _write_canonical_doc(rd, _ABSENT_CLAUSE)
        scanned = [str(p) for p in gate._input_doc_dirs(rd)]
        assert str(_pl.input_doc_dir(rd)) in scanned, (
            f"_path_layout says the Path-A entry is {_pl.input_doc_dir(rd)}, "
            f"but the gate scanned {scanned}")


class TestGateReadsEveryTextBearingExtension:
    """MUTATION killed: `_DOC_EXTS` narrowed back to `(".md",)`."""

    @pytest.mark.parametrize("name", [
        "spec.txt", "spec.rst", "spec.md",
    ])
    def test_legacy_root_extension_is_read(self, tmp_path, name):
        rd = _make_rundir(tmp_path)
        docs = rd / "input" / "docs"
        docs.mkdir(parents=True)
        (docs / name).write_text(_ABSENT_CLAUSE)
        r = _run_gate(rd)
        rep = _gate_report(rd)
        assert r.returncode == 1, (
            f"a MUST-emit clause in input/docs/{name} must be read; the "
            f"pre-fix `*.md` glob saw only .md, i.e. 86 of 163 files in the "
            f"committed corpus.\n{r.stdout}\n{r.stderr}\n{rep}")
        assert rep["verdict"] == "FAIL"

    @pytest.mark.parametrize("name", ["spec.txt", "spec.rst", "spec.md"])
    def test_canonical_root_extension_is_read(self, tmp_path, name):
        rd = _make_rundir(tmp_path)
        _write_canonical_doc(rd, _ABSENT_CLAUSE, name=name)
        r = _run_gate(rd)
        assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
        assert _gate_report(rd)["verdict"] == "FAIL"

    def test_nested_subdirectory_is_read(self, tmp_path):
        """Real corpora nest (`input/docs/<vendor>/…`); a flat glob missed it."""
        rd = _make_rundir(tmp_path)
        nested = rd / "phase1" / "input_doc" / "vendor" / "part_a"
        nested.mkdir(parents=True)
        (nested / "spec.txt").write_text(_ABSENT_CLAUSE)
        r = _run_gate(rd)
        assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"

    def test_binary_doc_formats_are_not_read_as_text(self, tmp_path):
        """`.pdf` is NOT in _DOC_EXTS — the extraction track converts it into
        the canonical `.txt`, which IS read.  Reading raw PDF bytes as text
        would be a fabricated clause source."""
        rd = _make_rundir(tmp_path)
        docs = rd / "input" / "docs"
        docs.mkdir(parents=True)
        (docs / "spec.pdf").write_bytes(b"%PDF-1.4\n" + _ABSENT_CLAUSE.encode())
        r = _run_gate(rd)
        assert r.returncode == 0
        rep = _gate_report(rd)
        assert rep["verdict"] == "VACUOUS_PASS"
        assert rep["input_docs_read"] == []


class TestGateBothRootsAtOnce:
    """Both roots are scanned, and a clause repeated across them is asserted
    once (the dedup key is the artifact path, not the file)."""

    def test_clauses_from_both_roots_are_collected(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_canonical_doc(rd, "MUST emit `phase2/stage1/rtl/chip_top.v`\n")
        docs = rd / "input" / "docs"
        docs.mkdir(parents=True)
        (docs / "legacy.md").write_text(_ABSENT_CLAUSE)
        r = _run_gate(rd)
        rep = _gate_report(rd)
        assert r.returncode == 1
        assert sorted(x["artifact_path"] for x in rep["results"]) == [
            "phase2/stage1/rtl/chip_top.v",
            "plugin_output/declaration.json",
        ], rep
        assert len(rep["input_doc_dirs_scanned"]) == 2, rep

    def test_same_artifact_in_both_roots_asserted_once(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_canonical_doc(rd, _ABSENT_CLAUSE)
        docs = rd / "input" / "docs"
        docs.mkdir(parents=True)
        (docs / "legacy.md").write_text(_ABSENT_CLAUSE)
        _run_gate(rd)
        rep = _gate_report(rd)
        assert rep["clauses_found"] == 1, rep
