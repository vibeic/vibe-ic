"""v1.6.144 (#57) — shared helper for FPGA-prototype-stage analog
stub waivers.

The 5 analog/mixed-signal structural gates (analog_block_coverage_check,
analog_hardmacro_check, mixed_signal_cosim_check,
analog_flow_compliance_check, analog_digital_interface_check) all FAIL
on `mixed_signal_otp` chips between `phase2.fpga_burn` and the
end-to-end analog A1-A9 flow — the analog runner emits
`PASS_WITH_WAIVERS` with every per-block step
`WAIVED: missing-artifact`, but downstream gates re-check and FAIL.

This module provides the shared detection logic so each gate accepts
`--allow-fpga-stub` (CLI) or `PHASE23_ANALOG_FPGA_STUB=1` (env var) to
demote missing-artifact failures to `PASS_WITH_WAIVERS` at the FPGA
prototype stage. The same gates re-fire WITHOUT the waiver flag at
`phase3.foundry_handoff` for tapeout signoff.

chip-AGNOSTIC — no class detection or chip-specific literals; the
waiver is a stage marker, not a chip-class predicate.
"""
from __future__ import annotations

import argparse
import os
from typing import Optional

_ENV_VAR = "PHASE23_ANALOG_FPGA_STUB"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def fpga_stub_waiver_active(args: Optional[argparse.Namespace] = None
                             ) -> bool:
    """Return True iff the FPGA-prototype-stage analog stub waiver is
    in effect — either via the `--allow-fpga-stub` CLI flag (when
    `args` is provided) or the `PHASE23_ANALOG_FPGA_STUB` env var.

    Either signal is sufficient. The env var lets the phase23
    umbrella runner enable the waiver for downstream gate invocations
    without having to know each gate's CLI signature.
    """
    if args is not None and getattr(args, "allow_fpga_stub", False):
        return True
    return os.environ.get(_ENV_VAR, "").strip().lower() in _TRUTHY


def add_fpga_stub_argparse(ap: argparse.ArgumentParser) -> None:
    """Attach the `--allow-fpga-stub` flag to an existing parser.

    Use from each of the 5 analog gates' `main()` argparse setup so
    the flag surfaces consistently across the gate family.
    """
    ap.add_argument(
        "--allow-fpga-stub",
        action="store_true",
        dest="allow_fpga_stub",
        help=(
            "Demote per-block missing-artifact failures to "
            "PASS_WITH_WAIVERS at the FPGA prototype stage. The same "
            "gate re-fires without this flag at "
            "phase3.foundry_handoff for tapeout signoff. Also "
            "controllable via the PHASE23_ANALOG_FPGA_STUB=1 env var "
            "for the phase23 umbrella runner."
        ),
    )


def fpga_stub_reason() -> str:
    """Human-readable rationale string embedded in the gate's verdict
    JSON summary when the waiver fires."""
    return (
        "FPGA prototype stage — per-block analog artifacts pending "
        "A1-A9 completion; gate re-fires without --allow-fpga-stub at "
        "phase3.foundry_handoff for tapeout signoff."
    )


__all__ = [
    "fpga_stub_waiver_active",
    "add_fpga_stub_argparse",
    "fpga_stub_reason",
]
