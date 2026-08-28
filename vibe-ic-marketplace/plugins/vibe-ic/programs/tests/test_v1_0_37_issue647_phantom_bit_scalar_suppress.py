"""Regression for ORGANIC #647 — phase1 fabricated per-bit scalar ports from a
packed bus: a single L3 row `io_in | 38` yielded the packed `io_in` PLUS 27+
phantom scalars `io_in0..io_in26` (width=None, no evidence), inflating
L9.top_ports 21→48 and making the generated TB wire nonexistent ports
(iverilog rc=29).

Fix (chip-AGNOSTIC, defense-in-depth backstop to the #627 extraction-row
guard): `_v647_drop_redundant_bit_scalars` drops a `<base><digits>` pin when a
sibling named exactly `<base>` exists with width>1 (a packed bus) AND the
scalar is itself a bit (width None or 1). Applied to L1.pin_table before L9
promotion.

ACCEPTANCE (issue): an interface doc with one `io_in | 38` row → L9 emits
exactly one `io_in` port (width 38), zero `io_in<N>` scalars.

NEGATIVE no-leak: a scalar whose packed parent does NOT exist is KEPT (a real
`gpio5` with no packed `gpio`); a packed bus whose own name has no digit suffix
is KEPT (`user_irq`); a genuine independent multi-bit port is KEPT.

chip-AGNOSTIC: pure `<base><digits>` name shape + packed-parent width check; no
chip/SKU literal.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── (1) the helper unit ──────────────────────────────────────────────────────

def test_drops_phantom_bit_scalars_of_packed_bus():
    pins = [
        {"name": "clk_i", "width": 1},
        {"name": "io_in", "width": 38, "msb": 37, "lsb": 0},
        {"name": "io_in0"}, {"name": "io_in1", "width": 1}, {"name": "io_in2"},
        {"name": "addr", "width": 8, "msb": 7, "lsb": 0}, {"name": "addr3"},
    ]
    out = [p["name"] for p in R._v647_drop_redundant_bit_scalars(pins)]
    assert out == ["clk_i", "io_in", "addr"]


def test_keeps_scalar_without_packed_parent_NOLEAK():
    """A `<base><N>` scalar whose `<base>` is NOT a packed bus is a legit port
    and must be kept."""
    pins = [{"name": "gpio5", "width": 1}, {"name": "ch3", "width": 1}]
    out = [p["name"] for p in R._v647_drop_redundant_bit_scalars(pins)]
    assert out == ["gpio5", "ch3"]


def test_keeps_packed_bus_and_independent_ports_NOLEAK():
    pins = [
        {"name": "user_irq", "width": 3, "msb": 2, "lsb": 0},   # packed, no idx
        {"name": "wbs_dat_i", "width": 32, "msb": 31, "lsb": 0},
        {"name": "chan", "width": 4, "msb": 3, "lsb": 0},
        {"name": "chan1", "width": 8, "msb": 7, "lsb": 0},      # own width → keep
    ]
    out = [p["name"] for p in R._v647_drop_redundant_bit_scalars(pins)]
    assert out == ["user_irq", "wbs_dat_i", "chan", "chan1"]


def test_no_packed_bus_is_noop():
    pins = [{"name": "a", "width": 1}, {"name": "a3"}]
    assert R._v647_drop_redundant_bit_scalars(pins) == pins


# ── (2) the acceptance: full phase1 → exactly one io_in, zero scalars ─────────

def _final_l9_names(proj):
    import json
    import glob
    l9 = glob.glob(str(proj / "phase1" / "generated_docs" / "L9*.json"))
    assert l9, "phase1 did not emit an L9 spec"
    return [p.get("name", "")
            for p in json.load(open(l9[0])).get("top_ports", [])]


def test_end_to_end_single_io_in_row_no_phantoms(tmp_path):
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L3_external_interface.md").write_text(
        "# Bus IF\n\n## External Interface\n\n"
        "| Signal | Direction | Width | Description |\n|---|---|---|---|\n"
        "| `clk_i` | input | 1 | clock |\n"
        "| `io_in` | in | 38 | User GPIO inputs (`io_in[37:0]`) |\n")
    runner = _PROGRAMS / "phase1_one_shot_runner.py"
    r = _pr.run([sys.executable, str(runner), str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    names = _final_l9_names(proj)
    import re
    assert names.count("io_in") == 1, names
    assert not [n for n in names if re.match(r"^io_in\d+$", n)], names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
