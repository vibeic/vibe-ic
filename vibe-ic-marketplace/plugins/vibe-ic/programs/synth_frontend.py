"""Shared SystemVerilog-frontend selection logic.

Both the Phase-2 (`design_one_shot_runner.step_yosys_synth`,
`design_one_shot_runner.step_reference_tb`) and the Phase-3
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


# `sv2v` parse-error signatures that indicate the construct is an
# SVA / sequence / property the converter cannot lower — NOT a genuine RTL
# defect. The synth path escapes such closures via `yosys -m slang` (full
# SV-2017), but the simulation / reference_tb path historically had iverilog
# → sv2v ONLY with no slang/verilator escape, so an identical closure that
# SYNTHESISES clean was structurally unreachable in sim (ORGANIC #657). The
# canonical signature is sv2v's consecutive-repetition lexer token
# `(Sym_brack_l_aster)` / `unexpected token [*` inside a sequence/property
# block. chip-AGNOSTIC: tool error-token + SV-keyword surface only.
SV2V_ASSERTION_PARSE_SIGNATURES: Tuple[str, ...] = (
    "Sym_brack_l_aster",        # sv2v lexer token for `[*` (consecutive-rep)
    "unexpected token [*",      # sv2v parse error rendering of the same
    "unexpected token [=",      # `[=N]` non-consecutive repetition
    "unexpected token [->",     # `[->N]` goto repetition
    "Parse error",              # sv2v generic parse error (qualified below)
)

# SystemVerilog assertion / sequence / property KEYWORDS. A sv2v parse error
# is treated as an assertion-construct gap (→ verilator escape) only when the
# converted source ALSO carries one of these — so a genuine non-assertion RTL
# defect that happens to print "Parse error" still FAILs honestly.
SVA_KEYWORDS: Tuple[str, ...] = (
    "assert property", "assume property", "cover property",
    "sequence ", "property ", " throughout ", " intersect ", " within ",
    "[*", "[=", "[->",
)


def sim_frontend_should_try_verilator(
    rtl_files: Sequence[Union[str, Path]],
    sv2v_rc: int,
    sv2v_err: str,
    rtl_text_blob: str,
) -> Tuple[bool, str]:
    """Decide whether the SIM / reference_tb frontend should escape to a
    verilator (or slang) elaboration after the iverilog → sv2v ladder has
    FAILED on an SVA / sequence / property construct (ORGANIC #657).

    Mirrors the asymmetry the synth path already closes via `yosys -m slang`:
    the synth frontend accepts full SV-2017 (incl. SVA sequences), but the
    sim frontend trailed it. The verilator escape is attempted ONLY when:

      * the sv2v pre-pass itself FAILED (sv2v_rc != 0), AND
      * sv2v's stderr carries an SVA/sequence/property parse signature
        (e.g. the consecutive-repetition `[*N]` lexer token), AND
      * the actual RTL text carries an SVA keyword (so a non-assertion
        "Parse error" — a real RTL defect — does NOT trigger the escape), AND
      * at least one `.sv` input is present.

    Returns (should_try, reason). Honesty preserved: a defect ALL SV-2017
    frontends reject still FAILs (verilator will also fail, and the caller
    keeps the honest FAIL). chip-AGNOSTIC: tool error-token + SV-keyword
    surface only — no chip/vendor/file literal."""
    has_sv = any(str(f).lower().endswith(".sv") for f in rtl_files)
    if not has_sv:
        return False, "no .sv input — verilator escape would not help"
    if sv2v_rc == 0:
        return False, "sv2v converted cleanly — no escape needed"
    err = sv2v_err or ""
    sig_hit = any(s in err for s in SV2V_ASSERTION_PARSE_SIGNATURES)
    if not sig_hit:
        return False, ("sv2v failure carries no SVA/sequence parse "
                       "signature — not an assertion-construct gap")
    blob = rtl_text_blob or ""
    kw_hit = any(k in blob for k in SVA_KEYWORDS)
    if not kw_hit:
        return False, ("sv2v parse error but RTL has no SVA/sequence/"
                       "property keyword — treat as genuine defect, FAIL")
    return True, ("sv2v cannot lower an SVA/sequence/property construct "
                  "(e.g. consecutive-repetition [*N]); the identical "
                  "closure elaborates under a full SV-2017 frontend — "
                  "escaping to verilator (mirrors the synth slang path)")


def decide_sv2v_tb_define(
    files_text: "dict[str, str]",
    sim_define: str = "SIMULATION",
    synth_define: str = "SYNTHESIS",
) -> Tuple[str, str]:
    """Pick the sv2v -D<define> for the reference-TB pre-pass so the
    staged conditional-compilation arm actually resolves (ORGANIC #640).

    The canonical vendor assertion-macro header (ifdef VERILATOR / elsif
    SYNTHESIS / else -> include "<standard-macros>.svh") is frequently
    shipped in a SYNTHESIS-pruned REUSED-IP closure with ONLY the
    synthesis-arm dummy-macros .svh staged; the simulation-arm
    standard-macros .svh is intentionally excluded. The TB pre-pass
    historically hardcoded -DSIMULATION, which takes the else arm and
    includes a file that was never staged, so sv2v dies at the lexer
    ("Could not find file ...") before any parsing, even though the
    IDENTICAL closure converts clean under -DSYNTHESIS (which the #587
    synth-frontend path already uses, and which PASSes).

    This decision is purely STRUCTURAL and chip-AGNOSTIC: it asks the
    shared sv_package_closure_check.audit gate whether the include
    closure resolves under the simulation define-set; if and ONLY IF the
    sim define-set leaves an UNRESOLVED include hole that the synth
    define-set instead resolves cleanly, flip to the synth define so the
    staged arm is selected. There is NO chip/vendor/SKU/file string
    literal in the logic; the only inputs are the closure-gate verdicts
    under two abstract define-sets.

    Returns (define, reason) where define is the chosen macro name
    (default sim_define; the historical behaviour is preserved for every
    closure that already resolves under simulation, so this NEVER masks a
    genuine missing-include / RTL defect: when BOTH define-sets leave a
    hole, or neither does, the sim define is kept and the honest failure
    stands)."""
    try:
        import sv_package_closure_check as _cc
    except Exception as exc:  # pragma: no cover - import guard
        return sim_define, f"closure gate unavailable ({exc}); keep -D{sim_define}"

    if not files_text:
        # Empty input must NOT trigger a flip; an under-populated closure
        # is itself a defect the honest failure should still surface.
        return sim_define, f"no staged sources; keep -D{sim_define}"

    try:
        sim_report = _cc.audit(files_text, {sim_define})
        synth_report = _cc.audit(files_text, {synth_define})
    except Exception as exc:  # pragma: no cover - defensive
        return sim_define, f"closure audit error ({exc}); keep -D{sim_define}"

    sim_missing = sim_report.get("missing_includes") or []
    synth_missing = synth_report.get("missing_includes") or []

    # Flip ONLY when the simulation arm has an include hole AND the
    # synthesis arm resolves that very closure cleanly (every include
    # missing under -DSIMULATION is present under -DSYNTHESIS). If the
    # synth arm ALSO leaves an include unresolved, the closure is genuinely
    # under-staged; keep -DSIMULATION so the honest failure stands.
    if sim_missing and not synth_missing:
        return synth_define, (
            f"-D{sim_define} leaves an include closure hole "
            f"{sim_missing!r} that -D{synth_define} resolves "
            f"(synthesis-pruned assertion-macro closure, #640); "
            f"selecting -D{synth_define}")
    return sim_define, (
        f"-D{sim_define} include closure complete (or both arms "
        f"under-staged); keep -D{sim_define}")


# ORGANIC #668 — verilator error tokens that mark a SIM-ONLY-CONSTRUCT failure:
# a verilator-unsupported construct that lives inside a dead `ifdef SIMULATION
# arm (std::randomize / $urandom-class randomisation helpers) which the IDENTICAL
# closure elaborates cleanly under -DSYNTHESIS (the construct is gone — the
# synthesizable `else passthrough is taken instead). These are NOT genuine RTL
# defects; they are a define-set mismatch. chip-AGNOSTIC: verilator tool-token
# surface + the standard randomisation-helper vocabulary, no chip/vendor literal.
VERILATOR_SIMONLY_CONSTRUCT_SIGNATURES: Tuple[str, ...] = (
    "Duplicate declaration of signal: stdrand",   # std::randomize() scaffold
    "stdrand",                                     # verilator std::randomize tmp
    "std::randomize",
    "randomize() with",
    "Unsupported: $urandom",
    "Unsupported: randomize",
    "Unsupported: 'randomize'",
    "Unsupported: std::",
)


def verilator_should_retry_synthesis_define(
    verilator_err: str,
    sim_define: str = "SIMULATION",
    synth_define: str = "SYNTHESIS",
) -> Tuple[bool, str]:
    """ORGANIC #668 — decide whether the verilator SIM escape, after FAILING
    under -D<sim_define>, should retry the SAME closure under -D<synth_define>.

    The verilator SIM escape historically hardcoded -DSIMULATION, so it compiled
    the sim-only `ifdef SIMULATION arm of a vendor primitive library (e.g. a
    randomised-delay CDC model using std::randomize()/$urandom) and died on a
    sim-only-construct error verilator cannot lower — even though that arm is
    functionally DEAD and the IDENTICAL closure elaborates + runs to $finish
    under -DSYNTHESIS (the synthesizable `else passthrough), the SAME define the
    synth slang path already uses successfully. `decide_sv2v_tb_define` only
    flips to SYNTHESIS on an include HOLE, and the #657 escape only fires on an
    SVA signature; neither covers this, and the escape never tried SYNTHESIS.

    Retry iff verilator's stderr carries a SIM-ONLY-CONSTRUCT signature. Honesty
    preserved: a closure that ALSO fails under -D<synth_define> still FAILs (the
    caller keeps the honest failure). chip-AGNOSTIC: tool error-token + the
    standard SIMULATION/SYNTHESIS define names, no chip/vendor/file literal.

    Returns (should_retry, reason)."""
    err = verilator_err or ""
    hit = any(s in err for s in VERILATOR_SIMONLY_CONSTRUCT_SIGNATURES)
    if not hit:
        return False, (
            f"verilator failure carries no sim-only-construct signature — "
            f"not a -D{sim_define}/-D{synth_define} define-set mismatch; "
            f"keep the honest FAIL")
    return True, (
        f"verilator failed under -D{sim_define} on a sim-only construct "
        f"(std::randomize/$urandom in a dead `ifdef {sim_define} arm); the "
        f"IDENTICAL closure elaborates under -D{synth_define} (the "
        f"synthesizable `else passthrough — the define the synth path "
        f"already uses) — retrying under -D{synth_define}")


# ORGANIC E2E (opentitan_aes GDS blocker, 2026-07-01) — the phase-3 yosys/slang/
# sv2v synth frontends hardcode -DSIMULATION, so they compile the `ifdef
# SIMULATION DV-only arm ($urandom / std::randomize / $value$plusargs-in-a-
# constant-context / a slang "Feature unimplemented" on a sim-only construct) of
# a vendor primitive library and FAIL — even though the IDENTICAL closure
# elaborates under -DSYNTHESIS (the synthesizable `else passthrough). This is the
# phase-3 companion to the phase-2 #668 verilator retry, but the error signatures
# are the slang / sv2v / yosys forms (a superset that also covers verilator).
SYNTH_FRONTEND_SIMONLY_CONSTRUCT_SIGNATURES: Tuple[str, ...] = (
    "$urandom",
    "std::randomize",
    "value$plusargs",
    "$value$plusargs",
    "Feature unimplemented",
    "not allowed in a constant context",
) + VERILATOR_SIMONLY_CONSTRUCT_SIGNATURES


def synth_frontend_should_retry_under_synthesis(
    synth_err: str,
    sim_define: str = "SIMULATION",
    synth_define: str = "SYNTHESIS",
) -> Tuple[bool, str]:
    """Phase-3 companion to #668 — decide whether a phase-3 yosys/slang/sv2v synth
    build that FAILED under -D<sim_define> should retry the SAME closure under
    -D<synth_define>. Retry iff the error carries a sim-only-construct signature
    (the DV-only `ifdef <sim_define> arm). Honesty preserved: a closure that ALSO
    fails under -D<synth_define> keeps the honest FAIL at the caller. chip-AGNOSTIC:
    tool error-token + the standard SIMULATION/SYNTHESIS define names, no chip /
    vendor / file literal.

    Returns (should_retry, reason)."""
    err = synth_err or ""
    hit = any(s in err for s in SYNTH_FRONTEND_SIMONLY_CONSTRUCT_SIGNATURES)
    if not hit:
        return False, (
            f"synth failure carries no sim-only-construct signature — not a "
            f"-D{sim_define}/-D{synth_define} define-set mismatch; keep the "
            f"honest FAIL")
    return True, (
        f"synth failed under -D{sim_define} on a sim-only construct "
        f"($urandom/std::randomize in a dead `ifdef {sim_define} arm); the "
        f"IDENTICAL closure elaborates under -D{synth_define} (the synthesizable "
        f"`else passthrough) — retrying under -D{synth_define}")


