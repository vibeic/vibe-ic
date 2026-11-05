"""R-0915-86 (1) — the frozen-audit replay, calibrated before it judges.

`audit_replay` re-judges a FROZEN run snapshot with the CURRENT tree's programs.
It is how a JUDGEMENT change — R-0915-85's 23-words-to-5 reform, any audit /
compliance / review change — is measured on r26, run16 and SPM in seconds,
without re-running an EDA tool that may no longer exist.

The subject is fixed (a frozen directory) and the instrument is fixed (one
`flow_compliance_check ... --strict` invocation), so the only variable across two
replays is the TREE. That is the experiment. These tests pin the mechanics of it
with a STUB checker — a five-line program that writes a completion audit — so the
replay's own behaviour is measured rather than the 15,000-line checker's:

  * the snapshot is never modified (the whole premise: it is evidence),
  * the replay reads only a table IT wrote, never one left in the snapshot,
  * a checker that writes nothing REFUSES rather than passing,
  * both calibration directions, per R-0915-86 (3).

The real thing — r26 and run16 replayed with this tree's real checker — is a
MEASUREMENT recorded in the lane's findings. A test that re-runs the real
compliance pass over a 150 MB snapshot is not a test.
"""
from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path

R = importlib.import_module("audit_replay")

_STUB = '''\
import json, sys
from pathlib import Path
proj = Path(sys.argv[1])
steps = json.loads(Path(__file__).with_name("_stub_table.json").read_text())
out = proj / "reports" / "audit" / "phase23_completion_audit.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    "version": "stub", "run_at": "2026-09-16T00:00:00+00:00",
    "verdict": steps["verdict"],
    "command_argv": [__file__, str(proj), "--strict"],
    "gate_execution_ledger": steps.get("ledger", []),
    "steps": steps["steps"]}))
raise SystemExit(steps.get("rc", 0))
'''

_STUB_WRITES_NOTHING = '''\
import sys
raise SystemExit(1)
'''


def _tmp() -> Path:
    """mkdtemp, not pytest's tmp_path — the EDA image's tmp_path carries a
    newline in this repo's containers."""
    return Path(tempfile.mkdtemp(prefix="replay_"))


def _steps(pairs):
    return [{"id": i, "name": "step %s" % i, "stage": "stage1", "status": s}
            for i, s in pairs]


def _tree(root: Path, table, body=_STUB) -> Path:
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    (progs / "flow_compliance_check.py").write_text(body, encoding="utf-8")
    (progs / "_stub_table.json").write_text(json.dumps(table), encoding="utf-8")
    return root


def _snapshot(root: Path, recorded_steps, recorded_verdict, argv=None):
    (root / "reports" / "audit").mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "a.md").write_text("doc", encoding="utf-8")
    (root / "reports" / "audit" / "phase23_completion_audit.json").write_text(
        json.dumps({
            "version": "1.21.6", "run_at": "2026-09-15T00:00:00+00:00",
            "verdict": recorded_verdict,
            "command_argv": argv or ["flow_compliance_check.py", "/orig",
                                     "--strict"],
            # R-0915-88: present and empty is what a run whose hand-offs were
            # all answered looks like; ABSENT means the table cannot state its
            # RUN SHAPE and is refused, which is a different test.
            "gate_execution_ledger": [],
            "steps": _steps(recorded_steps)}), encoding="utf-8")
    return root


def _replay(snapshot, tree, workdir, out, reference=None):
    argv = [str(snapshot), "--tree", str(tree), "--workdir", str(workdir),
            "--json", str(out)]
    if reference is not None:
        argv += ["--reference", str(reference)]
    return R.main(argv)


def _scenario(recorded, replayed, recorded_verdict="PASS_WITH_WAIVERS",
              replayed_verdict="PASS_WITH_WAIVERS", rc=0, body=_STUB,
              snap_argv=None):
    base = _tmp()
    snap = _snapshot(base / "snap", recorded, recorded_verdict, argv=snap_argv)
    tree = _tree(base / "tree", {"verdict": replayed_verdict,
                                 "steps": _steps(replayed), "rc": rc}, body=body)
    out = base / "audit_replay.json"
    code = _replay(snap, tree, base / "wd", out)
    return code, json.loads(out.read_text(encoding="utf-8")), base


