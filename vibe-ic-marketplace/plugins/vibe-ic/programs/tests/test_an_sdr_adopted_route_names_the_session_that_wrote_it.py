"""An SDR-adopted route names the openroad session that wrote it.

MEASURED on spm run23 (final re-run on main 240c0a353, via icspm5), step 21:

    provenance.jsonl  row  57  openroad  routed.def d7b41629...  (reconstructed)
                      row 108  phase3_one_shot_runner re-emit     b5bfaf42...
                      row 161  phase3_one_shot_runner re-emit     6f8e3d27...  = disk
    provenance_check --tool openroad --require-measured
        -> routed.def hash mismatch  log=d7b41...  disk=6f8e3...  -> FAIL

and p3final.log: `SDR ADOPT: finishing the post-route tail from candidate.def
with postroute_drv_repair omitted` / `SDR_ADOPT ADOPTED`. The parent session
stops at the accept having written nothing; the ADOPT TAIL -- a fresh openroad
session restored from the candidate database -- writes routed.def, <top>.def and
<top>_pnr.v. It declared no outputs, so no openroad record carried those bytes.

The tail now declares the shipped products it writes (read off its own Tcl),
with any earlier copy set aside for the session and put back if it was not
rewritten -- so only bytes the session wrote are attested, and the file on disk
is what main would leave. The shape #2569 gave the sign-off repair sessions. Driven through the REAL `_pnr_adopt_sdr_candidates`
over the REAL PnR template; the container is faked only where openroad writes
its files, and logs the invocation exactly as `_docker_exec` does. The verdict
is the real `provenance_check`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase3_one_shot_runner as R                              # noqa: E402
import provenance_check as PC                                   # noqa: E402
from test_sdr_checkpoint_and_child import _full_pnr_tcl

TOP = "chip_top"
PNR = "phase3/stage3/pnr"
ROUTED = f"{PNR}/routed.def"
ORIGINAL = b"VERSION 5.8 ;\nDESIGN chip_top ;\n# the original route\nEND DESIGN\n"
EARLIER = b"VERSION 5.8 ;\nDESIGN chip_top ;\n# an earlier re-run\nEND DESIGN\n"
ADOPTED = b"VERSION 5.8 ;\nDESIGN chip_top ;\n# the adopted candidate\nEND DESIGN\n"


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()




def _run23(tmp_path: Path, monkeypatch) -> Path:
    """run23's ledger before the adoption: row 57 (the original route, a
    reconstructed openroad record) and row 108 (a nameless runner re-emit);
    the disk holds the earlier re-run's bytes."""
    proj = tmp_path / "proj"
    pnr = proj / PNR
    pnr.mkdir(parents=True)
    (pnr / "pnr.tcl").write_text(
        _full_pnr_tcl(tmp_path).replace(str(tmp_path / "out"), str(pnr)))
    (pnr / "routed.def").write_bytes(EARLIER)
    with (proj / "provenance.jsonl").open("w") as f:
        f.write(json.dumps({
            "tool": "openroad", "command": "openroad -no_init -exit pnr.tcl",
            "exit_code": 0, "duration_ms": None, "reconstructed": True,
            "timestamp": "2026-09-23T11:38:55Z",
            "outputs": {ROUTED: _sha(ORIGINAL)}}) + "\n")
        f.write(json.dumps({
            "tool": "phase3_one_shot_runner",
            "command": "re-emit (phase3 iteration)", "exit_code": 0,
            "duration_ms": None, "reconstructed": True,
            "timestamp": "2026-09-23T17:24:00Z",
            "outputs": {ROUTED: _sha(EARLIER)}}) + "\n")
    monkeypatch.setattr(R, "_PROV_SINK", proj)
    return proj






def _step21(proj: Path):
    out = proj / "pc.json"
    rc = PC.main([str(proj), "--output", ROUTED, "--tool", "openroad",
                  "--json", str(out)])
    return rc, json.loads(out.read_text())["checks"][0]


# ── run23's adoption: RED on main ──────────────────────────────────────────









# ── what the check refused before, it still refuses ───────────────────────

def test_run23s_ledger_as_it_stands_still_fails(tmp_path, monkeypatch):
    proj = _run23(tmp_path, monkeypatch)
    (proj / ROUTED).write_bytes(ADOPTED)
    with (proj / "provenance.jsonl").open("a") as f:
        f.write(json.dumps({
            "tool": "phase3_one_shot_runner",
            "command": "re-emit (phase3 iteration)", "exit_code": 0,
            "timestamp": "2026-09-24T02:07:49Z", "reconstructed": True,
            "outputs": {ROUTED: _sha(ADOPTED)}}) + "\n")
    rc, check = _step21(proj)
    assert (rc, check["status"]) == (1, "FAIL"), check
    assert any("hash mismatch" in r for r in check["reasons"]), check




# ── r2 (ruling): every route-producing path names its producer ─────────────
