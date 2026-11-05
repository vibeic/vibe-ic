#!/usr/bin/env python3
"""Tests for gatekeeper_review.py — the deterministic PR gatekeeper that
AGGREGATES the existing governance programs against a PR change-set and emits a
verdict (chip-AGNOSTIC).


The §4.05/General/no-cheat AGENT-JUDGMENT gate is INTENTIONALLY NOT covered
here — it is the loop's Step-2.7 (documented in the program docstring); a test
of that boundary asserts the program does NOT claim to evaluate it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1] / "gatekeeper_review.py"
_spec = importlib.util.spec_from_file_location("gatekeeper_review", _PROG)
gk = importlib.util.module_from_spec(_spec)
sys.modules["gatekeeper_review"] = gk          # required: @dataclass needs it
_spec.loader.exec_module(gk)


def _a_real_deny_token() -> str:
    """Return one token from the CANONICAL chip deny list shipped with the real
    source_chip_agnostic_check program. The gate reads THAT list (not the
    synthetic plugin's), so a chip-token test must use a token that is really
    on it. Falls back to a known historical token if the file is unreadable."""
    deny = Path(__file__).resolve().parent / "chip_deny_list.txt"
    try:
        for ln in deny.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                return s
    except OSError:
        pass
    return "md905"


# ---------------------------------------------------------------------------
# Synthetic plugin-root builder: the minimal tree the file-walking gates need
# to report PASS, so a clean diff yields a clean machine verdict.
# ---------------------------------------------------------------------------
def _build_clean_plugin(tmp_path: Path, version: str = "1.0.96") -> Path:
    """Create .../vibe-ic-marketplace/plugins/vibe-ic with a single program +
    its test, an empty deny list, a flow YAML with a substance gate, and a
    matching marketplace.json — everything the composed gates inspect."""
    repo = tmp_path
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": version}) + "\n")

    # marketplace.json pinned to the SAME version (sync gate PASS).
    mkt_dir = repo / "vibe-ic-marketplace" / ".claude-plugin"
    mkt_dir.mkdir(parents=True)
    (mkt_dir / "marketplace.json").write_text(json.dumps({
        "name": "vibe-ic-marketplace",
        "plugins": [{"name": "vibe-ic",
                     "source": "./plugins/vibe-ic",
                     "version": version}],
    }) + "\n")

    # one program + its test (D1 PASS).
    progs = plugin / "programs"
    (progs / "tests").mkdir(parents=True)
    (progs / "widget.py").write_text("def go():\n    return 1\n")
    (progs / "tests" / "test_widget.py").write_text(
        "import widget\n\ndef test_go():\n    assert widget.go() == 1\n")
    (progs / "tests" / "chip_deny_list.txt").write_text("# empty deny list\n")

    # flow YAML with a substance gate so D2 (file_presence_only) is clean.
    flow = plugin / "flow"
    flow.mkdir()
    (flow / "phase1_phase2_phase3.yaml").write_text(
        "steps:\n"
        "  - id: s1\n"
        '    gate:\n'
        '      program_exit_zero: "widget"\n')
    # D2 also delegates to gate_self_assertion_check + single_testpath_guard
    # + flow_condition_reachability_check (vibe-ic#220); ship inert
    # pass-through stand-ins so the audit does not flag them missing. This
    # tuple must track audit_d2's guard list.
    for guard in (
                  "flow_condition_reachability_check"):
        (progs / f"{guard}.py").write_text(
            "import sys\n"
            "def main(argv=None):\n"
            "    return 0\n"
            "if __name__ == '__main__':\n"
            "    sys.exit(main())\n")
        (progs / "tests" / f"test_{guard}.py").write_text(
            f"import {guard}\n\ndef test_ok():\n    assert {guard}.main([]) == 0\n")
    # Full review consumes hygiene evidence and a BASE-owned debt ledger.
    # This fixture's tiny hygiene producer checks its own widget; it does not
    # run the repository's global corpus or replace the debt adjudicator.
    import test_issue1498_hygiene_subset_rule_is_wired as H
    record = H._record([H._gate("fixture widget", "PASS")])
    script = repo / "fixture-hygiene.sh"
    script.write_text("python3 - \"$@\" <<'PY'\n"
        "import argparse,json,pathlib,runpy,sys\n"
        "p=argparse.ArgumentParser();p.add_argument('--summary-json');a=p.parse_args()\n"
        "widget=pathlib.Path('vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py')\n"
        "assert runpy.run_path(str(widget))['go']() == 1\n"
        f"pathlib.Path(a.summary_json).write_text({json.dumps(record)!r})\n"
        "PY\n")
    import subprocess
    # Keep the audit scaffolding in BASE: the subject is a widget repair,
    # not an addition of the fixture's synthetic gates or flow declaration.
    (progs / "widget.py").write_text("def go():\n    return 0\n")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@invalid", "commit", "-qm", "fixture BASE ledger"], check=True)
    subprocess.run(["git", "-C", str(repo), "tag", "BASE"], check=True)
    # The review is of one real candidate commit, not BASE reviewing itself.
    # Repair real behavior while the debt ledger and scaffolding stay BASE-owned.
    (progs / "widget.py").write_text("def go():\n    return 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@invalid", "commit", "-qm",
                    "repair fixture widget result"], check=True)
    return repo, plugin


@pytest.fixture(autouse=True)
def _route_fixture_hygiene(monkeypatch):
    """Use the existing explicit script seam for this module's tiny subject."""
    actual = gk.repo_hygiene_gate

    def run(repo, **kwargs):
        script = repo / "fixture-hygiene.sh"
        if script.is_file() and kwargs.get("script") is None:
            kwargs["script"] = script
        return actual(repo, **kwargs)

    monkeypatch.setattr(gk, "repo_hygiene_gate", run)


# ---------------------------------------------------------------------------
# 1. clean diff -> MERGE_OK
# ---------------------------------------------------------------------------
def test_clean_diff_merge_ok(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    _write_ppa_answers(repo, plugin)
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="core-agent",
        commit_cmds=["git commit -m 'fix'", "git push origin main"],
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    # Every machine gate green => MERGE_OK.
    by_name = {g.name: g for g in v.gates}
    assert by_name["version_bump_monotonic_check"].rc == 0
    assert by_name["source_chip_agnostic_check"].rc == 0
    assert by_name["git_prohibition_guard"].rc == 0
    assert by_name["full_suite_run_check"].rc == 0
    assert v.verdict == "MERGE_OK", v.blocking
    assert v.blocking == []


# ---------------------------------------------------------------------------
# 2. a diff adding a chip-token -> REQUEST_CHANGES
# ---------------------------------------------------------------------------
def test_chip_token_request_changes(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    # source_chip_agnostic_check reads the CANONICAL deny list shipped with the
    # real program (programs/tests/chip_deny_list.txt) — not the synthetic
    # plugin's. So we plant a token that is ALREADY on that canonical list into
    # the synthetic plugin's non-allowlisted source (programs/widget.py).
    token = _a_real_deny_token()
    (plugin / "programs" / "widget.py").write_text(
        f"# target part: {token}\ndef go():\n    return 1\n")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["source_chip_agnostic_check"].rc == 1, \
        by_name["source_chip_agnostic_check"].summary
    assert v.verdict == "REQUEST_CHANGES"
    assert any("source_chip_agnostic_check" in b for b in v.blocking)




# ---------------------------------------------------------------------------
# 4. a non-monotonic version (current <= previous) -> REQUEST_CHANGES
# ---------------------------------------------------------------------------
def test_non_monotonic_version_request_changes(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.95")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        # current == previous == 1.0.95: NO bump.
        override_cur="1.0.95", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["version_bump_monotonic_check"].rc == 1, \
        by_name["version_bump_monotonic_check"].summary
    assert v.verdict == "REQUEST_CHANGES"
    assert any("version_bump_monotonic_check" in b for b in v.blocking)


def test_regression_version_request_changes(tmp_path):
    """A version DOWNGRADE is also a non-monotonic FAIL."""
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.94")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.94", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["version_bump_monotonic_check"].rc == 1
    assert v.verdict == "REQUEST_CHANGES"


# ---------------------------------------------------------------------------
# 5. cadence selection: x.y.0 -> FULL ; x.y.Z (Z>0) -> TARGETED
# ---------------------------------------------------------------------------
def test_cadence_minor_milestone_selects_full(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.1.0")
    _write_ppa_answers(repo, plugin)
    # A FULL milestone with a full-suite pytest cmd => cadence gate PASS.
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        # THE RUNNER, not a bare `pytest`. Since the 2026-08-31 ruling the
        # cadence gate judges COVERAGE of the tracked corpus, and a bare
        # `pytest` resolves to `pytest.ini`'s single testpath — one tree of
        # five. `./run_tests.sh` is the invocation that reaches all of them.
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.1.0", override_prev="1.0.99",
    )
    assert v.cadence == "FULL", v.version_bump
    by_name = {g.name: g for g in v.gates}
    assert v.verdict == "MERGE_OK", v.blocking




def test_cadence_patch_selects_targeted(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    _write_ppa_answers(repo, plugin)
    # A patch with a SUBSET pytest run is fine for TARGETED cadence.
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    assert v.cadence == "TARGETED", v.version_bump
    by_name = {g.name: g for g in v.gates}
    assert v.verdict == "MERGE_OK", v.blocking


def test_derive_cadence_unit():
    assert gk.derive_cadence("1.1.0", "1.0.99")[0] == "FULL"
    assert gk.derive_cadence("1.0.96", "1.0.95")[0] == "TARGETED"
    assert gk.derive_cadence("2.0.0", "1.9.9")[0] == "FULL"
    assert gk.derive_cadence(None, None)[0] == "NONE"


# ---------------------------------------------------------------------------
# 6. out-of-scope-by-role touching the plugin/MCP -> REJECT
# ---------------------------------------------------------------------------
def test_out_of_scope_role_touching_mcp_rejects(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="field-agent",                    # may only touch backlog
        override_files=[
            "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/server.py",  # MCP!
        ],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["agent_checkin_scope_guard"].rc == 1, \
        by_name["agent_checkin_scope_guard"].summary
    assert v.verdict == "REJECT", v.blocking


def test_out_of_scope_role_touching_plugin_rejects(tmp_path):
    # field-agent is still backlog-only — touching the plugin is out-of-scope -> REJECT.
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="field-agent",                    # backlog only
        override_files=[
            "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py",  # plugin!
        ],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    assert v.verdict == "REJECT", v.blocking


def test_benchmark_agent_pure_plugin_fix_not_rejected_by_scope(tmp_path):
    """2026-06-21 "USE PR to issue bugs": a benchmark-agent PURE plugin-fix PR
    (no benchmark-data/ paths) is in-scope — the scope gate must NOT REJECT it."""
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="benchmark-agent",
        override_files=[
            "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py",  # pure plugin fix
        ],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    assert v.verdict != "REJECT", v.blocking


def test_benchmark_agent_mixed_results_and_plugin_rejects(tmp_path):
    """NO-MIX anti-gaming: a benchmark-agent commit that bundles a benchmark RESULT
    with a plugin edit is unsalvageable -> REJECT (split into a pure result commit
    + a pure plugin-fix PR)."""
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="benchmark-agent",
        override_files=[
            "benchmark-data/evaluation/rtllm/run/RESULT.md",          # a RESULT
            "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py",  # + a plugin edit
        ],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    assert v.verdict == "REJECT", v.blocking


def test_in_scope_role_not_rejected(tmp_path):
    """A field-agent touching ONLY the backlog is in scope (no REJECT)."""
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin,
        role="field-agent",
        override_files=[
            "vibe-ic-marketplace/community/backlogs/item-1.yaml",
        ],
        override_cur=None, override_prev=None,  # backlog-only PR: no version bump
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["agent_checkin_scope_guard"].rc == 0
    assert v.verdict != "REJECT"


# ---------------------------------------------------------------------------
# 7. git_prohibition_guard composition: a forbidden git op in the commit
#    command strings blocks the PR.
# ---------------------------------------------------------------------------
def test_forbidden_git_op_request_changes(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        commit_cmds=["git push --force origin main"],   # forbidden
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["git_prohibition_guard"].rc == 1, \
        by_name["git_prohibition_guard"].summary
    assert v.verdict == "REQUEST_CHANGES"
    assert any("git_prohibition_guard" in b for b in v.blocking)


def test_force_with_lease_is_allowed(tmp_path):
    """--force-with-lease is the safe sibling and must NOT be flagged."""
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    _write_ppa_answers(repo, plugin)
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        commit_cmds=["git push --force-with-lease origin main"],
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["git_prohibition_guard"].rc == 0
    assert v.verdict == "MERGE_OK", v.blocking


# ---------------------------------------------------------------------------
# 8. JSON shape: admission scope and advisory state remain explicit.
# ---------------------------------------------------------------------------
def test_json_five_section_shape(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    d = gk._verdict_to_dict(v)
    assert set(d.keys()) == {"verdict", "gates", "cadence", "scope",
                             "standalone_admission", "required_parent_units",
                             "version_bump", "blocking"}
    assert isinstance(d["gates"], list) and d["gates"]
    for g in d["gates"]:
        assert set(g.keys()) == {"name", "rc", "summary", "advisory"}
    assert d["verdict"] in ("MERGE_OK", "REQUEST_CHANGES", "REJECT")


# ---------------------------------------------------------------------------
# 9. CLI end-to-end via main() with --changed-file + --json.
# ---------------------------------------------------------------------------
#: THE APPENDIX-C ANSWERS DOCUMENT A MERGE-OK FIXTURE NOW NEEDS.
#:
#: `ppa_pr_scope_check`'s absent-document arm became BLOCKING on 2026-08-31 by
#: the expiry condition gatekeeper_review.py had written for itself, so a
#: fixture that reaches MERGE_OK must answer the merge condition like any other
#: change-set. This is NOT a relaxation of the fixture: the document is
#: verified, and every piece of evidence in it has to resolve — the artefact's
#: sha256 is computed from the file rather than asserted, and the two `test`
#: refs name a test that exists. An answers document that lied would leave the
#: gate red, which is the point of the gate.
def _write_ppa_answers(repo, plugin):
    import hashlib
    rel_src = "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"
    rel_tst = ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
               "test_widget.py::test_go")
    # Preserve the existing behavior assertion and bind the actual source;
    # do not replace it with assert True or invent a physical measurement.
    digest = "sha256:" + hashlib.sha256((repo / rel_src).read_bytes()).hexdigest()
    gh = repo / ".github"
    gh.mkdir(parents=True, exist_ok=True)
    (gh / "ppa_pr_answers.json").write_text(json.dumps({
        "schema": "vibeic.ppa.pr_answers.v1",
        "answers": [
            {"question": 1, "evidence": [{"kind": "path", "ref": rel_src}]},
            {"question": 2, "evidence": [{"kind": "path", "ref": rel_src}]},
            {"question": 3, "evidence": [{"kind": "artefact", "ref": rel_src,
                                          "sha256": digest}]},
            {"question": 4, "evidence": [{"kind": "test", "ref": rel_tst}]},
            {"question": 5, "evidence": [{"kind": "test", "ref": rel_tst}]},
        ],
    }, indent=2) + "\n")


def test_cli_main_merge_ok(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    # The Appendix-C merge condition is blocking on ALL arms since 2026-08-31,
    # its absent arm included, so a MERGE_OK fixture answers it.
    _write_ppa_answers(repo, plugin)
    # Initialise a real git repo so the version-resolution path (head/base
    # plugin.json) works through `git show`.
    import subprocess
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os
    full_env = {**os.environ, **env}
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    # base commit with version 1.0.95.
    pj = plugin / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "1.0.95"}) + "\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"],
                   check=True, env=full_env)
    base_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    # head commit with version 1.0.96 + matching marketplace.
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "1.0.96"}) + "\n")
    mkt = repo / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    md = json.loads(mkt.read_text())
    md["plugins"][0]["version"] = "1.0.96"
    mkt.write_text(json.dumps(md) + "\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "head"],
                   check=True, env=full_env)

    changed = tmp_path / "changed.txt"
    changed.write_text(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py\n")
    out_json = tmp_path / "verdict.json"

    rc = gk.main([
        "--base", base_sha, "--head", "HEAD",
        "--role", "core-agent",
        "--repo", str(repo),
        "--plugin-root", str(plugin),
        "--changed-file", str(changed),
        "--json", str(out_json),
    ])
    assert rc == 0, out_json.read_text()
    report = json.loads(out_json.read_text())
    assert report["verdict"] == "MERGE_OK", report["blocking"]
    assert report["cadence"] == "TARGETED"
    assert report["version_bump"] == "1.0.95->1.0.96"





def test_cli_main_request_changes_rc1(tmp_path):
    """main() returns rc=1 for REQUEST_CHANGES (here: a non-monotonic bump)."""
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.95")
    changed = tmp_path / "changed.txt"
    changed.write_text(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py\n")
    # Drive a real chip token (already on the canonical deny list) to force
    # REQUEST_CHANGES deterministically through the CLI source-agnostic gate.
    token = _a_real_deny_token()
    (plugin / "programs" / "widget.py").write_text(
        f"# part {token}\ndef go():\n    return 1\n")
    import subprocess, os
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    full_env = {**os.environ, **env}
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"],
                   check=True, env=full_env)
    base_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    pj = plugin / ".claude-plugin" / "plugin.json"
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "1.0.96"}) + "\n")
    mkt = repo / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    md = json.loads(mkt.read_text()); md["plugins"][0]["version"] = "1.0.96"
    mkt.write_text(json.dumps(md) + "\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "head"],
                   check=True, env=full_env)
    rc = gk.main([
        "--base", base_sha, "--head", "HEAD",
        "--role", "core-agent",
        "--repo", str(repo), "--plugin-root", str(plugin),
        "--changed-file", str(changed),
    ])
    assert rc == 1


