"""A reused-IP upstream erratum is applied to the STAGED copy only, by sha256,
and disclosed everywhere (owner ruling 2026-09-28, lane isaprod, ruling 2 = B).

MEASURED on a reused bit-serial core (lane isaprod, vibeic-eda 0.3.84): the
pinned release zeroes the wrong register; the public architecture suite matched
9/40 signatures on the pinned file and 40/40 on the upstream one-line fix. The
owner ruled: apply the upstream fix as a DISCLOSED deviation, keep the
unmodified result as evidence, and never hand-edit.

These tests pin the mechanism both ways, on synthetic IP (no chip, vendor or
PDK literal): a record that binds applies and discloses; a BEFORE-sha mismatch
refuses by name and changes nothing; fetched bytes that do not hash to the
AFTER sha are refused; a design no record binds is staged byte-identical to its
input; the input tree is never written; and ruling A (`report_supplied`) turns
the mechanism off in one line.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import reused_ip_erratum as E  # noqa: E402

BEFORE = b"module rf_if; assign zero = &addr; endmodule\n"
AFTER = b"module rf_if; assign zero = !(|addr); endmodule\n"
UPSTREAM = "github.com/example-org/core_x"
PIN = "a" * 40
FIX = "b" * 40
APPLY = {"reused_ip_errata": "apply"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _catalog(tmp: Path, **over) -> Path:
    root = tmp / "plugin"
    d = root / "ip-catalog" / "cpu" / "core_x" / "errata"
    d.mkdir(parents=True)
    rec = {
        "schema": E.SCHEMA, "ip": "core_x", "pinned_version": "1.0.0",
        "upstream": UPSTREAM, "pinned_commit": PIN, "file": "rtl/rf_if.v",
        "sha256_before": _sha(BEFORE), "fix_commit": FIX,
        "fix_url": "https://example.invalid/rf_if.v",
        "sha256_after": _sha(AFTER), "erratum": "zero register",
        "reason": "suite evidence", "owner_ruling": "ruling 2 (B)",
    }
    rec.update(over)
    (d / "fix.json").write_text(json.dumps(rec))
    return root


def _project(tmp: Path, staged: bytes = BEFORE, declare: bool = True) -> Path:
    p = tmp / "proj"
    (p / "input" / "vendor_rtl").mkdir(parents=True)
    (p / "input" / "vendor_rtl" / "rf_if.v").write_bytes(BEFORE)
    (p / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (p / "phase2" / "stage1" / "rtl" / "rf_if.v").write_bytes(staged)
    (p / "plugin_output").mkdir()
    decl = {"ip_upstream": {"core_x": f"{UPSTREAM}@{PIN} (ISC)"}} if declare else {}
    (p / "plugin_output" / "declaration.json").write_text(json.dumps(decl))
    return p


def _staged(p: Path) -> bytes:
    return (p / "phase2" / "stage1" / "rtl" / "rf_if.v").read_bytes()


def _fetch_after(_url: str) -> bytes:
    return AFTER


def test_a_binding_record_is_applied_to_the_staged_copy_and_disclosed(tmp_path):
    root = _catalog(tmp_path)
    p = _project(tmp_path)
    doc = E.apply_errata(p, fetch=_fetch_after, root=root, pol=APPLY)
    assert [r["status"] for r in doc["rows"]] == [E.APPLIED]
    assert _staged(p) == AFTER
    # the disclosure, one line, in the flow record and in provenance
    line = doc["disclosures"][0]
    assert line.startswith("deviation from core_x 1.0.0: upstream bbbbbbbbbb "
                           "applied (erratum zero register)")
    rec = json.loads((p / E.FLOW_RECORD_REL).read_text())
    assert rec["disclosures"] == [line]
    prov = [json.loads(x) for x in (p / "provenance.jsonl").read_text().splitlines()]
    assert [x["disclosure"] for x in prov] == [line]
    assert E.disclosure_lines(p)[0].startswith("deviation from core_x 1.0.0")


def test_the_input_tree_is_never_written(tmp_path):
    root = _catalog(tmp_path)
    p = _project(tmp_path)
    before = {f: f.read_bytes() for f in (p / "input").rglob("*") if f.is_file()}
    E.apply_errata(p, fetch=_fetch_after, root=root, pol=APPLY)
    after = {f: f.read_bytes() for f in (p / "input").rglob("*") if f.is_file()}
    assert before == after
    assert (p / "input" / "vendor_rtl" / "rf_if.v").read_bytes() == BEFORE


def test_a_before_sha_mismatch_is_refused_by_name_and_changes_nothing(tmp_path):
    root = _catalog(tmp_path)
    other = b"module rf_if; /* a different revision */ endmodule\n"
    p = _project(tmp_path, staged=other)
    doc = E.apply_errata(p, fetch=_fetch_after, root=root, pol=APPLY)
    row = doc["rows"][0]
    assert row["status"] == E.REFUSED
    assert "no fuzzy apply" in row["why"] and _sha(other) in row["why"]
    assert _staged(p) == other
    assert doc["disclosures"] == []


def test_fetched_bytes_that_miss_the_after_sha_are_refused(tmp_path):
    root = _catalog(tmp_path)
    p = _project(tmp_path)
    doc = E.apply_errata(p, fetch=lambda _u: AFTER + b"// retyped\n",
                         root=root, pol=APPLY)
    assert doc["rows"][0]["status"] == E.REFUSED
    assert "sha256_after" in doc["rows"][0]["why"]
    assert _staged(p) == BEFORE


def test_no_network_leaves_the_supplied_file_and_says_so(tmp_path):
    root = _catalog(tmp_path)
    p = _project(tmp_path)

    def _down(_url):
        raise OSError("network unreachable")
    doc = E.apply_errata(p, fetch=_down, root=root, pol=APPLY)
    assert doc["rows"][0]["status"] == E.NOT_APPLIED
    assert "network unreachable" in doc["rows"][0]["why"]
    assert _staged(p) == BEFORE and doc["disclosures"] == []


def test_without_a_binding_record_the_supplied_rtl_is_staged_unchanged(tmp_path):
    # (a) no record at all; (b) a record for a commit the design does not pin.
    p = _project(tmp_path)
    empty = tmp_path / "empty_plugin"
    (empty / "ip-catalog").mkdir(parents=True)
    doc = E.apply_errata(p, fetch=_fetch_after, root=empty, pol=APPLY)
    assert doc["rows"] == [] and _staged(p) == BEFORE
    root = _catalog(tmp_path, pinned_commit="c" * 40)
    doc = E.apply_errata(p, fetch=_fetch_after, root=root, pol=APPLY)
    assert doc["rows"] == [] and _staged(p) == BEFORE
    assert not (p / E.FLOW_RECORD_REL).exists()


def test_ruling_a_turns_the_mechanism_off_in_one_line(tmp_path):
    root = _catalog(tmp_path)
    p = _project(tmp_path)
    doc = E.apply_errata(p, fetch=_fetch_after, root=root,
                         pol={"reused_ip_errata": "report_supplied"})
    assert doc["rows"][0]["status"] == E.NOT_APPLIED
    assert _staged(p) == BEFORE


def test_the_shipped_policy_is_ruling_b():
    assert E.errata_enabled()[0] is True


def test_the_shipped_record_is_well_formed_and_pins_both_hashes():
    records, refusals = E.load_errata()
    assert refusals == []
    assert records, "the plugin ships no erratum record"
    for r in records:
        assert r["sha256_before"] != r["sha256_after"]
        assert r["fix_commit"] in r["fix_url"]


def test_the_staging_step_applies_and_discloses(tmp_path, monkeypatch):
    """Through `reused_ip_rtl_consume` and the runner's step record."""
    import reused_ip_rtl_consume as C
    import design_one_shot_runner as D
    root = _catalog(tmp_path)
    p = _project(tmp_path)
    (p / "phase2" / "stage1" / "rtl" / "rf_if.v").unlink()
    real = E.apply_errata
    monkeypatch.setattr(E, "apply_errata",
                        lambda proj, rtl=None, **kw: real(
                            proj, rtl, fetch=_fetch_after, root=root, pol=APPLY))
    res = C.consume_reused_ip_rtl(p)
    assert "rf_if.v" in res["staged"]
    assert _staged(p) == AFTER
    assert res["deviation_disclosures"][0].startswith("deviation from core_x")
    note = D._deviation_note(res)
    assert note.startswith(" DISCLOSED: deviation from core_x 1.0.0")
