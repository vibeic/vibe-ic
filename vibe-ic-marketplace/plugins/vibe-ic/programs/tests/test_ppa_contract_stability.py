#!/usr/bin/env python3
"""Byte-stability — the property eleven other lanes are relying on.

WHY THIS FILE IS THE ONE THAT MATTERS MOST
==========================================
Every other PPA lane hashes against the contract. If the contract digest is not
a pure function of the declared inputs and the bytes under the run root, then
two runs that were genuinely identical produce two identities, every comparison
built on them is comparing things that were never the same, and NOTHING
downstream can detect it -- a wrong digest looks exactly like a right one.

So this is asserted, not assumed, and it is asserted the only way that means
anything: TWO PROCESSES. A same-process comparison would be satisfied by a hash
seed or a dict iteration order that happened to be stable within one
interpreter, which is precisely the failure mode. One of the tests below goes
further and gives the two processes DIFFERENT `PYTHONHASHSEED` values, because
that is the mechanism by which set and dict ordering actually varies between
runs of CPython.

THE CONVERSE IS ALSO ASSERTED
=============================
A digest that never moves is stable and useless. Every declared artefact is
perturbed by exactly one byte in turn, and the contract digest must move for
each -- otherwise "the inputs were the same" would be a claim the contract
could make about inputs that were not.

chip-AGNOSTIC: synthetic bytes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_ppa_contract_fixtures import (  # noqa: E402
    BUILD, PLUGIN_ROOT,
    base_declaration, make_run_tree, write_json,
)

import _progress_run as _pr  # noqa: E402

#: Key names that would make a document differ between two identical runs. A
#: contract carrying any of these cannot be byte-compared, and then the whole
#: identity story degrades into "diff it and decide which differences do not
#: count" -- which is the judgement a digest exists to remove.
_TIME_VARYING = ("timestamp", "generated_at", "created_at", "date", "time",
                 "now", "hostname", "host", "pid", "user", "username",
                 "cwd", "uuid", "run_id", "elapsed", "duration")


def _build(tmp_path: Path, name: str, seed: str = "0",
           declaration=None, root: Path = None) -> Path:
    """Build a contract in its OWN process, optionally with a hash seed."""
    root = root or make_run_tree(tmp_path / "run")
    decl = write_json(tmp_path / f"{name}.declaration.json",
                      declaration or base_declaration())
    out = tmp_path / f"{name}.contract.json"
    env = dict(os.environ, PYTHONHASHSEED=seed)
    proc = _pr.run(
        [sys.executable, str(BUILD), "--declaration", str(decl),
         "--root", str(root), "--out", str(out), "--no-image-labels"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT), env=env)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    return out


def test_the_same_input_twice_gives_a_byte_identical_contract(tmp_path):
    first = _build(tmp_path, "a")
    second = _build(tmp_path, "b")
    assert first.read_bytes() == second.read_bytes(), (
        "two builds of the same declaration over the same bytes produced "
        "different documents; every lane that hashes against this contract is "
        "now comparing things that were never the same")


def test_byte_stability_survives_a_different_hash_seed(tmp_path):
    """The mechanism by which dict and set ordering actually varies.

    Without this, a same-seed comparison would pass over a serializer that had
    quietly started depending on iteration order, and the instability would
    surface later as two identities for one run -- on a different host, in
    somebody else's lane."""
    first = _build(tmp_path, "seed0", seed="0")
    second = _build(tmp_path, "seed12345", seed="12345")
    assert first.read_bytes() == second.read_bytes()


def test_byte_stability_survives_a_different_run_directory(tmp_path):
    """Same content, different host path. The contract records a root LABEL,
    never a host path, so a run reproduced somewhere else is recognisably the
    same run rather than a new one."""
    here = _build(tmp_path / "one", "x")
    there = _build(tmp_path / "two", "x")
    assert here.read_bytes() == there.read_bytes()


def test_the_contract_carries_no_time_varying_field(tmp_path):
    """A program-first statement of the rule above, so a future author who
    adds `generated_at` is told by a test rather than by a broken comparison
    six lanes away."""
    document = json.loads(_build(tmp_path, "keys").read_text())
    offenders = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if any(t == lowered or lowered.endswith("_" + t)
                       for t in _TIME_VARYING):
                    offenders.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(document)
    assert not offenders, (
        "the contract carries time- or host-varying field(s) %s, so two "
        "identical runs can no longer be byte-compared" % offenders)

    # Positive control. "The walk found nothing" and "the walk did not run"
    # print the same empty list, so the scanner is shown to fire on a document
    # that DOES carry one before its silence on the real document is believed.
    offenders.clear()
    walk({"run_manifest": {"generated_at": "2026-08-21T00:00:00Z"}})
    assert offenders == ["$.run_manifest.generated_at"], (
        "the time-varying-field scanner does not detect a field it was "
        "written to detect, so its silence above establishes nothing")


def test_one_byte_in_any_declared_artefact_moves_the_contract_digest(tmp_path):
    """Every artefact, one at a time. A digest that moves for the RTL but not
    for the SDC would let a changed problem pass as the same problem."""
    root = make_run_tree(tmp_path / "run")
    baseline = json.loads(_build(tmp_path, "base", root=root).read_text())
    original = baseline["contract_digest"]

    declared = [r["path"] for r in baseline["run_manifest"]["artefacts"]]
    assert declared, "the fixture declares no artefacts; this test is vacuous"

    for rel in declared:
        target = root / rel
        before = target.read_bytes()
        try:
            target.write_bytes(before + b" ")     # exactly one byte
            moved = json.loads(
                _build(tmp_path, "moved", root=root).read_text())
            assert moved["contract_digest"] != original, (
                f"changing one byte of {rel} did not move the contract "
                f"digest; the contract cannot tell these two runs apart")
        finally:
            target.write_bytes(before)

    restored = json.loads(_build(tmp_path, "restored", root=root).read_text())
    assert restored["contract_digest"] == original, (
        "restoring the bytes did not restore the digest, so the digest "
        "depends on something other than the declared inputs")


def test_the_file_on_disk_is_the_bytes_the_digest_was_taken_over(tmp_path):
    """A reader who re-hashes the document must get the number it states about
    itself. If the writer pretty-printed it, they would not."""
    sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
    from _ppa import canonical_json, contract as C   # noqa: E402
    path = _build(tmp_path, "bytes")
    text = path.read_text()
    document = json.loads(text)
    assert text == canonical_json.dumps(document) + "\n"
    assert document["contract_digest"] == C.contract_digest_of(document)
