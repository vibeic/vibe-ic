"""ORGANIC #612 [MEDIUM] — the L9 memory prose walker promoted name-only
tokens (I/O pins / EDA config keys / PDK-FPGA platform names) to kind=ram/sram
macros. `_v1_6_441_is_useful_memory_entry` admitted ANY entry with a non-null
`name`, even when depth/width/port_count were all None, so the back-walker's
garbage name (latched off a nearby bare SRAM/RAM/ROM prose mention) passed.

POSITIVE: a real macro (depth/width/port present) stays useful; a name-only
entry whose NAME carries a memory token (data_ram / inst_fifo / l1_cache) stays.

NEGATIVE no-leak: the exact observed garbage names (i_rst, RESET_PC, WITH_CSR,
FP_CORE_UTIL, PL_TARGET_DENSITY, FP_PDN_HOFFSET, GF180MCU, Cyclone10LP,
sky130_fd_sc_hd, i_gpio, o_gpio) are NO LONGER useful → routed to
memory_candidates, not memories[]. And a non-memory word that merely CONTAINS
a memory substring (PROGRAM/DIAGRAM/HISTOGRAM → "ram") is not mis-promoted.

chip-AGNOSTIC: structural (depth/width/port) + memory-name-token shape only.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

U = P._v1_6_441_is_useful_memory_entry


def test_structural_macro_still_useful():
    assert U({"name": "u_sram", "depth": 256, "width": 32}) is True
    assert U({"name": None, "depth": 1024, "width": 8}) is True
    assert U({"name": "buf", "port_count": 2}) is True  # port evidence


def test_name_only_with_memory_token_useful():
    for nm in ("data_ram", "inst_fifo", "l1_cache", "sram0", "boot_rom",
               "reg_file" if False else "regfile_bank", "scratch_mem"):
        assert U({"name": nm}) is True, f"{nm} carries a memory token → useful"


def test_name_only_nonmemory_tokens_rejected():
    # the exact garbage observed on disk (#612), all depth=width=port=None
    for nm in ("i_rst", "RESET_PC", "WITH_CSR", "FP_CORE_UTIL",
               "PL_TARGET_DENSITY", "FP_PDN_HOFFSET", "GF180MCU",
               "Cyclone10LP", "sky130_fd_sc_hd", "i_gpio", "o_gpio"):
        assert U({"name": nm}) is False, (
            f"{nm} carries NO memory token and no structural field → must be "
            f"rejected from memories[] (#612)")


def test_memory_substring_in_nonmemory_word_not_promoted():
    # 'ram' as a mid-word substring (preceded by a letter) must NOT match
    for nm in ("PROGRAM", "DIAGRAM", "HISTOGRAM", "diagram_ctrl"):
        assert U({"name": nm}) is False, f"{nm} is not a memory macro"


def test_non_dict_and_empty():
    assert U(None) is False
    assert U({}) is False
    assert U({"name": None}) is False
