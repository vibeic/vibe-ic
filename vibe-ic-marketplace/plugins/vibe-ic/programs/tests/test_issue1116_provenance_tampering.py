"""vibe-ic#1116 — can an agent make a check pass by editing the evidence?

#1116 ran four tampering methods against LibreLane's `Magic.DRC` state and all
four succeeded. This module runs the same four against OUR ledger, because the
issue's point was to audit ourselves rather than to criticise them.

The load-bearing test is (A2): the two-edit attack. Our recorded digests already
catch (A1) — a file edited WITHOUT its ledger line — and `provenance_logger`'s
docstring claimed that was the hard case, on the grounds that forging an entry
needs a hash collision. It does not. The agent edits the artefact and rewrites
the ledger line with the new digest: two edits, no collision. That claim is
corrected in the same change as these tests, because a false security argument
is worse than a missing one — it stops people looking.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "provenance_chain_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_pcc_under_test", MOD)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_pcc_under_test"] = m
    spec.loader.exec_module(m)
    return m


G = _load()
_H = lambda b: hashlib.sha256(b).hexdigest()


def _ledger(project: Path, records) -> Path:
    """Write a CHAINED ledger the way `provenance_logger` now writes one."""
    p = project / "provenance.jsonl"
    lines = []
    for rec in records:
        if lines:
            rec = dict(rec, chain_prev=_H(lines[-1].encode()))
        lines.append(json.dumps(rec, ensure_ascii=False))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture()
def honest(tmp_path):
    """A completed step: one artefact, one chained ledger recording its digest."""
    proj = tmp_path / "run"
    (proj / "phase2/stage2/synth").mkdir(parents=True)
    net = proj / "phase2/stage2/synth/netlist.v"
    net.write_text("module honest(); endmodule\n", encoding="utf-8")
    _ledger(proj, [
        {"tool": "setup", "exit_code": 0, "outputs": {}},
        {"tool": "yosys", "exit_code": 0,
         "outputs": {"phase2/stage2/synth/netlist.v":
                     "sha256:" + _H(net.read_bytes())}},
    ])
    return proj, net


def test_0_the_honest_baseline_passes(honest, capsys):
    """The control for the pair. If this failed, every arm below would 'detect'
    tampering that was never there."""
    proj, _ = honest
    assert G.main([str(proj)]) == G.RC_OK
    out = capsys.readouterr().out
    assert "chain intact" in out, out
    assert "TAMPER-EVIDENT, NOT TAMPER-PROOF" in out, out


def test_A1_artefact_edited_without_its_ledger_line_is_caught(honest, capsys):
    """The case the existing digests already catch — pinned so a later change
    cannot lose it while adding the chain."""
    proj, net = honest
    net.write_text("module tampered(); endmodule\n", encoding="utf-8")
    assert G.main([str(proj)]) == G.RC_TAMPER
    err = capsys.readouterr().err
    assert "not the one the step produced" in err, err


def test_A2_the_two_edit_attack_is_caught_ONLY_IF_the_chain_is_not_fixed_up(
        honest, capsys):
    """The two-edit attack: edit the artefact AND rewrite its ledger line with
    the new digest. No hash collision — which is what `provenance_logger`'s
    docstring wrongly claimed was required.

    Digest re-derivation alone says OK, which is the whole point. The chain
    dissents **only because the attacker did not update the FOLLOWING record's
    `chain_prev`.** See the next test for what happens when they do.
    """
    proj, net = honest
    net.write_text("module tampered(); endmodule\n", encoding="utf-8")
    led = proj / "provenance.jsonl"
    lines = led.read_text().splitlines()
    lines.append(json.dumps({"tool": "klayout", "exit_code": 0, "outputs": {},
                             "chain_prev": _H(lines[1].encode())}))
    rec = json.loads(lines[1])
    rec["outputs"]["phase2/stage2/synth/netlist.v"] = "sha256:" + _H(net.read_bytes())
    lines[1] = json.dumps(rec, ensure_ascii=False)   # chain NOT recomputed
    led.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recs, raws = G.read_records(led)
    assert not G.verify_digests(proj, recs)[0], (
        "the two-edit attack must defeat digest re-derivation, or this test is "
        "not exercising the attack it claims to")

    assert G.main([str(proj)]) == G.RC_TAMPER
    assert "edited between" in capsys.readouterr().err


def test_A3_a_CHAIN_AWARE_attacker_is_NOT_caught_and_this_is_pinned(honest,
                                                                    capsys):
    """THE LIMITATION, asserted rather than described, because the defect this
    whole change corrects was a security claim nobody re-checked.

    An attacker who edits the artefact, rewrites its ledger line AND recomputes
    every subsequent `chain_prev` produces a ledger that is internally perfect.
    This program reports an intact chain — correctly, because it IS intact.

    So the chain is TAMPER-EVIDENT, NOT TAMPER-PROOF, and the honest floor it
    raises is "the attacker must know the chain exists". That is worth having
    and it is not a defence against a determined producer. The remaining half
    of vibe-ic#1116 — an anchor OUTSIDE the producer's reach — is not delivered
    by this change, and this test exists so nobody can later mistake a green
    chain for evidence that the artefacts are genuine.

    If someone lands that anchor, THIS TEST SHOULD START FAILING. That is the
    signal that the gap closed.
    """
    proj, net = honest
    net.write_text("module tampered(); endmodule\n", encoding="utf-8")
    led = proj / "provenance.jsonl"
    lines = led.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["outputs"]["phase2/stage2/synth/netlist.v"] = "sha256:" + _H(net.read_bytes())
    lines[1] = json.dumps(rec, ensure_ascii=False)
    lines.append(json.dumps({"tool": "klayout", "exit_code": 0, "outputs": {},
                             "chain_prev": _H(lines[1].encode())}))
    led.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rc = G.main([str(proj)])
    out = capsys.readouterr().out
    assert rc == G.RC_OK, (
        "if this now FAILS, an out-of-reach anchor has been added and the "
        "limitation this test pins no longer holds — delete it and say so")
    assert "TAMPER-EVIDENT, NOT TAMPER-PROOF" in out, (
        "the passing path MUST state its own limit; a bare [PASS] here would "
        "read as evidence the artefacts are genuine, which it is not")


def test_B_a_record_deleted_from_the_middle_is_caught(honest, capsys):
    """Removing evidence is tampering too: a step that failed can be made not
    to have happened. The chain notices because record N+1 still points at the
    record that is gone."""
    proj, _ = honest
    led = proj / "provenance.jsonl"
    lines = led.read_text().splitlines()
    lines.append(json.dumps({"tool": "klayout", "exit_code": 1, "outputs": {},
                             "chain_prev": _H(lines[1].encode())}))
    del lines[1]                                   # the inconvenient record
    led.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert G.main([str(proj)]) == G.RC_TAMPER
    assert "edited between" in capsys.readouterr().err


def test_C_repointing_an_output_at_another_file_is_caught(honest, capsys):
    """LibreLane's method (C): leave the artefact alone and point the record at
    a different file that says what you want."""
    proj, _ = honest
    other = proj / "phase2/stage2/synth/decoy.v"
    other.write_text("module decoy(); endmodule\n", encoding="utf-8")
    led = proj / "provenance.jsonl"
    lines = led.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["outputs"] = {"phase2/stage2/synth/decoy.v":
                      rec["outputs"]["phase2/stage2/synth/netlist.v"]}
    lines[1] = json.dumps(rec, ensure_ascii=False)
    led.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert G.main([str(proj)]) == G.RC_TAMPER
    err = capsys.readouterr().err
    assert "decoy.v" in err, err


def test_D_a_ledger_with_no_chain_is_NOT_CHECKED_rather_than_passed(tmp_path,
                                                                    capsys):
    """#1116's method (D) asked whether any digest is recorded at all. Ours are
    — but a ledger written before the chain existed cannot answer the question
    this program asks, and saying so is the difference between a checker and a
    rubber stamp.

    'No chain' and 'an intact chain' are different observations. rc 2, not 0.
    """
    proj = tmp_path / "legacy"
    (proj / "phase2/stage2/synth").mkdir(parents=True)
    net = proj / "phase2/stage2/synth/netlist.v"
    net.write_text("module legacy(); endmodule\n", encoding="utf-8")
    (proj / "provenance.jsonl").write_text(
        json.dumps({"tool": "a", "outputs": {}}) + "\n"
        + json.dumps({"tool": "yosys", "outputs": {
            "phase2/stage2/synth/netlist.v": "sha256:" + _H(net.read_bytes())}})
        + "\n", encoding="utf-8")
    assert G.main([str(proj)]) == G.RC_UNRUNNABLE
    err = capsys.readouterr().err
    assert "NOT_CHECKED" in err and "predates" in err, err


def test_an_absent_or_empty_ledger_is_refused_not_passed(tmp_path, capsys):
    """A chain over nothing is not an intact chain."""
    proj = tmp_path / "empty"
    proj.mkdir()
    assert G.main([str(proj)]) == G.RC_UNRUNNABLE
    (proj / "provenance.jsonl").write_text("\n", encoding="utf-8")
    assert G.main([str(proj)]) == G.RC_UNRUNNABLE
    assert "not an intact chain" in capsys.readouterr().err


def test_the_chain_is_computed_over_the_RAW_bytes_not_a_reserialisation(honest):
    """A chain compared against `json.dumps` of the parsed record would break on
    whitespace and pass on a real edit. Re-writing a line with identical content
    but different formatting must NOT read as tampering, and the digest of the
    raw line is what makes that true."""
    proj, _ = honest
    led = proj / "provenance.jsonl"
    recs, raws = G.read_records(led)
    assert raws[0] == led.read_text().splitlines()[0].encode()
    assert not G.verify_chain(recs, raws)


# ---------------------------------------------------------------------------
# The PRODUCER half. Without this the chain is only ever exercised against
# ledgers this test file wrote itself, which would prove the verifier and not
# the thing that has to emit the field in production.
# ---------------------------------------------------------------------------
def test_the_logger_actually_writes_the_chain(tmp_path):
    """`provenance_logger` must emit `chain_prev` on every record after the
    first. Driven as a real subprocess, because a fixture copy of the record
    shape would drift from the code that actually runs."""
    import subprocess
    logger = PROGRAMS / "provenance_logger.py"
    proj = tmp_path / "run"
    proj.mkdir()
    for i in range(3):
        out = proj / f"out{i}.txt"
        r = subprocess.run(
            [sys.executable, str(logger), "--project", str(proj),
             "--tool", "echo", "--output", out.name,
             "--", "sh", "-c", f"echo body{i} > {out}"],
            capture_output=True, text=True)
        assert r.returncode in (0, 2), r.stdout + r.stderr

    recs = [json.loads(l) for l in
            (proj / "provenance.jsonl").read_text().splitlines() if l.strip()]
    assert len(recs) == 3, recs
    assert "chain_prev" not in recs[0], "nothing precedes the first record"
    assert all("chain_prev" in r for r in recs[1:]), \
        "the logger did not chain records 2..N — the verifier would report " \
        "NOT_CHECKED on every ledger it writes"

    # and the chain it wrote must verify
    recs2, raws = G.read_records(proj / "provenance.jsonl")
    assert not G.verify_chain(recs2, raws), G.verify_chain(recs2, raws)
