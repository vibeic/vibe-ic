#!/usr/bin/env python3
"""pdk_cell_models.py — single source of truth for per-PDK stdcell Verilog
simulation models that live INSIDE the EDA container.

Why this module exists
----------------------
Two programs need the same fact — "where is this PDK's stdcell Verilog
simulation model?":

  * ``fault_atpg_run.py``  (Step 11 ATPG) already carried the mapping in its
    private ``PDK_CONFIG[...]["cell_model"]`` and consequently WORKS on the
    open PDKs.
  * ``sdf_gate_sim.py``    (Step 29 SDF-annotated gate-level sim) looked ONLY
    at the host-side ``<project>/input/pdk/verilog/`` staging directory, which
    the open-PDK flow never creates.  The lookup returned ``None``, the sim
    returned ``NOT_APPLICABLE`` ("no PDK cell Verilog model found"), no
    ``results.log`` was produced, and Step 29 was promoted to
    SKIPPED-CONDITION by a capability-gap marker — even though the very same
    container that ran ATPG has the models on disk.

Keeping the paths here (and asserting in the test-suite that
``fault_atpg_run.PDK_CONFIG`` agrees) means the two consumers cannot drift
apart again.

chip-AGNOSTIC.  Keyed on PDK identity only — no IC, top-module, vendor SKU or
design literal appears here.  ``cell_prefixes`` is the library's own cell
naming convention, which is a property of the PDK, not of any design.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

# Per-PDK in-container stdcell simulation models.
#
#   container_paths : read in order; the FIRST entries must be the UDP /
#                     primitive definitions the later stdcell models reference
#                     (iverilog needs the primitive before the cell that uses
#                     it), mirroring the order fault_atpg_run passes to
#                     `--cell-model-path`.
#   cell_prefixes   : how this library names its cells.  Used to identify the
#                     PDK from a gate netlist when the caller did not pass an
#                     explicit id.
PDK_CELL_MODELS: Dict[str, Dict[str, object]] = {
    "ihp-sg13g2": {
        "cell_prefixes": ("sg13g2_",),
        "container_paths": [
            "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/"
            "sg13g2_udp.v",
            "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/"
            "sg13g2_stdcell.v",
        ],
    },
    "sky130": {
        "cell_prefixes": ("sky130_fd_sc_",),
        "container_paths": [
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "sky130_fd_sc_hd.v",
        ],
    },
    "gf180": {
        "cell_prefixes": ("gf180mcu_fd_sc_",),
        "container_paths": [
            "/foss/pdks/ciel/gf180mcu/versions/"
            "8f2d1529c86235d726979eb9ecb7e9628108590b"
            "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
            "/verilog/gf180mcu_fd_sc_mcu7t5v0.v",
        ],
    },
}


def known_pdk_ids() -> List[str]:
    """Sorted list of PDK ids this module can resolve models for. Pure."""
    return sorted(PDK_CELL_MODELS)


def container_model_paths(pdk_id: Optional[str]) -> List[str]:
    """In-container model paths for `pdk_id`, or [] when unknown. Pure."""
    entry = PDK_CELL_MODELS.get(str(pdk_id or "").strip())
    if not entry:
        return []
    return list(entry.get("container_paths") or [])


def detect_pdk_id(cell_names: Sequence[str] | set) -> Optional[str]:
    """Identify the PDK from the cell names a gate netlist instantiates.

    Returns the PDK id whose `cell_prefixes` cover the MOST used cells, or
    None when nothing matches (an unknown / commercial library).  Pure — no
    filesystem or container access, so it is unit-testable and cannot silently
    succeed on the wrong library.
    """
    best, best_hits = None, 0
    for pdk_id, entry in sorted(PDK_CELL_MODELS.items()):
        prefixes = tuple(entry.get("cell_prefixes") or ())
        hits = sum(1 for c in cell_names
                   if isinstance(c, str) and c.startswith(prefixes))
        if hits > best_hits:
            best, best_hits = pdk_id, hits
    return best
