"""v0.2.44 deterministic blindness-audit regressions.

Pins ORGANIC-20260605-blindness-deterministic-audit-guard (#413): the
prompt-only blindness contract was text-only and was skirted twice in one
campaign (an agent self-ran the host scorer mid-loop; another read a dataset
makefile for naming authority). `programs/blindness_audit.py` is the
deterministic transcript auditor; `benchmark_dispatch.py --score` runs it as
a front-door gate when `<RUNDIR>/transcripts/` is exported.

chip-AGNOSTIC: synthetic transcripts use generic Prob/design names only.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import blindness_audit as ba  # noqa: E402
from _entry_guard_fixture import write_prompt_report  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
DISPATCH = PLUGIN / "programs" / "benchmark_dispatch.py"
AUDIT = PLUGIN / "programs" / "blindness_audit.py"

_DS = Path("/data/bench/dataset")
_ALLOWED = ["*_prompt.txt"]


def _kinds(text):
    return [(f["kind"], f.get("class", "")) for f in
            ba.audit_text(text, _DS, _ALLOWED, "t.log")]


# ── V1: dataset-file access beyond allowed prompts ────────────────────────

def test_prompt_reads_and_bare_root_are_clean():
    text = (f"Reading {_DS}/Prob001_prompt.txt now\n"
            f"DATASET is {_DS}\n"
            f"also {_DS}/Prob002_prompt.txt for the next batch item\n")
    assert _kinds(text) == []


def test_sibling_ref_and_test_files_flagged():
    text = (f"cat {_DS}/Prob113_ref.sv\n"
            f"grep clk {_DS}/Prob113_test.sv\n")
    ks = _kinds(text)
    assert len(ks) == 2
    assert all(k == "dataset-file-access" and "oracle" in c for k, c in ks)


def test_build_files_flagged():
    text = (f"Read {_DS}/accu/Makefile\n"
            f"open {_DS}/adder/makefile\n"
            f"see {_DS}/common/verif.mk\n")
    ks = _kinds(text)
    assert len(ks) == 3
    assert all("build file" in c for _, c in ks)


def test_score_channel_path_flagged():
    text = f"ls {_DS}/proj7/score/src/test_dut.py\n"
    ks = _kinds(text)
    assert len(ks) == 1 and "score/ channel" in ks[0][1]


def test_other_nonprompt_dataset_file_flagged():
    ks = _kinds(f"head {_DS}/readme_notes.txt\n")
    assert len(ks) == 1 and ks[0][0] == "dataset-file-access"


# ── V2: agent-side scorer invocation ──────────────────────────────────────

def test_scorer_python_invocation_flagged():
    ks = _kinds("python3 /x/benchmark/score_iverilog_tb.py "
                "--bench b --dataset d --run r\n")
    assert ("scorer-self-run" in [k for k, _ in ks])


def test_dispatch_score_invocation_flagged():
    ks = _kinds("$ benchmark_dispatch.py mybench --score --run /tmp/r\n")
    assert [k for k, _ in ks] == ["scorer-self-run"]


def test_prose_mention_of_scorer_not_flagged():
    # shipped instructions quoted into the agent prompt mention the scorer
    # name WITHOUT a command shape — must not fire.
    text = ("The host orchestrator scores via the canonical scorer at "
            "`${CLAUDE_PLUGIN_ROOT}/benchmark/score_iverilog_tb.py` "
            "AFTER all batches finish.\n")
    assert _kinds(text) == []


# ── allowed-glob resolution ───────────────────────────────────────────────

def test_registry_narrows_allowed_globs():
    assert ba._allowed_globs("verilogeval-v2", []) == ["*_prompt.txt"]


def test_explicit_globs_override():
    assert ba._allowed_globs("verilogeval-v2", ["spec.md"]) == ["spec.md"]


# ── CLI exit codes ────────────────────────────────────────────────────────

def _run_cli(args):
    return subprocess.run([sys.executable, str(AUDIT)] + args,
                          capture_output=True, text=True, timeout=60)


def test_cli_clean_rc0(tmp_path):
    t = tmp_path / "transcripts"; t.mkdir()
    (t / "a.log").write_text(f"read {_DS}/Prob001_prompt.txt ok\n")
    r = _run_cli(["--dataset", str(_DS), str(t)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_cli_violation_rc1_names_path(tmp_path):
    t = tmp_path / "transcripts"; t.mkdir()
    (t / "agent3.log").write_text(f"cat {_DS}/sub/Makefile\n")
    r = _run_cli(["--dataset", str(_DS), str(t)])
    assert r.returncode == 1
    assert "agent3.log" in r.stdout and "Makefile" in r.stdout


def test_cli_nothing_to_audit_rc2(tmp_path):
    r = _run_cli(["--dataset", str(_DS), str(tmp_path / "absent")])
    assert r.returncode == 2


# ── dispatch --score front-door gate ──────────────────────────────────────

def _stage_run(tmp_path, with_violation: bool):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("Build a thing.\n")
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    (run / "work").mkdir()
    (run / ".bench_config.json").write_text(json.dumps({
        "bench": "verilogeval-v2", "dataset": str(ds), "shape": "C",
        "problems": 1, "batches": 1, "clean_room": True,
        "floor_only": False, "inherited_from": None, "seed_run": None}))
    t = run / "transcripts"; t.mkdir()
    body = (f"read {ds}/Prob001_prompt.txt\n" +
            (f"cat {ds}/Prob001_ref.sv\n" if with_violation else ""))
    (t / "batch00.log").write_text(body)
    # Stage the producer-derived prompt report so this downstream blindness
    # test reaches its subject without weakening the upstream entry contract.
    write_prompt_report(run)
    return ds, run


def test_score_front_door_refuses_on_violation(tmp_path):
    ds, run = _stage_run(tmp_path, with_violation=True)
    r = subprocess.run(
        [sys.executable, str(DISPATCH), "verilogeval-v2", "--score",
         "--run", str(run), "--dataset", str(ds)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "blindness audit FAILed" in (r.stdout + r.stderr)


def test_score_front_door_passes_audit_then_proceeds(tmp_path):
    ds, run = _stage_run(tmp_path, with_violation=False)
    r = subprocess.run(
        [sys.executable, str(DISPATCH), "verilogeval-v2", "--score",
         "--run", str(run), "--dataset", str(ds)],
        capture_output=True, text=True, timeout=60)
    # the audit must PASS and the gate must NOT be the failure reason;
    # the scorer itself then runs (and may fail on the empty synthetic run).
    out = r.stdout + r.stderr
    assert "blindness_audit: PASS" in out
    assert "blindness audit FAILed" not in out


# ── shipped instruction text carries the new prohibitions ─────────────────

def test_instruction_text_names_build_files_and_self_scoring():
    hb = (PLUGIN / "benchmark")
    for shape in ("b", "c", "d"):
        txt = (hb / f"blind_instructions_shape_{shape}.md").read_text()
        assert "BUILD files" in txt, shape
        assert "blindness_audit.py" in txt, shape
    skill = (PLUGIN / "skills" / "open-benchmark-methodology" /
             "SKILL.md").read_text()
    assert "the host scorer" in skill and "blindness_audit.py" in skill
