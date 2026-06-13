"""ORGANIC #602 ROUND 2 — classify-neutral file exclusion.

Field-agent artifact-first re-verify (CLI fed real commits) found
fix_surface_classify returned MIXED for EVERY real commit, defeating its
own reason to exist:

  - EVERY core-agent fix commit bumps marketplace.json + plugin.json (a
    mandatory push step), regenerates INDEX.md, and ships test files.
    Those carried no producer/consumer signal → "ambiguous" → MIXED → a
    needless 40-min re-run on every fix. Measured: #599 (pure run_status
    consumer), #600, #597 all wrongly MIXED. CONSUMER_ONLY only ever
    appeared on hand-crafted bump-less diffs that don't exist in practice.
  - test files were listed under PRODUCERS (their asserts quote producer
    tokens like ".snap(grid_dbu, grid_dbu)") — tests are the author's
    EVIDENCE, not a runtime surface.
  - prose/JSON hunk contexts were scraped for bogus 'symbols' (Auto, the,
    artifact, _).

Round-2 fix: a classify-NEUTRAL exclusion set (version bumps, INDEX.md,
tests, prose .md) dropped before bucketing; symbol extraction restricted
to real def/class/constant (no prose-word fallback). The decisive proof is
the real-commit shape returning the RIGHT verdict, not MIXED.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fix_surface_classify as F  # noqa: E402


# ── the field agent's real-commit shape: a consumer change + the MANDATORY
#    version bumps + INDEX + a test file → CONSUMER_ONLY, not MIXED ───────────

REAL_CONSUMER_COMMIT = """\
--- a/programs/foo_check.py
+++ b/programs/foo_check.py
@@ -10,7 +10,7 @@ def _emit_verdict(ok):
-    msg = "old verdict text"
+    msg = "new verdict text"
--- a/.claude-plugin/marketplace.json
+++ b/.claude-plugin/marketplace.json
@@ -10,7 +10,7 @@ "plugins": [
-      "version": "0.3.49",
+      "version": "0.3.50",
--- a/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json
+++ b/vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json
@@ -1,4 +1,4 @@
-  "version": "0.3.49",
+  "version": "0.3.50",
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md
@@ -1,2 +1,2 @@
-674 programs
+675 programs
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_foo.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_foo.py
@@ -1,3 +1,4 @@ def test_x():
+    assert ".snap(grid_dbu, grid_dbu)" in src
"""

REAL_PRODUCER_COMMIT = """\
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
@@ -2200,7 +2200,7 @@ def step_gds(project, top, pdk, container):
-    reg.snap(g, g)
+    reg.snap(g, g)  # tweaked
--- a/.claude-plugin/marketplace.json
+++ b/.claude-plugin/marketplace.json
@@ -10,7 +10,7 @@ "plugins": [
-      "version": "0.3.49",
+      "version": "0.3.50",
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_snap.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_snap.py
@@ -1,3 +1,4 @@ def test_y():
+    assert classify_per_rule(x)
"""


def test_real_consumer_commit_is_consumer_only_not_mixed():
    rep = F.classify_diff(REAL_CONSUMER_COMMIT)
    assert rep["verdict"] == "CONSUMER_ONLY"     # was wrongly MIXED before
    # the version bumps + INDEX + test were excluded, not bucketed
    assert rep["ambiguous"] == []
    assert rep["consumers"]                       # the foo_check verdict edit
    assert len(rep["neutral"]) >= 4               # 2 bumps + INDEX + test


def test_real_producer_commit_is_producer_despite_bump_and_test():
    rep = F.classify_diff(REAL_PRODUCER_COMMIT)
    assert rep["verdict"] == "PRODUCER"
    # the test file (with a consumer-looking `classify_per_rule` assert) is
    # neutral-excluded → does NOT leak a consumer signal → stays PRODUCER
    assert rep["consumers"] == []


def test_test_file_not_classified_as_producer():
    """A test whose asserts quote producer tokens must not be a producer —
    tests are evidence, not a surface."""
    diff = """\
--- a/programs/tests/test_v0_3_48_snap.py
+++ b/programs/tests/test_v0_3_48_snap.py
@@ -1,3 +1,4 @@ def test_snap():
+    assert "_gds_grid_snap" in src
"""
    rep = F.classify_diff(diff)
    assert rep["producers"] == []
    assert rep["verdict"] == "CONSUMER_ONLY"     # no real surface → no re-run


def test_version_or_doc_only_commit_is_consumer_only():
    """A bump-only / docs-only commit has no runtime surface → artifact-first
    (no re-run), never MIXED."""
    diff = """\
--- a/.claude-plugin/marketplace.json
+++ b/.claude-plugin/marketplace.json
@@ -10,7 +10,7 @@ "plugins": [
-      "version": "0.3.49",
+      "version": "0.3.50",
--- a/docs/architecture/ALL_STEPS.md
+++ b/docs/architecture/ALL_STEPS.md
@@ -1,2 +1,2 @@
-old prose
+new prose
"""
    rep = F.classify_diff(diff)
    assert rep["verdict"] == "CONSUMER_ONLY"


# ── neutral-file recogniser ─────────────────────────────────────────────────

def test_neutral_file_matches_the_named_files():
    for p in [".claude-plugin/marketplace.json",
              "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json",
              "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md",
              "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_x.py",
              "vibe-ic-marketplace/plugins/vibe-ic/skills/foo/SKILL.md"]:
        assert F._neutral_file(p), p


def test_real_runtime_surface_is_not_neutral():
    for p in ["programs/phase3_one_shot_runner.py",
              "programs/foo_check.py",
              "programs/fix_surface_classify.py"]:
        assert F._neutral_file(p) is None, p


# ── symbol extraction no longer scrapes prose words ─────────────────────────

def test_symbol_from_context_rejects_prose_words():
    # JSON / markdown / comment contexts must not yield bogus 'symbols'
    for ctx in ["Auto-generated catalog", "the off-grid residual",
                "artifact-first verify", "\"plugins\": [", "# a comment"]:
        assert F._symbol_from_context(ctx) is None, ctx


def test_symbol_from_context_still_reads_real_code():
    assert F._symbol_from_context("def step_pnr(p):") == "step_pnr"
    assert F._symbol_from_context("class Foo:") == "Foo"
    assert F._symbol_from_context("_GDS_GRID_SNAP_PY = r'''") == "_GDS_GRID_SNAP_PY"


# ── real-git canary: the field agent's exact two cases ──────────────────────

def _repo_root():
    root = PROG
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    return root if (root / ".git").exists() else None


def test_real_issue599_commit_is_consumer_only():
    import pytest
    root = _repo_root()
    if not root:
        pytest.skip("not in a git checkout")
    sha = F.resolve_commit("599", root)
    if not sha:
        pytest.skip("#599 commit not in history")
    diff = F._git(root, "show", sha, "--format=", "--unified=3")
    if not diff:
        pytest.skip("git show failed")
    assert F.classify_diff(diff)["verdict"] == "CONSUMER_ONLY"


def test_real_issue600_commit_is_producer():
    import pytest
    root = _repo_root()
    if not root:
        pytest.skip("not in a git checkout")
    # the v0.3.48 #600 round-2 commit touched the streamout producer
    diff = F._git(root, "show", "6a73bad1", "--format=", "--unified=3")
    if not diff:
        pytest.skip("#600 commit not in this checkout")
    assert F.classify_diff(diff)["verdict"] == "PRODUCER"
