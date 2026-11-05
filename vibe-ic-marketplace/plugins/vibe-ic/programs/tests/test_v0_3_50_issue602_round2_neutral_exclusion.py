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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402
import fix_surface_classify as F  # noqa: E402
import _issue600_producing_commits as _P  # noqa: E402


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
    """The classifier, over the REAL #599 commit, says CONSUMER_ONLY.

    THE SKIP THAT USED TO STAND HERE WAS NEVER A PASS (vibe-ic#2145). It read
    "#599 commit not in history" and fired on every checkout, because
    `resolve_commit` only looked 400 commits back and #599's commit is 3094
    back — so this canary had never once been exercised. Then `ebb00b1b4`
    landed with "the #599 label probe" in its SUBJECT while closing #2111 and
    #2106; it entered the window, the old resolver returned it, and this test
    failed on its FIRST EVER exercise against a commit that is not #599's.

    Both halves are fixed in `resolve_commit` (a CLAIM, not a mention; no
    window), so the skip is gone in both directions: the resolution is now
    ASSERTED. If a future history genuinely carries no #599 claim, this goes
    RED and names it, rather than reporting green by not looking.

    THE SUBJECT IS ANCHORED BY CONTENT, NOT BY SHA. A sha literal does not
    survive a history rewrite — the sibling #600 canary below hardcodes
    `6a73bad1` and has been silently skipping since the 2026-09-07 rewrite. The
    real #599 commit is the one that turned `phase1_expert_parse_track`'s
    printed `VACUOUS_PASS:` into `INCOMPLETE:` (see the tie-break test in
    test_v0_3_51_...), so requiring that file in the diff is what makes this a
    canary over #599 rather than over whatever the resolver happened to return.
    `ebb00b1b4`, the decoy, does not touch it.
    """
    import pytest
    root = _repo_root()
    if not root:
        pytest.skip("not in a git checkout")
    sha = F.resolve_commit("599", root)
    assert sha, ("no commit in this history CLAIMS #599 — resolve_commit "
                 "returned None; this canary cannot be exercised and is not "
                 "reported as a pass")
    diff = F._git(root, "show", sha, "--format=", "--unified=3")
    assert diff, f"git show {sha} produced no diff"
    assert "programs/phase1_expert_parse_track.py" in diff, (
        f"resolve_commit('599') returned {sha}, whose diff does not touch "
        "phase1_expert_parse_track.py — that is not #599's commit")
    assert F.classify_diff(diff)["verdict"] == "CONSUMER_ONLY"


def test_real_issue600_commit_is_producer():
    """ORGANIC #600 — the classifier over REAL commits that PRODUCE the artefact.

    ANCHORED BY CONTENT, NOT BY A SHA (vibe-ic#2162). This canary used to read
    `git show 6a73bad1`. That sha is gone -- the pre-v1.0.0 history was squashed
    into one "initial public release" commit -- so it had been SKIPPING on every
    checkout, silently, for as long as that squash has existed. A skip is not a
    pass, and a canary that stopped watching without anyone noticing is worse
    than no canary.

    Rewiring it to the ISSUE NUMBER is the obvious repair and it is wrong,
    measured: `resolve_commit("600")` reaches `311f8fc81bcf`, a CONSUMER_ONLY
    commit, so it would turn a silent skip into a red that says nothing about
    the classifier. An issue number is no more durable than a sha; both name a
    commit, and this canary is about a KIND of commit.

    So the subject is a PREDICATE over the diff -- see
    `_issue600_producing_commits`, which selects by the enclosing symbol of the
    hunks and never by `classify_diff` (selecting with the classifier and then
    asserting its answer is a tautology). MEASURED on this history (main
    89f66304f5a0): 37 commits qualify -- 31 MIXED, 6 PRODUCER, 0 CONSUMER_ONLY.

    This file's half guards the #602 NEUTRAL EXCLUSION: every one of those 37
    also bumps the version manifests and ships test files, and before #602 that
    alone made each of them MIXED-by-ambiguity. Its twin in the #603 file guards
    the widened consumer vocabulary. Two canaries, because one could not say
    which of the two rules moved a verdict."""
    root = _repo_root()
    if not root:
        pytest.skip("not in a git checkout")
    pop, why = _P.producing_commits(root)
    assert pop, why
    verdicts = {sha: F.classify_diff(diff)["verdict"] for sha, diff in pop}
    _P.assert_population_is_safe_and_producer_is_reachable(verdicts)
