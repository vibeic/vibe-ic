"""ORGANIC #603 — consumer FUNCTIONS living INSIDE a runner/producer file.

#602's neutral-exclusion fix stopped every real commit classifying MIXED,
but consumer recognition was keyed mainly on FILE PATH (is this a known
standalone checker?) + a narrow function-name set. A consumer FUNCTION
inside a runner file was unrecognised: a pure verdict-message edit to
`_emit_lvs_verdict` in phase3_one_shot_runner.py classified as
ambiguous → MIXED → "justified re-run" — but it only builds a verdict
STRING (no route/geometry), verifiable against the persisted
lvs_verdict.json in seconds → CONSUMER_ONLY is correct. This is the MOST
COMMON consumer-fix shape: the #585 ROUTE_NOT_CONVERGED verdict, the #590
lvs upstream-SKIP message, the #595 OFFGRID cross-ref note are all
verdict/message edits INSIDE phase3_one_shot_runner.py.

Round fix: classify by the CHANGED HUNK's semantics — broaden the CONSUMER
vocabulary to the emitter/verdict/message/note/report/finding/disclosure
family (and fix the `\bverdict\b` word-boundary that missed `verdict`
inside `_emit_lvs_verdict`). Crucially the ordinary-English tokens (note,
finding, mismatch) match ONLY their CODE forms (`note = …`, `_mismatch`),
never as a bare word, so the same word in a PRODUCER function's docstring
cannot false-fire (the #602-round-1 prose-word regression — re-pinned here
by the real #600 commit, whose `_gds_grid_snap` docstring contains the
word "note" yet must stay PRODUCER).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fix_surface_classify as F  # noqa: E402


# ── the field agent's exact case: a consumer function in a runner file ──────

VERDICT_MSG_IN_RUNNER = """\
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
@@ -5600,7 +5600,7 @@ def _emit_lvs_verdict(result):
-    return "LVS clean"
+    return "LVS clean (all nets matched)"
"""

NOTE_MSG_IN_RUNNER = """\
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
@@ -5800,7 +5800,7 @@ def step_lvs(project, top):
-        note = "OFFGRID cross-ref"
+        note = "OFFGRID cross-ref (see #595)"
"""

STEP_PNR_IN_RUNNER = """\
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
@@ -2200,7 +2200,7 @@ def step_pnr(project, top):
-    tcl = _build_pnr_tcl(project, top)
+    tcl = _build_pnr_tcl(project, top, x=1)
"""

BOTH_IN_RUNNER = STEP_PNR_IN_RUNNER + """\
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
@@ -5600,7 +5600,7 @@ def _emit_lvs_verdict(r):
-    return "clean"
+    return "clean!"
"""


def test_verdict_message_inside_runner_is_consumer_only():
    rep = F.classify_diff(VERDICT_MSG_IN_RUNNER)
    assert rep["verdict"] == "CONSUMER_ONLY"     # was wrongly MIXED
    assert rep["ambiguous"] == []


def test_note_message_inside_runner_is_consumer_only():
    rep = F.classify_diff(NOTE_MSG_IN_RUNNER)
    assert rep["verdict"] == "CONSUMER_ONLY"


def test_step_pnr_inside_runner_stays_producer():
    rep = F.classify_diff(STEP_PNR_IN_RUNNER)
    assert rep["verdict"] == "PRODUCER"


def test_both_kinds_in_runner_is_mixed_NO_LEAK():
    rep = F.classify_diff(BOTH_IN_RUNNER)
    assert rep["verdict"] == "MIXED"


# ── the regression guard: an ordinary English word in a PRODUCER docstring
#    must NOT false-fire consumer (the #602-round-1 prose-word failure) ───────

def test_producer_docstring_with_word_note_stays_producer():
    """`_gds_grid_snap`'s docstring literally contains '(snapped_ok, note)';
    the bare word 'note' must not pull a geometry producer into MIXED."""
    diff = """\
--- a/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
+++ b/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
@@ -4267,7 +4267,8 @@ def _read_mfg_grid_um_for_pdk(pdk):
 def _gds_grid_snap(project, top, pdk, container, gds_path):
-    \"\"\"snap the streamed GDS via Region.snap. Returns (ok, note).\"\"\"
+    \"\"\"snap the streamed GDS via Region.snap (local + placement).
+    Returns (snapped_ok, note). NONFATAL.\"\"\"
"""
    rep = F.classify_diff(diff)
    # the bare word 'note' must NOT make this consumer/MIXED; it stays
    # PRODUCER (real #600 canary confirms the live commit; here we only
    # assert the prose 'note' did not leak a consumer signal)
    assert rep["verdict"] == "PRODUCER"
    assert rep["consumers"] == []


def test_bare_english_note_not_a_consumer_token():
    # a hunk whose only 'consumer-looking' text is the English word note in
    # prose → no consumer signal (must be the code form `note =`)
    h = F.classify_hunk("programs/phase3_one_shot_runner.py", "step_pnr",
                        "# leave a note here about the route")
    assert h["consumer_evidence"] is None


def test_note_assignment_is_a_consumer_token():
    h = F.classify_hunk("programs/phase3_one_shot_runner.py", "step_lvs",
                        'note = "OFFGRID cross-ref"')
    assert h["consumer_evidence"] is not None
    assert h["class"] == "consumer"


# ── emitter / verdict function-name family is recognised by NAME ────────────

def test_emit_verdict_symbol_recognised_as_consumer():
    for sym in ("_emit_lvs_verdict", "_emit_drc_message", "build_verdict",
                "_lvs_verdict"):
        h = F.classify_hunk("programs/phase3_one_shot_runner.py", sym, "")
        assert h["class"] == "consumer", sym


def test_verdict_word_boundary_fix():
    """The bug: `\\bverdict\\b` did not match 'verdict' inside
    '_emit_lvs_verdict' (underscore is a word char). Now it does."""
    assert F._any(F.CONSUMER_PATTERNS, "_emit_lvs_verdict") is not None


# ── real-git canary: the field agent's two reference commits unchanged ──────

def _root():
    r = PROG
    while r != r.parent and not (r / ".git").exists():
        r = r.parent
    return r if (r / ".git").exists() else None


def test_real_issue599_still_consumer_only():
    import pytest
    root = _root()
    if not root:
        pytest.skip("not a git checkout")
    sha = F.resolve_commit("599", root)
    if not sha:
        pytest.skip("#599 not in history")
    diff = F._git(root, "show", sha, "--format=", "--unified=3")
    assert F.classify_diff(diff)["verdict"] == "CONSUMER_ONLY"


def test_real_issue600_still_producer():
    import pytest
    root = _root()
    if not root:
        pytest.skip("not a git checkout")
    diff = F._git(root, "show", "6a73bad1", "--format=", "--unified=3")
    if not diff:
        pytest.skip("#600 not in this checkout")
    assert F.classify_diff(diff)["verdict"] == "PRODUCER"
