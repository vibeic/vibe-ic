"""Unit tests for provenance_check.py."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

LOGGER = Path(__file__).parent.parent / "provenance_logger.py"
CHECKER = Path(__file__).parent.parent / "provenance_check.py"
assert LOGGER.exists() and CHECKER.exists()


def _run_check(*args) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True, text=True)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _log_entry(project: Path, tool: str, out_rel: str, exit_code: int = 0):
    """Append a hand-constructed entry (simulates a logger run)."""
    abs_p = project / out_rel
    entry = {
        "timestamp": "2026-04-22T10:00:00Z",
        "tool": tool,
        "version": "mock",
        "cwd": str(project),
        "argv": ["mock"],
        "inputs": {},
        "outputs": {out_rel: _sha(abs_p) if abs_p.exists() else "missing"},
        "exit_code": exit_code,
        "duration_s": 0.1,
        "stdout_sha": "sha256:0",
        "stderr_sha": "sha256:0",
        "stdout_tail": "",
        "stderr_tail": "",
    }
    with (project / "provenance.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def test_passes_when_log_and_hash_match(tmp_path):
    (tmp_path / "out.txt").write_text("content\n")
    _log_entry(tmp_path, "cat", "out.txt")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 0


def test_fails_when_file_missing(tmp_path):
    # Log claims output but it doesn't exist on disk
    (tmp_path / "provenance.jsonl").write_text(json.dumps({
        "timestamp": "2026-04-22T10:00:00Z",
        "tool": "cat", "version": "", "cwd": str(tmp_path), "argv": [],
        "inputs": {}, "outputs": {"gone.txt": "sha256:abc"},
        "exit_code": 0, "duration_s": 0,
        "stdout_sha": "", "stderr_sha": "", "stdout_tail": "", "stderr_tail": "",
    }) + "\n")
    r = _run_check(str(tmp_path), "--output", "gone.txt", "--tool", "cat")
    assert r.returncode == 1
    assert "missing" in (r.stdout + r.stderr).lower()


def test_fails_on_hash_mismatch(tmp_path):
    f = tmp_path / "out.txt"
    f.write_text("v1")
    _log_entry(tmp_path, "cat", "out.txt")
    # Modify file after logging
    f.write_text("v2-different")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 1
    assert "hash mismatch" in (r.stdout + r.stderr).lower()


def test_fails_on_wrong_tool(tmp_path):
    (tmp_path / "out.txt").write_text("x")
    _log_entry(tmp_path, "cat", "out.txt")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "yosys,openroad")
    assert r.returncode == 1


def test_fails_on_nonzero_exit_entry(tmp_path):
    (tmp_path / "out.txt").write_text("x")
    _log_entry(tmp_path, "cat", "out.txt", exit_code=1)
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 1


def test_fails_with_no_log(tmp_path):
    (tmp_path / "out.txt").write_text("x")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 1


def test_require_entries_mode(tmp_path):
    for i in range(3):
        _log_entry(tmp_path, f"t{i}", f"f{i}")
        (tmp_path / f"f{i}").write_text("x")
    r = _run_check(str(tmp_path), "--require-entries", "3")
    assert r.returncode == 0
    r = _run_check(str(tmp_path), "--require-entries", "5")
    assert r.returncode == 1


def test_logger_and_checker_roundtrip(tmp_path):
    """Invoke provenance_logger end-to-end, then provenance_check it."""
    (tmp_path / "in.txt").write_text("hello")
    subprocess.run([
        sys.executable, str(LOGGER),
        "--project", str(tmp_path),
        "--tool", "echo",
        "--output", "out.txt",
        "--",
        "sh", "-c", "echo roundtrip > out.txt",
    ], check=True, timeout=15)
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "echo")
    assert r.returncode == 0, r.stdout + r.stderr


# These are consumer contract fixtures, not native EDA measurements. The native
# handoff validator has its own transport tests; real retained producer/consumer
# controls additionally exercise it without replacing any native validation.
import pytest  # noqa: E402
import provenance_check as pc  # noqa: E402
import synth_handoff_netlist_check as handoff  # noqa: E402


@pytest.fixture
def synthesis_chain(tmp_path, monkeypatch):
    p = tmp_path / "project"
    rels = {
        "parent": "phase3/librelane/02-yosys-synthesis/top.nl.v",
        "native": "phase3/librelane/postmap/01-vibeic-postmaprepair/top.nl.v",
        "canonical": "phase2/stage2/synth/netlist.v",
        "mapped": "phase2/stage2/synth/top_synth.v",
    }
    for name, rel in rels.items():
        path = p / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("parent\n" if name == "parent" else "post-map child\n")
    (p / "phase2/stage2/synth/synth_inputs.json").write_text(json.dumps({
        "netlist": "top_synth.v", "librelane_synthesis": {"post_map": {"fixture": True}}}))
    (p / "phase3/librelane_switch.json").write_text(json.dumps({"post_map_repair": "pre_placement"}))
    rows = [
        {"timestamp": "2026-10-20T00:00:00Z", "record": "artefact", "tool": "yosys",
         "exit_code": 0, "outputs": {rels["parent"]: _sha(p / rels["parent"])},
         "measurement": {"schema": "mcp-eda/measurement/1", "measured": True}},
        {"timestamp": "2026-10-20T00:00:01Z", "record": "artefact", "tool": "openroad",
         "produced_by": "Vibeic.PostMapRepair", "exit_code": 0,
         "outputs": {rels[k]: _sha(p / rels[k]) for k in ("canonical", "mapped")},
         "measurement": {"schema": "mcp-eda/measurement/1", "measured": True}},
    ]
    native = {"verdict": "PASS", "producer": "LibreLane.Yosys.Synthesis -> Vibeic.PostMapRepair",
              **{k: str(p / v) for k, v in rels.items()}}
    calls = []
    def validate(project):
        assert project == p
        calls.append(project)
        return native
    monkeypatch.setattr(handoff, "bound_handoff", validate)
    def run(tools="yosys,yosys-abc", output=None, pnr=False):
        (p / "provenance.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        report = tmp_path / "report.json"
        args = [str(p), "--tool", tools, "--require-measured", "--json", str(report)]
        args += ["--pnr-netlist"] if pnr else ["--output", output or rels["canonical"]]
        rc = pc.main(args)
        return rc, json.loads(report.read_text())
    return p, rels, rows, native, calls, run


@pytest.mark.parametrize("pnr", [False, True])
def test_native_synthesis_chain_keeps_both_writer_identities(synthesis_chain, pnr):
    _, _, _, _, calls, run = synthesis_chain
    rc, report = run(pnr=pnr)
    assert rc == 0
    assert {row["status"] for row in report["checks"]} == {"PASS"}
    assert {row["tool"] for row in report["checks"]} == {"openroad"}
    for row in report["checks"]:
        chain = row["synthesis_lineage"]
        assert chain["parent"]["tool"] == "yosys"
        assert chain["child"]["produced_by"] == "Vibeic.PostMapRepair"
        assert chain["allowed_tools_scope"] == "native_yosys_parent"
    assert len(calls) == 1  # Fresh per analysis, shared only by the two aliases.
    assert run(pnr=pnr)[0] == 0
    assert len(calls) == 2


@pytest.mark.parametrize("damage", ["missing_parent", "parent_tool", "parent_hash", "child_tool",
                                    "child_publisher", "child_exit", "child_hash", "missing_child",
                                    "native_handoff", "native_producer"])
def test_native_synthesis_chain_refuses_a_broken_link(synthesis_chain, damage):
    _, _, rows, native, _, run = synthesis_chain
    if damage == "missing_parent":
        rows.pop(0)
    elif damage == "parent_tool":
        rows[0]["tool"] = "foreign"
    elif damage == "parent_hash":
        rows[0]["outputs"] = {key: "sha256:" + "0" * 64 for key in rows[0]["outputs"]}
    elif damage == "child_tool":
        rows[1]["tool"] = "yosys"  # Relabelling OpenROAD cannot satisfy the parent allow-list.
    elif damage == "child_publisher":
        rows[1]["produced_by"] = "unrelated.OpenROAD"
    elif damage == "child_exit":
        rows[1]["exit_code"] = 1
    elif damage == "child_hash":
        rows[1]["outputs"] = {key: "sha256:" + "0" * 64 for key in rows[1]["outputs"]}
    elif damage == "missing_child":
        rows.pop(1)
    elif damage == "native_handoff":
        native.update(verdict="FAIL", findings=["current native input changed"])
    elif damage == "native_producer":
        native["producer"] = "unrelated.OpenROAD"
    rc, report = run()
    assert rc == 1
    assert {row["status"] for row in report["checks"]} == {"FAIL"}


@pytest.mark.parametrize("writer", [0, 1])
@pytest.mark.parametrize("measurement,expected_rc,status", [
    ({"schema": "mcp-eda/measurement/1", "measured": False,
      "not_measured_class": "TOOL_DID_NOT_RUN", "not_measured_reason": "no work"}, 1, "FAIL"),
    (None, 0, "UNMEASURED"),
])
def test_native_synthesis_chain_measures_both_runs(synthesis_chain, writer, measurement, expected_rc, status, capsys):
    _, _, rows, _, _, run = synthesis_chain
    if measurement is None:
        del rows[writer]["measurement"]
    else:
        rows[writer]["measurement"] = measurement
    rc, report = run()
    assert rc == expected_rc
    assert {row["status"] for row in report["checks"]} == {status}
    if status == "UNMEASURED":
        assert "INCOMPLETE:" in capsys.readouterr().out


def test_native_synthesis_chain_does_not_broaden_generic_tool_filters(synthesis_chain):
    p, _, rows, _, calls, run = synthesis_chain
    rel = "phase3/stage3/pnr/other.v"
    path = p / rel
    path.parent.mkdir(parents=True)
    path.write_text("post-map child\n")
    rows[1]["outputs"][rel] = _sha(path)
    rc, report = run(output=rel)
    assert rc == 1
    assert report["checks"][0]["status"] == "FAIL"
    assert len(calls) == 0


def test_native_synthesis_chain_preserves_terminal_tool_mode(synthesis_chain):
    _, _, _, _, calls, run = synthesis_chain
    rc, report = run(tools="openroad")
    assert rc == 0
    assert {row["status"] for row in report["checks"]} == {"PASS"}
    assert len(calls) == 0


@pytest.mark.parametrize("verified,expected_rc,status", [(False, 1, "FAIL"),
    (pc._tool_log_provenance.UNCALIBRATED, 0, "NOT_MEASURED")])
def test_native_synthesis_chain_preserves_parent_witness_disposition(
        synthesis_chain, monkeypatch, verified, expected_rc, status, capsys):
    _, _, rows, _, _, run = synthesis_chain
    monkeypatch.setattr(pc._tool_log_provenance, "claims_witness", lambda row: row.get("tool") == "yosys")
    monkeypatch.setattr(pc._tool_log_provenance, "verify_witness", lambda row, project: (verified, "controlled reader result"))
    rc, report = run()
    assert rc == expected_rc
    assert {row["status"] for row in report["checks"]} == {status}
    if status == "NOT_MEASURED":
        assert "INCOMPLETE:" in capsys.readouterr().out
