"""tests/test_provenance_output_hash_completeness_check.py — v1.6.31

Eight cases:
  1. happy path — outputs declared + hashes match on-disk         PASS
  2. entry has no `outputs` key                                   FAIL
  3. output value is not a sha256:<hex> string                    FAIL
  4. declared output file does not exist on disk                  FAIL
  5. declared sha256 disagrees with computed                      FAIL
  6. all timestamps on :00 second boundaries (synthetic)          PASS+WARN
  7. all timestamps on :00 with --strict-timing                   FAIL
  8. provenance.jsonl missing                                     VACUOUS_PASS
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from programs.provenance_output_hash_completeness_check import audit


def _sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _make_provenance(project: Path, entries: list) -> None:
    project.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries]
    (project / "provenance.jsonl").write_text("\n".join(lines) + "\n")


def _write_real_output(project: Path, rel: str, body: bytes) -> str:
    """Write `body` to <project>/<rel>; return the actual sha256:<hex>."""
    dst = project / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(body)
    return f"sha256:{_sha256_of(body)}"


def test_happy_path_passes(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    body_a = b"// real synth log\n" + b"X" * 200
    body_b = b"// real netlist\n" + b"Y" * 500
    sha_a = _write_real_output(p, "phase2/stage2/synth/yosys.log", body_a)
    sha_b = _write_real_output(p, "phase2/stage2/synth/netlist.v", body_b)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/yosys.log": sha_a,
                     "phase2/stage2/synth/netlist.v": sha_b}},
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS", [(f.rule, f.detail) for f in findings]
    assert findings == []


def test_outputs_missing_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "command": "yosys -p ..."},  # NO outputs key
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)


def test_hash_shape_invalid_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": "yes-it-exists"}},
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_HASH_SHAPE_INVALID" for f in findings)


def test_output_file_missing_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/never_emitted.v":
                     "sha256:" + "a" * 64}},
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUT_FILE_MISSING" for f in findings)


def test_hash_mismatch_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    body = b"// real content\n" + b"Z" * 200
    _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    # Provenance claims a wrong hash
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v":
                     "sha256:" + "0" * 64}},
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_HASH_MISMATCH" for f in findings)


def test_synthetic_timestamps_warn_by_default(tmp_path: Path) -> None:
    """All timestamps on :00 seconds → ATTEST_TIMING_SUSPICIOUS WARNING.
    Default mode keeps verdict PASS so that a fast-tool false positive
    doesn't block a real run."""
    p = tmp_path / "proj"
    body = b"// real\n" + b"Q" * 200
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:01:00Z", "tool": "yosys-abc",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:05:00Z", "tool": "openroad",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert any(f.rule == "ATTEST_TIMING_SUSPICIOUS"
               and f.severity == "WARNING" for f in findings)


def test_synthetic_timestamps_strict_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    body = b"// real\n" + b"Q" * 200
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T10:00:00Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:01:00Z", "tool": "yosys-abc",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:05:00Z", "tool": "openroad",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
    ])
    verdict, findings = audit(p, strict_timing=True)
    assert verdict == "FAIL"
    assert any(f.rule == "ATTEST_TIMING_SUSPICIOUS"
               and f.severity == "ERROR" for f in findings)


def test_no_provenance_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


# --------- v1.6.32 additions ---------

