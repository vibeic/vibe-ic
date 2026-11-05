#!/usr/bin/env python3
"""#528 — the enumerating check, and the four gates that land with it.

WHAT IS BEING PINNED, AND WHY IN THIS SHAPE
===========================================
#515 and #521 each fixed a batch of gates that exited 0 while their own report
said `skipped: true`, and each was driven by a BEHAVIOURAL sweep that could
reach 47% of the population — because making a gate skip needs its CLI
interface AND a crafted input, and a gate that refuses the probe's argv leaves
the denominator silently.

So the tests below are deliberately split in two, and the split is the point:

  * the ROUTING of the four gates fixed here is pinned by EXECUTION, through
    `flow_compliance_check._check_program_exit_zero` — the shipped function,
    unmocked, running the real gate as a real subprocess. Asserting `rc == 2`
    alone proves the gate changed its mind, not that the tier moved.

  * the ENUMERATION is pinned by driving `gate_skip_routing_check` over
    SYNTHETIC plugin trees built here, so its predicates are exercised on
    inputs whose right answer is known by construction — including a gate whose
    only interface is a flag, which is the shape that made the sweeps blind.

The one thing NOT tested by executing a gate is the enumeration's own reach,
because there is nothing to execute: it reads source. What IS tested is that it
FIRES on a planted defect and that its recognisers do not fire on the two
shapes measured to be false positives.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


# ==========================================================================
# 1. THE CONSUMER CONTRACT — measured, not assumed.
#
# Everything this check decides rests on WHICH channels the tier-deciding
# consumer reads. That claim is verified against the shipped function rather
# than restated from its docstring.
# ==========================================================================


def test_consumer_reads_only_two_channels(tmp_path, monkeypatch):
    """A JSON report saying VACUOUS_PASS is NOT a third channel.

    `_check_program_exit_zero` never opens the report file, so a gate whose
    only disclosure is `{"verdict": "VACUOUS_PASS"}` in its `--json` target is
    credited a plain PASS. This is why the check does not accept the report as
    routing.
    """
    # `_resolve_program_cmd` resolves a bare name against the module's
    # PROGRAMS_DIR, read at call time. The fixture is planted in a tmp programs
    # dir and the REAL consumer is pointed at it -- never written into the
    # shipped programs/, where a parallel worker globbing programs/*.py would
    # see it appear and vanish.
    progs = tmp_path / "programs"
    progs.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(_flow, "PROGRAMS_DIR", progs)
    gate = progs / "_i528_report_only_disclosure_check.py"
    gate.write_text(textwrap.dedent('''\
        """Temporary fixture planted by test_gate_skip_routing_check."""
        import json, sys
        from pathlib import Path
        Path("out.json").write_text(json.dumps({"verdict": "VACUOUS_PASS"}))
        print("examined nothing")
        sys.exit(0)
        '''), encoding="utf-8")
    passed, out = _flow._check_program_exit_zero(
        project, "_i528_report_only_disclosure_check")
    assert passed is True, out
    assert not out.startswith("__VACUOUS_HINT__"), (
        "a report-only disclosure was promoted to VACUOUS; the check's "
        "two-channel model would then be wrong")
    assert json.loads((project / "out.json").read_text())["verdict"] == \
        "VACUOUS_PASS", "the fixture did write the report the consumer ignored"


# ==========================================================================
# 2. THE ENUMERATION FIRES ON A PLANTED DEFECT — and on the shapes the
#    behavioural sweeps could not reach.
# ==========================================================================








































# ==========================================================================
# 3. THE RATCHET — all four directions.
# ==========================================================================














# ==========================================================================
# 4. THE EXCLUSION REGISTRY — reasons, in the code, checked.
# ==========================================================================






# ==========================================================================
# 5. THE FOUR GATES FIXED HERE — pinned through the REAL consumer.
# ==========================================================================
def _tier(project: Path, cmd: str) -> str:
    passed, out = _flow._check_program_exit_zero(project, cmd)
    if out.startswith("__VACUOUS_HINT__"):
        return "VACUOUS"
    if out.startswith("INCOMPLETE:"):
        return "INCOMPLETE"
    return "PASS" if passed else "FAIL"


def test_marketplace_sync_missing_manifest_reaches_rc_two(tmp_path):
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = _pr.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "no .claude-plugin/marketplace.json" in r.stdout


def test_marketplace_sync_manifest_without_plugins_array_reaches_rc_two(
        tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "x", "plugins": "not-a-list"}), encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = _pr.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2, (r.stdout, r.stderr)


@pytest.mark.parametrize("manifest", [
    pytest.param({"name": "x"}, id="plugins-key-ABSENT"),
    pytest.param({"name": "x", "plugins": []}, id="plugins-EMPTY-list"),
    pytest.param({"name": "x", "plugins": ["a", "b"]}, id="entries-not-dicts"),
])
def test_marketplace_sync_zero_comparisons_reaches_rc_two(tmp_path, manifest):
    """#528 follow-up — a PASS over zero version comparisons, three spellings.

    `.get("plugins", [])` hands back the default for an ABSENT key, and that
    default IS a list, so the `not isinstance(..., list)` guard never fires.
    Measured against the pre-#528 file, all three of these answered rc 0 with
    `[PASS] ... 0 plugin entr(ies)` — a plain PASS over nothing, in the gate
    `gatekeeper_review` treats as green when `rc in (0, -1)`.

    The routing is from `matched`, the gate's OWN record of what it compared,
    not from any of these input shapes — which is why one predicate covers all
    three and would cover a fourth spelling nobody has written yet.
    """
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = _pr.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "no version was compared" in r.stdout, r.stdout
    snippet = (r.stdout[-300:] + "\n" + r.stderr[-300:]).strip()
    assert _flow._stdout_signals_vacuous(snippet), snippet


def test_marketplace_sync_still_passes_when_it_compares_something(tmp_path):
    """MUTATION CONTROL for the three above: one real, in-sync entry.

    Without this, routing `matched == []` could be widened to route every PASS
    and no test would notice.
    """
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "x", "plugins": [
            {"name": "p", "source": "./p", "version": "1.2.3"}]}),
        encoding="utf-8")
    pj = tmp_path / "p" / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text(json.dumps({"version": "1.2.3"}),
                                    encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = _pr.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "1 plugin entr(ies)" in r.stdout, r.stdout


def test_marketplace_sync_still_fails_on_real_drift(tmp_path):
    """MUTATION CONTROL: a drifted entry must stay rc 1, never become vacuous.

    A FINDING beats a skip. If the zero-denominator branch were ever placed
    before the findings check, real drift would be silenced — which is worse
    than the defect being fixed.
    """
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "x", "plugins": [
            {"name": "p", "source": "./p", "version": "9.9.9"}]}),
        encoding="utf-8")
    pj = tmp_path / "p" / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text(json.dumps({"version": "1.2.3"}),
                                    encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = _pr.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 1, (r.stdout, r.stderr)


def test_marketplace_docstring_lists_exactly_its_three_vacuous_reasons():
    """The docstring promised a case the code did not implement.

    Round one said "a manifest with no plugins[] array", which reads like the
    ABSENT-key case; the code only covered "present and not a list". A
    docstring that describes a branch nobody wrote is how the gap survived
    review. Each reason token must appear in BOTH the module docstring and the
    code, so the two cannot drift apart again silently.
    """
    src = (_PROGRAMS / "marketplace_version_sync_check.py").read_text(
        encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    for reason in ("no-marketplace-json", "manifest-has-no-plugins-array",
                   "no-plugin-entries-compared"):
        assert reason in doc, f"{reason} is routed but undocumented"
        assert f'"{reason}"' in src, f"{reason} is documented but not routed"


def test_reports_taxonomy_empty_directory_is_the_same_zero_as_a_missing_one(
        tmp_path):
    """#528 follow-up, neighbour sweep — absent and empty are one denominator.

    This gate routed its vacuous tier from an INPUT SHAPE (`reports.is_dir()`).
    A reports/ that exists and holds nothing was examined exactly as much —
    zero entries — and answered `[PASS] ... all 0 reports/ entries match`.
    Both states must reach the same tier because the gate looked at the same
    nothing.
    """
    (tmp_path / "reports").mkdir()
    assert _tier(tmp_path, "reports_subfolder_taxonomy_check .") == "INCOMPLETE"
    missing = tmp_path / "sibling"
    missing.mkdir()
    assert _tier(missing, "reports_subfolder_taxonomy_check .") == "INCOMPLETE"


def test_reports_taxonomy_still_passes_over_a_populated_directory(tmp_path):
    """MUTATION CONTROL for the test above."""
    (tmp_path / "reports" / "phase1").mkdir(parents=True)
    assert _tier(tmp_path, "reports_subfolder_taxonomy_check .") == "PASS"


def test_top_level_outputs_already_routes_from_its_denominator(tmp_path):
    """The neighbour that was ALREADY right, pinned so it stays right.

    `top_level_outputs_in_canonical_check` computes `if not entries:
    vacuous_pass = True` — the denominator, not a directory test. Measured
    across every zero-denominator input it accepts, it answers VACUOUS; with
    one real entry it answers PASS. It is in this file because comparing it
    against `reports_subfolder_taxonomy_check` is what made the difference
    between "routes from the input shape" and "routes from the count" visible.
    """
    assert _tier(tmp_path, "top_level_outputs_in_canonical_check .") == "INCOMPLETE"
    populated = tmp_path / "p"
    (populated / "reports").mkdir(parents=True)
    assert _tier(populated, "top_level_outputs_in_canonical_check .") == "PASS"


@pytest.mark.parametrize("cwd,args", [
    (_PLUGIN, []),                                # repo_hygiene_gates.sh
    (_PLUGIN.parents[2], ["--marketplace-dir", str(_PLUGIN)]),  # gatekeeper
    (_PLUGIN.parents[2], ["--marketplace-dir", str(_PLUGIN.parents[1])]),
])
def test_marketplace_sync_landing_usages_are_unaffected(cwd, args):
    """Every real invocation in the repo still answers rc 0.

    `tools/ci/pre_commit_check.sh` (guarded on `.claude-plugin` existing),
    `tools/ci/repo_hygiene_gates.sh` (cwd = the plugin) and
    `.github/workflows/gatekeeper-ci.yml` (`--marketplace-dir`) all supply a
    tree where the manifest exists, so the changed branch never fires there.
    """
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = _pr.run([sys.executable, str(prog), *args], cwd=str(cwd),
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_marketplace_sync_gate_wrapper_no_longer_greens_an_empty_tree(tmp_path):
    """`gatekeeper_review.GateResult.green` is `rc in (0, -1)`.

    Before #528 this gate answered rc 0 over a tree with no manifest, so a
    MERGE gate was green about a comparison that never happened.
    """
    import gatekeeper_review as gr
    assert gr.marketplace_sync_gate(_PLUGIN).green is True
    assert gr.marketplace_sync_gate(tmp_path).green is False


def test_reports_taxonomy_skip_reaches_the_vacuous_tier(tmp_path):
    assert _tier(tmp_path, "reports_subfolder_taxonomy_check .") == "INCOMPLETE"


def test_top_level_outputs_skip_reaches_the_vacuous_tier(tmp_path):
    assert _tier(tmp_path, "top_level_outputs_in_canonical_check .") == "INCOMPLETE"


def test_cross_layer_reference_skip_reaches_the_vacuous_tier(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_SYSTEM_OVERVIEW.json").write_text('{"a": 1}', encoding="utf-8")
    assert _tier(tmp_path, "cross_layer_reference_check .") == "VACUOUS"


def test_cross_layer_corpus_mode_is_untouched():
    """The mode `tools/ci/repo_hygiene_gates.sh` runs returns before the
    changed branch, and that script's `run` helper treats ANY non-zero rc as a
    hard FAILED — so this is the assertion that would have caught a regression
    in CI rather than in review."""
    src = (_PROGRAMS / "cross_layer_reference_check.py").read_text(
        encoding="utf-8")
    corpus_block, _, project_block = src.partition("if not args.project:")
    assert "VACUOUS_PASS" not in corpus_block.split("def main")[-1], (
        "the corpus path must not have grown a vacuous branch; CI's `run` "
        "helper would turn its rc 2 into a hard FAILED")
    assert "_vx.exit_code" in project_block