# ---------------------------------------------------------------------------
# 10. §4.05 BOUNDARY: this program must NOT claim to evaluate the agent-judgment
#     gate. We assert (a) no gate named for §4.05/general/no-cheat exists, and
#     (b) the docstring documents the boundary + Step-2.7 ownership.
# ---------------------------------------------------------------------------
def test_no_agent_judgment_gate_present(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    names = {g.name for g in v.gates}
    for forbidden in ("agent_judgment", "no_cheat", "general_check",
                      "section_4_05", "4.05", "leak_check"):
        assert forbidden not in names


def test_docstring_documents_step_2_7_boundary():
    doc = gk.__doc__ or ""
    assert "Step-2.7" in doc
    assert "4.05" in doc
    # The verdict-printer footer also reminds the caller.
    src = _PROG.read_text(encoding="utf-8")
    assert "Step-2.7" in src and "before merge" in src


# ---------------------------------------------------------------------------
# 11. blindness gate is optional + non-blocking when transcripts absent.
# ---------------------------------------------------------------------------
def test_blindness_skipped_when_absent(tmp_path):
    repo, plugin = _build_clean_plugin(tmp_path, version="1.0.96")
    _write_ppa_answers(repo, plugin)
    v = gk.review(
        "BASE", "HEAD",
        repo=repo, plugin_root=plugin, role="core-agent",
        override_files=["vibe-ic-marketplace/plugins/vibe-ic/programs/widget.py"],
        override_cur="1.0.96", override_prev="1.0.95",
    )
    by_name = {g.name: g for g in v.gates}
    assert by_name["blindness_audit"].rc == -1  # SKIP, non-blocking
    assert v.verdict == "MERGE_OK", v.blocking


# ---------------------------------------------------------------------------
# vibe-ic#1208 — `_run_program` is the one chokepoint all 15 gate drivers go
# through, and it had no `timeout=` at all. The wait lands in
# `subprocess.communicate` -> `selector.poll`, which `--timeout-method=thread`
# cannot interrupt, so THREE of this file's sibling modules could not be run in
# a pinned selection on clean a38902d1 at all: the invocation produced no
# summary line, which greps as neither a pass nor a failure.
# ---------------------------------------------------------------------------
def _sleeper(tmp_path: Path, seconds: float) -> Path:
    p = tmp_path / "sleeper.py"
    p.write_text(f"import time\ntime.sleep({seconds})\n")
    return p


def test_a_driven_program_that_overruns_is_STOPPED(tmp_path):
    """The bound exists. Without it this call never returns."""
    import time
    t0 = time.monotonic()
    rc, _out, err = gk._run_program(_sleeper(tmp_path, 30), [], timeout=1.0)
    elapsed = time.monotonic() - t0
    # THE BOUND FIRED. That is what `1208` in the error text means, and it is
    # the same statement `elapsed < 15` was making with a stopwatch — except
    # this one cannot be flipped by another tenant on the host. The 30 s sleeper
    # is what makes it non-vacuous: without the bound there is no `1208` to find.
    assert "1208" in err, (err, f"observed {elapsed:.1f}s")
    assert rc != 0, (rc, "a program that was STOPPED reported success")


def test_an_overrun_is_NEVER_reported_as_a_clean_result(tmp_path):
    """The half that matters. A bounded wait that returned 0 would be a WORSE
    defect than the hang: it converts "never finished" into "clean", and every
    caller here treats rc 0 as a passing gate."""
    rc, _out, err = gk._run_program(_sleeper(tmp_path, 30), [], timeout=1.0)
    assert rc != 0, (rc, err)
    assert rc == 124, rc
    assert "UNDETERMINED" in err, err


def test_a_program_that_finishes_INSIDE_the_bound_still_returns_its_own_rc(
        tmp_path):
    """The inverse, without which the two above are satisfied by a
    `_run_program` that fails everything. Both a clean exit and a real
    non-zero must still come through unchanged."""
    ok = tmp_path / "ok.py"
    ok.write_text("print('fine')\n")
    rc, out, _err = gk._run_program(ok, [], timeout=60.0)
    assert rc == 0, rc
    assert "fine" in out, out

    bad = tmp_path / "bad.py"
    bad.write_text("import sys\nsys.exit(3)\n")
    rc2, _o, _e = gk._run_program(bad, [], timeout=60.0)
    assert rc2 == 3, rc2


# ---------------------------------------------------------------------------
# The ADVISORY disclosure wired in because nothing else ran it.
#
# `corpus_cardinality_pin_scan` was authored, tested and merged, and then
# reachable from no runner, no flow clause, no CI line and no skill. It is
# composed here — the gate a maintainer runs BEFORE every push — because that
# is where an author-facing report is still cheap to act on. It may never
# block, and it must DISCLOSE an absent subject rather than report a clean
# zero over a population nobody opened.
#
# (Its sibling, `content_pinned_authority_verified_only_at_merge`, read the
# protected-path byte register that the owner removed on 2026-09-27, and went
# with it.)
# ---------------------------------------------------------------------------
