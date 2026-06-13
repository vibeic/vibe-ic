"""Shared SystemVerilog-frontend selection logic.

Both the Phase-2 (`phase2_one_shot_runner.step_yosys_synth`,
`phase2_one_shot_runner.step_reference_tb`) and the Phase-3
(`phase3_one_shot_runner.step_synth`) backend steps read RTL with a
*default* frontend that only handles a SystemVerilog SUBSET:

  * yosys built-in `read_verilog -sv`  (the two synth steps), and
  * `iverilog -g2012`                  (the reference-TB / sim step).

Both fail at the first *modern* SystemVerilog construct that is pervasive
in production open-source CPU / SoC IP pulled by the catalog-glue
integrator path — packages with typed/parameterised members,
package-scoped types used as port/parameter types, `module M import
pkg::*; (...)` (import-before-ANSI-port-list), and named-field struct
literals `'{field: value, ...}` — even though the RTL is fully
synthesizable / elaborable by a full SV-2017 frontend.

This module centralises the ONE decision both phases need:

    "after the default frontend attempt, do I need to fall through to an
     SV-aware frontend, and why?"

so the rule lives in exactly one place rather than being copy-pasted
(and allowed to diverge) across three call-sites.

The actual SV-aware frontends invoked on a positive decision are:

  * synth steps : `yosys -m slang` / `read_slang` (PREFERRED — full
                  SV-2017, preserves hierarchy, no temp files) then an
                  `sv2v` pre-pass emitting Verilog-2005 for the default
                  yosys frontend; and
  * the TB step : an `sv2v` pre-pass emitting Verilog-2005 that `iverilog`
                  can compile (or a `verilator --lint-only` elaboration
                  sanity gate when sv2v is unavailable).

Chip-AGNOSTIC: every decision is driven by file *extension* and tool
*error signatures* only — never a chip-class / vendor string literal.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple, Union

# yosys built-in Verilog-2005 frontend (`read_verilog -sv`) error
# signatures that indicate an unsupported SystemVerilog construct rather
# than a genuine RTL defect. Kept verbatim from the original Phase-3
# Fix #5 list so the Phase-3 behaviour is byte-for-byte preserved.
SLANG_ERROR_SIGNATURES: Tuple[str, ...] = (
    "unexpected TOK_IMPORT",
    "syntax error",
    "Executing Verilog-2005 frontend",
    "unsupported SystemVerilog",
    "TOK_PACKAGE",
    "TOK_TYPEDEF",
)

# `iverilog -g2012` error signatures that indicate the same family of
# unsupported modern-SystemVerilog constructs (iverilog ≤ 14 implements a
# SystemVerilog SUBSET only). The exact diagnostics differ from yosys's,
# so the TB path carries its own signature set — but it is consumed by the
# SAME `decide_synth_frontend()` decision function below.
IVERILOG_SV_ERROR_SIGNATURES: Tuple[str, ...] = (
    "syntax error",
    "sorry: ",                       # iverilog "sorry: <feature> not supported"
    "is not yet supported",
    "not supported in this context",
    "Unknown package",
    "Unable to bind",                # package-scoped type/parameter not bound
    "error: Package",
    "assignment pattern",            # '{field: value, ...} named-field literal
    "Could not find a module named", # unresolved package-typed type reference
    "Net data type requires SystemVerilog",
)

# Backward-compat alias used by the original Phase-3 module-level name.
_SLANG_ERROR_SIGNATURES = SLANG_ERROR_SIGNATURES


def decide_synth_frontend(
    rtl_files: Sequence[Union[str, Path]],
    default_rc: int,
    default_netlist_exists: bool,
    default_log: str,
    error_signatures: Sequence[str] = SLANG_ERROR_SIGNATURES,
) -> Tuple[bool, str]:
    """Decide whether to invoke an SV-aware fallback frontend after the
    *default* frontend attempt.

    Parameters
    ----------
    rtl_files
        The RTL inputs fed to the default frontend.
    default_rc
        Return code of the default frontend attempt.
    default_netlist_exists
        Whether the default attempt produced its expected output artefact
        (synth netlist for the synth steps, ``.vvp`` for the TB step).
    default_log
        Combined stdout+stderr of the default frontend attempt.
    error_signatures
        Tool-specific error-signature set. Defaults to the yosys
        ``read_verilog -sv`` signatures; the iverilog TB path passes
        :data:`IVERILOG_SV_ERROR_SIGNATURES`.

    Returns
    -------
    (need_sv_fallback, reason)
        ``need_sv_fallback`` is True when EITHER the default attempt
        failed / produced no artefact AND its log carries an SV error
        signature, OR any input file is ``.sv`` and the default attempt
        failed / produced no artefact.

    A ``.sv`` extension alone does NOT force the fallback when the default
    frontend already succeeded — both `read_verilog -sv` and
    `iverilog -g2012` handle plenty of `.sv` files, and re-running
    wastefully would only risk regressions. Chip-AGNOSTIC: extension +
    error-signature only.
    """
    default_failed = (default_rc != 0) or (not default_netlist_exists)
    has_sv = any(str(f).lower().endswith(".sv") for f in rtl_files)
    if not default_failed:
        return False, "default frontend succeeded"
    sig_hit = any(s in (default_log or "") for s in error_signatures)
    if sig_hit:
        return True, "default frontend errored with an SV signature"
    if has_sv:
        return True, ("default frontend failed and inputs include "
                      ".sv files — trying SV-2017 frontend")
    return False, ("default frontend failed but no SV signature / .sv "
                   "input — fallback would not help")


def decide_iverilog_sv_fallback(
    rtl_files: Sequence[Union[str, Path]],
    default_rc: int,
    default_artifact_exists: bool,
    default_log: str,
) -> Tuple[bool, str]:
    """Convenience wrapper for the reference-TB / simulation step.

    Identical decision to :func:`decide_synth_frontend` but pre-bound to
    the iverilog error-signature set, so the TB call-site reads cleanly
    while still sharing the single decision implementation.
    """
    return decide_synth_frontend(
        rtl_files, default_rc, default_artifact_exists, default_log,
        error_signatures=IVERILOG_SV_ERROR_SIGNATURES)
