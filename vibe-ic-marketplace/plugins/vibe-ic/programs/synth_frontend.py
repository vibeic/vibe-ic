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

Chip-AGNOSTIC: every decision is driven by an OBSERVABLE OUTCOME (did the
frontend produce an elaborated design / any usable output?), a DESIGN
PROPERTY of the RTL (does it branch on the sim/synth define? does it carry
SVA constructs?), and file *extension* — never a chip-class / vendor string
literal, and (since v1.4.x) never the tool's error PHRASING. See the
OBSERVABLE-OVER-WORDING doctrine block below.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Sequence, Tuple, Union

# ---------------------------------------------------------------------------
# OBSERVABLE-OVER-WORDING doctrine (v1.4.x, mirrors the lec_run slang-retry fix)
#
# A control decision must key on an OBSERVABLE OUTCOME ("did the frontend
# produce an elaborated design / any usable output?") or on a DESIGN PROPERTY
# of the RTL ("does this source actually carry a define-conditional arm?"),
# NEVER on the tool's error PHRASING. Tools rename diagnostics between
# releases; a wording allow-list that drives a RETRY silently stops firing on
# the reworded abort and turns a recoverable closure into an honest-looking
# FALSE FAIL, with nothing in the log to show the capability was skipped.
#
# The signature tuples below are RETAINED but DEMOTED to explanatory strings:
# they colour the reason text in the log and nothing more. Grep for
# `_EXPLANATORY_ONLY` — no `if` that changes control flow may read them.
# ---------------------------------------------------------------------------
_EXPLANATORY_ONLY = "not a control predicate — reason-string colouring only"

# Bound on how much RTL text a design-property probe will read. A closure can
# be hundreds of files; the directives/constructs we look for appear early and
# often, so a cap keeps the probe O(1) without changing any verdict.
_BLOB_SCAN_CAP_BYTES = 2_000_000


def read_text_blob(files: Sequence[Union[str, Path]],
                   cap_bytes: int = _BLOB_SCAN_CAP_BYTES) -> str:
    """Concatenate `files` into one text blob for a DESIGN-PROPERTY probe.

    Unreadable / binary files are skipped rather than raising: a design-property
    probe is advisory input to a retry decision, never a verdict, so a partial
    blob must degrade to "property not observed" (fail-safe: no retry) instead
    of exploding the caller."""
    out: List[str] = []
    total = 0
    for f in files:
        if total >= cap_bytes:
            break
        try:
            txt = Path(f).read_text(errors="replace")
        except (OSError, ValueError):
            continue
        out.append(txt[:cap_bytes - total])
        total += len(txt)
    return "\n".join(out)


def define_conditional_arms_present(
    rtl_text_blob: str,
    sim_define: str = "SIMULATION",
    synth_define: str = "SYNTHESIS",
) -> Tuple[bool, str]:
    """DESIGN PROPERTY: does this source actually branch on the sim/synth define?

    This is the invariant that bounds every ``-D<sim>`` → ``-D<synth>`` retry in
    this module. If the closure carries NO `` `ifdef/`ifndef/`elsif `` on either
    define name, then re-reading it under the other define feeds the frontend
    BYTE-IDENTICAL text — the retry provably cannot change the outcome, so it is
    skipped (no wasted tool invocation, and no possibility of a verdict change).

    Returns (present, evidence) where evidence names the directives found."""
    blob = rtl_text_blob or ""
    if not blob:
        return False, "no RTL text available to probe"
    pat = re.compile(
        r"`(ifdef|ifndef|elsif)\s+(" + re.escape(sim_define) + r"|"
        + re.escape(synth_define) + r")\b")
    hits = {f"`{m.group(1)} {m.group(2)}" for m in pat.finditer(blob)}
    if not hits:
        return False, (
            f"no `ifdef/`ifndef/`elsif on {sim_define}/{synth_define} in the "
            f"RTL — flipping the define feeds byte-identical source")
    return True, "RTL carries " + ", ".join(sorted(hits))


# DESIGN PROPERTY (not a tool-wording probe): simulation-only constructs as they
# appear in the RTL SOURCE. Used ONLY to colour the reason string with WHY the
# sim arm is likely unsynthesizable; the retry decision never depends on it.
_SIMONLY_SOURCE_CONSTRUCTS: Tuple[str, ...] = (
    "$urandom", "$random", "std::randomize", "randomize()",
    "$value$plusargs", "$plusargs", "$fdisplay", "$fatal", "$dumpfile",
)


