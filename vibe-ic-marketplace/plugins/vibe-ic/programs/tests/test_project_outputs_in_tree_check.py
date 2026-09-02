#!/usr/bin/env python3
"""Tests for project_outputs_in_tree_check.py — chip-AGNOSTIC volatile-
storage gate.

Covers:
  1. POSITIVE_PASS — RESULT.md / waivers.json / reports/ have no /tmp
                     references.
  2. POSITIVE_FAIL — RESULT.md cites a /tmp/<file> AND that file exists
                     on disk (live external artifact).
  3. SKIP_NON_APPLICABLE — project tree is empty (no scan target files
                     at all → rc 2, a REAL disclosed skip). #619: this used
                     to be "PASS, the SKIP analogue", and the analogue was
                     the defect — the P0 umbrella reads exit codes, so a
                     skip spelled `0` was aggregated as a clean scan.
  4. SKIP_NO_CONSTRUCT — same (covered by #3).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / \
    "project_outputs_in_tree_check.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


@pytest.fixture
def volatile_project():
    """A project root that really is on a VOLATILE root, whatever TMPDIR says.

    THIS GATE ONLY EVER LOOKS AT PATHS UNDER `/tmp/`, `/var/tmp/`, `/dev/shm/`
    or `/run/` — `_PATH_RE` admits nothing else, and its own PASS line says so
    ("no /tmp / /var/tmp / /dev/shm / /run paths referenced"). A test whose
    SUBJECT is built under pytest's `tmp_path` therefore measures the gate only
    when the harness's TMPDIR happens to be volatile, and measures the harness
    otherwise.

    MEASURED, one variable, same tree (0b8cca0736) and same pinned image
    `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…`:

        TMPDIR unset (basetemp /tmp/pytest-of-…)         19 passed
        TMPDIR=<bind mount>/tmp (non-volatile)            2 failed, 17 passed

    and the two that fell over were exactly the two below. The run had already
    said so in its own words, three lines above the failure —
    `scratch_root_guard: … NOT under a volatile root (/tmp/, /var/tmp/,
    /dev/shm/, /run/) [the external-storage gate cannot see a subject built
    here]`. That INFO line is the discriminator between a defect in this gate
    and an artefact of the measurement shape; this fixture removes the variable
    it is warning about, so the two tests below measure the gate either way.

    Deliberately NOT a change to the gate: the volatile-prefix scope is what
    the gate is FOR, and widening it to fit a harness would be the tail wagging
    the dog. `test_genuine_external_artifact_still_fails_from_a_volatile_
    project` already pins its own subject the same way, for the same reason.
    """
    import shutil
    import tempfile
    d = Path(tempfile.mkdtemp(dir="/tmp", prefix="voltproj-"))
    assert str(d.resolve()).startswith("/tmp/")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# -- Test 1: POSITIVE_PASS — clean project --

def test_positive_pass_clean_project(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Project results\n"
        "All artifacts under reports/ and rtl/ — no volatile paths.\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({}))
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "build.json").write_text(json.dumps({
        "status": "PASS", "artifact": "phase2/stage1/rtl/chip_top.sv",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "no /tmp" in r.stdout


# -- Test 2: POSITIVE_FAIL — live /tmp artifact --

def test_positive_fail_live_tmp(tmp_path):
    # Create an artifact in /tmp that actually exists.
    sentinel = Path("/tmp") / f"vibe_test_artifact_{tmp_path.name}.gds"
    sentinel.write_text("# fake GDS\n")
    try:
        (tmp_path / "RESULT.md").write_text(
            f"GDS produced at: {sentinel}\n"
        )
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert "live external-storage" in r.stdout
        assert str(sentinel) in r.stdout
    finally:
        try:
            sentinel.unlink()
        except FileNotFoundError:
            pass


# -- Test 3: SKIP_NON_APPLICABLE — empty project (no scan files) --

def test_skip_empty_project(tmp_path):
    """#619 — VERDICT CHANGED HERE, deliberately: rc 0 -> rc 2.

    An empty project is a scan that opened NOTHING, and this file used to call
    that "PASS, the SKIP analogue". The analogue is the bug:
    `gate_zero_denominator_refuses_check` drives every gate against a fresh
    empty project and reported this one as ZERO_DENOMINATOR_EXITS_ZERO, because
    the P0 umbrella reads exit codes and never the prose that honestly said
    `0 file(s) scanned`.

    It is this gate specifically that may not take the `_ZERO_IS_A_PASS` route:
    its subject IS "outputs written outside the tree", and an empty canonical
    tree is that condition's strongest symptom, not evidence against it.
    """
    # Empty project — no RESULT.md, no waivers.json, no reports/.
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout
    assert "read 0 file(s)" in r.stdout
    assert str(tmp_path) in r.stdout, "the refusal must name the tree it read"


# -- Test 4: SKIP_NO_CONSTRUCT — only unrelated files --

def test_skip_unrelated_files(tmp_path):
    """Files exist, but NONE of them is in `_SCAN_GLOBS`, so the scan still
    opened zero declaration files — same verdict as an empty tree (#619). The
    predicate is `scanned == 0`, not `the directory is empty`."""
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.sv").write_text(
        "module top();\nendmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout
    assert "read 0 file(s)" in r.stdout


# -- Test 5: WARN — dangling /tmp reference (file gone) --

def test_dangling_tmp_reference(tmp_path):
    """Reference to /tmp/<file> that no longer exists → still FAIL
    (because findings list is non-empty), with WARN sub-line."""
    (tmp_path / "RESULT.md").write_text(
        "# Lost results\n"
        "Used /tmp/dead_artifact_xyz_does_not_exist_anywhere.gds\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    # No live findings, but dangling counted in fail_count.
    assert "[WARN]" in r.stdout
    assert "dangling external-path" in r.stdout


# -- Test 6: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "Cache: /tmp/build_cache_123/intermediate.json\n"
    )
    rationale = (
        "Build cache lives in /tmp by design — never used as audit "
        "evidence; ticket BUILD-101 documents the cache architecture "
        "and rotation policy."
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "project_artifacts_external_storage_intentional": rationale,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_WITH_WAIVER]" in r.stdout


# -- Test 7: usage error --

def test_usage_error():
    r = subprocess.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 2


# ── R7 (v1.3.50) — a PINNED plugin worktree is a legit plugin source ─────────

def test_r7_pinned_plugin_wt_prefix_passes(tmp_path):
    """A `/tmp/.../wt-*/vibe-ic-marketplace/plugins/vibe-ic/...` reference (real
    plugin.json) is a legit plugin SOURCE — disclosed, NON-blocking (PASS).

    Uses a real volatile prefix (/tmp) because that is what triggered the
    original false positive."""
    import shutil
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-v1350-"))
    try:
        root = volbase / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "vibe-ic", "version": "1.3.50"}))
        (root / "programs").mkdir()
        src = root / "programs" / "flow_compliance_check.py"
        src.write_text("# pinned plugin program\n")
        (tmp_path / "RESULT.md").write_text(f"Ran gate at: {src}\n")
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "pinned plugin-source" in r.stdout
    finally:
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_pinned_plugin_claude_worktrees_passes(tmp_path):
    """The `.claude/worktrees/<wt>/vibe-ic-marketplace/plugins/vibe-ic/...`
    pinning marker variant is also recognised as plugin source (PASS)."""
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="run-"))
    try:
        root = (volbase / ".claude" / "worktrees" / "agent-xyz"
                / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}")
        (root / "phase1_phase2_phase3.yaml").write_text("steps: []\n")
        src = root / "phase1_phase2_phase3.yaml"
        (tmp_path / "RESULT.md").write_text(f"config: {src}\n")
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "pinned plugin-source" in r.stdout
    finally:
        import shutil
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_genuine_volatile_output_still_fails(tmp_path):
    """A genuine volatile project OUTPUT (real /tmp GDS, NOT a plugin root) must
    STILL FAIL — the R7 exemption must not create a false-negative."""
    import tempfile
    outdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="realrun-"))
    sentinel = outdir / "design.gds"
    sentinel.write_text("# fake GDS\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"GDS produced at: {sentinel}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


def test_r7_anchor_substring_without_plugin_json_fails(tmp_path):
    """A /tmp path that merely CONTAINS the plugin anchor substring but has NO
    `.claude-plugin/plugin.json` is NOT a real plugin root → must FAIL (the hard
    marker gate blocks the false-negative)."""
    import tempfile
    outdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-fake-"))
    fake = (outdir / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "out.gds")
    fake.parent.mkdir(parents=True)
    fake.write_text("# not a plugin\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"Output: {fake}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


def test_r7_dotdot_escape_out_of_plugin_still_fails(tmp_path):
    """§4.05 false-negative guard — a `..`-escape that starts inside a pinned
    plugin worktree but climbs OUT to a genuine volatile output
    (`.../vibe-ic/../../../design.gds`) must NOT be exempted: normalization
    destroys the plugin anchor, so it is (correctly) FLAGGED."""
    import shutil
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-v1350-"))
    try:
        root = volbase / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}")
        # a real output ABOVE the plugin, reached via .. from inside it
        escaped = volbase / "design.gds"
        escaped.write_text("# real volatile output\n")
        cited = root / ".." / ".." / ".." / "design.gds"   # escapes to volbase
        (tmp_path / "RESULT.md").write_text(f"GDS at: {cited}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_intree_dotdot_still_recognised(tmp_path):
    """An IN-TREE `..` that stays under the plugin root
    (`.../vibe-ic/programs/../plugin.json`) is still recognised as plugin
    source (PASS) — the guard only rejects escapes, not in-tree normalization."""
    import shutil
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-v1350-"))
    try:
        root = volbase / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}")
        (root / "programs").mkdir()
        (root / "phase3_one_shot_runner.py").write_text("# src\n")
        cited = root / "programs" / ".." / "phase3_one_shot_runner.py"
        (tmp_path / "RESULT.md").write_text(f"ran: {cited}\n")
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "pinned plugin-source" in r.stdout
    finally:
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_plugin_root_without_pin_marker_fails(tmp_path):
    """A real plugin root (has plugin.json) but with NO worktree/scratch pin
    marker above the anchor is NOT exempted → FAIL. Keeps the exemption narrow."""
    import tempfile
    outdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="plainroot-"))
    root = outdir / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text("{}")
    src = root / "x.py"
    src.write_text("# x\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"ref: {src}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


# ── In-tree self-references (audit self-inflation) ───────────────────────────
# A project audited from a volatile root (the standard way to audit without
# mutating the original) writes its OWN absolute paths into reports/**/*.json.
# Those are in-tree BY DEFINITION; before the fix the gate reported them as
# external storage, so the audit manufactured its own violations.
#
# `tmp_path` is itself under /tmp, so these tests reproduce the real condition
# without simulating it: the project root genuinely IS at a volatile path.

def test_in_tree_self_reference_is_not_external_storage(tmp_path):
    """The defect direction. A report citing the project's OWN absolute path
    must not be an external-storage finding — the file is inside the tree."""
    own = tmp_path / "phase3" / "stage4" / "gds" / "top.gds"
    own.parent.mkdir(parents=True)
    own.write_text("# GDS\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gds_substance.json").write_text(json.dumps({
        "gds": str(own), "status": "PASS",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "external-storage artifact" not in r.stdout


def test_in_tree_self_reference_is_disclosed_not_silent(volatile_project):
    """The exemption must be visible. A silently-dropped class reads as
    'nothing was there' — the gate has to say what it excused.

    The project root must itself be VOLATILE for this class to exist at all:
    an in-tree self-reference is only a candidate finding when the tree is
    somewhere `_PATH_RE` looks. See the `volatile_project` fixture.
    """
    proj = volatile_project
    own = proj / "phase2" / "stage2" / "synth" / "netlist.v"
    own.parent.mkdir(parents=True)
    own.write_text("// netlist\n")
    (proj / "reports").mkdir()
    (proj / "reports" / "synth.json").write_text(json.dumps(
        {"netlist": str(own)}))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in-tree self-reference" in r.stdout
    assert str(proj) in r.stdout


def test_genuine_external_artifact_still_fails_from_a_volatile_project(
        tmp_path):
    """ANTI-RUBBER-STAMP. The project root is volatile, so a blanket
    'everything under /tmp is fine' rule would pass this — it must not.
    A path OUTSIDE the project is still external storage."""
    import tempfile
    outside = Path(tempfile.mkdtemp(dir="/tmp", prefix="outside-"))
    stray = outside / "chip_top.gds"
    stray.write_text("# real GDS left outside the tree\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"the GDS is at {stray}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert str(stray) in r.stdout
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


def test_symlink_out_of_the_tree_is_still_external(volatile_project):
    """A path that is LEXICALLY inside the project but symlinks OUT of it is
    still external storage — the artifact does not live in the tree. Pins
    that the containment test resolves rather than string-prefixes.

    SCOPE, stated because this test does not cover it and a reader will look:
    the ADMISSION filter (`_PATH_RE`) is a string prefix over the CITED text,
    and only `_inside_project` resolves. So a report citing a lexically-inside
    path that symlinks onto volatile storage is invisible to this gate whenever
    the project root is NOT itself volatile — the ordinary case for a real run
    under `$HOME`. That is a gate hole, not a harness artefact, and it is
    reported separately rather than papered over here; this test's subject is
    the resolution step, and it is pinned on a volatile root so it measures
    that step rather than the harness's TMPDIR.
    """
    proj = volatile_project
    import tempfile
    outside = Path(tempfile.mkdtemp(dir="/tmp", prefix="linktarget-"))
    target = outside / "netlist.v"
    target.write_text("// lives outside\n")
    inside = proj / "steps" / "9_synth"
    inside.mkdir(parents=True)
    link = inside / "netlist.v"
    link.symlink_to(target)
    try:
        (proj / "reports").mkdir()
        (proj / "reports" / "s.json").write_text(json.dumps(
            {"netlist": str(link)}))
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


def test_project_root_itself_cited_is_in_tree(tmp_path):
    """The boundary case: a report citing the project ROOT (not a child).
    `p == project` must count as inside, not merely `project in p.parents`."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "audit.json").write_text(json.dumps(
        {"project": str(tmp_path)}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


# ── #619 — the refusal must not become a way to duck the scan ────────────────

def test_one_declaration_file_is_enough_to_make_it_answer(tmp_path):
    """THE REFUSAL'S OWN FALSE-POSITIVE GUARD. The moment the scan opens ONE
    file the gate is back on the hook: rc 0, and the count it discloses is 1.
    A refusal that widened past `scanned == 0` would switch the gate off for
    thinly-populated projects."""
    (tmp_path / "RESULT.md").write_text("all artefacts under reports/\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "1 file(s) scanned" in r.stdout


def test_a_real_violation_in_a_one_file_project_is_still_rc_1(tmp_path):
    """THE ANTI-RUBBER-STAMP. rc 2 must not have become the answer for any
    project the gate can still read: the smallest project that CAN carry a
    violation still FAILs on one."""
    import tempfile
    outside = Path(tempfile.mkdtemp(dir="/tmp", prefix="r619-outside-"))
    stray = outside / "chip_top.gds"
    stray.write_text("# a real GDS left outside the tree\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"GDS produced at: {stray}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert str(stray) in r.stdout
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)
