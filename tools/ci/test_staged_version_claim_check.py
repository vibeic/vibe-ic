"""tests/test_staged_version_claim_check.py — pytest harness for the
mirror-leak guard.

Each test feeds a synthetic unified-zero diff via --diff-from-stdin and
asserts the exit code + stderr/stdout content. We rely on the program's
own argv plumbing rather than git fixtures so the test stays hermetic
and fast.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAM = Path(__file__).resolve().parent / "staged_version_claim_check.py"


def _make_plugin_json(tmp_path: Path, version: str) -> Path:
    """Write a plugin.json under the canonical path so the program's
    default --plugin-json discovery finds it."""
    p = tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / ".claude-plugin" / "plugin.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": "vibe-ic", "version": version}))
    return p


def _run(plugin_dir: Path, diff_text: str):
    return subprocess.run(
        [sys.executable, str(PROGRAM), "--diff-from-stdin",
         "--repo-root", str(plugin_dir)],
        input=diff_text, capture_output=True, text=True, timeout=10,
    )


# A synthetic unified=0 diff that adds N lines to a single file.
def _diff(path: str, *added_lines: str) -> str:
    body = (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -10,0 +11,{len(added_lines)} @@\n"
    )
    for ln in added_lines:
        body += f"+{ln}\n"
    return body


# ────────────────────────────────────────────────────────────────
# Happy paths
# ────────────────────────────────────────────────────────────────
def test_no_version_in_diff_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff("foo.py", "x = 1", "y = 'hello'"))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "PASS" in cp.stdout


def test_equal_version_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# bumped to v1.6.18 (matches plugin.json)"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_lower_version_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# legacy: v1.6.10 - obsolete handling"))
    assert cp.returncode == 0


def test_changelog_path_skipped(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "CHANGELOG.md", "## v1.6.99 (planned)"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_doc_artifact_version_reference_passes(tmp_path):
    # ALL_STEPS_v2.2.0 is a DOC-version namespace, not a plugin claim. A file
    # that REFERENCES the doc by name in prose — without a trailing extension,
    # or with a brace-glob the filename-extension carve-out misses — must NOT
    # be gated (regression for the v0.2.38 ② pre-commit false-positive).
    _make_plugin_json(tmp_path, "0.2.38")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_all_steps_covers_flow.py",
        "# guards docs/architecture/ALL_STEPS_v2.2.0.{md,zh-TW.md} vs the flow",
        "# the human-readable ALL_STEPS_v2.2.0 docs are hand-maintained"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_doc_artifact_carveout_does_not_mask_self_claim(tmp_path):
    # the doc-artifact carve-out must NOT exempt a real forward plugin self-claim
    _make_plugin_json(tmp_path, "0.2.38")
    cp = _run(tmp_path, _diff("src/x.py", "# ships in vibe-ic v0.3.0 release"))
    assert cp.returncode == 1
    assert "claimed v0.3.0" in cp.stdout


def test_community_backlog_prose_versions_skipped(tmp_path):
    # backlog filings quote external spec sections / doc versions in prose —
    # those are NOT plugin self-claims and the whole tree is path-skipped.
    _make_plugin_json(tmp_path, "0.2.39")
    cp = _run(tmp_path, _diff(
        "community/backlogs/ORGANIC-20260521-some-filing.yaml",
        "  Verilog 1995 §3.7.5 — identifiers are case-sensitive",
        "  1.2.3 Title; modern Markdown ## Architecture",
        '  Doc citing "Debug Module 0.13.2 defines exactly one of ..."'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


# ────────────────────────────────────────────────────────────────
# Historical-reference filtering
# ────────────────────────────────────────────────────────────────
def test_supersedes_historical_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# v2.0.0 supersedes the v1.6.99 design (mentioned for context)"))
    # The 'v2.0.0' comes first and is NOT preceded by historical kw → still
    # flagged. Only 'v1.6.99' (preceded by 'supersedes') is filtered.
    # That's the right behavior; if a commit claims v2.0.0 it should bump.
    # Confirm we caught the FIRST one (v2.0.0) but skipped the historical.
    assert cp.returncode == 1
    assert "claimed v2.0.0" in cp.stdout


def test_was_historical_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "  # field renamed (was v1.6.99 dtop_module_name)"))
    assert cp.returncode == 0, cp.stdout


def test_pre_historical_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# pre-v1.6.99 layout used the old key"))
    assert cp.returncode == 0


def test_from_historical_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# Imported from v1.6.99 of the upstream API"))
    assert cp.returncode == 0


def test_since_historical_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# this rule has been enforced since v1.6.99"))
    assert cp.returncode == 0


# ────────────────────────────────────────────────────────────────
# Real catch — the deFintek 9d4e984a pattern
# ────────────────────────────────────────────────────────────────
def test_forward_claim_fails_mirror_leak_pattern(tmp_path):
    """Reproduce the 9d4e984a pattern: code comment claims v1.6.19 but
    plugin.json is at 1.6.18 (the literal scenario that motivated this
    hook)."""
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/foo.py",
        "    # Schema v2 canonical field — added v1.6.19. Honoured before legacy"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v1.6.19" in cp.stdout
    assert "1.6.18" in cp.stdout


def test_forward_claim_in_test_name_fails(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "tests/test_x.py",
        "def test_v1_6_19_schema_v2_top_module_field_honoured(tmp_path):"))
    # underscore form `v1_6_19` is NOT picked up by the dot-only regex —
    # documented limitation. We don't gate that case (would have too many
    # false positives in identifier names).
    assert cp.returncode == 0


def test_forward_claim_dot_form_fails(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "tests/test_x.py", '    """v1.6.19 — drift detector for the two templates."""'))
    assert cp.returncode == 1


def test_minor_version_jump_fails(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# Wave 95 / v1.7.0 — protocol redesign"))
    assert cp.returncode == 1
    assert "claimed v1.7.0" in cp.stdout


def test_major_version_jump_fails(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff("src/x.py", "# v2.0.0 release"))
    assert cp.returncode == 1


# ────────────────────────────────────────────────────────────────
# Multi-line / multi-file diffs
# ────────────────────────────────────────────────────────────────
def test_multiple_violations_all_reported(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    diff = _diff(
        "src/a.py",
        "# v1.6.19 first claim",
        "x = 1",
        "# v1.7.0 second claim",
    )
    cp = _run(tmp_path, diff)
    assert cp.returncode == 1
    assert "claimed v1.6.19" in cp.stdout
    assert "claimed v1.7.0" in cp.stdout


def test_two_files_two_violations(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    diff = (
        _diff("src/a.py", "# v1.6.19 first")
        + _diff("src/b.py", "# v1.6.20 second")
    )
    cp = _run(tmp_path, diff)
    assert cp.returncode == 1
    assert "src/a.py" in cp.stdout
    assert "src/b.py" in cp.stdout


# ────────────────────────────────────────────────────────────────
# Robustness
# ────────────────────────────────────────────────────────────────
def test_ipv4_not_parsed_as_version(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, _diff(
        "src/x.py", "# server at <lan-ip>"))
    # <lan-ip> has 4 components, regex requires exactly 3 → no match.
    assert cp.returncode == 0, cp.stdout


def test_no_plugin_json_skips(tmp_path):
    # No plugin.json at all → SKIP
    cp = _run(tmp_path, _diff("src/x.py", "# v1.6.99 forward claim"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_empty_diff_passes(tmp_path):
    _make_plugin_json(tmp_path, "1.6.18")
    cp = _run(tmp_path, "")
    assert cp.returncode == 0


# ────────────────────────────────────────────────────────────────
# Program-internal version constants (.py) — separate semver namespace
# ────────────────────────────────────────────────────────────────
def test_program_version_constant_assignment_skipped(tmp_path):
    # A program's own `VERSION = "1.0.0"` is its semver, not a plugin claim,
    # even though 1.0.0 > the plugin's 0.2.27.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/ams_analysis_select.py",
        'VERSION = "1.0.0"'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_program_version_dict_field_skipped(tmp_path):
    # A report dict's `"version": "1.0.0",` inside a .py is the program's
    # own report-schema version, not a plugin claim.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/gds_topcell_name_check.py",
        '        "version": "1.0.0",'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_comment_claim_in_py_still_fails_despite_const_carveout(tmp_path):
    # The .py carve-out covers ONLY the assignment shape; a prose COMMENT
    # claim (the 9d4e984a motivating leak) in a .py must STILL fail.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/foo.py",
        "    # Schema v2 field — added v9.9.9. Honoured before legacy"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v9.9.9" in cp.stdout


# ────────────────────────────────────────────────────────────────
# Filename-embedded doc versions — separate version namespace
# ────────────────────────────────────────────────────────────────
def test_filename_embedded_doc_version_skipped(tmp_path):
    # A reference to a doc filename like ALL_STEPS_v2.2.0.md is the doc's
    # version, not a plugin claim (v2.2.0 > plugin 0.2.27 numerically).
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "docs/architecture/FLOW_STEPS_GENERATED.md",
        "> (`CANONICAL_FLOW_v2.2.0.md`, `ALL_STEPS_v2.2.0.md`) link here."))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_real_claim_alongside_filename_version_still_fails(tmp_path):
    # The filename carve-out is PER-MATCH: a genuine forward claim on the
    # same line as a filename-version reference must still fail.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "src/x.py", "see ALL_STEPS_v2.2.0.md ; now bumping to v9.9.9"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v9.9.9" in cp.stdout


def test_annotated_version_field_in_py_skipped(tmp_path):
    # A dataclass-annotated `version: str = "1.1.0"` is the program's own
    # semver field, not a plugin claim.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/foo.py",
        '    version: str = "1.1.0"'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_letter_prefixed_section_ref_skipped(tmp_path):
    # `A3.1.1` / `C3.4.1` are spec-section anchors (source citations in the
    # protocol-synth requirement tables), not semver — a digit triple whose
    # first digit is immediately preceded by a non-v letter is excluded.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/ace_protocol_synth.py",
        '    {"id": "FR-CLOCK-01", "text": "rising-edge", "source": "A3.1.1"},'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_v_prefixed_version_still_fails_not_treated_as_identifier(tmp_path):
    # The letter-prefix exclusion must NOT swallow a real `v`-prefixed claim:
    # `v` is consumed by the version regex, so the char before is whitespace.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff("src/x.py", "# bumping to v9.9.9 now"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v9.9.9" in cp.stdout


def test_historical_1_6_x_provenance_exempt(tmp_path):
    # The plugin RESET from the 1.6.x dev series to 0.2.x; a bare `v1.6.596`
    # provenance comment is a BACKWARD ref to the superseded scheme, not a
    # forward claim — must NOT fire (this is the recurring AID-sync false-positive).
    _make_plugin_json(tmp_path, "0.2.31")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/index.js",
        "  // ported from phase3_one_shot_runner v1.6.596 tie-cell discovery"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_historical_band_does_not_cover_future_1_0_x(tmp_path):
    # The band is the 1.6.x dev series only — a genuine forward 1.0.x claim
    # (the future release line) is still caught.
    _make_plugin_json(tmp_path, "1.0.0")
    cp = _run(tmp_path, _diff("src/x.py", "# bumping to v1.0.1 release"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v1.0.1" in cp.stdout


def test_forward_claim_in_current_scheme_still_fails_with_band(tmp_path):
    # The historical band must not weaken same-scheme forward-claim detection.
    _make_plugin_json(tmp_path, "0.2.31")
    cp = _run(tmp_path, _diff("src/x.py", "# Wave NN / v0.3.0 — next minor"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v0.3.0" in cp.stdout


def test_versioned_arch_doc_path_skipped(tmp_path):
    # ALL_STEPS_v2.2.0.md / FLOW_STEPS_GENERATED.md carry the doc/flow version
    # (2.2.0 scheme) in their title — a namespace distinct from plugin semver,
    # path-skipped like CANONICAL_FLOW_.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "docs/architecture/ALL_STEPS_v2.2.0.md",
        "# Vibe-IC — ALL Steps: Phase → Stage → Step (v2.2.0)"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


# ────────────────────────────────────────────────────────────────
# Dependency-tool-version carve-out (ORGANIC-20260603 follow-up):
# a third-party tool / PDK / runtime version (netgen 1.5.316, yosys 0.40.0,
# sky130 1.0.0, …) is NOT a plugin self-claim, even when it sorts above
# plugin.json — but the carve-out must not open a self-claim hole.
# ────────────────────────────────────────────────────────────────
def test_netgen_tool_version_exempt(tmp_path):
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff(
        "mcp-eda/src/lib/netgen_verdict.mjs",
        "//   Empirically confirmed in-container (netgen 1.5.316, magic 8.3.x)."))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_yosys_tool_version_exempt(tmp_path):
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff("src/x.py", "# requires yosys 0.40.0 or newer"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_pdk_version_exempt(tmp_path):
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff("src/x.py", "# pinned to sky130 1.0.0 PDK"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_cocotb_runtime_version_exempt(tmp_path):
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff("src/x.py", "// substituted cocotb 2.0.1"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_dependency_carveout_does_not_hole_bare_claim(tmp_path):
    # A bare forward triple with NO tool-name prefix must still be gated.
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff("src/x.py", "# v1.5.316 — next release"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "claimed v1.5.316" in cp.stdout


def test_dependency_carveout_does_not_hole_plugin_claim(tmp_path):
    # 'plugin'/'release'/'vibe-ic' before the triple are NOT tool names.
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff("src/x.py", "# plugin 1.5.316 is the target"))
    assert cp.returncode == 1, cp.stdout + cp.stderr
    cp2 = _run(tmp_path, _diff("src/x.py", "# vibe-ic 1.5.316 ships next"))
    assert cp2.returncode == 1, cp2.stdout + cp2.stderr


def test_guard_source_self_documents_shapes_is_skipped(tmp_path):
    # The guard's OWN source documents the bad shapes it gates (a bare
    # vX.Y.Z, a `vibe-ic X.Y.Z` self-claim example) — symmetric with the
    # test-harness skip, it must not gate its own implementation file.
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff(
        "tools/ci/staged_version_claim_check.py",
        "    # self-claim hole: a bare `v1.5.316`, or `vibe-ic 1.5.316`"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_guard_test_harness_still_skipped(tmp_path):
    # The pytest harness injects fake-future versions; still exempt.
    _make_plugin_json(tmp_path, "0.2.33")
    cp = _run(tmp_path, _diff(
        "tools/ci/test_staged_version_claim_check.py",
        "    cp = _run(tmp_path, _diff('src/x.py', '# v9.9.9 fixture'))"))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_commit_msg_hook_and_its_harness_skipped(tmp_path):
    # ORGANIC-20260606 #422: the commit-msg version-sync hook + its pytest
    # harness carry illustrative shapes ("from v1.2.3", "feat(v1.2.3)")
    # that DESCRIBE what the hook gates — same self-exemption case as this
    # guard's own source/harness above, incl. the opensource_repo mirror.
    _make_plugin_json(tmp_path, "0.2.52")
    for path in ("tools/ci/check_version_sync_with_commit.sh",
                 "tools/ci/test_check_version_sync_with_commit.py",
                 "opensource_repo/tools/ci/check_version_sync_with_commit.sh"):
        cp = _run(tmp_path, _diff(path, '# fixture: "feat(v9.9.9): new gate"'))
        assert cp.returncode == 0, path + cp.stdout + cp.stderr


def test_package_lock_dependency_versions_skipped(tmp_path):
    # ORGANIC follow-up 2026-06-05: lockfiles enumerate DEPENDENCY versions
    # ("version": "0.99.0" of some npm package), not plugin self-claims —
    # mirroring mcp-eda's package-lock.json produced 484 false
    # positives without this path skip.
    _make_plugin_json(tmp_path, "0.2.45")
    cp = _run(tmp_path, _diff(
        "opensource_repo/mcp-eda/package-lock.json",
        '"version": "0.99.0",'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_lockfile_carveout_does_not_mask_plugin_json_claim(tmp_path):
    # the exemption is path-scoped: a plugin.json self-claim still FAILs.
    _make_plugin_json(tmp_path, "0.2.45")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/README.md",
        "Now at v0.99.0 with the new gate."))
    assert cp.returncode == 1, cp.stdout + cp.stderr


def test_flow_assessment_review_docs_skipped(tmp_path):
    # ORGANIC-20260606: external reviewer assessment/analysis archives on the
    # FLOW (docs/architecture/Vibe-IC_*) discuss the flow/doc version scheme
    # (v2.2.0 / v2.3.0 / …) — a namespace distinct from plugin semver — in
    # verbatim third-party prose that cannot be rephrased historical. Path
    # carve-out, same family as ALL_STEPS_ / CANONICAL_FLOW_.
    _make_plugin_json(tmp_path, "0.2.91")
    for path in (
        "docs/architecture/Vibe-IC_v2.3.0_Assessment.md",
        "opensource_repo/docs/architecture/Vibe-IC_Flow_Completeness_Analysis.md",
    ):
        cp = _run(tmp_path, _diff(
            path,
            "| 評估面向 | v2.2.0 評分 | v2.3.0 評分 | 提升原因 |",
            "v2.3.0 作為發佈版本，完整度已達業界可接受水準。"))
        assert cp.returncode == 0, f"{path}: " + cp.stdout + cp.stderr


def test_flow_doc_carveout_does_not_mask_plugin_claim(tmp_path):
    # the exemption is path-scoped: the SAME flow-version prose in a
    # non-exempt path (a program comment) still FAILs.
    _make_plugin_json(tmp_path, "0.2.91")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/foo.py",
        "# upgraded for v2.3.0 of the plugin"))
    assert cp.returncode == 1, cp.stdout + cp.stderr


def test_flow_namespace_version_exempt(tmp_path):
    # "flow v2.3.1" cites the canonical-flow DOC version (a sibling
    # namespace), not the plugin's own semver — plugin sources legitimately
    # carry it in comments ("flow v2.3.1 (review R3) — …").
    _make_plugin_json(tmp_path, "0.2.91")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/foo.py",
        "# flow v2.3.1 (review R3) — IP integration checklist",
        '            f"designer-collaboration review (flow v2.3.1)")})'))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_flow_namespace_requires_immediate_precedence(tmp_path):
    # strict immediacy: "the plugin flow. v0.3.0 adds X" must STILL fail —
    # the period is not a stripped separator, so this is a forward claim.
    _make_plugin_json(tmp_path, "0.2.91")
    cp = _run(tmp_path, _diff(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/foo.py",
        "# the plugin flow. v0.3.0 adds X"))
    assert cp.returncode == 1, cp.stdout + cp.stderr


# ── ORGANIC #537 — benchmark RESULT report exemption ───────────────────────

def _svc():
    import importlib.util
    spec = importlib.util.spec_from_file_location("svc_mod", PROGRAM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_537_result_reports_path_skipped():
    # §6 Reproduce sections embed EXTERNAL dataset/tool versions (release
    # tags, docker image pins) — not plugin self-claims.
    svc = _svc()
    assert svc._path_skipped("cvdp_open_run_v0325/RESULT_v110.md")
    assert svc._path_skipped("benchmark_external/rtllm/RESULT_v0132_shape_b.md")
    assert svc._path_skipped("some_run/RESULT.md")


def test_537_negative_plugin_docs_still_gated():
    # NEGATIVE no-leak: plugin self-documentation stays under the gate.
    svc = _svc()
    assert not svc._path_skipped(
        "vibe-ic-marketplace/plugins/vibe-ic/README.md")
    assert not svc._path_skipped("docs/architecture/OVERVIEW.md")
    assert not svc._path_skipped(
        "vibe-ic-marketplace/plugins/vibe-ic/skills/foo/SKILL.md")


def test_537_benchmark_registry_path_skipped():
    # second #537 site: the registry of EXTERNAL benchmarks carries upstream
    # dataset release tags (HF v1.1.0 etc.) — not plugin self-claims.
    svc = _svc()
    assert svc._path_skipped(
        "vibe-ic-marketplace/plugins/vibe-ic/benchmark/"
        "BENCHMARK_REGISTRY.json")