# ── CALIBRATION (R-0915-86 (3)) ──────────────────────────────────────────────

def test_KNOWN_NEGATIVE_the_same_judgement_exits_0_with_an_empty_diff():
    steps = [("2", "PASS"), ("7", "INCOMPLETE")]
    rc, rep, _ = _scenario(steps, steps)
    assert rc == 0
    assert rep["verdict"] == "NO_REGRESSION"
    assert rep["diff"]["changed"] == []
    assert rep["diff"]["unchanged_step_count"] == 2


def test_KNOWN_POSITIVE_a_judgement_change_on_one_step_exits_1_and_is_named():
    """The measurement the replay exists for: the tree's judgement moved a step
    on a subject that did not change by one byte."""
    rc, rep, _ = _scenario([("2", "PASS"), ("7", "PASS")],
                           [("2", "PASS"), ("7", "INCOMPLETE")])
    assert rc == 1
    assert [e["id"] for e in rep["diff"]["regressions"]] == ["7"]
    assert rep["diff"]["regressions"][0]["current"] == "INCOMPLETE"


def test_a_judgement_that_greens_a_step_exits_0_and_is_listed():
    rc, rep, _ = _scenario([("7", "INCOMPLETE")], [("7", "PASS")])
    assert rc == 0
    assert [e["id"] for e in rep["diff"]["improvements"]] == ["7"]


# ── the snapshot is evidence ─────────────────────────────────────────────────

def test_the_snapshot_is_not_modified():
    """`flow_compliance_check` is a PRODUCER as well as a judge — its own
    --read-only docstring records 25 files added and 17 rewritten by ONE
    invocation over a published tree. The replay works on a copy for exactly
    that reason, and this test is the proof rather than the promise."""
    steps = [("2", "PASS")]
    base = _tmp()
    snap = _snapshot(base / "snap", steps, "PASS")
    before = {str(p.relative_to(snap)): p.stat().st_mtime_ns
              for p in sorted(snap.rglob("*")) if p.is_file()}
    tree = _tree(base / "tree", {"verdict": "PASS", "steps": _steps(steps)})
    _replay(snap, tree, base / "wd", base / "o.json")
    after = {str(p.relative_to(snap)): p.stat().st_mtime_ns
             for p in sorted(snap.rglob("*")) if p.is_file()}
    assert before == after


def test_the_replay_reads_only_a_table_IT_wrote():
    """The recorded audit is deleted from the COPY before the checker runs, so
    a checker that silently produced nothing cannot be mistaken for one that
    agreed with the record. Without this, a no-op checker reads as a perfect
    match — the most convincing false green available."""
    rc, rep, _ = _scenario([("2", "PASS")], [], body=_STUB_WRITES_NOTHING)
    assert rc == 2
    assert rep["verdict"] == "REFUSED"
    assert "wrote no" in rep["refusal"]


def test_a_checker_rc_of_1_is_NOT_a_refusal():
    """A compliance pass exits 1 exactly when the project FAILs — that run
    completed and wrote the table naming which step went red. Refusing there
    would throw away the only thing the replay is for."""
    rc, rep, _ = _scenario([("2", "FAIL")], [("2", "FAIL")],
                           recorded_verdict="FAIL", replayed_verdict="FAIL",
                           rc=1)
    assert rc == 0
    assert rep["replay"]["rc"] == 1
    assert rep["verdict"] == "NO_REGRESSION"




# ── R-0915-88 follow-up: `--baseline`, the reference this program RECORDS ────
#
# MEASURED on the arm's first full landing run: BOTH frozen snapshots came back
# NOT_COMPARABLE, because the reference each offers is its own recorded audit and
# the LAST compliance pass of a run overwrites that file (9 steps from a
# stage-scoped pass, against a full pass's 69). The refusal was CORRECT and the
# arm was still useless — it refused forever, and a gate that always refuses is a
# gate nobody reads.

def _baseline_run(base, snap, tree, path, extra=()):
    argv = [str(snap), "--tree", str(tree), "--workdir", str(base / "wd"),
            "--baseline", str(path), "--json", str(base / "r.json"), *extra]
    return R.main(argv), json.loads((base / "r.json").read_text())


