"""Tests for agent_checkin_scope_guard.py — the 5-agent check-in path-scope gate.

This guard is a RESTRICTING gate, so per the open-benchmark-methodology § 4.05
doctrine the load-bearing half is the NEGATIVE no-leak proof: for every
restricted role we assert the guard STILL CATCHES a path that sits JUST OUTSIDE
its allow-list (a plugin path for the benchmark-agent, a benchmark-data path for
the field-agent, etc.). The positive cases prove the allow-list fires; the
negative cases prove it is not too wide.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import agent_checkin_scope_guard as g  # noqa: E402

# Canonical sample paths, one per protected zone.
P_BENCH_DATA = "benchmark-data/ic/spm/reports/final_summary.md"
P_BENCH_RUN = "benchmark-data/evaluation/rtllm/run_blind/samples/foo.v"
P_BACKLOG = "vibe-ic-marketplace/community/backlogs/ORGANIC-20260613-x.yaml"
P_PLUGIN = "vibe-ic-marketplace/plugins/vibe-ic/programs/design_one_shot_runner.py"
P_PLUGIN_SKILL = "vibe-ic-marketplace/plugins/vibe-ic/skills/phase1/SKILL.md"
P_MCP = "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/index.js"
P_ROOT = "README.md"
P_TOOLS = "tools/gen_programs_index.py"


# --------------------------------------------------------------------------
# core-agent — unrestricted (owns plugin + MCP + everything)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    P_BENCH_DATA, P_BACKLOG, P_PLUGIN, P_PLUGIN_SKILL, P_MCP, P_ROOT, P_TOOLS,
])
def test_core_agent_may_touch_anything(path):
    assert g.evaluate("core-agent", [path]) == []


# --------------------------------------------------------------------------
# benchmark-agent (2026-06-21 "USE PR to issue bugs"): benchmark-data/ (results)
# AND plugin/MCP (fixes via version-less PR) allowed — but NEVER MIXED in one
# commit (the anti-gaming NO-MIX invariant). backlog + other paths denied.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    P_BENCH_DATA, P_BENCH_RUN,         # results
    P_PLUGIN, P_PLUGIN_SKILL, P_MCP,   # plugin/MCP fixes (pure commit, for a PR)
])
def test_benchmark_agent_pure_result_or_pure_fix_passes(path):
    assert g.evaluate("benchmark-agent", [path]) == []


@pytest.mark.parametrize("path,zone", [
    (P_BACKLOG, "backlog"),        # NO MORE backlog — must now be caught
    (P_ROOT, "repo (other)"),
    (P_TOOLS, "repo (other)"),
])
def test_benchmark_agent_forbidden_paths_still_caught(path, zone):
    """NO-LEAK: benchmark-agent must NEVER pass a backlog / root / tools path."""
    viol = g.evaluate("benchmark-agent", [path])
    assert len(viol) == 1
    assert viol[0]["path"] == path
    assert viol[0]["zone"] == zone


def test_benchmark_agent_NOMIX_results_plus_plugin_is_blocked():
    """§4.05 LOAD-BEARING: the anti-gaming NO-MIX invariant must catch a commit
    that bundles a benchmark RESULT with a plugin/MCP edit (the hand-patch-and-
    report-the-inflated-number vector)."""
    for fix in (P_PLUGIN, P_PLUGIN_SKILL, P_MCP):
        viol = g.evaluate("benchmark-agent", [P_BENCH_DATA, fix])
        zones = [v["zone"] for v in viol]
        assert any(z.startswith("NO-MIX") for z in zones), (fix, zones)


def test_benchmark_agent_NOMIX_no_leak_pure_commits_pass():
    """§4.05 no-leak boundary: ONLY the MIX is blocked — a pure plugin-fix commit
    (no results) and a pure result commit (no plugin) both PASS, so the gate is
    not too wide and still lets the legitimate PR / result channels through."""
    assert g.evaluate("benchmark-agent", [P_PLUGIN, P_PLUGIN_SKILL, P_MCP]) == []   # pure fix
    assert g.evaluate("benchmark-agent", [P_BENCH_DATA, P_BENCH_RUN]) == []          # pure results


# --------------------------------------------------------------------------
# field-agent — ONLY backlog; benchmark-data + plugin + MCP all denied
# (the user's explicit rule: Field Agent cannot check in to Benchmark / plugin / MCP)
# --------------------------------------------------------------------------
def test_field_agent_backlog_passes():
    assert g.evaluate("field-agent", [P_BACKLOG]) == []


@pytest.mark.parametrize("path,zone", [
    (P_BENCH_DATA, "benchmark-data"),   # NO-LEAK: field-agent ≠ benchmark-data
    (P_BENCH_RUN, "benchmark-data"),
    (P_PLUGIN, "plugin"),
    (P_MCP, "MCP (mcp-eda)"),
    (P_ROOT, "repo (other)"),
])
def test_field_agent_forbidden_paths_still_caught(path, zone):
    viol = g.evaluate("field-agent", [path])
    assert len(viol) == 1
    assert viol[0]["zone"] == zone


# --------------------------------------------------------------------------
# ic-expert-agent — design-time, NOTHING may be checked in
# --------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["ic-expert-agent"])
@pytest.mark.parametrize("path", [P_BENCH_DATA, P_BACKLOG, P_PLUGIN, P_MCP, P_ROOT])
def test_design_time_roles_may_not_check_in_anything(role, path):
    assert len(g.evaluate(role, [path])) == 1


# --------------------------------------------------------------------------
# Mixed lists, dedup, normalization
# --------------------------------------------------------------------------
def test_mixed_list_reports_only_the_offender():
    # benchmark-agent: a pure result + a now-forbidden backlog path -> only the
    # backlog is an offender (no plugin present, so no NO-MIX).
    viol = g.evaluate("benchmark-agent", [P_BENCH_DATA, P_BACKLOG])
    assert [v["path"] for v in viol] == [P_BACKLOG]


def test_path_normalization_absolute_and_dotslash():
    abs_backlog = "/home/testuser/vibe-ic/" + P_BACKLOG
    assert g.normalize_path("/home/testuser/vibe-ic/" + P_PLUGIN) == P_PLUGIN
    assert g.normalize_path("./" + P_BENCH_DATA) == P_BENCH_DATA
    # benchmark-agent: an absolute BACKLOG path (now forbidden) still gets caught
    assert len(g.evaluate("benchmark-agent", [abs_backlog])) == 1


def test_duplicate_paths_collapsed():
    # use a still-forbidden path (backlog) so dedup collapses to a single violation
    viol = g.evaluate("benchmark-agent", [P_BACKLOG, P_BACKLOG, "./" + P_BACKLOG])
    assert len(viol) == 1


def test_mcp_classified_before_plugin():
    # mcp-eda is under the plugin tree; the tighter zone must win.
    assert g.classify_zone(P_MCP) == "MCP (mcp-eda)"
    assert g.classify_zone(P_PLUGIN) == "plugin"


# --------------------------------------------------------------------------
# CLI exit codes
# --------------------------------------------------------------------------
def test_cli_pass(capsys):
    assert g.main(["--role", "benchmark-agent", "--paths", P_BENCH_DATA]) == 0


def test_cli_fail(capsys):
    # backlog is now forbidden for benchmark-agent (PR-not-backlog directive)
    rc = g.main(["--role", "benchmark-agent", "--paths", P_BACKLOG])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "backlog" in out


def test_cli_fail_nomix(capsys):
    # NO-MIX: bundling a result with a plugin edit fails with the split hint
    rc = g.main(["--role", "benchmark-agent", "--paths", P_BENCH_DATA, P_PLUGIN])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "NO-MIX" in out and "SPLIT" in out.upper()


def test_cli_unknown_role_is_arg_error():
    assert g.main(["--role", "nope-agent", "--paths", P_ROOT]) == 2


def test_cli_missing_role_is_arg_error():
    assert g.main(["--paths", P_ROOT]) == 2


def test_cli_list_roles_ok(capsys):
    assert g.main(["--list-roles"]) == 0
    out = capsys.readouterr().out
    for role in g.ROLE_ALLOW:
        assert role in out


def test_cli_no_path_source_is_arg_error():
    assert g.main(["--role", "core-agent"]) == 2


def test_every_known_role_has_a_description():
    assert set(g.ROLE_DESC) == set(g.ROLE_ALLOW)
