"""#173 (A13) — a clean full run must report 0 provenance-hash-completeness
faults.

Root cause (reproduced across many clean run trees — sha256, picorv32, serv,
subservient): `ip_catalog_pull` (ip_catalog_pull.py) records the RTL files it
copied as an `outputs_sha256` LIST of bare sha256 hex digests + a `files_pulled`
count — a legitimate AGGREGATE provenance shape distinct from the per-path
`outputs` dict the in-runner tool entries use. `provenance_output_hash_
completeness_check` only inspected `outputs`, so EVERY reused-IP / SoC-class
design false-FAILed with PROVENANCE_OUTPUTS_MISSING — "2 faults after a normal
clean full run" = two pulled IPs → two entries.

The check now natively recognises the `event == "ip_catalog_pull"` aggregate
schema. These tests pin: (a) a well-formed aggregate record passes, (b) the gate
is NOT weakened — an EMPTY / malformed / count-mismatched aggregate still faults,
a NORMAL tool entry with empty `outputs` still faults, and a real FILE_MISSING
still faults, (c) a v1.0.74 `outputs`-dict entry is still verified on-disk.

chip-AGNOSTIC: keyed on the `ip_catalog_pull` event schema, no IP / chip literal.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import provenance_output_hash_completeness_check as C  # noqa: E402


def _write(tmp_path, entries):
    p = tmp_path / "provenance.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return tmp_path


def test_wellformed_ip_catalog_pull_aggregate_passes(tmp_path):
    _write(tmp_path, [
        {"event": "ip_catalog_pull", "ip": "ibex", "version": "0.91",
         "files_pulled": 2, "outputs_sha256": ["a" * 64, "b" * 64]},
        {"event": "ip_catalog_pull", "ip": "sha256_core", "version": "0.80",
         "files_pulled": 1, "outputs_sha256": ["c" * 64]},
    ])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "PASS", [f.rule for f in findings]
    assert not findings


def test_empty_aggregate_still_faults(tmp_path):
    _write(tmp_path, [
        {"event": "ip_catalog_pull", "ip": "x", "outputs_sha256": []}])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)


def test_malformed_aggregate_hash_shape_faults(tmp_path):
    _write(tmp_path, [
        {"event": "ip_catalog_pull", "ip": "x", "files_pulled": 1,
         "outputs_sha256": ["not-a-sha256"]}])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_HASH_SHAPE_INVALID" for f in findings)


def test_count_mismatch_faults(tmp_path):
    _write(tmp_path, [
        {"event": "ip_catalog_pull", "ip": "x", "files_pulled": 3,
         "outputs_sha256": ["a" * 64]}])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)


def test_normal_entry_empty_outputs_still_faults(tmp_path):
    # Gate NOT weakened for ordinary tool entries: a non-pull entry with empty
    # outputs still fails exactly as before (the aggregate acceptance is scoped
    # strictly to event == ip_catalog_pull).
    _write(tmp_path, [{"tool": "yosys", "outputs": {}}])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUTS_MISSING" for f in findings)


def test_v1074_outputs_dict_still_verified_on_disk(tmp_path):
    # When the pull entry ALSO carries the v1.0.74 per-path `outputs` dict, THAT
    # is verified on-disk (preferred) — a declared file that is missing still
    # faults even though the aggregate list is well-formed.
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    real = tmp_path / "phase2" / "stage1" / "rtl" / "core.v"
    real.write_text("module core; endmodule\n")
    good_hash = "sha256:" + C._file_sha256(real)
    _write(tmp_path, [
        {"event": "ip_catalog_pull", "ip": "x", "files_pulled": 2,
         "outputs": {"phase2/stage1/rtl/core.v": good_hash,
                     "phase2/stage1/rtl/gone.v": "sha256:" + "d" * 64},
         "outputs_sha256": ["a" * 64, "b" * 64]}])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUT_FILE_MISSING" for f in findings)


def test_real_file_missing_still_faults(tmp_path):
    # A genuine FILE_MISSING (non-pull tool entry) is unaffected by the fix.
    _write(tmp_path, [
        {"tool": "openroad",
         "outputs": {"phase3/stage3/pnr/routed.def": "sha256:" + "a" * 64}}])
    verdict, findings = C.audit(tmp_path)
    assert verdict == "FAIL"
    assert any(f.rule == "PROVENANCE_OUTPUT_FILE_MISSING" for f in findings)
