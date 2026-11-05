"""A route a sign-off repair PRODUCED and the runner PROMOTED stays bound to the
openroad run that produced its bytes.

MEASURED on spm run23 after a phase-3 re-run: step 21 FAILED

    provenance_check . --output phase3/stage3/pnr/routed.def --tool openroad
        --require-measured
    -> hash mismatch: log=sha256:d7b41629... disk=sha256:b5bfaf42...

provenance.jsonl held two records of routed.def: 11:38Z openroad d7b41629 (the
ORIGINAL route) and 17:24Z phase3_one_shot_runner b5bfaf42 (a bulk re-emit). The
bytes on disk were openroad's -- the repair session wrote `routed_repaired.def`
and the runner copied it over routed.def -- but the repair's openroad invocation
declared no outputs, so no record carried b5bfaf42 under the tool that made it.

THE CHECK IS NOT LOOSENED. `provenance_check` already binds an artefact to a run
BY CONTENT (`_declares`); the missing thing was the producing record. The runner
now declares what each route-producing openroad session writes
(`_run_route_producer`, removing any copy an earlier run left at that path first)
and records every promotion with its source, sha and producing entry
(`_record_route_promotion`).

The container is faked only where openroad would write its file; the runner's own
`_log_invocation`, promotion and re-emit bookkeeping run as shipped, and the
verdict is the real `provenance_check`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R                          # noqa: E402
import provenance_check as PC                               # noqa: E402

PNR = "phase3/stage3/pnr"
ROUTED = f"{PNR}/routed.def"
ORIGINAL = b"VERSION 5.8 ;\nDESIGN spm ;\n# the original route\nEND DESIGN\n"
REPAIRED = b"VERSION 5.8 ;\nDESIGN spm ;\n# the repaired route\nEND DESIGN\n"


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _project(tmp_path: Path) -> Path:
    """run23's ledger before the re-run: the ORIGINAL route, by openroad."""
    proj = tmp_path / "proj"
    (proj / PNR).mkdir(parents=True)
    (proj / ROUTED).write_bytes(ORIGINAL)
    (proj / f"{PNR}/spm.def").write_bytes(ORIGINAL)
    (proj / "provenance.jsonl").write_text(json.dumps({
        "record": "invocation", "tool": "openroad",
        "command": "openroad -no_init -exit /w/phase3/stage3/pnr/pnr.tcl",
        "exit_code": 0, "timestamp": "2026-09-23T11:38:00Z",
        "outputs": {ROUTED: _sha(ORIGINAL)}}) + "\n")
    return proj




def _check(proj: Path):
    out = proj / "pc.json"
    rc = PC.main([str(proj), "--output", ROUTED, "--tool", "openroad",
                  "--json", str(out)])
    return rc, json.loads(out.read_text())["checks"][0]


@pytest.fixture
def sink(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    monkeypatch.setattr(R, "_PROV_SINK", proj)
    return proj






# ── the repair promotion binds: RED on main (no producer declares the bytes) ─







# ── the other direction: nothing the check refused before is accepted now ──

def test_run23s_ledger_as_it_stands_still_fails(sink):
    """The measured shape: original openroad record + a nameless re-emit."""
    (sink / ROUTED).write_bytes(REPAIRED)
    with (sink / "provenance.jsonl").open("a") as f:
        f.write(json.dumps({
            "tool": "phase3_one_shot_runner",
            "command": "re-emit (phase3 iteration)", "exit_code": 0,
            "timestamp": "2026-09-23T17:24:00Z", "reconstructed": True,
            "outputs": {ROUTED: _sha(REPAIRED)}}) + "\n")
    rc, check = _check(sink)
    assert (rc, check["status"]) == (1, "FAIL"), check
    assert any("hash mismatch" in r for r in check["reasons"]), check




def test_a_stale_older_openroad_entry_alone_fails(sink):
    (sink / ROUTED).write_bytes(REPAIRED)
    rc, check = _check(sink)
    assert (rc, check["status"]) == (1, "FAIL"), check
    assert any("hash mismatch" in r for r in check["reasons"]), check
