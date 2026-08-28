"""#480 (HIGH) — blindness_audit must not CRASH on Claude-Code jsonl.

ORGANIC-20260607-blindness-audit-jsonl-crash. A Claude-Code transcript is one
JSON object per line; a single line concatenates a LEGAL prompt-file read with
the rest of the JSON:

    {"...","input":{"file_path":".../<prob>_prompt.txt"}},"caller":{"type":"direct"}}

The old auditor regexed over the RAW line and (via the disk-truth ladder)
glued the legal path onto the trailing JSON into one enormous token →
``OSError: File name too long`` → the uncaught crash exited 1, which
``benchmark_dispatch.py --score`` consumed as ``rc == 1`` and MISLABELLED as
"agent accessed non-prompt dataset files" blindness FAIL. Genuinely-blind
campaigns could not be canonically scored (all 4 benchmarks of a campaign hit
it; hosts fell back to manual grep audits).

The fix: (1) the transcript walker parses each line with ``json.loads`` and
scans the STRUCTURED tool-use input field VALUES (file_path / command / …),
never the raw line; non-JSON lines fall back to the legacy text scan. (2) an
auditor-internal exception surfaces as a NAMED ``AUDIT_ERROR`` with its own
exit code (``EXIT_AUDIT_ERROR == 3``), distinct from a blindness violation,
and ``--score`` maps it to a clearly-distinct refusal — never the blindness
FAIL message.

ACCEPTANCE (issue ## 驗收, executed end-to-end below):
  * a real-shaped Claude-Code jsonl line with a legitimate ``_prompt.txt``
    read followed by ``},"caller":{"type":"direct"}}`` on the same line →
    audit PASS;
  * a synthetic genuine violation line (a read of a ``*_ref.sv`` path) →
    audit FAILs with the violation named;
  * a corrupt / non-JSON line → no crash (graceful skip);
  * an internal OSError surfaces as AUDIT_ERROR, never a blindness FAIL.

chip-AGNOSTIC: synthetic Prob* names + tmp_path datasets only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import blindness_audit as ba  # noqa: E402
from _entry_guard_fixture import write_prompt_report  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
AUDIT = PLUGIN / "programs" / "blindness_audit.py"
DISPATCH = PLUGIN / "programs" / "benchmark_dispatch.py"

_ALLOWED = ["*_prompt.txt"]


# ── the EXACT issue shape: legal prompt read + caller frame on one line ──────

def _legit_prompt_line(ds: Path) -> str:
    """A real-shaped Claude-Code jsonl line: a tool_use input with a file_path
    ending in _prompt.txt, followed by },"caller":{"type":"direct"}} on the
    SAME line (the exact concatenation from the issue)."""
    return ('{"type":"assistant","message":{"content":[{"type":"tool_use",'
            '"name":"Read","input":{"file_path":"' + str(ds) +
            '/Prob001_prompt.txt"}}]},"caller":{"type":"direct"}}')


def test_legit_jsonl_prompt_read_passes(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("Build a thing.\n")
    fs = ba.audit_text(_legit_prompt_line(ds), ds, _ALLOWED, "t.jsonl")
    assert fs == [], fs


def test_legit_jsonl_prompt_read_passes_when_path_on_disk(tmp_path):
    # the disk-truth ladder's exists() probe is the line that crashed; ensure
    # an ON-DISK prompt file (so the ladder actively probes) still PASSes.
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob042_prompt.txt").write_text("spec")
    line = ('{"input":{"file_path":"' + str(ds) +
            '/Prob042_prompt.txt"}},"caller":{"type":"direct"}}')
    assert ba.audit_text(line, ds, _ALLOWED, "t.jsonl") == []


# ── the crash itself: giant concatenated token must NOT raise ────────────────

def test_giant_concatenated_jsonl_line_does_not_crash(tmp_path):
    # reproduces the OSError: File name too long — an on-disk dataset + a JSON
    # tail full of spaces drove the old ladder to extend to EOL and probe a
    # >4000-char path. Must be handled, never raised.
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("spec")
    giant = '"' + (',"k":"v with spaces and more text"') * 4000
    line = '{"input":{"file_path":"' + str(ds) + '/Prob001_prompt.txt' + giant + '}}'
    # would previously raise OSError([Errno 36] File name too long)
    fs = ba.audit_text(line, ds, _ALLOWED, "t.jsonl")
    assert isinstance(fs, list)          # no crash; legal prompt → no finding
    assert fs == []


# ── genuine violation inside JSON: a *_ref.sv read must FAIL, named ──────────

def test_jsonl_ref_read_is_flagged(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_ref.sv").write_text("module RefModule; endmodule\n")
    line = ('{"type":"assistant","message":{"content":[{"type":"tool_use",'
            '"name":"Read","input":{"file_path":"' + str(ds) +
            '/Prob001_ref.sv"}}]},"caller":{"type":"direct"}}')
    fs = ba.audit_text(line, ds, _ALLOWED, "t.jsonl")
    assert len(fs) == 1, fs               # exactly one finding (no double-count)
    assert fs[0]["kind"] == "dataset-file-access"
    assert "test/ref/golden" in fs[0]["class"]
    assert fs[0]["path"] == f"{ds}/Prob001_ref.sv"


def test_jsonl_bash_command_scorer_self_run_flagged(tmp_path):
    # a Bash tool_use whose `command` field self-runs the host scorer
    ds = tmp_path / "ds"; ds.mkdir()
    line = ('{"type":"assistant","message":{"content":[{"type":"tool_use",'
            '"name":"Bash","input":{"command":"python3 '
            '/x/benchmark/score_iverilog_tb.py --bench b"}}]}}')
    fs = ba.audit_text(line, ds, _ALLOWED, "t.jsonl")
    assert [f["kind"] for f in fs] == ["scorer-self-run"]


def test_jsonl_list_field_paths_scanned(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    line = ('{"input":{"paths":["' + str(ds) + '/Prob001_prompt.txt","' +
            str(ds) + '/Prob001_test.sv"]}}')
    fs = ba.audit_text(line, ds, _ALLOWED, "t.jsonl")
    assert len(fs) == 1
    assert fs[0]["path"] == f"{ds}/Prob001_test.sv"


# ── corrupt / non-JSON line: graceful, no crash ─────────────────────────────

def test_corrupt_non_json_line_no_crash(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    fs = ba.audit_text("{not valid json at all, truncated mid-", ds,
                       _ALLOWED, "t.jsonl")
    assert fs == []


def test_non_json_legacy_text_lines_still_scanned(tmp_path):
    # plain-text READ-line transcripts (the legacy format) must still work
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("spec")
    assert ba.audit_text(f"READ {ds}/Prob001_prompt.txt\n", ds,
                         _ALLOWED, "t.log") == []
    fs = ba.audit_text(f"cat {ds}/Prob001_ref.sv\n", ds, _ALLOWED, "t.log")
    assert len(fs) == 1 and "oracle" in fs[0]["class"]


# ── CLI exit codes: clean / violation / AUDIT_ERROR ─────────────────────────

def _run_cli(args):
    return _pr.run([sys.executable, str(AUDIT)] + args,
                          capture_output=True, text=True)


def test_cli_legit_jsonl_rc0(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("spec")
    t = tmp_path / "transcripts"; t.mkdir()
    (t / "batch.jsonl").write_text(_legit_prompt_line(ds) + "\n")
    r = _run_cli(["--dataset", str(ds), str(t)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_cli_giant_line_does_not_crash_rc0(tmp_path):
    # END-STATE of the filed defect: the previously-crashing campaign line now
    # exits 0 (PASS), NOT 1 (which would be mislabelled as a blindness FAIL).
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("spec")
    t = tmp_path / "transcripts"; t.mkdir()
    giant = '"' + (',"k":"v with spaces here"') * 4000
    line = '{"input":{"file_path":"' + str(ds) + '/Prob001_prompt.txt' + giant + '}}'
    (t / "batch.jsonl").write_text(line + "\n")
    r = _run_cli(["--dataset", str(ds), str(t)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert "File name too long" not in r.stderr


def test_cli_jsonl_violation_rc1(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_ref.sv").write_text("ref")
    t = tmp_path / "transcripts"; t.mkdir()
    line = ('{"input":{"file_path":"' + str(ds) + '/Prob001_ref.sv"}},'
            '"caller":{"type":"direct"}}')
    (t / "batch.jsonl").write_text(line + "\n")
    r = _run_cli(["--dataset", str(ds), str(t)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Prob001_ref.sv" in r.stdout


def test_audit_error_exit_code_is_three_and_named():
    # the named status is distinct from the violation code
    assert ba.EXIT_AUDIT_ERROR == 3
    assert ba.EXIT_VIOLATION == 1
    assert ba.EXIT_AUDIT_ERROR != ba.EXIT_VIOLATION


def test_internal_exception_surfaces_as_audit_error(tmp_path, monkeypatch):
    # An auditor-internal exception while SCANNING must surface as AUDIT_ERROR
    # (exit 3), NEVER as a blindness violation (exit 1). Force a non-OSError
    # internal failure so we exercise main()'s catch (not the _extract_rel
    # OSError guard).
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("spec")
    t = tmp_path / "transcripts"; t.mkdir()
    (t / "batch.jsonl").write_text(_legit_prompt_line(ds) + "\n")

    def boom(*a, **k):
        raise RuntimeError("synthetic internal auditor failure")

    monkeypatch.setattr(ba, "audit_text", boom)
    rc = ba.main(["--dataset", str(ds), str(t)])
    assert rc == ba.EXIT_AUDIT_ERROR == 3
    assert rc != ba.EXIT_VIOLATION       # NEVER folded into a blindness FAIL


# ── dispatch --score consumer contract ──────────────────────────────────────

def _stage_run(tmp_path, transcript_body: str):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("Build a thing.\n")
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    (run / "work").mkdir()
    # The upstream entry gate now validates producer semantics, not file
    # presence.  Stage its producer-derived prompt envelope so this test still
    # isolates the downstream blindness-audit behaviour.
    write_prompt_report(run)
    (run / ".bench_config.json").write_text(json.dumps({
        "bench": "verilogeval-v2", "dataset": str(ds), "shape": "C",
        "problems": 1, "batches": 1, "clean_room": True,
        "floor_only": False, "inherited_from": None, "seed_run": None}))
    t = run / "transcripts"; t.mkdir()
    (t / "batch00.jsonl").write_text(transcript_body)
    return ds, run


def _score(ds, run):
    return _pr.run(
        [sys.executable, str(DISPATCH), "verilogeval-v2", "--score",
         "--run", str(run), "--dataset", str(ds)],
        capture_output=True, text=True)


def test_dispatch_legit_jsonl_passes_audit_then_proceeds(tmp_path):
    # END-TO-END acceptance: the exact issue-shaped jsonl prompt read now
    # scores THROUGH the audit (no blindness FAIL), instead of crashing.
    ds, run = _stage_run(tmp_path, _legit_prompt_line(ds=tmp_path / "ds") + "\n")
    out = _score(ds, run)
    text = out.stdout + out.stderr
    assert "blindness_audit: PASS" in text, text
    assert "blindness audit FAILed" not in text
    assert "AUDIT_ERROR" not in text
    assert "Traceback" not in text


def test_dispatch_jsonl_ref_read_refused_as_violation(tmp_path):
    body = ('{"input":{"file_path":"' + str(tmp_path / "ds") +
            '/Prob001_ref.sv"}},"caller":{"type":"direct"}}\n')
    ds, run = _stage_run(tmp_path, body)
    out = _score(ds, run)
    assert out.returncode != 0
    assert "blindness audit FAILed" in (out.stdout + out.stderr)


def test_dispatch_giant_line_not_mislabelled_as_blindness_fail(tmp_path):
    # the core bug: the campaign-killing line must NOT produce the
    # "blindness audit FAILed — an agent accessed non-prompt dataset files"
    # message. It now PASSes cleanly.
    giant = '"' + (',"k":"v with spaces"') * 4000
    body = ('{"input":{"file_path":"' + str(tmp_path / "ds") +
            '/Prob001_prompt.txt' + giant + '}}\n')
    ds, run = _stage_run(tmp_path, body)
    out = _score(ds, run)
    text = out.stdout + out.stderr
    assert "agent accessed non-prompt" not in text, text
    assert "blindness_audit: PASS" in text, text


def test_dispatch_handles_audit_error_distinctly(tmp_path, monkeypatch):
    # When the auditor itself exits AUDIT_ERROR (3), --score must refuse with a
    # message clearly DISTINCT from the blindness-violation message, and must
    # NOT say the agent accessed dataset files. Drive cmd_score in-process with
    # a controlled subprocess.call: clean-room guard returns 0, the auditor
    # returns 3.
    sys.path.insert(0, str(PLUGIN / "programs"))
    import benchmark_dispatch as bd  # noqa: E402

    ds, run = _stage_run(tmp_path, _legit_prompt_line(ds=tmp_path / "ds") + "\n")

    def fake_call(cmd, *a, **k):
        prog = str(cmd[1]) if len(cmd) > 1 else ""
        if prog.endswith("blindness_audit.py"):
            return 3                               # AUDIT_ERROR
        return 0                                   # clean-room guard etc. pass

    monkeypatch.setattr(bd.subprocess, "call", fake_call)

    try:
        bd.cmd_score("verilogeval-v2", str(run), str(ds))
        raised = None
    except SystemExit as e:
        raised = str(e)
    assert raised is not None
    assert "AUDIT_ERROR" in raised
    assert "not a blindness violation" in raised.lower()
    # MUST NOT reuse the blindness-violation wording
    assert "agent accessed non-prompt" not in raised


def test_dispatch_source_maps_audit_error_distinctly():
    # belt-and-braces: the source carries the explicit rc==3 mapping and keeps
    # the AUDIT_ERROR refusal lexically distinct from the blindness FAIL.
    src = (PLUGIN / "programs" / "benchmark_dispatch.py").read_text()
    assert "rc == 3" in src
    assert "AUDIT_ERROR" in src
    idx = src.index("rc == 3")
    branch = src[idx:idx + 700]
    assert "NOT a blindness" in branch or "not a blindness" in branch.lower()