def simonly_constructs_in_source(rtl_text_blob: str) -> Tuple[bool, str]:
    """DESIGN PROPERTY: does the RTL literally contain sim-only constructs?

    Explanatory only — reported in the retry reason so the log says WHAT made
    the simulation arm unsynthesizable, derived from the DESIGN rather than
    from whatever the tool happened to call it this release."""
    blob = rtl_text_blob or ""
    hits = sorted({c for c in _SIMONLY_SOURCE_CONSTRUCTS if c in blob})
    if not hits:
        return False, "no sim-only construct visible in the RTL source"
    return True, "RTL source contains " + ", ".join(hits)


def _wording_note(err: str, signatures: Sequence[str]) -> str:
    """Reason-string colouring ONLY (see :data:`_EXPLANATORY_ONLY`).

    Names the recognised phrase when the tool happens to use one we know, so
    the log stays as readable as it was under the old allow-list. Returns a
    neutral note otherwise — an UNRECOGNISED phrasing is explicitly NOT a
    reason to withhold the retry; that was the bug this doctrine retires."""
    e = err or ""
    for s in signatures:
        if s in e:
            return f"tool reported {s!r}"
    first = next((ln.strip() for ln in e.splitlines() if ln.strip()), "")
    if first:
        return f"tool phrasing unrecognised ({first[:120]!r}) — decided on the observable"
    return "tool produced no diagnostic text — decided on the observable"

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

# DESIGN PROPERTY (v1.4.x): modern-SystemVerilog constructs as they appear in
# the RTL SOURCE — exactly the family named in this module's docstring that
# `read_verilog -sv` / `iverilog -g2012` cannot read but a full SV-2017 frontend
# can. Reading these from the SOURCE (rather than from the tool's error text)
# is what lets the fallback fire on a REWORDED abort, and closes the residual
# hole the file-extension test leaves: a `.v` file carrying SV constructs.
MODERN_SV_CONSTRUCTS: Tuple[str, ...] = (
    "package ", "endpackage", "import ", "::", "typedef ",
    "'{",                       # named-field / assignment-pattern literal
    "interface ", "modport", "struct packed", "union packed",
)


def decide_synth_frontend(
    rtl_files: Sequence[Union[str, Path]],
    default_rc: int,
    default_netlist_exists: bool,
    default_log: str,
    error_signatures: Sequence[str] = SLANG_ERROR_SIGNATURES,
    rtl_text_blob: str = "",
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
    # DESIGN PROPERTY first (v1.4.x): does the RTL actually contain a modern-SV
    # construct the default Verilog-2005 frontend cannot read? This closes the
    # residual hole the extension test leaves — a `.v` file carrying SV
    # constructs — WITHOUT consulting the tool's phrasing, and it fires whatever
    # the frontend called its abort.
    if rtl_text_blob:
        sv_hit = sorted({c for c in MODERN_SV_CONSTRUCTS
                         if c in rtl_text_blob})
        if sv_hit:
            return True, (
                f"default frontend produced no netlist and the RTL contains "
                f"modern-SV constructs ({', '.join(repr(c) for c in sv_hit)}) "
                f"the Verilog-2005 frontend cannot read — trying the SV-2017 "
                f"frontend [{_wording_note(default_log, error_signatures)}]")
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
    rtl_text_blob: str = "",
) -> Tuple[bool, str]:
    """Convenience wrapper for the reference-TB / simulation step.

    Identical decision to :func:`decide_synth_frontend` but pre-bound to
    the iverilog error-signature set, so the TB call-site reads cleanly
    while still sharing the single decision implementation.
    """
    return decide_synth_frontend(
        rtl_files, default_rc, default_artifact_exists, default_log,
        error_signatures=IVERILOG_SV_ERROR_SIGNATURES,
        rtl_text_blob=rtl_text_blob)


