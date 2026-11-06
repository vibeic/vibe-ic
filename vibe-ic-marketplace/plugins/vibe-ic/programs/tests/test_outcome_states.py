"""Outcome states: one run is the verdict, and only a plain FAIL is red (owner, 2026-09-27).

Every claim is proved by a one-file pytest session run in a child process with
the real plugin loaded (``-p _outcome_states``), and every conversion has its
paired control: the same failure under the conditions that make it a real
failure must stay FAIL. A converter without that control could be a converter
that paints every red grey, which is the one thing this tier must never do.

    1. a missing tool on the host         -> NOT_VERIFIED (host, tool, remedy)
       the tool present, a real assert    -> FAIL
    2. ImageNotResolvable from _eda_pin   -> NOT_VERIFIED
       the same exception planted by test -> FAIL
    3. a `measures` test on a loaded host -> NOT_MEASURED (with the numbers)
       the same failure serial and quiet  -> FAIL
       the same failure -n 16 but quiet   -> FAIL (workers are never a cause)
       an UNMARKED test under -n 16       -> FAIL
    4. a `bookkeeping` stale count        -> BOOKKEEPING (stated vs actual)
       a property assert in that test     -> FAIL
    5. VIBEIC_REQUIRE_EDA_VERIFICATION=1  -> the NOT_VERIFIED case is red
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest  # noqa: E402

#: This file's assertions quote the child's "`yosys` is not on PATH"; on a host
#: without yosys, a regression here would otherwise be converted into the very
#: state it is testing. Measured: the drop-the-presence-check mutation read
#: "17 passed, 1 skipped" until this mark was added.
pytestmark = pytest.mark.outcome_state_exempt(
    "the subject is the outcome-state tier itself")

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"

#: A conftest for the child that pins the host's load reading, so the "quiet"
#: and "loaded" arms do not depend on what else this machine is doing.
_LOAD_CONFTEST = "import os\nos.getloadavg = lambda: ({load}, {load}, {load})\n"










# ---------------------------------------------------------------------------
# 1. a missing tool
# ---------------------------------------------------------------------------
_RUNS_YOSYS = ("def test_synth():\n"
               "    subprocess.run(['yosys', '-V'], check=True)\n"
               "    assert 1 == 2, 'the synthesised netlist is wrong'\n")












# ---------------------------------------------------------------------------
# 2. no resolvable image
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 3. measurements
# ---------------------------------------------------------------------------
_MEASURES = ("@pytest.mark.measures\n"
             "def test_linear():\n"
             "    assert 40.0 < 15.0, 'cost 40.0x for a 6x netlist'\n")
_UNMARKED = ("def test_linear():\n"
             "    assert 40.0 < 15.0, 'cost 40.0x for a 6x netlist'\n")












# ---------------------------------------------------------------------------
# 4. bookkeeping
# ---------------------------------------------------------------------------
_BOOK = ("@pytest.mark.bookkeeping(regenerate='python3 gen_counts.py',\n"
         "                         match=r'is stale')\n"
         "def test_count():\n"
         "    assert {cond}, {msg!r}\n")








# ---------------------------------------------------------------------------
# 5. the landing contract is unchanged
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# the markers are declared on the tests the brief names
# ---------------------------------------------------------------------------
def _marked(path, func, mark):
    import ast
    tree = ast.parse((Path(__file__).parent / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return [d for d in node.decorator_list
                    if mark in ast.unparse(d)]
    raise AssertionError(f"{path}::{func} not found")


def test_the_named_measuring_and_bookkeeping_tests_carry_their_marks():
    observed = {
        (p, f, m): bool(_marked(p, f, f"mark.{m}")) for p, f, m in (
            ("test_v0_3_37_issue548_pnr_timeouts.py",
             "test_reset_dependency_check_pattern_b_is_linear_not_quadratic", "measures"),
            ("test_pytest_per_file_junit.py",
             "test_silent_pytest_boundaries_keep_a_long_session_alive", "measures"),
            ("test_program_inventory_no_drift.py",
             "test_the_writer_is_idempotent_and_touches_nothing_that_agrees", "bookkeeping"),
            ("test_issue538_merge_gate_covers_ci_hygiene.py",
             "test_a_new_program_without_a_regenerated_index_is_refused", "bookkeeping"),
            ("test_flow_matrix_census_freshness.py",
             "test_the_census_block_is_fresh", "bookkeeping"),
            ("test_flow_matrix_census_freshness.py",
             "test_the_published_total_equals_the_live_census", "bookkeeping"),
        )}
    assert [k for k, v in observed.items() if not v] == [], observed






# ---------------------------------------------------------------------------
# 2b. the container runs other bytes than the pin (fleet upgraded mid-run)
# ---------------------------------------------------------------------------
_MISMATCH_TEXT = (
    "ENV_REFUSED: analog_a3_netlist_emit: CONTAINER_IMAGE_MISMATCH: container "
    "vibeic-eda runs sha256:7a01d48e, but the pinned runtime is "
    "ghcr.io/vibeic/vibeic-eda@sha256:93d88e9e; required sha256:93d88e9e, "
    "found sha256:7a01d48e")












# ---------------------------------------------------------------------------
# 6. at the site: require_tools / skip_if_not_measurable (owner 2026-09-29)
# ---------------------------------------------------------------------------
_REQUIRES = ("import _outcome_states as S\n"
             "def test_x():\n"
             "    S.require_tools({tools})\n"
             "    assert 1 == 2, 'the tool half ran and found a real defect'\n")










_CEILING = ("import _outcome_states as S\n"
            "def test_x():\n"
            "    S.skip_if_not_measurable('still running at the 55s ceiling',\n"
            "                             progress=S.{progress})\n"
            "    pytest.fail('still running at the 55s ceiling')\n")
















def _calls(path, func, callee):
    import ast
    tree = ast.parse((Path(__file__).parent / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return any(isinstance(c, ast.Call)
                       and getattr(c.func, "attr", getattr(c.func, "id", "")) == callee
                       for c in ast.walk(node))
    raise AssertionError(f"{path}::{func} not found")


def test_the_named_sites_report_their_state_during_the_run():
    """The sites the 2026-09-29 census found failing (or silently passing) for
    a missing tool or a load-bound ceiling each call the site helper."""
    sites = (
        ("test_formal_die_chiptop_core_binding.py", "_require_yosys", "require_tools"),
        ("test_organic_20260704_rcvar_whitebox_flat.py",
         "test_flat_result_compiles_and_whitebox_signal_visible", "require_tools"),
        ("test_v1_11_78_alias_wrapper_hidden_from_verilator_lint.py",
         "test_iverilog_still_binds_the_alias_top", "require_tools"),
        ("test_v1_11_78_alias_wrapper_hidden_from_verilator_lint.py",
         "test_verilator_lint_is_clean_with_the_guard", "require_tools"),
        ("test_v1_2_47_alias_param_forward.py",
         "test_param_aliased_completion_compiles", "require_tools"),
        ("test_v1_2_47_alias_param_forward.py",
         "test_nonparam_aliased_completion_still_compiles", "require_tools"),
        ("test_v1_2_48_alias_json_unwrap.py",
         "test_json_wrapped_completion_compiles_under_iverilog", "require_tools"),
        ("test_v1_2_harness_toplevel_alias.py",
         "test_aliased_completion_compiles", "require_tools"),
        ("test_v1_3_88_issue119_chip_top_reemit_pull_restore.py",
         "test_reemit_restores_pull_and_design_resets", "require_tools"),
        ("test_cvdp_gate_alias_compliance.py",
         "test_wrapper_correctness_from_prompt_name", "require_tools"),
        ("test_deterministic_rtl_dispatcher.py",
         "test_cli_generates_and_compiles", "require_tools"),
        ("test_v1_3_85_chip_top_vl_tri_outermost.py",
         "test_autoemit_moves_pull_to_outermost_face_end_to_end", "require_tools"),
        ("test_die_density_keepout_census_runs_in_openroad.py", "_route",
         "probe_skip_reason"),
        ("test_landing_merge_verdict.py",
         "_assert_interruption_cleans_every_parallel_arm", "skip_if_not_measurable"),
        ("test_issue1129_gatekeeper_prepare_landing.py",
         "test_the_real_program_runs_against_this_repo_and_honours_its_boundary",
         "skip_if_not_measurable"),
    )
    missing = [s for s in sites if not _calls(*s)]
    assert missing == [], missing


def _keywords_of(path, func, callee):
    import ast
    tree = ast.parse((Path(__file__).parent / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return [sorted(k.arg for k in c.keywords) for c in ast.walk(node)
                    if isinstance(c, ast.Call)
                    and getattr(c.func, "attr", getattr(c.func, "id", "")) == callee]
    raise AssertionError(f"{path}::{func} not found")


def test_every_ceiling_site_states_its_progress_evidence_and_its_ceiling_sample():
    """R-0929-ENV-AT-RUNTIME at the sites: each ceiling/stall call passes what
    it observed (`progress=`) and the load it read AT the ceiling
    (`conditions=`), and the evidence each one has is the evidence it uses:
    issue1129's Stalled maps to PROGRESS_NONE, and the landing helper FAILs a
    cleanup that STARTED, and a verifier that created worktrees after the
    signal, before it can reach the ceiling helper."""
    sites = (("test_landing_merge_verdict.py",
              "_assert_interruption_cleans_every_parallel_arm", 2),
             ("test_issue1129_gatekeeper_prepare_landing.py",
              "test_the_real_program_runs_against_this_repo_and_honours_its_boundary", 1))
    for path, func, n in sites:
        kws = _keywords_of(path, func, "skip_if_not_measurable")
        assert kws == [["conditions", "progress"]] * n, (path, kws)
    src = (Path(__file__).parent / "test_issue1129_gatekeeper_prepare_landing.py").read_text()
    assert "states.PROGRESS_NONE if seen" in src
    land = (Path(__file__).parent / "test_landing_merge_verdict.py").read_text()
    body = land[land.index("def _assert_interruption_cleans_every_parallel_arm"):]
    body = body[:body.index("\ndef ")]
    last_skip = body.rindex("states.skip_if_not_measurable(")
    # A cleanup that STARTED and a verifier that went on AFTER the signal
    # (later worktrees) are observed behaviour: both FAIL before the helper.
    for evidence in ("if still_running and started:",
                     "if still_running and len(after_signal) >= 2:"):
        assert body.index(evidence) < last_skip, evidence
