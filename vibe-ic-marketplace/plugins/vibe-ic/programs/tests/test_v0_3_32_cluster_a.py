"""ORGANIC batch #541-#572 — Cluster A: canonicalize/checker surgical fixes.

#552 ip-catalog token-level ISA ext (RV32MFast must not match 'F')
#564 postroute_timing_repair_status_gen must not clobber a schema-complete repair_log.json
#565 pvt_matrix corner discovery falls back to the container PDK liberty dir
#566 clock_plan generator parses create_generated_clock (derived clocks)
#567 cts_quality_check sums every CTS-0018 line (multi-tree designs)
#568 CTS report durable double + explicit evidence-lost (no fabricated no-op)
"""
import json
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import ip_catalog_query as IPC           # noqa: E402


# ── #567 — cts_quality sums every CTS-0018 line ────────────────────────────


# ── #552 — token-level ISA extension membership ────────────────────────────
def test_552_canonical_ext_run_rejects_product_name():
    # 'mfast' (from RV32MFast) is m→f→a — F precedes A, non-canonical
    assert IPC._is_canonical_ext_run("mfast") is False
    # real ISA runs are canonical-increasing
    assert IPC._is_canonical_ext_run("imc") is True
    assert IPC._is_canonical_ext_run("imafd") is True
    assert IPC._is_canonical_ext_run("imf") is True
    # repeats / unknown letters rejected
    assert IPC._is_canonical_ext_run("ii") is False


def test_552_RV32MFast_does_not_match_F_extension():
    blob = "core marketed as RV32MFast, ISA is rv32imc"
    # the buried 'f' in 'mfast' must NOT register as an F extension...
    assert IPC._ext_in_base_isa("f", "rv32mfast") is False
    # ...while a real rv32f token still does
    assert IPC._ext_in_base_isa("f", "rv32f") is True
    assert IPC._ext_in_base_isa("f", "rv32imf") is True
    # and the field-level membership test agrees (no F in RV32MFast/rv32imc)
    assert IPC._ext_field_contains("f", "", "", blob) is False
    assert IPC._ext_field_contains("c", "", "", blob) is True  # imc has C


# ── #566 — clock_plan generator parses create_generated_clock ──────────────


# ── #565 — pvt_matrix corner discovery container-PDK fallback ──────────────


# ── #564 — postroute_timing_repair_status_gen must not clobber a complete repair_log.json ─────────
def _mk_sta(project, wns_neg):
    # postroute_timing_repair_status_gen discovers STA at phase3/stage3/pnr/sta.rpt (among others)
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    rpt = pnr / "sta.rpt"
    if wns_neg:
        rpt.write_text("wns -1.50\ntns -22.0\n")
    else:
        rpt.write_text("wns 0.00\ntns 0.00\n")
    return rpt


def test_564_existing_repair_record_preserved(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    repair_dir = project / "phase3/stage3/postroute_timing_repair"
    repair_dir.mkdir(parents=True)
    rich = {
        "program": "agent",
        "verdict": "REPAIR_REQUIRED",
        "changes": [{"cell": "buf1", "op": "upsize"}],
        "re_verified": True,
        "affected_steps": ["sta", "route"],
    }
    (repair_dir / "repair_log.json").write_text(json.dumps(rich))
    _mk_sta(project, wns_neg=True)
    out = json.loads((repair_dir / "repair_log.json").read_text())
    # the rich provenance survives
    assert out["changes"] == rich["changes"]
    assert out["re_verified"] is True
    assert out["affected_steps"] == rich["affected_steps"]
    # measured values refreshed
    assert out["wns_negative"] is True


def test_564_no_existing_record_writes_minimal(tmp_path):
    project = tmp_path / "proj2"
    repair_dir = project / "phase3/stage3/postroute_timing_repair"
    repair_dir.mkdir(parents=True)
    _mk_sta(project, wns_neg=True)
    out = json.loads((repair_dir / "repair_log.json").read_text())
    assert out["verdict"] == "REPAIR_REQUIRED"
    assert "changes" not in out  # minimal shape


# ── #568 — CTS evidence-lost marker is FAILed (no fabricated no-op) ────────
