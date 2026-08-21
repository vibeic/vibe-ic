"""Three-tier classify dispatch: deterministic ends + AI-adjudicated middle.

The user's architecture: CONSUMER_ONLY and PRODUCER are decided
DETERMINISTICALLY by the rule engine; MIXED is the genuine uncertainty the
rules could not settle, so instead of defaulting to a ~40-min re-run it is
handed to an AI agent with the MINIMAL material (the ambiguous hunks only,
not the whole diff). This is the program-first / agent-on-uncertain split
(why_not_bucket_a): rules where sure, LLM only on the residual.

Locally verifiable: a MIXED verdict carries an `adjudication` bundle whose
`ambiguous_hunks` are EXACTLY the hunks the engine could not classify (and
nothing the engine already decided); the deterministic verdicts carry no
bundle; the CLI `--adjudication-bundle` emits it; the field-agent SKILL.md
wires MIXED → adjudicate-before-re-run.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fix_surface_classify as F  # noqa: E402


MIXED_DIFF = """\
--- a/programs/phase3_one_shot_runner.py
+++ b/programs/phase3_one_shot_runner.py
@@ -2200,7 +2200,7 @@ def step_pnr(p):
-    tcl = _build_pnr_tcl(p)
+    tcl = _build_pnr_tcl(p, x=1)
--- a/programs/some_helper.py
+++ b/programs/some_helper.py
@@ -5,6 +5,7 @@ def _frobnicate(x):
+    y = x + 1
"""

CONSUMER_DIFF = """\
--- a/programs/foo_check.py
+++ b/programs/foo_check.py
@@ -10,7 +10,7 @@ def _emit_verdict(ok):
-    msg = "old"
+    msg = "new"
"""

PRODUCER_DIFF = """\
--- a/programs/phase3_one_shot_runner.py
+++ b/programs/phase3_one_shot_runner.py
@@ -2200,7 +2200,7 @@ def step_pnr(p):
-    tcl = _build_pnr_tcl(p)
+    tcl = _build_pnr_tcl(p, x=1)
"""


# ── deterministic ends carry NO adjudication bundle ─────────────────────────

def test_consumer_only_has_no_bundle():
    rep = F.classify_diff(CONSUMER_DIFF)
    assert rep["verdict"] == "CONSUMER_ONLY"
    assert rep["adjudication"] is None
    assert rep["action"].startswith("artifact-first verify")


def test_producer_has_no_bundle():
    rep = F.classify_diff(PRODUCER_DIFF)
    assert rep["verdict"] == "PRODUCER"
    assert rep["adjudication"] is None
    assert "re-run" in rep["action"]


# ── MIXED carries a bundle of EXACTLY the ambiguous hunks ───────────────────

def test_mixed_carries_adjudication_bundle():
    rep = F.classify_diff(MIXED_DIFF)
    assert rep["verdict"] == "MIXED"
    b = rep["adjudication"]
    assert b is not None
    # exactly the unknown hunk is handed to the agent — NOT the producer one
    syms = [h["symbol"] or h["path"] for h in b["ambiguous_hunks"]]
    assert syms == ["_frobnicate"]
    # the engine's already-decided producer is given as context, not asked
    assert "step_pnr" in b["already_decided"]["producers"]


def test_bundle_hunk_carries_changed_lines_for_the_agent():
    b = F.classify_diff(MIXED_DIFF)["adjudication"]
    h = b["ambiguous_hunks"][0]
    assert h["path"] == "programs/some_helper.py"
    assert any("y = x + 1" in c for c in h["changed"])
    assert h["why_ambiguous"]                       # explained


def test_bundle_carries_the_decision_question():
    b = F.classify_diff(MIXED_DIFF)["adjudication"]
    q = b["question"].lower()
    assert "consumer" in q and "producer" in q
    assert "re-run" in q                            # the decision rule


def test_action_for_mixed_says_adjudicate_first_not_just_rerun():
    rep = F.classify_diff(MIXED_DIFF)
    a = rep["action"].lower()
    assert "adjudicate" in a                        # agent step is explicit
    assert "artifact-first" in a                    # the consumer outcome
    # not a blind "always re-run"
    assert a != "justified re-run (launch async + run_status)"


# ── adjudication_bundle is minimal: only ambiguous, never deterministic ─────

def test_bundle_excludes_deterministic_hunks():
    rep = F.classify_diff(MIXED_DIFF)
    b = F.adjudication_bundle(rep)
    paths = {h["path"] for h in b["ambiguous_hunks"]}
    assert "programs/phase3_one_shot_runner.py" not in paths  # step_pnr decided
    assert "programs/some_helper.py" in paths


# ── CLI --adjudication-bundle ───────────────────────────────────────────────

def _cli(diff_text, tmp_path, *flags):
    f = tmp_path / "d.diff"
    f.write_text(diff_text)
    return subprocess.run(
        [sys.executable, str(PROG / "fix_surface_classify.py"),
         "--diff-file", str(f), *flags],
        capture_output=True, text=True)


def test_cli_bundle_on_mixed(tmp_path):
    r = _cli(MIXED_DIFF, tmp_path, "--adjudication-bundle")
    assert r.returncode == 11
    out = json.loads(r.stdout)
    assert [h["symbol"] for h in out["ambiguous_hunks"]] == ["_frobnicate"]


def test_cli_bundle_empty_on_deterministic(tmp_path):
    r = _cli(CONSUMER_DIFF, tmp_path, "--adjudication-bundle")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["adjudication"] is None
    assert "no agent" in out["note"]


# ── field-agent SKILL.md wires MIXED → adjudicate-before-re-run ─────────────

def test_skill_wires_three_tier_adjudication():
    skill = PROG.parent / "skills" / "field-agent-loop" / "SKILL.md"
    if not skill.is_file():
        skill = PROG / "skills" / "field-agent-loop" / "SKILL.md"
    t = skill.read_text(errors="replace")
    assert "--adjudication-bundle" in t
    assert "AI-adjudicate" in t
    # the three tiers are labelled deterministic vs uncertain
    assert "deterministic" in t and "uncertain" in t
    # MIXED must NOT auto-re-run without reading the bundle
    assert "Do NOT auto-re-run a MIXED" in t
