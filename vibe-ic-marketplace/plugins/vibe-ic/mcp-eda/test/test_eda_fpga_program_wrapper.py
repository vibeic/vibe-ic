#!/usr/bin/env python3
"""The public FPGA wrapper delegates programming to the device driver."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX_JS = ROOT / "src" / "index.js"
DRIVER_PATH = (
    ROOT / "src" / "devices" / "fpga" / "terasic-de10lite" / "driver.py"
)
assert INDEX_JS.exists()
assert DRIVER_PATH.exists()


def test_eda_fpga_program_no_direct_execsync_quartus_pgm():
    """Wave 33: index.js must NOT contain `execSync(...quartus_pgm` in
    the eda_fpga_program handler. The legacy back-door exec was the
    Hole-1 violation. The legacy `quartus_pgm -l` JTAG-list call
    inside verify_burn is still allowed because it's a read-only
    enumeration, not a burn.
    """
    src = INDEX_JS.read_text()
    # Locate the eda_fpga_program tool block.
    start = src.find('server.tool(\n  "eda_fpga_program"')
    assert start > 0, "eda_fpga_program handler not found in index.js"
    # Find the matching closing `);` for that server.tool call. We
    # use a pragmatic heuristic: look for the next "// ─── Tool: "
    # marker.
    end = src.find("// ─── Tool: ", start + 1)
    assert end > start, "could not locate eda_fpga_program block end"
    block = src[start:end]
    # Permitted: quartus_pgm -l (verify_burn JTAG-list inside an
    # execSync call). FORBIDDEN: any execSync that programs a SOF.
    forbidden = re.findall(
        r"execSync\([^)]*quartus_pgm\s+-c[^)]*-o", block)
    assert not forbidden, (
        f"WAVE33: eda_fpga_program contains direct burn execSync — "
        f"{forbidden}"
    )
    assert "terasic-de10lite" in block and "driver.py" in block, (
        "WAVE33: eda_fpga_program must delegate to "
        "device_fpga_de10lite_program's driver.py"
    )