def test_baseline_records_the_table_AND_the_tree_that_produced_it():
    """A baseline that cannot say what produced it answers "did the judgement
    change?" with "changed from what?"."""
    base = _tmp()
    steps = [("2", "PASS"), ("7", "INCOMPLETE")]
    snap = _snapshot(base / "snap", steps, "PASS")
    tree = _tree(base / "tree", {"verdict": "PASS", "steps": _steps(steps)})
    path = base / "ref" / "snap.json"
    rc, rep = _baseline_run(base, snap, tree, path)
    assert rc == 0 and rep["verdict"] == "BASELINE_RECORDED"
    rec = json.loads(path.read_text())
    assert rec["table"]["step_count"] == 2
    assert rec["recorded_by_tree"]["tree"] == str(tree)
    assert "replay_argv" in rec and "--strict" in rec["replay_argv"]
    assert rep["diff"] is None, "--baseline records; it does not grade"


def test_KNOWN_POSITIVE_a_baseline_REFUSES_to_overwrite_without_force():
    """A reference that can be silently re-cut is a reference that makes red
    diffs disappear — the `--write-baseline` shape this repo forbids."""
    base = _tmp()
    steps = [("2", "PASS")]
    snap = _snapshot(base / "snap", steps, "PASS")
    tree = _tree(base / "tree", {"verdict": "PASS", "steps": _steps(steps)})
    path = base / "ref.json"
    assert _baseline_run(base, snap, tree, path)[0] == 0
    before = path.read_text()
    rc, rep = _baseline_run(base, snap, tree, path)
    assert rc == 2 and "already exists" in rep["refusal"]
    assert path.read_text() == before, "the existing reference was overwritten"


def test_KNOWN_NEGATIVE_force_baseline_does_overwrite():
    """The escape hatch exists and is explicit — the refusal must be a refusal,
    not an impossibility."""
    base = _tmp()
    snap = _snapshot(base / "snap", [("2", "PASS")], "PASS")
    tree_a = _tree(base / "ta", {"verdict": "PASS",
                                 "steps": _steps([("2", "PASS")])})
    path = base / "ref.json"
    assert _baseline_run(base, snap, tree_a, path)[0] == 0
    tree_b = _tree(base / "tb", {"verdict": "FAIL",
                                 "steps": _steps([("2", "FAIL")]), "rc": 1})
    rc, _ = _baseline_run(base, snap, tree_b, path, extra=["--force-baseline"])
    assert rc == 0
    assert json.loads(path.read_text())["table"]["steps"]["2"]["status"] == "FAIL"


def test_a_recorded_baseline_is_the_reference_the_next_run_diffs_against():
    """The whole point: subject, scope and run shape equal by construction, and
    the TREE the only variable — which is the experiment."""
    base = _tmp()
    steps = [("2", "PASS"), ("7", "PASS")]
    snap = _snapshot(base / "snap", steps, "PASS")
    tree_a = _tree(base / "ta", {"verdict": "PASS", "steps": _steps(steps)})
    path = base / "ref.json"
    assert _baseline_run(base, snap, tree_a, path)[0] == 0

    worse = [("2", "PASS"), ("7", "FAIL")]
    tree_b = _tree(base / "tb", {"verdict": "FAIL", "steps": _steps(worse),
                                 "rc": 1})
    out = base / "after.json"
    rc = _replay(snap, tree_b, base / "wd_b", out, reference=path)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 1
    assert [e["id"] for e in rep["diff"]["regressions"]] == ["7"]
# ── R-0915-88: the RUN SHAPE reaches the replay too ─────────────────────────


# ── the refusals ─────────────────────────────────────────────────────────────

def test_a_STAGE_SCOPED_recorded_table_is_REFUSED_not_diffed():
    """MEASURED 2026-09-16 and the reason this refusal exists: BOTH frozen
    snapshots the orchestrator supplied carry a 9-step stage-scoped audit,
    because the LAST compliance invocation of a run overwrites the full table.
    Diffing 69 against 9 prints 60 REMOVED steps and reads as a catastrophe
    that never happened. The TABLE is still emitted — it is the baseline."""
    rc, rep, _ = _scenario(
        [("A1", "PASS")], [("2", "PASS"), ("7", "PASS")],
        snap_argv=["stage4_compliance.py", ".", "--exclude-step", "39"])
    assert rc == 2
    assert "NOT_COMPARABLE" in rep["refusal"]
    assert rep["table"] is not None, "the baseline table must survive a refusal"
    assert rep["table"]["step_count"] == 2


