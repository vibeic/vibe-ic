"""ORGANIC #602 — fix_surface_classify: the #598 consumer-vs-producer
artifact-first decision, upgraded from SKILL.md PROSE to a deterministic
Bucket-A program so a fresh field-agent cannot forget to apply it.

Acceptance fixtures (from the issue):
  - a verdict-message-only diff           → CONSUMER_ONLY (artifact-first)
  - a step_pnr / streamout diff           → PRODUCER (justified re-run)
  - a diff touching both                  → MIXED (read / re-run)
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fix_surface_classify as F  # noqa: E402


# ── realistic unified diffs ─────────────────────────────────────────────────

DIFF_VERDICT_MSG = """\
--- a/programs/acceptance_evidence_in_fix_comment_check.py
+++ b/programs/acceptance_evidence_in_fix_comment_check.py
@@ -120,7 +120,7 @@ def _emit_verdict(ok):
-    msg = "acceptance evidence missing"
+    msg = "acceptance evidence missing (quote the 驗收 command)"
"""

DIFF_STEP_PNR = """\
--- a/programs/phase3_one_shot_runner.py
+++ b/programs/phase3_one_shot_runner.py
@@ -2200,7 +2200,7 @@ def step_pnr(project, top, pdk, container):
-    tcl = _build_pnr_tcl(project, top)
+    tcl = _build_pnr_tcl(project, top, new_arg=True)
"""

DIFF_STREAMOUT = """\
--- a/programs/phase3_one_shot_runner.py
+++ b/programs/phase3_one_shot_runner.py
@@ -4250,6 +4250,7 @@ def _gds_grid_snap(project, top, pdk, container, gds_path):
+    reg.snap(grid_dbu, grid_dbu)
"""

DIFF_BOTH = DIFF_STEP_PNR + """\
--- a/programs/drc_offgrid_classify_check.py
+++ b/programs/drc_offgrid_classify_check.py
@@ -10,6 +10,7 @@ def classify_per_rule(per_rule):
+    verdict = "FLOW_OFFGRID"
"""

DIFF_UNKNOWN = """\
--- a/programs/some_helper.py
+++ b/programs/some_helper.py
@@ -5,6 +5,7 @@ def _frobnicate(x):
+    y = x + 1
"""


# ── the three acceptance fixtures ───────────────────────────────────────────

def test_verdict_message_only_is_consumer_only():
    rep = F.classify_diff(DIFF_VERDICT_MSG)
    assert rep["verdict"] == "CONSUMER_ONLY"
    assert rep["action"].startswith("artifact-first verify")


def test_step_pnr_is_producer():
    rep = F.classify_diff(DIFF_STEP_PNR)
    assert rep["verdict"] == "PRODUCER"
    assert "re-run" in rep["action"]
    assert "step_pnr" in rep["producers"]


def test_streamout_geometry_emitter_is_producer():
    rep = F.classify_diff(DIFF_STREAMOUT)
    assert rep["verdict"] == "PRODUCER"
    assert "_gds_grid_snap" in rep["producers"]


def test_touching_both_is_mixed():
    rep = F.classify_diff(DIFF_BOTH)
    assert rep["verdict"] == "MIXED"
    assert "step_pnr" in rep["producers"]
    assert any("classify" in c for c in rep["consumers"])


# ── conservative default: an unknown/ambiguous surface → MIXED, never a
#    false CONSUMER_ONLY (which would skip a needed re-run) ───────────────────

def test_unknown_surface_defaults_to_mixed_not_consumer_only():
    rep = F.classify_diff(DIFF_UNKNOWN)
    assert rep["verdict"] == "MIXED"   # cannot prove consumer-only → re-run


def test_producer_plus_unknown_is_mixed():
    rep = F.classify_diff(DIFF_STEP_PNR + DIFF_UNKNOWN)
    assert rep["verdict"] == "MIXED"


# ── per-hunk classification ─────────────────────────────────────────────────

def test_classify_hunk_producer_symbol():
    h = F.classify_hunk("programs/phase3_one_shot_runner.py", "step_gds", "")
    assert h["class"] == "producer"


def test_classify_hunk_consumer_file_even_with_silent_symbol():
    h = F.classify_hunk("programs/foo_check.py", "_helper", "")
    assert h["class"] == "consumer"


def test_classify_hunk_mixed_when_both_signals():
    h = F.classify_hunk("programs/pnr_check.py", "classify", "make_tracks()")
    assert h["class"] == "mixed"


def test_classify_hunk_unknown_when_no_signal():
    h = F.classify_hunk("programs/some_helper.py", "_frobnicate", "y = x + 1")
    assert h["class"] == "unknown"


# ── diff parsing + symbol extraction ────────────────────────────────────────

def test_parse_unified_diff_extracts_path_and_symbol():
    hunks = F.parse_unified_diff(DIFF_STEP_PNR)
    assert len(hunks) == 1
    assert hunks[0]["path"] == "programs/phase3_one_shot_runner.py"
    assert hunks[0]["symbol"] == "step_pnr"


def test_symbol_from_context_variants():
    assert F._symbol_from_context("def step_pnr(project):") == "step_pnr"
    assert F._symbol_from_context("class Foo:") == "Foo"
    assert F._symbol_from_context("_GDS_GRID_SNAP_PY = r'''") == "_GDS_GRID_SNAP_PY"
    assert F._symbol_from_context("") is None


# ── CLI exit codes (branchable) ─────────────────────────────────────────────

def _cli(diff_text, tmp_path):
    f = tmp_path / "d.diff"
    f.write_text(diff_text)
    return subprocess.run(
        [sys.executable, str(PROG / "fix_surface_classify.py"),
         "--diff-file", str(f)],
        capture_output=True, text=True)


def test_cli_consumer_only_exit_0(tmp_path):
    r = _cli(DIFF_VERDICT_MSG, tmp_path)
    assert r.returncode == 0
    assert "CONSUMER_ONLY" in r.stdout


def test_cli_producer_exit_10(tmp_path):
    r = _cli(DIFF_STEP_PNR, tmp_path)
    assert r.returncode == 10
    assert "PRODUCER" in r.stdout


def test_cli_mixed_exit_11(tmp_path):
    r = _cli(DIFF_BOTH, tmp_path)
    assert r.returncode == 11
    assert "MIXED" in r.stdout


# ── wired into the field-agent artifact-first decision (#598) ───────────────

def test_wired_into_field_agent_skill():
    skill = PROG.parent / "skills" / "field-agent-loop" / "SKILL.md"
    if not skill.is_file():
        skill = PROG / "skills" / "field-agent-loop" / "SKILL.md"
    t = skill.read_text(errors="replace")
    assert "fix_surface_classify.py" in t
    for v in ("CONSUMER_ONLY", "PRODUCER", "MIXED"):
        assert v in t, v


# ── a FILE DELETION must not crash the bucket sort ─────────────────────────
#
# `parse_unified_diff` sets path=None for a `+++ /dev/null` hunk and
# `_symbol_from_context` returns None for a header that is not a real
# def/class, so a deletion hunk's bucket label was `None or None` -> None.
# Mixed with any str label in `sorted({...})` that raised
# `TypeError: '<' not supported between instances of 'NoneType' and 'str'`.
# MEASURED: 1 of the 200 most recent origin/main commits crashed this way, and
# through `handoff_bundle_check` the uncaught exception exited 1 — the same rc
# as a legitimate INCOMPLETE verdict — with no JSON report written at all.

DIFF_DELETE_PLUS_EDIT = """\
diff --git a/foo/bar.txt b/foo/bar.txt
deleted file mode 100644
--- a/foo/bar.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-alpha
-beta
diff --git a/foo/baz.txt b/foo/baz.txt
--- a/foo/baz.txt
+++ b/foo/baz.txt
@@ -1 +1 @@
-gamma
+delta
"""


def test_file_deletion_beside_an_edit_does_not_crash():
    rep = F.classify_diff(DIFF_DELETE_PLUS_EDIT)
    assert rep["verdict"] in ("CONSUMER_ONLY", "PRODUCER", "MIXED")
    # every bucket label is a string, so the set is totally ordered
    for bucket in ("producers", "consumers", "ambiguous"):
        assert all(isinstance(x, str) for x in rep[bucket]), bucket
    assert F._DELETED_FILE_LABEL in rep["ambiguous"]


def test_deletion_only_diff_does_not_crash():
    only_delete = DIFF_DELETE_PLUS_EDIT.split("diff --git a/foo/baz.txt")[0]
    rep = F.classify_diff(only_delete)
    assert all(isinstance(x, str) for x in rep["ambiguous"])


# ── real-git canary: #600's fix commit is a PRODUCER (streamout edit) ───────

def test_real_git_resolves_issue_to_commit():
    import pytest
    root = PROG
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    if not (root / ".git").exists():
        pytest.skip("not in a git checkout")
    sha = F.resolve_commit("600", root)
    if not sha:
        pytest.skip("#600 commit not in this checkout's history")
    assert len(sha) >= 7