# ---------------------------------------------------------------------------
# slang frontend load-prefix — probe built-in `read_slang` vs a loadable .so.
#
# THE BUG this centralises (v1.3.43): every SV synth recipe hardcoded
# `yosys -p 'plugin -i slang; read_slang …'`. The vibeic-eda fork's yosys
# (0.66+232) ships slang COMPILED-IN (built-in `read_slang`; there is NO
# `slang.so`), so `plugin -i slang` ERRORs "Can't load module ./slang" and
# ABORTS the ENTIRE `-p` script → synth silently falls back to `read_verilog`,
# which can't prune a masked generate branch (OpenTitan AES: "aes_sbox_dom not
# part of the design"). The fix: skip `plugin -i slang` when `read_slang` is
# built-in, keep it for images that ship slang as a separate loadable module.
# Single source of truth for all 3 call-sites (design_one_shot_runner +
# phase3_one_shot_runner ×2). chip-AGNOSTIC: tool probe only, no chip literal.
#
# Probe = `yosys -p 'read_slang'` (NO plugin load, NO file). A BUILT-IN command
# begins executing the SLANG frontend then errors on "no input files"; an
# ABSENT command (image where slang is an unloaded .so, or genuinely missing)
# yields "No such command: read_slang".
SLANG_PROBE_CMD: str = (
    "export PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH && "
    "yosys -p 'read_slang'"
)