def test_a_prior_replay_report_is_usable_as_the_reference():
    """The intended experiment: today's baseline becomes tomorrow's reference,
    so both sides come from the same fixed invocation on the same frozen
    subject and the ONLY difference is the tree."""
    base = _tmp()
    steps = [("2", "PASS"), ("7", "PASS")]
    snap = _snapshot(base / "snap", steps, "PASS")
    tree_a = _tree(base / "tree_a", {"verdict": "PASS", "steps": _steps(steps)})
    baseline = base / "baseline.json"
    assert _replay(snap, tree_a, base / "wd_a", baseline) == 0

    worse = [("2", "PASS"), ("7", "FAIL")]
    tree_b = _tree(base / "tree_b", {"verdict": "FAIL", "steps": _steps(worse),
                                     "rc": 1})
    out = base / "after.json"
    rc = _replay(snap, tree_b, base / "wd_b", out, reference=baseline)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 1
    assert [e["id"] for e in rep["diff"]["regressions"]] == ["7"]


def test_a_snapshot_with_NO_recorded_audit_and_no_reference_REFUSES():
    """Nothing to compare read as nothing changed is the zero-denominator
    green. It refuses instead."""
    base = _tmp()
    snap = base / "snap"
    (snap / "reports").mkdir(parents=True)
    tree = _tree(base / "tree", {"verdict": "PASS", "steps": _steps([("2",
                                                                     "PASS")])})
    out = base / "o.json"
    rc = _replay(snap, tree, base / "wd", out)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 2 and "nothing to diff against" in rep["refusal"]


def test_a_directory_that_is_not_a_run_snapshot_REFUSES():
    base = _tmp()
    notasnap = base / "notasnap"
    notasnap.mkdir()
    tree = _tree(base / "tree", {"verdict": "PASS", "steps": []})
    out = base / "o.json"
    rc = _replay(notasnap, tree, base / "wd", out)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 2 and "no reports/ directory" in rep["refusal"]


def test_a_tree_with_no_compliance_checker_REFUSES():
    base = _tmp()
    snap = _snapshot(base / "snap", [("2", "PASS")], "PASS")
    empty = base / "tree"
    (empty / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
     / "programs").mkdir(parents=True)
    out = base / "o.json"
    rc = _replay(snap, empty, base / "wd", out)
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 2 and "no compliance checker" in rep["refusal"]


def test_no_timeout_kill_or_deadline_appears_in_this_program():
    """The owner's standing rule, pinned in the file."""
    src = Path(R.__file__).read_text(encoding="utf-8")
    body = src.split('"""', 2)[2]
    for banned in ("timeout=", "subprocess.TimeoutExpired", ".kill(",
                   ".terminate(", "signal.alarm", "SIGKILL"):
        assert banned not in body, "%r must not appear in audit_replay" % banned


# ── snapshot and --tree given together: decided, and refused only on collision ──

def test_a_tree_that_is_the_snapshot_is_refused(tmp_path, capsys):
    """RED on main: nothing decided the both-given case, so a --tree pointed at
    the snapshot re-judged it with its own frozen programs and reported that
    as a replay."""
    snap = tmp_path / "snap"
    snap.mkdir()
    rc = R.main([str(snap), "--tree", str(snap), "--workdir", str(tmp_path / "w")])
    assert rc == 2
    assert "same or nested" in capsys.readouterr().err


def test_a_tree_nested_inside_the_snapshot_is_refused(tmp_path, capsys):
    snap = tmp_path / "snap"
    (snap / "checkout").mkdir(parents=True)
    rc = R.main([str(snap), "--tree", str(snap / "checkout"),
                 "--workdir", str(tmp_path / "w")])
    assert rc == 2
    assert "same or nested" in capsys.readouterr().err


def test_separate_snapshot_and_tree_are_not_refused_by_this_check(tmp_path, capsys):
    """CONTROL: the ordinary invocation (real_ic_arm.sh:298 passes both, always)
    must not be caught by the collision refusal."""
    snap = tmp_path / "snap"
    tree = tmp_path / "tree"
    snap.mkdir()
    tree.mkdir()
    R.main([str(snap), "--tree", str(tree), "--workdir", str(tmp_path / "w")])
    assert "same or nested" not in capsys.readouterr().err
