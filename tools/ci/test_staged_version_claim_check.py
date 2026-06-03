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


def test_versioned_arch_doc_path_skipped(tmp_path):
    # ALL_STEPS_v2.2.0.md / FLOW_STEPS_GENERATED.md carry the doc/flow version
    # (2.2.0 scheme) in their title — a namespace distinct from plugin semver,
    # path-skipped like CANONICAL_FLOW_.
    _make_plugin_json(tmp_path, "0.2.27")
    cp = _run(tmp_path, _diff(
        "docs/architecture/ALL_STEPS_v2.2.0.md",
        "# Vibe-IC — ALL Steps: Phase → Stage → Step (v2.2.0)"))
    assert cp.returncode == 0, cp.stdout + cp.stderr