def test_path_traversal_outside_project_fails(tmp_path: Path) -> None:
    """An output declared with `../` traversal that resolves outside the
    project tree must FAIL with PROVENANCE_PATH_OUTSIDE_PROJECT."""
    p = tmp_path / "proj"
    # Create a file outside the project tree
    outside = tmp_path / "external" / "lib_cell.gds"
    outside.parent.mkdir(parents=True, exist_ok=True)
    body = b"\x00\x06\x00\x02" + b"X" * 500
    outside.write_bytes(body)
    sha = "sha256:" + _sha256_of(body)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "klayout",
         "outputs": {"../external/lib_cell.gds": sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_PATH_OUTSIDE_PROJECT" for f in findings)


def test_path_absolute_outside_project_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    outside = tmp_path / "external" / "ref.gds"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"X" * 600)
    sha = "sha256:" + _sha256_of(b"X" * 600)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "klayout",
         "outputs": {str(outside): sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_PATH_OUTSIDE_PROJECT" for f in findings)


def test_newest_record_of_a_path_is_the_one_that_must_match(tmp_path: Path) -> None:
    """Two entries for one path, NEWEST declaring a digest the file does not
    carry ⇒ FAIL.

    This used to assert PROVENANCE_HASH_INCONSISTENT — the rule that read any
    two differing records of a path as a self-contradicting chain. That shape
    is what a legitimate re-run produces, so the rule fired on honest ledgers
    and the check became unsatisfiable after the first iteration. The ledger
    is append-only, so a later record SUPERSEDES an earlier one and only the
    newest is a claim about the bytes on disk.

    The detection this test defends is unchanged and is asserted below: a
    newest record that disagrees with disk is still a broken chain. Note the
    OLDEST record here matches the file exactly and does not rescue it."""
    p = tmp_path / "proj"
    body = b"// real netlist\n" + b"Y" * 500
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    bogus = "sha256:" + "f" * 64
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T03:15:42Z", "tool": "rerun-yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": bogus}},
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_HASH_MISMATCH" for f in findings)


def test_a_superseded_record_does_not_fault_the_ledger(tmp_path: Path) -> None:
    """The mirror of the above: same two-record shape, but the NEWEST record
    is the one that matches disk — a plain re-run. It must PASS, and the
    superseded record must be reported rather than silently dropped."""
    p = tmp_path / "proj"
    stale = "sha256:" + "e" * 64
    body = b"// real netlist\n" + b"Z" * 500
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": stale}},
        {"timestamp": "2026-05-08T03:15:42Z", "tool": "rerun-yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS", [(f.rule, f.detail) for f in findings]
    assert any(f.rule == "PROVENANCE_OUTPUT_SUPERSEDED" for f in findings)


def test_jsonl_parse_error_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    (p / "provenance.jsonl").write_text(
        '{"valid": "row"}\n'
        '{not even close to JSON\n'
    )
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_PARSE_ERROR" for f in findings)


def test_round_minute_no_subsec_pattern_warns(tmp_path: Path) -> None:
    """Pattern B: all entries on round-minute boundaries with zero
    sub-second precision. Catches v10627-vendor-style fabrication."""
    p = tmp_path / "proj"
    body = b"// real\n" + b"Q" * 200
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T10:01:00Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:05:00Z", "tool": "yosys-abc",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:11:00Z", "tool": "openroad",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T11:30:00Z", "tool": "klayout",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert any(f.rule == "ATTEST_TIMING_SUSPICIOUS"
               and f.severity == "WARNING" for f in findings)


def test_realistic_subsecond_jitter_does_not_warn(tmp_path: Path) -> None:
    """Real tools log with sub-second precision and irregular gaps.
    No pattern should fire."""
    p = tmp_path / "proj"
    body = b"// real\n" + b"Q" * 200
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    _make_provenance(p, [
        {"timestamp": "2026-05-08T10:00:17.412Z", "tool": "yosys",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:01:43.901Z", "tool": "yosys-abc",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:09:12.058Z", "tool": "openroad",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:14:35.726Z", "tool": "klayout",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert not any(f.rule == "ATTEST_TIMING_SUSPICIOUS" for f in findings)


def test_regular_cadence_pattern_warns(tmp_path: Path) -> None:
    """Pattern C: ≥3 consecutive gaps that are exact multiples of 60s.
    Even with non-:00 seconds, the regularity is the giveaway."""
    p = tmp_path / "proj"
    body = b"// real\n" + b"Q" * 200
    sha = _write_real_output(p, "phase2/stage2/synth/netlist.v", body)
    # Each gap = 300s (5 min). Seconds field is :17 so pattern A & B
    # won't fire, only pattern C.
    _make_provenance(p, [
        {"timestamp": "2026-05-08T10:00:17Z", "tool": "t1",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:05:17Z", "tool": "t2",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:10:17Z", "tool": "t3",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
        {"timestamp": "2026-05-08T10:15:17Z", "tool": "t4",
         "outputs": {"phase2/stage2/synth/netlist.v": sha}},
    ])
    verdict, findings = audit(p)
    assert verdict == "PASS"
    susp = [f for f in findings if f.rule == "ATTEST_TIMING_SUSPICIOUS"]
    assert susp, [(f.rule, f.detail) for f in findings]
    assert "300" in susp[0].detail or "60" in susp[0].detail


# ---------------------------------------------------------------------------
# #365 per-invocation command-audit records (regression: the completion audit
# FAILed every phase-3 run whose report/probe tool invocations declared no
# output, even with clean DRC/LVS/STA sign-off). The `_log_invocation` writer
# contract is "empty is honest" for a call site that declared nothing; the gate
# must DISCLOSE such a row, not FAIL it — while still verifying any invocation
# row that DOES declare outputs, and still FAILing a NON-invocation artefact row
# with empty outputs.
# ---------------------------------------------------------------------------
def _invocation_row(**over) -> dict:
    """A command-audit row in the shape `_log_invocation` ACTUALLY writes.

    The fixture mirrors the PRODUCER on purpose: `record`, `command`,
    `exit_code` and `version_capture` are UNCONDITIONAL in the writer's entry
    dict and `outputs` is the only conditional key, so a fixture that omits the
    probe fields would prove the exemption on a row shape that never occurs.
    """
    row = {"record": "invocation", "timestamp": "2026-05-08T03:14:23Z",
           "tool": "sta", "version": "OpenSTA 2.5.0",
           "version_capture": "probed",
           "command": "sta -no_init -exit power.tcl > power.rpt",
           "exit_code": 0, "duration_ms": 4120, "duration_s": 4.12,
           "measured": True,
           "marker": "phase3/stage3/sta/power.tcl"}
    row.update(over)
    return row


def test_invocation_record_no_declared_output_is_disclosed_not_fatal(
        tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _make_provenance(p, [_invocation_row()])          # no outputs declared
    verdict, findings = audit(p)
    assert verdict == "PASS", [(f.rule, f.detail) for f in findings]
    disc = [f for f in findings
            if f.rule == "PROVENANCE_INVOCATION_NO_DECLARED_OUTPUT"]
    assert disc, [(f.rule, f.severity) for f in findings]
    assert disc[0].severity == "DISCLOSED"
    assert not any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)


@pytest.mark.parametrize("missing", ["command", "exit_code",
                                     "version_capture"])
def test_bare_invocation_claim_cannot_buy_the_exemption(
        tmp_path: Path, missing: str) -> None:
    """§4.05 NEGATIVE CONTROL — the exemption must not be purchasable by
    asserting the class alone.

    `_log_invocation` emits `command`, `exit_code` and `version_capture`
    UNCONDITIONALLY, so a row that declares `record: invocation` while lacking
    any of them did not come from that writer. Such a row is hand-written,
    truncated or forged and must still FAIL — otherwise adding one line to a
    ledger would exempt any artefact-producing tool run from hash verification.
    """
    row = _invocation_row()
    row.pop(missing)
    p = tmp_path / "proj"
    _make_provenance(p, [row])
    verdict, findings = audit(p)
    assert verdict == "FAIL", [(f.rule, f.detail) for f in findings]
    assert any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)
    assert not any(f.rule == "PROVENANCE_INVOCATION_NO_DECLARED_OUTPUT"
                   for f in findings)


def test_invocation_record_that_declares_outputs_is_still_verified(
        tmp_path: Path) -> None:
    """An invocation row that DECLARES an output is NOT exempt — a wrong hash
    still FAILs (the exemption is scoped to EMPTY outputs only)."""
    p = tmp_path / "proj"
    _write_real_output(p, "phase3/stage3/pnr/top.gds", b"real gds bytes\n" * 9)
    _make_provenance(p, [
        _invocation_row(tool="magic", command="magic ... stream out",
                        outputs={"phase3/stage3/pnr/top.gds":
                                 "sha256:" + "0" * 64}),
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_HASH_MISMATCH" for f in findings)


def test_invocation_exemption_is_counted_in_the_disclosure_census(
        tmp_path: Path) -> None:
    """The exemption must be VISIBLE, not silent: a skipped row that no reader
    can see is the hidden decision this file's DISCLOSED severity exists to
    prevent. It must land in `disclosed_count` on the verdict line."""
    from programs.provenance_output_hash_completeness_check import audit_counted
    p = tmp_path / "proj"
    _make_provenance(p, [_invocation_row(), _invocation_row(tool="yosys")])
    verdict, findings, _counts = audit_counted(p)
    assert verdict == "PASS"
    assert sum(1 for f in findings if f.severity == "DISCLOSED") == 2


def test_non_invocation_record_with_empty_outputs_still_fails(
        tmp_path: Path) -> None:
    """The exemption is scoped to record=="invocation"; an artefact-declaration
    row (no `record`, or any other value) with empty outputs still FAILs."""
    p = tmp_path / "proj"
    _make_provenance(p, [
        {"timestamp": "2026-05-08T03:14:23Z", "tool": "yosys",
         "command": "yosys synth", "outputs": {}},   # empty dict, no record
    ])
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)