def read_slang_is_builtin(probe_output: str) -> bool:
    """True iff `read_slang` is available WITHOUT `plugin -i slang`.

    Decided from the output of :data:`SLANG_PROBE_CMD`. The ONLY case that
    REQUIRES the plugin load is an unloaded loadable module — which ALWAYS
    prints the definitive "No such command: read_slang". So we key the load
    on exactly that signal and DEFAULT TO BUILT-IN otherwise (fork-safe: the
    shipped `vibeic-eda` image is built-in and produces positive evidence
    like "Executing SLANG frontend" / "no input files"; an inconclusive or
    empty probe must NOT emit a load that would abort the fork's -p script).
    A `.so` image correctly shows "No such command" until the module is
    loaded, so it still gets the load prefix."""
    return "No such command: read_slang" not in (probe_output or "")


def slang_load_prefix(probe_output: str) -> str:
    """Return the `yosys -p` prefix that makes `read_slang` available.

    ``""``               — `read_slang` is COMPILED-IN → emit NO plugin load
                            (emitting one would ABORT the whole `-p` script on
                            the fork image, the bug this fixes).
    ``"plugin -i slang; "`` — `read_slang` is NOT built-in → load the module
                            (image ships slang as a `.so`; if it is genuinely
                            absent the load fails loudly and the caller's
                            sv2v / read_verilog fallback engages, exactly as
                            before this fix)."""
    return "" if read_slang_is_builtin(probe_output) else "plugin -i slang; "


# per-container memo so the probe runs once, not on every synth call.
_SLANG_PREFIX_CACHE: dict = {}


def resolve_slang_load_prefix(container: str, exec_fn) -> str:
    """Probe `container` ONCE (memoised) and return the slang load-prefix.

    ``exec_fn(container, cmd) -> (rc, out, err)`` is the caller's docker-exec
    (both runners' ``_docker_exec`` match this signature). On any probe error
    the fork-safe default is ``""`` (the shipped `vibeic-eda` image ships
    slang built-in; skipping the load is correct there, and on a `.so` image a
    wrongly-skipped load merely triggers the sv2v fallback — recoverable —
    whereas a wrongly-emitted load ABORTS the script, the bug we are fixing)."""
    if container in _SLANG_PREFIX_CACHE:
        return _SLANG_PREFIX_CACHE[container]
    try:
        rc, out, err = exec_fn(container, SLANG_PROBE_CMD)
        pref = slang_load_prefix((out or "") + "\n" + (err or ""))
    except Exception:
        pref = ""
    _SLANG_PREFIX_CACHE[container] = pref
    return pref