# `sv2v` parse-error signatures that indicate the construct is an
# SVA / sequence / property the converter cannot lower — NOT a genuine RTL
# defect. The synth path escapes such closures via `yosys -m slang` (full
# SV-2017), but the simulation / reference_tb path historically had iverilog
# → sv2v ONLY with no slang/verilator escape, so an identical closure that
# SYNTHESISES clean was structurally unreachable in sim (ORGANIC #657). The
# canonical signature is sv2v's consecutive-repetition lexer token
# `(Sym_brack_l_aster)` / `unexpected token [*` inside a sequence/property
# block. chip-AGNOSTIC: tool error-token + SV-keyword surface only.
# _EXPLANATORY_ONLY (v1.4.x): RETAINED for the reason string, RETIRED as a
# control predicate. `Sym_brack_l_aster` is an Alex-generated lexer token name
# — the most volatile string sv2v emits — and keying the escape on it meant a
# rename silently skipped the capability. The decision now reads the OBSERVABLE
# (sv2v produced no conversion) + the DESIGN PROPERTY (SVA_KEYWORDS in the RTL).
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
    converted_exists: bool = True,
) -> Tuple[bool, str]:
    """Decide whether the SIM / reference_tb frontend should escape to a
    verilator (or slang) elaboration after the iverilog → sv2v ladder has
    FAILED on an SVA / sequence / property construct (ORGANIC #657).

    Mirrors the asymmetry the synth path already closes via `yosys -m slang`:
    the synth frontend accepts full SV-2017 (incl. SVA sequences), but the
    sim frontend trailed it.

    OBSERVABLE-BASED (v1.4.x). The escape used to require a match against sv2v's
    parse-error PHRASING — including `Sym_brack_l_aster`, an Alex-generated
    LEXER TOKEN NAME and the single most volatile string that tool emits. A
    rename there silently skipped the whole verilator capability and produced a
    FALSE FAIL. The escape now fires on:

      * the OBSERVABLE: sv2v produced NO usable conversion (non-zero rc, or no
        converted output file) — whatever it said about why, AND
      * the DESIGN PROPERTY: the RTL genuinely contains an SVA / sequence /
        property construct, i.e. something sv2v is known not to lower and a full
        SV-2017 frontend does. This is read from the RTL SOURCE, not from the
        error text, so a real RTL defect in an assertion-free design still FAILs
        honestly rather than being escaped, AND
      * at least one `.sv` input is present (structural — sv2v/verilator escape
        cannot help a pure Verilog-2005 closure).

    §4.05 — widening the ESCAPE does not widen PASS: verilator must still build
    AND run the TB to its completion marker for the caller to accept a pass, so
    a design with a genuine functional bug fails on the escape path exactly as
    it would have on the iverilog path. And because the escape only runs when
    sv2v produced NOTHING, there is no existing result to shop for.

    Returns (should_try, reason). chip-AGNOSTIC: file extension + SV-keyword
    surface of the DESIGN — no chip/vendor/file literal."""
    has_sv = any(str(f).lower().endswith(".sv") for f in rtl_files)
    if not has_sv:
        return False, "no .sv input — verilator escape would not help"
    if sv2v_rc == 0 and converted_exists:
        return False, "sv2v converted cleanly — no escape needed"
    blob = rtl_text_blob or ""
    kw_hit = sorted({k for k in SVA_KEYWORDS if k in blob})
    if not kw_hit:
        return False, ("sv2v produced no conversion and the RTL carries no "
                       "SVA/sequence/property construct — nothing a full "
                       "SV-2017 frontend would lower differently; treat as a "
                       "genuine defect and FAIL")
    note = _wording_note(sv2v_err, SV2V_ASSERTION_PARSE_SIGNATURES)
    return True, (
        f"sv2v produced NO conversion and the RTL contains SVA/sequence/"
        f"property constructs ({', '.join(repr(k) for k in kw_hit)}) that sv2v "
        f"cannot lower; the identical closure elaborates under a full SV-2017 "
        f"frontend — escaping to verilator (mirrors the synth slang path) "
        f"[{note}]")


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
# _EXPLANATORY_ONLY (v1.4.x): RETAINED for the reason string, RETIRED as a
# control predicate — verilator renames its `Unsupported:` diagnostics between
# releases, so this allow-list silently stopped firing on reworded aborts. The
# retry now reads the OBSERVABLE (no runnable simulation produced) + the DESIGN
# PROPERTY (the closure branches on the sim/synth define).
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
    rtl_text_blob: str = "",
    tb_text: str = "",
    produced_output: bool = False,
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
    synth slang path already uses successfully.

    OBSERVABLE-BASED (v1.4.x). The retry is NOT keyed on how verilator phrased
    the abort — verilator renames its `Unsupported:` diagnostics between
    releases, so that allow-list silently stopped firing and produced a FALSE
    FAIL. It is keyed on the OBSERVABLE (the build produced no runnable
    simulation) plus the DESIGN PROPERTY that the closure branches on the define
    set at all.

    THE TESTBENCH GUARD (§4.05, new — the old wording gate had no equivalent):
    the retry is REFUSED when the TESTBENCH itself branches on the define set.
    Flipping the define is only sound while it changes the DUT's arms; if it
    also changes the TB, the retry could compile away the TB's own checking and
    run to completion vacuously — converting a genuine failure into a pass. That
    is the one way this retry could widen PASS, so it is closed explicitly.

    Honesty preserved: a closure that ALSO fails under -D<synth_define> still
    FAILs (the caller keeps the honest failure), and the caller's completion
    -MARKER check still has to be satisfied by the retry's own transcript.
    chip-AGNOSTIC: preprocessor grammar + the standard SIMULATION/SYNTHESIS
    define names, no chip/vendor/file literal.

    Returns (should_retry, reason)."""
    if produced_output:
        return False, (
            f"the -D{sim_define} build already produced a runnable simulation — "
            f"no retry (a real result must not be re-run under -D{synth_define})")
    arms, arm_evidence = define_conditional_arms_present(
        rtl_text_blob, sim_define, synth_define)
    if not arms:
        return False, (
            f"verilator produced no simulation, but {arm_evidence}; a "
            f"-D{synth_define} retry would re-read byte-identical source — "
            f"keep the honest FAIL")
    tb_arms, tb_evidence = define_conditional_arms_present(
        tb_text, sim_define, synth_define)
    if tb_arms:
        return False, (
            f"REFUSING the -D{synth_define} retry: the TESTBENCH itself "
            f"branches on the define set ({tb_evidence}). Flipping the define "
            f"could compile away the TB's own checking and let the run finish "
            f"vacuously — that would convert a genuine FAIL into a pass. Keep "
            f"the honest FAIL")
    _, construct_evidence = simonly_constructs_in_source(rtl_text_blob)
    note = _wording_note(verilator_err, VERILATOR_SIMONLY_CONSTRUCT_SIGNATURES)
    return True, (
        f"verilator produced NO simulation under -D{sim_define} and the DUT "
        f"closure branches on the define set ({arm_evidence}; "
        f"{construct_evidence}) while the TESTBENCH does not — so the "
        f"-D{synth_define} arm is a DIFFERENT source and the TB's checking is "
        f"unaffected; retrying under -D{synth_define} [{note}]")


# ORGANIC E2E (opentitan_aes GDS blocker, 2026-07-01) — the phase-3 yosys/slang/
# sv2v synth frontends hardcode -DSIMULATION, so they compile the `ifdef
# SIMULATION DV-only arm ($urandom / std::randomize / $value$plusargs-in-a-
# constant-context / a slang "Feature unimplemented" on a sim-only construct) of
# a vendor primitive library and FAIL — even though the IDENTICAL closure
# elaborates under -DSYNTHESIS (the synthesizable `else passthrough). This is the
# phase-3 companion to the phase-2 #668 verilator retry, but the error signatures
# are the slang / sv2v / yosys forms (a superset that also covers verilator).
# _EXPLANATORY_ONLY (v1.4.x): RETAINED for the reason string, RETIRED as a
# control predicate — see the doctrine block at the top of this module. The
# retry now reads the OBSERVABLE (no netlist produced) + the DESIGN PROPERTY.
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
    rtl_text_blob: str = "",
    produced_output: bool = False,
    sim_define: str = "SIMULATION",
    synth_define: str = "SYNTHESIS",
) -> Tuple[bool, str]:
    """Phase-3 companion to #668 — decide whether a phase-3 yosys/slang/sv2v synth
    build that FAILED under -D<sim_define> should retry the SAME closure under
    -D<synth_define>.

    OBSERVABLE-BASED (v1.4.x, mirrors the lec_run slang-retry fix). The decision
    is NOT keyed on how the tool phrased its abort — that allow-list turned every
    reworded diagnostic (slang/yosys/sv2v rename theirs between releases) into a
    silent FALSE FAIL. It is keyed on:

      1. the OBSERVABLE: the build produced NO usable output (`produced_output`
         is False — the caller's netlist-exists / rc check), and
      2. the DESIGN PROPERTY: the closure actually branches on the sim/synth
         define, so flipping it can change what the frontend reads at all.

    Both are required. (2) is what BOUNDS the widened trigger: with no
    define-conditional arm the retry would re-read byte-identical text, so it is
    skipped — cannot help, cannot hurt. With no RTL text supplied the property is
    unobservable and the answer is fail-safe NO (never retry on nothing).

    §4.05 — this widens what is RETRIED, never what PASSES. The caller keeps the
    retry's own rc/artifact check, so a closure that also fails under
    -D<synth_define> keeps the honest FAIL; and because the retry only runs when
    NO output exists, there is no result to shop for. chip-AGNOSTIC: preprocessor
    grammar + the standard SIMULATION/SYNTHESIS define names, no chip/vendor/file
    literal.

    Returns (should_retry, reason)."""
    if produced_output:
        # Anti-verdict-shopping: a real result already exists — never re-read it
        # with another define hoping for a better answer.
        return False, (
            f"synth already produced a netlist — no retry (a real result must "
            f"not be re-read under -D{synth_define})")
    arms, arm_evidence = define_conditional_arms_present(
        rtl_text_blob, sim_define, synth_define)
    if not arms:
        return False, (
            f"synth produced no netlist, but {arm_evidence}; a -D{synth_define} "
            f"retry would re-read byte-identical source — keep the honest FAIL")
    _, construct_evidence = simonly_constructs_in_source(rtl_text_blob)
    note = _wording_note(synth_err, SYNTH_FRONTEND_SIMONLY_CONSTRUCT_SIGNATURES)
    return True, (
        f"synth produced NO netlist under -D{sim_define} and the closure "
        f"branches on the define set ({arm_evidence}; {construct_evidence}), so "
        f"the -D{synth_define} arm is a DIFFERENT — synthesizable — source; "
        f"retrying under -D{synth_define} [{note}]")


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
# v1.4.x — A CAPABILITY PROBE SHOULD PROBE. The old probe ran `read_slang` with
# NO input and inspected the resulting error text. That asks "how did yosys
# phrase its complaint?" when the question is "can this image read SystemVerilog
# with read_slang?". The probe now TRIES THE CAPABILITY on a tiny synthetic
# fixture and observes whether a design came out the other side.
_SLANG_PROBE_MODULE: str = "_vibeic_slang_probe_m"
SLANG_PROBE_CMD: str = (
    "export PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH && "
    f"printf 'module {_SLANG_PROBE_MODULE}; endmodule\\n' "
    f"> /tmp/{_SLANG_PROBE_MODULE}.sv && "
    f"yosys -p 'read_slang /tmp/{_SLANG_PROBE_MODULE}.sv; stat'"
)


# The OBSERVABLE that a yosys command EXISTS: yosys numbers and announces each
# pass it actually dispatches ("1. Executing SLANG frontend."). An UNKNOWN
# command prints the `-- Running command ... --` banner but NEVER reaches a
# numbered pass. So "did a pass execute?" is positive CAPABILITY evidence, not
# an error phrase — it holds whatever yosys calls its not-found diagnostic.
_YOSYS_PASS_EXECUTED_RE = re.compile(r"^\s*\d+\.\s+Executing\s", re.MULTILINE)


def read_slang_is_builtin(probe_output: str) -> bool:
    """True iff `read_slang` is available WITHOUT `plugin -i slang`.

    Decided from the output of :data:`SLANG_PROBE_CMD`.

    OBSERVABLE-FIRST (v1.4.x): the primary signal is whether yosys actually
    DISPATCHED the command — i.e. a numbered pass executed. That is a direct
    observation of the capability rather than a probe of how yosys phrases a
    not-found error. The historical "No such command" test is retained as a
    secondary confirmation for the loadable-`.so` image, and the fork-safe
    default (BUILT-IN) still applies to an inconclusive or empty probe: on the
    shipped `vibeic-eda` image a wrongly-EMITTED `plugin -i slang` ABORTS the
    whole `-p` script (the bug this fixes), whereas a wrongly-SKIPPED load
    merely triggers the caller's sv2v / read_verilog fallback — recoverable."""
    out = probe_output or ""
    # STRONGEST evidence (v1.4.x): the probe FIXTURE came out the other side.
    # `stat` reports the elaborated design, so seeing the probe module's own
    # name means read_slang genuinely parsed and elaborated SystemVerilog — the
    # capability itself was exercised, not merely a diagnostic inspected.
    if _SLANG_PROBE_MODULE in out:
        return True
    # Fallback for a probe that could not write its fixture (read-only /tmp,
    # older SLANG_PROBE_CMD in a cached transcript): yosys numbers every pass it
    # dispatches, so a numbered pass is still positive capability evidence.
    if _YOSYS_PASS_EXECUTED_RE.search(out):
        return True
    return "No such command: read_slang" not in out


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


# ---------------------------------------------------------------------------
# STAGED-MACRO-AWARE sim-define selection (chip-AGNOSTIC)
#
# Every phase-3 synth read path historically forced ``-DSIMULATION`` so that a
# vendor primitive with an FPGA-only implementation (an Altera `altsyncram`, a
# Xilinx `BRAM`, …) took its behavioural `` `ifdef SIMULATION `` arm instead of
# a primitive that does not exist on an ASIC target. That intent is real and is
# PRESERVED below.
#
# The consequence that was NOT intended: when the project has STAGED A REAL
# VENDOR MACRO for that same cell (`input/pdk_local/<vendor>/` — Liberty + LEF
# + GDS + Verilog model), the forced define ALSO makes the macro-instantiation
# arm unreachable. Synthesis then silently takes the behavioural arm and maps a
# storage macro to flip-flops. Measured on a 128x8 OTP: 1024 `$_DFFE_*` enable
# flops in place of one macro instance — i.e. a one-time-programmable memory
# that is VOLATILE in silicon and loses its contents at power-off.
#
# The decision below is keyed on the GENERAL property "is a real macro staged
# for a cell this RTL can only instantiate with the define ABSENT?" — not on
# OTP, not on any vendor, not on any chip. Any vendor macro with a behavioural
# fallback has this shape.
#
# HONESTY / §4.05. This never widens PASS:
#   * No macro staged  -> the sim define is KEPT and the emitted command is
#     BYTE-IDENTICAL to the historical flow. The behavioural path that the
#     define was added for is untouched.
#   * Macro staged but NOT instantiable (no staged cell appears in the RTL, or
#     it has no Liberty/LEF blackbox source for synth to bind) -> the sim
#     define is KEPT (safe, historical) and the verdict is reported at ERROR
#     severity. A silent fall-through to behavioural is exactly how the
#     volatile-OTP defect shipped, so the one thing this must never do is stay
#     quiet about it.
# ---------------------------------------------------------------------------

def _strip_comments(text: str) -> str:
    """Drop /* */ and // comments so a commented-out instantiation (or a
    cell name merely mentioned in a comment) is never read as a use."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _strip_string_literals(text: str) -> str:
    """Blank "..." so a cell name inside a string is not read as a use."""
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


# Cell/module NAME declarations in each staged-macro artifact kind. Structural
# vocabulary of the file formats themselves — no vendor/chip literal.
#
# Deliberately NOT anchored to the start of a line. Vendors ship compact and
# machine-generated Liberty/LEF where the declaration does not begin a line,
# and a missed declaration here degrades SILENTLY to the behavioural path —
# the exact failure this decision exists to prevent. A leading `\b` is enough
# to keep the near-miss keywords out: `endmodule`, `scaled_cell (`,
# `test_cell (` and `cell_leakage_power` all have a word character before the
# keyword, so no word boundary exists and none of them match.
_MACRO_DECL_RES: "dict[str, object]" = {
    ".v":   re.compile(r"\bmodule\s+([A-Za-z_]\w*)"),
    ".sv":  re.compile(r"\bmodule\s+([A-Za-z_]\w*)"),
    ".lib": re.compile(r"\bcell\s*\(\s*\"?([A-Za-z_]\w*)"),
    ".lef": re.compile(r"\bMACRO\s+([A-Za-z_]\w*)"),
}

# A staged cell is BINDABLE by the phase-3 synth read paths only through an
# artifact those paths actually read: the Liberty blackbox (`read_liberty -lib
# -setattr blackbox`) or a LEF outline. A macro shipping ONLY a `.v` behavioural
# model has nothing for synth to bind to, so dropping the define would trade a
# silent wrong netlist for a hard elaboration failure — report instead.
_BLACKBOX_SOURCE_EXTS = (".lib", ".lef")


def staged_macro_cells(
    staged_macro_files: Sequence[Union[str, Path]],
) -> "dict[str, set]":
    """Map every cell NAME declared by a staged macro artifact to the set of
    artifact extensions that declare it.

    Purely structural: reads `module` (Verilog model), `cell (` (Liberty) and
    `MACRO` (LEF) declarations. Unreadable / binary artifacts (a `.gds`) are
    skipped rather than raising — a staging probe must degrade to "nothing
    observed" instead of exploding the caller."""
    cells: "dict[str, set]" = {}
    for f in staged_macro_files or ():
        p = Path(f)
        rex = _MACRO_DECL_RES.get(p.suffix.lower())
        if rex is None:
            continue
        try:
            txt = p.read_text(errors="replace")[:_BLOB_SCAN_CAP_BYTES]
        except (OSError, ValueError):
            continue
        for name in rex.findall(_strip_comments(txt)):
            cells.setdefault(name, set()).add(p.suffix.lower())
    return cells


def _instantiated_cells(text: str, cells: "Sequence[str]") -> "set":
    """Cell names INSTANTIATED in `text` (`<Cell> <inst> (` or `<Cell> #(`).

    A bare mention (a comment, a string, a `module <Cell>` declaration of the
    macro itself) is not an instantiation and must not count."""
    body = _strip_string_literals(_strip_comments(text or ""))
    hit = set()
    for c in cells:
        # `(?!\w)` after the cell name stops a DIFFERENT identifier that merely
        # EXTENDS it (`<Cell>_inst (...)`) from being read as a use of <Cell>.
        pat = re.compile(
            r"(?<![\w.])" + re.escape(c)
            + r"(?!\w)\s*(?:#\s*\(|[A-Za-z_]\w*\s*\()")
        for m in pat.finditer(body):
            # `module <Cell> (` is the macro's own declaration, not a use.
            head = body[max(0, m.start() - 12):m.start()]
            if re.search(r"\bmodule\s*$", head):
                continue
            hit.add(c)
            break
    return hit


# Conditional-compilation directives. A symbol is consumed ONLY for the
# directives that take one, and ONLY on the SAME line ([ \t] never matches a
# newline). This is deliberately NOT the shared
# `sv_package_closure_check._annotate_conditionals` walker: that one matches
# ``^\s*`(ifdef|ifndef|elsif|else|endif)\b\s*(\w+)?`` where ``\s*`` crosses
# newlines, so on a bare `` `else `` the optional symbol group SWALLOWS the
# first identifier of the next line. On exactly the shape this decision has to
# read —
#       `else
#         <VendorMacro> u_inst ( ... );
# — the macro's cell name is eaten and the arm looks like it instantiates
# nothing, which would silently return the WRONG verdict here. (That gate
# audits include closures, where the effect is a different and much rarer
# false negative; it is left alone rather than widened into this change.)
_PP_DIRECTIVE_RE = re.compile(
    r"^[ \t]*`(?:(ifdef|ifndef|elsif)[ \t]+(\w+)|(else|endif)\b)", re.M)


def _reachable_text(text: str, defines: "set") -> str:
    """Text surviving `ifdef/`ifndef/`elsif/`else/`endif under `defines`.

    Unbalanced directives degrade gracefully (the stack never underflows)."""
    defines = set(defines or ())
    out: List[str] = []
    # stack frames: [taken_now, any_arm_taken_yet]
    stack: List[List[bool]] = []
    pos = 0
    for m in _PP_DIRECTIVE_RE.finditer(text or ""):
        if all(fr[0] for fr in stack):
            out.append(text[pos:m.start()])
        pos = m.end()
        kw = m.group(1) or m.group(3)
        sym = m.group(2) or ""
        if kw == "ifdef":
            taken = sym in defines
            stack.append([taken, taken])
        elif kw == "ifndef":
            taken = sym not in defines
            stack.append([taken, taken])
        elif kw == "elsif":
            if stack:
                fr = stack[-1]
                taken = (sym in defines) and not fr[1]
                fr[0] = taken
                fr[1] = fr[1] or taken
        elif kw == "else":
            if stack:
                fr = stack[-1]
                fr[0] = not fr[1]
                fr[1] = True
        elif kw == "endif":
            if stack:
                stack.pop()
    if all(fr[0] for fr in stack):
        out.append(text[pos:])
    return "\n".join(out)


def decide_macro_aware_sim_define(
    rtl_text_blob: str,
    staged_macro_files: "Sequence[Union[str, Path]] | None" = None,
    sim_define: str = "SIMULATION",
) -> "dict":
    """Decide whether the phase-3 synth read paths may force ``-D<sim_define>``.

    Answers ONE general question: *is a real vendor macro staged for a cell that
    this RTL can only instantiate with the define ABSENT?* If so the define is
    DROPPED so the macro arm is reachable and synthesis instantiates the real
    macro. Otherwise the define is KEPT and the emitted synth command is
    byte-identical to the historical flow.

    Returns a report dict (also the record written into the run's reports):

      define_sim   bool  - keep ``-D<sim_define>`` on the synth read paths
      verdict      str   - BEHAVIOURAL_NO_MACRO / MACRO_INSTANTIATED /
                           MACRO_ALREADY_REACHABLE / MACRO_STAGED_UNUSABLE
      severity     str   - INFO / WARNING / ERROR
      reason       str   - why this path was taken, in words
      staged_cells list  - every cell name the staged artifacts declare
      macro_cells  list  - staged cells this RTL instantiates behind the define
      unbindable   list  - staged cells with no Liberty/LEF blackbox source
    """
    staged = staged_macro_cells(staged_macro_files or ())
    names = sorted(staged)
    base = {"staged_cells": names, "macro_cells": [], "unbindable": []}

    if not names:
        return dict(base, define_sim=True, verdict="BEHAVIOURAL_NO_MACRO",
                    severity="INFO",
                    reason=(f"no vendor macro staged under input/pdk_local/ — "
                            f"keeping -D{sim_define} so the behavioural "
                            f"fallback arm fires (historical flow, unchanged)"))

    blob = rtl_text_blob or ""
    with_sim = _instantiated_cells(_reachable_text(blob, {sim_define}), names)
    without_sim = _instantiated_cells(_reachable_text(blob, set()), names)
    # Cells the forced define makes UNREACHABLE — the defect's signature.
    gated = sorted(without_sim - with_sim)
    bindable = [c for c in gated
                if staged.get(c, set()) & set(_BLACKBOX_SOURCE_EXTS)]
    unbindable = [c for c in gated if c not in bindable]

    if bindable:
        return dict(base, define_sim=False, verdict="MACRO_INSTANTIATED",
                    severity="INFO", macro_cells=bindable,
                    unbindable=unbindable,
                    reason=(
                        f"staged vendor macro(s) {bindable!r} are instantiated "
                        f"by this RTL ONLY when {sim_define} is UNDEFINED; "
                        f"forcing -D{sim_define} would make the macro arm "
                        f"unreachable and synthesise the behavioural fallback "
                        f"in its place (a storage macro mapped to flip-flops). "
                        f"DROPPING -D{sim_define} so the real macro is "
                        f"instantiated"))

    if unbindable:
        return dict(base, define_sim=True, verdict="MACRO_STAGED_UNUSABLE",
                    severity="ERROR", unbindable=unbindable,
                    reason=(
                        f"staged macro(s) {unbindable!r} are gated behind "
                        f"{sim_define} being UNDEFINED, but ship NO Liberty/LEF "
                        f"for synth to bind as a blackbox — synth cannot "
                        f"instantiate them. KEEPING -D{sim_define} (the "
                        f"behavioural arm) so the run still elaborates, but the "
                        f"result is a BEHAVIOURAL model of a cell that was "
                        f"staged as a real macro. Stage the macro Liberty/LEF "
                        f"or remove the macro from input/pdk_local/"))

    if with_sim:
        return dict(base, define_sim=True, verdict="MACRO_ALREADY_REACHABLE",
                    severity="INFO", macro_cells=sorted(with_sim),
                    reason=(
                        f"staged macro(s) {sorted(with_sim)!r} are instantiated "
                        f"regardless of {sim_define} — keeping -D{sim_define} "
                        f"(historical flow, unchanged)"))

    # Staged, but this RTL instantiates it under NEITHER define-world.
    branches, arm_evidence = define_conditional_arms_present(
        blob, sim_define, sim_define)
    if branches:
        return dict(base, define_sim=True, verdict="MACRO_STAGED_UNUSABLE",
                    severity="ERROR",
                    reason=(
                        f"macro(s) {names!r} are staged under input/pdk_local/ "
                        f"and this RTL DOES branch on {sim_define} "
                        f"({arm_evidence}), yet instantiates none of the staged "
                        f"cells under either define-world — the RTL's macro arm "
                        f"names a cell that was never staged (or the staged cell "
                        f"was never wired in). Synthesis will take the "
                        f"behavioural arm. KEEPING -D{sim_define}; reconcile the "
                        f"instance name with the staged macro"))
    return dict(base, define_sim=True, verdict="BEHAVIOURAL_NO_MACRO",
                severity="WARNING",
                reason=(
                    f"macro(s) {names!r} are staged under input/pdk_local/ but "
                    f"this RTL neither instantiates them nor branches on "
                    f"{sim_define} — nothing for the synth define to select "
                    f"(the macro is presumably integrated by a later backend "
                    f"step). Keeping -D{sim_define} (historical flow, "
                    f"unchanged)"))
