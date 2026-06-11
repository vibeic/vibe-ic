"""ORGANIC #553 — L9 width extraction must not misread interrupt-ID table
column as port width.  Column header with id/position/mip keywords → not width.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase1_doc_one_shot_runner as R  # noqa: E402


def test_553_id_col_not_extracted_as_width():
    # RST grid table: signal | MIP bit | Direction | Description
    # "MIP bit" header → ID zone → width must be None for data rows.
    text = (
        "+------------------+----------+-----------+----------------------+\n"
        "| Signal Name      | MIP bit  | Direction | Description          |\n"
        "+==================+==========+===========+======================+\n"
        "| irq_software_i   | 3        | input     | software interrupt   |\n"
        "| irq_timer_i      | 7        | input     | timer interrupt      |\n"
        "| irq_external_i   | 11       | input     | external interrupt   |\n"
        "| irq_nm_i         | 31       | input     | non-maskable irq     |\n"
        "+------------------+----------+-----------+----------------------+\n"
    )
    zones = R._rst_col2_id_char_ranges(text)
    assert zones, "Should detect MIP-bit as ID col-2 zone"
    # Every data-row match offset must be inside a zone
    import re
    for m in R._RE_L1_L9_RST_IFACE_4COL.finditer(text):
        if m.group("signal").strip().lower() in {"signal", "name"}:
            continue
        assert R._in_id_col2_zone(m.start(), zones), (
            f"Row at offset {m.start()} should be in ID zone")


def test_553_real_width_col_not_suppressed():
    # RST grid table: signal | Width | Direction | Description
    # "Width" header → NOT an ID zone → widths extracted normally.
    text = (
        "+------------+-------+-----------+---------------------------+\n"
        "| Signal     | Width | Direction | Description               |\n"
        "+============+=======+===========+===========================+\n"
        "| data_o     | 32    | output    | data output bus           |\n"
        "| addr_o     | 12    | output    | address output            |\n"
        "+------------+-------+-----------+---------------------------+\n"
    )
    zones = R._rst_col2_id_char_ranges(text)
    assert not zones, "Width header should NOT create an ID zone"


def test_553_position_header_keyword():
    # "bit position" in header → ID zone
    text = (
        "+----------+--------------+-------+--------------------+\n"
        "| Signal   | bit position | Dir   | Description        |\n"
        "+==========+==============+=======+====================+\n"
        "| irq_i    | 3            | input | interrupt request  |\n"
        "+----------+--------------+-------+--------------------+\n"
    )
    zones = R._rst_col2_id_char_ranges(text)
    assert zones, "bit position header should be an ID zone"


def test_553_index_header_keyword():
    text = (
        "+--------+-------+-------+---------------------+\n"
        "| Signal | index | Dir   | Description         |\n"
        "+========+=======+=======+=====================+\n"
        "| reg_i  | 5     | input | register index      |\n"
        "+--------+-------+-------+---------------------+\n"
    )
    zones = R._rst_col2_id_char_ranges(text)
    assert zones


def test_553_negative_bits_header_not_id():
    # "bits" alone is a genuine width-column header → no ID zone
    text = (
        "+-----------+------+--------+--------------+\n"
        "| Signal    | Bits | Dir    | Description  |\n"
        "+===========+======+========+==============+\n"
        "| counter_o | 8    | output | counter out  |\n"
        "+-----------+------+--------+--------------+\n"
    )
    zones = R._rst_col2_id_char_ranges(text)
    assert not zones, "bits header should NOT be an ID zone"
