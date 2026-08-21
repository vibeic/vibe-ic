#!/usr/bin/env python3
"""Regression tests for issue #686 — spare_cell_preservation_check.py must
NOT slurp a large binary GDS as text.

Root cause (caravel round-6, public tree v1.0.47): _read_text() did an
unbounded path.read_text() on the canonical phase3/stage4/gds/*.gds which,
for a 2 GB BINARY streamout, materialized a ~10 GB Python str + a 100M-line
splitlines() — hanging flow_compliance_check (the SOLE ACCEPTANCE program)
for ~115 s/pass × 2 passes on ANY large-GDS project (chip-AGNOSTIC: any
small-design-in-a-large-fixed-wrapper or any real SoC with a hundreds-of-MB
streamout).

Fix: binary-sniff (NUL byte in head -> skip) + a hard MAX_SCAN_BYTES cap on
text reads. The DEF + netlist still establish spare survival.

§4.05 negative (no-leak): a REAL spare-cell preservation violation in a
NORMAL-size netlist must STILL be detected — the byte cap / binary skip
must not blanket-pass the check. Covered by
test_negative_real_violation_still_detected.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "spare_cell_preservation_check.py"
sys.path.insert(0, str(PROG.parent))
import spare_cell_preservation_check as scp  # noqa: E402


# GDSII stream header magic (record length 0x0006, record type/datatype
# 0x0002 = HEADER) followed by NUL-padded binary records — same bytes the
# real caravel streamout starts with (000600020258001c...).
_GDS_HEAD = bytes.fromhex("000600020258001c") + b"\x00" * 64


def _make_project(tmp_path: Path, *, gds_bytes: bytes,
                  netlist: str, def_text: str,
                  spares: list) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    gds_dir = tmp_path / "phase3" / "stage4" / "gds"
    pnr.mkdir(parents=True, exist_ok=True)
    gds_dir.mkdir(parents=True, exist_ok=True)
    (pnr / "spare_cells.json").write_text(json.dumps({"instances": spares}))
    (pnr / "user_project_wrapper_pnr.v").write_text(netlist)
    (pnr / "filled.def").write_text(def_text)
    (gds_dir / "user_project_wrapper.gds").write_bytes(gds_bytes)
    return tmp_path


# ── unit: the binary sniff + bounded read ──────────────────────────────
def test_looks_binary_detects_nul():
    assert scp._looks_binary(_GDS_HEAD) is True
    assert scp._looks_binary(b"module top; endmodule\n") is False


def test_read_text_skips_binary_gds(tmp_path):
    gds = tmp_path / "x.gds"
    gds.write_bytes(_GDS_HEAD + b"\x00" * 4096)
    # A binary artefact must read as empty (no name tokens to harvest).
    assert scp._read_text(gds) == ""


def test_read_text_caps_text_artefact(tmp_path):
    big = tmp_path / "big.def"
    # 4 MiB of ASCII well over the head sniff but well under the cap:
    # read in full (no NUL -> not binary).
    big.write_text("COMPONENT spare_0 ;\n" + ("x" * (4 * 1024 * 1024)))
    out = scp._read_text(big)
    assert "spare_0" in out
    assert len(out) <= scp.MAX_SCAN_BYTES


# ── repro: a LARGE binary GDS must NOT hang / blow memory ───────────────
def test_large_binary_gds_does_not_hang(tmp_path):
    """A multi-hundred-MB binary GDS must be processed in seconds, not
    materialized into a giant str + splitlines. We synthesize a 300 MB
    binary GDS (well past the 256 MiB cap and the original failure regime)
    and assert the audit returns quickly with the GDS contributing nothing
    to survival (DEF + netlist carry the names)."""
    big_gds = _GDS_HEAD + (b"\x00\x01\x02\x03" * (75 * 1024 * 1024))  # ~300 MB
    proj = _make_project(
        tmp_path,
        gds_bytes=big_gds,
        netlist="module top;\n  SPARE spare_inv_0 ( .A(n0) );\nendmodule\n",
        def_text="COMPONENTS 1 ;\n- spare_inv_0 sky130_fd_sc_hd__inv_1 "
                 "+ FIXED ( 0 0 ) N ;\nEND COMPONENTS\n",
        spares=[{"name": "spare_inv_0", "type": "inv"}],
    )
    t0 = time.time()
    result = scp.audit(proj)
    dt = time.time() - t0
    # Must finish fast — the original code took ~115 s/pass on a 2 GB GDS;
    # a generous ceiling that still fails hard on a re-introduced slurp.
    assert dt < 30, f"audit took {dt:.1f}s — binary GDS likely slurped again"
    assert result["verdict"] == "PASS"
    assert result["survived"] == 1
    assert not result["removed"]


# ── §4.05 NEGATIVE no-leak: a real violation must STILL be detected ─────
def test_negative_real_violation_still_detected(tmp_path):
    """A spare cell that was REMOVED (name absent from the normal-size
    netlist AND DEF) must STILL FAIL — the binary-skip / byte-cap must not
    blanket-pass the gate. Here the binary GDS is present but, as a real
    streamout, names never appear in it; the text artefacts are normal-size
    and one spare is genuinely gone."""
    proj = _make_project(
        tmp_path,
        gds_bytes=_GDS_HEAD + b"\x00" * 1024,
        # netlist + DEF contain spare_keep_0 but NOT spare_dropped_1.
        netlist="module top;\n  SPARE spare_keep_0 ( .A(n0) );\nendmodule\n",
        def_text="COMPONENTS 1 ;\n- spare_keep_0 sky130_fd_sc_hd__inv_1 "
                 "+ FIXED ( 0 0 ) N ;\nEND COMPONENTS\n",
        spares=[{"name": "spare_keep_0", "type": "inv"},
                {"name": "spare_dropped_1", "type": "nand2"}],
    )
    result = scp.audit(proj)
    assert result["verdict"] == "FAIL"
    removed_names = {r["name"] for r in result["removed"]}
    assert "spare_dropped_1" in removed_names
    assert "spare_keep_0" not in removed_names


# ── §4.05 NEGATIVE no-leak (memory bound on a binary file) ──────────────
def test_binary_gds_not_materialized_in_memory(tmp_path):
    """Process-level memory bound: the audit over a 300 MB binary GDS must
    not balloon RSS (the original slurp peaked ~10 GB on the 2 GB GDS).
    We measure via /usr/bin/time -v in a child process."""
    big_gds = _GDS_HEAD + (b"\x00\x01\x02\x03" * (75 * 1024 * 1024))  # ~300 MB
    proj = _make_project(
        tmp_path,
        gds_bytes=big_gds,
        netlist="module top;\n  SPARE spare_inv_0 ( .A(n0) );\nendmodule\n",
        def_text="COMPONENTS 1 ;\n- spare_inv_0 sky130_fd_sc_hd__inv_1 "
                 "+ FIXED ( 0 0 ) N ;\nEND COMPONENTS\n",
        spares=[{"name": "spare_inv_0", "type": "inv"}],
    )
    gnu_time = "/usr/bin/time"
    if not os.path.exists(gnu_time):
        pytest.skip("GNU time not available")
    p = subprocess.run(
        [gnu_time, "-v", sys.executable, str(PROG), str(proj),
         "--json", str(proj / "out.json")],
        capture_output=True, text=True,
    )
    peak_kb = None
    for line in p.stderr.splitlines():
        if "Maximum resident set size" in line:
            peak_kb = int(line.rsplit(" ", 1)[1])
    assert peak_kb is not None
    # Must stay well under 2 GB (original slurp was ~10 GB on a 2 GB GDS;
    # the 300 MB file here would have been ~1.5 GB+ str + splitlines).
    assert peak_kb < 2 * 1024 * 1024, f"peak RSS {peak_kb} kB too high"
