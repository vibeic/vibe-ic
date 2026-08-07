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
            # v1.8.43 — `primitives.v` MUST come first, and it was MISSING.
            # This entry violated the rule stated in this module's own
            # `container_paths` comment three lines above the table (and that
            # `ihp-sg13g2` obeys with `sg13g2_udp.v`): sky130's stdcell model
            # instantiates UDPs it does not define, and they live in a separate
            # file. MEASURED (spm x sky130A): compiling `sky130_fd_sc_hd.v`
            # alone gives iverilog
            #   67 error(s) during elaboration.
            #   *** These modules were missing:
            #         sky130_fd_sc_hd__udp_dff$PR_pp$PG$N referenced 1 times.
            #         sky130_fd_sc_hd__udp_dff$P_pp$PG$N   referenced 64 times.
            #         sky130_fd_sc_hd__udp_mux_2to1        referenced 1 times.
            # so `sdf_gate_sim` returned verdict=ERROR reason="compile failed",
            # `results.log` was never written, and canonical Step 29
            # (Post-Layout Gate-Level Simulation) came out MISSING on EVERY
            # sky130 run. `primitives.v` (50512 B) defines 46 primitives
            # including all three named above — verified in the container.
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "primitives.v",
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "sky130_fd_sc_hd.v",
        ],
    },
    "gf180": {
        "cell_prefixes": ("gf180mcu_fd_sc_",),
        # ciel stages PDK data under a CONTENT-ADDRESSED versions/<hash>/
        # directory that moves every time vibeic-eda's gf180mcu pin advances
        # (unlike sky130A / ihp-sg13g2 above, whose container paths are
        # stable). A hash baked in here as a literal goes stale the next time
        # the image is rebuilt against a newer ciel pin — measured 2026-08-07:
        # image 0.2.70/0.2.74 both ship gf180mcu at hash
        # b344c97eacc2aaf8e14ae7e43e2e9dc0871de2c0, not the hash below, and
        # Step 11 (fault_atpg_run) failed with `cp: cannot stat` on the stale
        # path for BOTH spm x gf180mcuD ATPG and scan-chain insertion.
        # GF180_CIEL_HASH_PLACEHOLDER below is what a caller substitutes via
        # `resolve_gf180_ciel_hash` + `materialize_gf180_paths` before use;
        # the literal hash stays as the offline fallback so nothing regresses
        # when a caller cannot reach docker (e.g. unit tests).
        "container_paths": [
            "/foss/pdks/ciel/gf180mcu/versions/"
            "8f2d1529c86235d726979eb9ecb7e9628108590b"
            "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
            "/verilog/gf180mcu_fd_sc_mcu7t5v0.v",
        ],
    },
}

# The literal ciel gf180mcu hash embedded in PDK_CELL_MODELS above (and, until
# each caller adopts `resolve_gf180_ciel_hash`, independently duplicated in
# `fault_atpg_run.PDK_CONFIG` and `fault_scan_chain_insert.SCAN_LIBERTY`).
# Kept as a named constant so a live-resolved hash can be swapped in by
# substring replacement without every call site re-deriving where in the
# path string the hash sits.
GF180_CIEL_HASH_FALLBACK = "8f2d1529c86235d726979eb9ecb7e9628108590b"


def known_pdk_ids() -> List[str]:
    """Sorted list of PDK ids this module can resolve models for. Pure."""
    return sorted(PDK_CELL_MODELS)


def container_model_paths(pdk_id: Optional[str]) -> List[str]:
    """In-container model paths for `pdk_id`, or [] when unknown. Pure."""
    entry = PDK_CELL_MODELS.get(str(pdk_id or "").strip())
    if not entry:
        return []
    return list(entry.get("container_paths") or [])


def resolve_gf180_ciel_hash(run_argv) -> Optional[str]:
    """Discover the ciel gf180mcu version hash actually present, by listing
    `ciel/gf180mcu/versions/` through `run_argv` — a caller-supplied
    `(argv: list[str], timeout: int) -> (returncode, stdout, stderr)`
    callable already wired to that caller's own docker access (e.g.
    `fault_atpg_run._run_docker`). This module stays docker-transport-
    agnostic on purpose — it never shells out itself.

    Returns the single hash directory name found, or None when the listing
    fails or is ambiguous (zero or more-than-one entry) — NEVER guesses among
    several, since ciel is expected to stage exactly one version per PDK at a
    time and more than one means something this function does not understand
    is going on."""
    try:
        rc, out, _err = run_argv(
            ["ls", "-1", "/foss/pdks/ciel/gf180mcu/versions/"], 30)
    except Exception:
        return None
    if rc != 0:
        return None
    hashes = [h for h in out.split() if h.strip()]
    return hashes[0] if len(hashes) == 1 else None


def materialize_gf180_paths(paths: Sequence[str], run_argv) -> List[str]:
    """Return `paths` with the fallback ciel hash swapped for the hash
    LIVE in the image/container `run_argv` reaches, when discovery
    succeeds and differs. On any discovery failure, returns `paths`
    UNCHANGED (today's behaviour, not a regression) — this function never
    raises and never fabricates a hash it did not observe."""
    live = resolve_gf180_ciel_hash(run_argv)
    if not live or live == GF180_CIEL_HASH_FALLBACK:
        return list(paths)
    return [p.replace(GF180_CIEL_HASH_FALLBACK, live) for p in paths]


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
