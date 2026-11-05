"""Steps 24, 26 and 26.5ic at their runner call sites, and the seal-ring
program's `--sealed-by` (lane mig101).

The runner's helpers and `die_finishing_gen` run for real.  Faked: the tool
arms' LibreLane runs (their records are written the way `librelane_ir_antenna`
writes them) and KLayout (a runner that writes what the PDK generator and the
seal-ring verifier write).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import die_finishing_gen as DFG  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()






# --- the refusals, re-read on every call ------------------------------------------





















# --- step 24 librelane publishes what the gates read --------------------------------



# --- step 26.5ic: _die_finishing hands the tool's output to die_finishing_gen --------













# --- die_finishing_gen --sealed-by: the tool's output judged like ours -------------

class _KLayout:
    """Writes what the PDK generator and the ring verifier write."""
    kind, detail = "test", "fake"

    def __init__(self):
        self.generator_calls = []

    def cpath(self, p):
        return str(p)

    def covers(self, p):
        return True

    def exists(self, p):
        return Path(str(p)).is_file()

    def klayout_bin(self):
        return "klayout"

    def run_argv(self, argv, env, timeout=1800):
        argv = [str(a) for a in argv]
        if argv[0] == "head":
            return 0, Path(argv[-1]).read_text()[:2000], ""
        if argv[0] == "sh":
            return 1, "", ""
        self.generator_calls.append(argv)
        out = argv[argv.index("--output") + 1]
        Path(out).write_bytes(Path(argv[argv.index("--input") + 1]).read_bytes() + b"+ring")
        return 0, "", ""

    def run(self, script, env, path_keys=(), timeout=1800):
        ok = Path(env["SEAL_OUT"]).is_file()
        Path(env["SEAL_REPORT"]).write_text(json.dumps(
            {"check": "pdk_seal_ring_present", "verdict": "PASS" if ok else "FAIL",
             "added_layers": ["81/0"], "ring": {"horizontal_crossings": 2,
                                                "vertical_crossings": 2,
                                                "centre_covered": False},
             "die_box_dbu": [0, 0, 100000, 100000],
             "ring_extent": {"outer": {"dbu": [0, 0, 100000, 100000], "um": [0, 0, 100, 100]},
                             "inner": {"dbu": [5000, 5000, 95000, 95000],
                                       "um": [5, 5, 95, 95]}}}))
        return 0, "", ""


def _dfg(tmp_path, monkeypatch, **kw):
    project = tmp_path / "p"
    (project / "phase3/stage3/pnr").mkdir(parents=True)
    gds = project / "phase3/stage3/pnr/top.gds"
    gds.write_bytes(b"die")
    (project / "phase3/stage3/pnr/routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\nEND DESIGN\n")
    script = tmp_path / "sealring.py"
    script.write_text("# --die-width\n")
    fake = _KLayout()
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: fake)
    res = DFG.run(project, str(gds), str(script), None, None, None, None, sys.executable,
                  None, 100.0, 100.0, None, True, None, **kw)
    return res, fake, gds


def test_a_sealed_by_stream_is_verified_and_shipped_without_our_generator(tmp_path, monkeypatch):
    tool = tmp_path / "tool_sealed.gds"
    tool.write_bytes(b"die+tool-ring")
    record = tmp_path / "record.json"
    record.write_text("{}")
    res, fake, gds = _dfg(tmp_path, monkeypatch, sealed_by=str(tool),
                          sealed_by_record=str(record))
    seal = res["seal_ring"]
    assert fake.generator_calls == []
    assert seal["state"] == "PASS", seal.get("reason")
    assert seal["producer"] == "librelane:KLayout.SealRing"
    assert seal["sealed_by"]["sha256"] == _sha(tool)
    assert seal["sealed_by"]["record_sha256"] == _sha(record)
    assert gds.read_bytes() == b"die+tool-ring"


def test_a_producer_refusal_fails_the_ring_by_name(tmp_path, monkeypatch):
    res, fake, gds = _dfg(tmp_path, monkeypatch,
                          sealed_by_error="LL_SEALRING_ORIGIN_UNSUPPORTED: [10, 10, 90, 90]")
    seal = res["seal_ring"]
    assert fake.generator_calls == []
    assert seal["state"] == "FAIL"
    assert "LL_SEALRING_ORIGIN_UNSUPPORTED" in seal["reason"]
    assert gds.read_bytes() == b"die"


def test_a_missing_sealed_by_stream_fails(tmp_path, monkeypatch):
    res, fake, gds = _dfg(tmp_path, monkeypatch, sealed_by=str(tmp_path / "absent.gds"))
    assert res["seal_ring"]["state"] == "FAIL" and fake.generator_calls == []


def test_without_sealed_by_our_generator_runs_as_before(tmp_path, monkeypatch):
    res, fake, gds = _dfg(tmp_path, monkeypatch)
    assert len(fake.generator_calls) == 1
    assert res["seal_ring"]["state"] == "PASS"
    assert "producer" not in res["seal_ring"]
