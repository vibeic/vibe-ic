#!/usr/bin/env python3
"""`_log_invocation` records the outputs a CALL SITE declared — and only those.

WHY THIS EXISTS. `provenance_output_hash_completeness_check` enforces
anti-fabrication doctrine rule #2 ("Provenance entries carry SHA256 of every
output"). Measured on two converged spm cells, 37 of 44 `provenance.jsonl`
entries carried no `outputs` at all: every long tool run went through one
recorder that logged command/exit/version/timing and nothing else.

The tempting fix is to scan for files modified during each command's window
and attach whatever moved. That associates a hash with a command that may not
have produced it — a FABRICATED attestation, precisely what this gate exists
to catch. A fabricated audit chain is worse than an incomplete one, because it
is believed. So the caller declares, and the recorder hashes only that.

Direction 1 of every pair below is a case that must record NOTHING.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import phase3_one_shot_runner as R      # noqa: E402


def test_a_declared_and_produced_output_is_hashed(tmp_path):
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "out.def"
    f.write_bytes(b"HELLO DEF\n")
    got = R._hash_declared_outputs(str(tmp_path), ["sub/out.def"])
    assert got == {
        "sub/out.def": "sha256:" + hashlib.sha256(b"HELLO DEF\n").hexdigest()}


def test_a_declared_but_UNPRODUCED_output_is_omitted(tmp_path):
    """DIRECTION 1. A tool that failed produced nothing.

    Recording a declaration the tool did not honour would be the same
    fabrication one layer down, and the gate's own
    PROVENANCE_OUTPUT_FILE_MISSING would then fire on our own entry.
    """
    assert R._hash_declared_outputs(str(tmp_path), ["never_made.gds"]) == {}


def test_an_output_outside_the_project_is_omitted(tmp_path):
    """DIRECTION 1 — the gate's PROVENANCE_PATH_OUTSIDE_PROJECT rule.

    The audit chain only attests artefacts the project owns.
    """
    outside = tmp_path.parent / "elsewhere.gds"
    outside.write_bytes(b"X")
    try:
        assert R._hash_declared_outputs(str(tmp_path), [str(outside)]) == {}
    finally:
        outside.unlink()


def test_declaring_nothing_records_nothing(tmp_path):
    """DIRECTION 1 — empty is honest."""
    assert R._hash_declared_outputs(str(tmp_path), None) == {}
    assert R._hash_declared_outputs(str(tmp_path), []) == {}


def test_the_hash_is_of_the_real_bytes_not_the_path(tmp_path):
    """A hash that did not read the file would survive a content change."""
    f = tmp_path / "a.gds"
    f.write_bytes(b"first")
    h1 = R._hash_declared_outputs(str(tmp_path), ["a.gds"])["a.gds"]
    f.write_bytes(b"second")
    h2 = R._hash_declared_outputs(str(tmp_path), ["a.gds"])["a.gds"]
    assert h1 != h2
    assert h2 == "sha256:" + hashlib.sha256(b"second").hexdigest()


def test_recorder_emits_no_outputs_key_when_nothing_survives(tmp_path, monkeypatch):
    """The entry must not carry an empty `outputs` — the gate treats an
    empty dict as PROVENANCE_OUTPUTS_MISSING, same as absent."""
    import json
    monkeypatch.setattr(R, "_PROV_SINK", str(tmp_path), raising=False)
    R._log_invocation("openroad -exit x.tcl", 0, 5, marker="pnr",
                      outputs=["did_not_happen.def"])
    line = (tmp_path / "provenance.jsonl").read_text().strip()
    entry = json.loads(line)
    assert "outputs" not in entry, entry


def test_recorder_emits_the_declared_output_when_it_exists(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(R, "_PROV_SINK", str(tmp_path), raising=False)
    (tmp_path / "r.def").write_bytes(b"DEF")
    R._log_invocation("openroad -exit x.tcl", 0, 5, marker="pnr",
                      outputs=["r.def"])
    entry = json.loads((tmp_path / "provenance.jsonl").read_text().strip())
    assert entry["outputs"] == {
        "r.def": "sha256:" + hashlib.sha256(b"DEF").hexdigest()}
