"""A register-field VALUE table was read as a pin table.

`| Value | Name | Description |` is an ENCODING table: its Name column holds
the symbolic names of the CODES a field may take. L1's narrative pin line-scan
anchors on a direction word ANYWHERE in the line, so such a row was promoted to
a chip pin whenever its description prose happened to contain one. Measured on
opentitan_aes: of 21 rows in those tables, 11 became pins and 10 did not, and
the only discriminator was the prose — `AES_ENC` is a pin because its
description reads "Invalid input values", `AES_DEC` beside it is not because
its reads "Decryption." Meanwhile L15, whose subject those tables are, reported
EXTRACTION_FOUND_NOTHING.

Header roles route the table: a value-ish column plus a name column and NO
direction column is an encoding table, so it goes to L15 and the L1 line-scan
stands down on its lines. A real port table always carries a direction column,
so the two populations cannot overlap and this can only ever REMOVE a
promotion the design never declared."""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

ENCODING_DOC = """# widget registers

### CTRL . OPERATION
2-bit one-hot field to select the operation of the unit.

| Value   | Name    | Description                                                      |
|:--------|:--------|:-----------------------------------------------------------------|
| 0x1     | ENC_OP  | 2'b01: Encryption. Invalid input values are mapped to ENC_OP.     |
| 0x2     | DEC_OP  | 2'b10: Decryption.                                                |
"""

PORT_DOC = """# widget interfaces

## Signals

| Name    | Direction | Description                |
|:--------|:----------|:---------------------------|
| `sclk_i`  | input   | Serial clock.              |
| `sdo_o`   | output  | Serial data out.           |
"""


def _run(tmp_path, docs, name="widget"):
    proj = tmp_path / "proj"
    d = proj / "input" / "docs"
    d.mkdir(parents=True)
    for fn, body in docs.items():
        (d / fn).write_text(body)
    (proj / "input" / "phase1_prompt.md").write_text(
        "Build a widget peripheral with a control register.\n")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(proj), "--ic-name", name],
        capture_output=True, text=True, timeout=1800)
    gd = proj / "phase1" / "generated_docs"
    l1 = json.loads((gd / "L1_DATASHEET.json").read_text())
    l15 = json.loads((gd / "L15_ENCODING_TABLES.json").read_text())
    return r, l1, l15


def test_encoding_table_rows_are_not_chip_pins(tmp_path):
    """The load-bearing red."""
    _r, l1, _l15 = _run(tmp_path, {"regs.md": ENCODING_DOC})
    names = {str(p.get("name")) for p in l1.get("pin_table") or []}
    assert "ENC_OP" not in names, sorted(names)
    assert "DEC_OP" not in names, sorted(names)


def test_the_encoding_table_reaches_its_own_layer(tmp_path):
    """The other half: routing it away from L1 is only right if it arrives
    somewhere. L15 is the layer whose subject it is."""
    _r, _l1, l15 = _run(tmp_path, {"regs.md": ENCODING_DOC})
    tables = (l15.get("fields") or {}).get("tables") or []
    assert tables, l15
    assert any("ENC_OP" in " ".join(t.get("rows") or []) for t in tables), tables
    assert l15.get("extraction_status") == "EXTRACTED", l15


def test_a_real_port_table_is_untouched(tmp_path):
    """Over-reach control, and it must pass on BOTH trees. A port table carries
    a direction column, which is exactly what an encoding table does not."""
    _r, l1, _l15 = _run(tmp_path, {"ifc.md": PORT_DOC})
    names = {str(p.get("name")) for p in l1.get("pin_table") or []}
    assert {"sclk_i", "sdo_o"} <= names, sorted(names)
