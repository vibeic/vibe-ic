#!/usr/bin/env python3
r"""deterministic_emit_chain.py — try every deterministic RTL emitter, in order.

THE PROGRAM HALF OF PROGRAM-FIRST, AS A CALLABLE.

The emitters existed and were good — `spec_artifact_registry` alone solves
125/156 of one open corpus deterministically — but reaching them meant either
running the whole runner or importing a benchmark's tier pipeline. So the same
chain got re-assembled in `verilogeval_tier_pipeline`, `verilogeval_human_tier_
pipeline`, `rtllm_tier_pipeline`, `cvdp_solve_pipeline` and `gates_atomic`, once
per benchmark, each with its own order and its own idea of what counts as a
solve. Four of those five also had the order WRONG: they demanded an
AI-authored file first and ran the program second, overwriting it.

One chain, one order, callable from anywhere:

    kind, rtl = try_emit(prompt_text, ifc_text, top)

`kind` names which emitter fired, or None when none did — and None is a real
answer, not a failure. It is the handover point where the runner WAIVEs to the
`spec-to-rtl` AI backup, which is the designed dual track.

THE CONTRACT IS EXACT-OR-NOTHING. An emitter returns RTL only when the prompt is
parse-complete for the shape it recognises. It never returns a guess: a guess
dressed as a program result is worse than a waive, because the waive is honest
about needing judgement and the guess is not.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _registry(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """The canonical recognisers. Broad coverage, mutual-exclusion checked."""
    try:
        import spec_artifact_registry as _reg
    except ImportError:
        return None, None
    return _reg.generate(prompt, top)


def _supplemental(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """Shapes the registry deliberately does not recognise.

    Kept a separate module on purpose: these were added so that widening the
    registry's recognisers could not put its existing coverage at risk. Ordered
    AFTER the registry for the same reason.
    """
    try:
        import fsm_vector_rtl_emit as _fve
    except ImportError:
        return None, None
    return _fve.emit({"prompt": prompt, "ifc": ifc})


def _bridged_ports(prompt: str):
    """(ins, outs) for the emitters that take an interface, or None.

    NONE IS "COULD NOT LOOK", `([], [])` IS "LOOKED AND THERE ARE NO PORTS".
    Both used to be `([], [])`, and the two are not the same event. `([], [])`
    is the honest answer for prose that states no ports; it is a LIE when the
    bridge or the parser was unavailable, and it is not an inert lie, because
    `_general` passes the result straight into `general_synth` — so a prompt
    whose ports could not be read produced an emit built as though it had none.
    That emit is then a candidate the chain can ACCEPT. A `None` here makes the
    interface-taking emitters SKIP instead, which waives to the AI backup: the
    outcome the module's own contract calls the honest one.

    RTLLM-dialect prose states its ports as `Input ports:` / `Output ports:`
    description blocks, which `port_parser` (bullet/ANSI-header dialect) reads as
    nothing. `prose_port_block_read.bridge_prompt` prepends an equivalent bullet
    block and is a no-op on prose that has none, so this is safe on every dialect;
    measured, it turns 0 parsed ports into >0 on 46 of the 50 RTLLM designs.

    THE BRIDGED TEXT IS FOR PORT PARSING ONLY. `rtllm_tier_pipeline` also handed
    the bridged text to `spec_artifact_registry.generate`; on today's registry
    that is a REGRESSION, not a recovery — the registry fires on 40/50 RTLLM
    designs from the raw prose and on only 26/50 from the bridged prose, because
    its recognisers have since absorbed the RTLLM dialect directly and the
    prepended bullet block breaks their anchors. So the registry keeps the raw
    prompt, and only the interface-taking emitters see the bridge.
    """
    try:
        import prose_port_block_read as _bridge          # noqa: PLC0415
        import port_parser as _pp                        # noqa: PLC0415
    except ImportError:
        return None
    try:
        ins, outs = _pp.parse_ports(_bridge.bridge_prompt(prompt))
    except Exception:                                    # noqa: BLE001
        return None
    return ins or [], outs or []


def _moore_arrow(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """Moore FSM stated as a complete arrow transition diagram.

    Exact-envelope: SKIPs unless every transition of a single-1-bit-input /
    single-1-bit-Moore-output machine is present.
    """
    try:
        import moore_arrow_fsm_synth as _ma              # noqa: PLC0415
    except ImportError:
        return None, None
    return None, _ma.synth(prompt, top)


def _dff_primitive(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """The bare single-bit D-FF (optionally active-high sync reset-to-0).

    Exact-envelope: SKIPs on async reset, non-zero reset value, enables, or any
    FSM/combinational cue.
    """
    try:
        import dff_primitive_synth as _dp                # noqa: PLC0415
    except ImportError:
        return None, None
    return None, _dp.synth(prompt, top)


def _arith_ext(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """Ripple/carry adders stated as prose + an interface (RTLLM dialect).

    Takes the RAW prompt for its body semantics and the BRIDGED ports for its
    interface — the split `rtllm_tier_pipeline` used.
    """
    try:
        import arith_ext_synth as _ax                    # noqa: PLC0415
    except ImportError:
        return None, None
    bridged = _bridged_ports(prompt)
    if bridged is None:                 # could not read the ports: SKIP, never
        return None, None               # synthesise an interface from silence
    ins, outs = bridged
    if not (ins and outs):
        return None, None
    return None, _ax.synth(prompt, ins, outs, top)


def _general(prompt: str, ifc: str, top: str) -> Tuple[Optional[str], Optional[str]]:
    """The structural bank: comparator / subtractor / BCD adder / multiplier /
    divider / up-down + Johnson counters / right + barrel shifters / edge +
    pulse detectors / pipelined adder.

    LAST IN THE CHAIN, and the ordering is measured rather than assumed.
    `rtllm_tier_pipeline` ran this BEFORE the registry ("narrower forms first").
    On today's registry that ordering is wrong: this bank fires on Prob085_shift4
    and Prob115_shift18 with an emit that FAILS the official testbench, while the
    registry's `shift_register` emit passes both. Narrow-first is only safe when
    a verifier decides; order decides when one is absent, and after-the-registry
    is the order that cannot lose ground.
    """
    try:
        import general_synth as _gs                      # noqa: PLC0415
    except ImportError:
        return None, None
    bridged = _bridged_ports(prompt)
    if bridged is None:                 # see `_bridged_ports`: an unread
        return None, None               # interface is not an empty one
    ins, outs = bridged
    return None, _gs.synth(prompt, ins, outs, top)


# ORDER IS THE CONTRACT. Broadest-and-most-checked first; the supplemental
# emitters are the fallback for what it declines. A caller that wants a
# different order is asking for a different chain, not for a parameter.
#
# The order is MEASURED, not asserted. Registry-first is the invariant
# `verilogeval_human_tier_pipeline` protected by name ("so the existing 125
# verified Tier1 are NEVER perturbed") and it still holds: on VerilogEval,
# `general_synth` fires on two problems the registry already solves and its emit
# FAILS the official test on both, so promoting it ahead of the registry would
# cost two solves. Everything below the registry is a fallback for prompts the
# registry declines, and none of them is measured to shadow a registry hit.
EMITTERS: List[Tuple[str, Callable[..., Tuple[Optional[str], Optional[str]]]]] = [
    ("spec_artifact_registry", _registry),
    ("fsm_vector_rtl_emit", _supplemental),
    # Exact-envelope solvers next: each SKIPs on any deviation from one stated
    # shape, so neither can shadow a registry hit, and both are measured to fire
    # only where they verify (Prob031_dff, Prob136_m2014_q6).
    ("moore_arrow_fsm_synth", _moore_arrow),
    ("dff_primitive_synth", _dff_primitive),
    # Then the interface-taking prose solvers, narrowest cue first.
    ("arith_ext_synth", _arith_ext),
    ("general_synth", _general),
]






def try_emit_ex(prompt_text: str, ifc_text: str = "", top: str = "TopModule",
                verify: Optional[Callable[[str], bool]] = None,
                check: bool = True):
    """(kind, rtl, rejected) — the first ACCEPTED emit, plus what was refused.

    `rejected` is [(emitter_name, [reason, ...])] for every emitter that produced
    RTL the chain would not stand behind. It is the diagnostic half: a run that
    waives to the AI backup after three emitters were refused is a very different
    event from one where no emitter recognised the prompt at all, and a 2-tuple
    cannot tell those apart. Reporting both as a bare handover hides the one that
    says a deterministic emitter is WRONG.
    """
    rejected: List[Tuple[str, List[str]]] = []
    if not (prompt_text or "").strip():
        return None, None, rejected
    for name, fn in EMITTERS:
        try:
            kind, rtl = fn(prompt_text, ifc_text, top)
        except Exception as exc:                       # noqa: BLE001
            # An emitter that raises must not take the chain down; the next one
            # and ultimately the AI backup are the designed fallbacks. But a
            # BARE `continue` made "this emitter crashed" and "this emitter
            # declined" the same observable, so a chain with three broken
            # emitters produced the same waive as a chain that simply did not
            # recognise the prompt — the distinction `rejected` exists to carry.
            rejected.append((name, [f"emitter raised "
                                    f"({type(exc).__name__}): {exc}"]))
            continue
        if not rtl:
            continue
        why = _refusals(prompt_text, rtl, verify, check)
        if why:
            rejected.append((kind or name, why))
            continue
        return (kind or name), rtl, rejected
    return None, None, rejected


def try_emit(prompt_text: str, ifc_text: str = "",
             top: str = "TopModule",
             verify: Optional[Callable[[str], bool]] = None,
             check: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """(kind, rtl) of the first emitter whose emit is ACCEPTED, or (None, None).

    (None, None) means "no program produced an emit this chain will stand
    behind" — hand to the AI backup.

    FIRING IS NOT ACCEPTING. Both deleted tier pipelines drew that line and it is
    the whole reason they could report a number: `verilogeval_human_tier_pipeline`
    ran the registry, VERIFIED the emit against the official testbench, and moved
    on to the next emitter when it failed; `rtllm_tier_pipeline` verified in
    `tier1_emit_verified` and refused to call an unverified emit a solve. Taking
    the first thing that came back was never the rule.

    `verify` is that step, as a callable, because the chain has no benchmark in
    it and must not grow one: the caller owns the oracle (compile+run against the
    real testbench) and passes `rtl -> bool`. An emit that fails it is DISCARDED
    and the chain continues, so a wrong early emit no longer buries a right later
    one.

    Without an oracle the chain cannot say whether an emit is RIGHT, and it says
    so by accepting any emit the conformance gate does not refuse — the runner
    has no testbench at rtl_gen time. That is the honest degradation, and it is
    not free: measured on the RTLLM designs, no-oracle acceptance ships 4 emits
    that do not pass, and on VerilogEval-v2 it ships `Prob099_m2014_q6c` — RTL
    that does not even COMPILE against the official test. The conformance gate
    does not catch those; only an oracle does.

    Use `try_emit_ex` when the caller needs to REPORT whether a waive was
    "nothing recognised it" or "what it emitted was refused".
    """
    kind, rtl, _rejected = try_emit_ex(prompt_text, ifc_text, top, verify, check)
    return kind, rtl


# Direction / net-type keywords that can precede an ANSI port name inside the
# module-header parens — never themselves a port name.
_PORT_DECL_KW = frozenset({
    "input", "output", "inout", "wire", "reg", "logic", "signed", "unsigned",
})


def _duplicate_header_port_names(rtl: str) -> List[str]:
    """Port names the module header declares MORE THAN ONCE, [] if none.

    A legal Verilog module header cannot repeat a port name, so a duplicate is a
    pure-syntax invariant violation with zero false positives — it happens when
    an upstream port list was doubled (a spec restating its interface) and a
    renderer emitted it verbatim. iverilog rejects it (`'x' has already been
    declared`), but the runner has no testbench at rtl_gen time, so without this
    rule the chain would stand behind an emit no compiler will ever accept.

    Per comma-separated header item the port name is the LAST identifier after
    ranges are stripped (`input wire [7:0] a` -> a; non-ANSI `a` -> a).
    """
    txt = re.sub(r"//[^\n]*", "", rtl or "")
    txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S)
    m = re.search(r"\bmodule\s+\w+\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;",
                  txt, re.S)
    if not m:
        return []
    names: List[str] = []
    for piece in m.group(1).split(","):
        piece = re.sub(r"\[[^\]]*\]", " ", piece)
        idents = [t for t in re.findall(r"[A-Za-z_]\w*", piece)
                  if t.lower() not in _PORT_DECL_KW]
        if idents:
            names.append(idents[-1])
    seen, dups = set(), []
    for n in names:
        if n in seen and n not in dups:
            dups.append(n)
        seen.add(n)
    return dups


def _refusals(prompt_text: str, rtl: str,
              verify: Optional[Callable[[str], bool]],
              check: bool = True) -> List[str]:
    """Why an emit that FIRED may NOT be returned as the chain's answer, [] if it
    may. Two rules, in the order both deleted pipelines applied them:

      1. `verify` — the caller's oracle. `verilogeval_human_tier_pipeline`
         (tier1_verify) and `rtllm_tier_pipeline` (tier1_emit_verified) both
         compiled and ran the emit against the real testbench before counting
         it. No oracle means rule 1 ABSTAINS — it does not pass.
      2. the conformance gate — an emit the real gate would BLOCK can never
         reach a host testbench, so it is not a solve even when it simulates.
         Ordered after rule 1 because a gate rule firing on RTL already known
         wrong says nothing extra.

    RULE 2 RUNS EVEN WITH NO ORACLE, which is the one place the two deleted
    pipelines had no opinion: they always had a testbench. The runner never does,
    and skipping the gate there would leave that path with no check at all — the
    state this module shipped in, where `emit_would_be_blocked` stated "a
    deterministic emit is only genuinely a solve when THIS returns []" and
    nothing on any production path called it. Measured, the gate refuses 0 of 262
    live emits on both VerilogEval corpora, so wiring it buys no accuracy today;
    it costs ~0.07 s per emit and makes the claim the docstring already made
    true. The accuracy is in rule 1.

    RULE 2 CAN ALSO FAIL TO RUN, AND THAT IS A THIRD OUTCOME. It used to be
    folded into the second: `emit_would_be_blocked` returned `[]` on an absent
    checker, an unwritten report, an unparseable report and a timeout alike, so
    "the gate examined this RTL and refused nothing" and "nothing examined this
    RTL" arrived here as the same empty list — and this function reads an empty
    list as ACCEPT. The failure direction was therefore PERMISSIVE: the one
    state in which the chain knows least was the state in which it stood behind
    the emit hardest. A NOT-MEASURED look is now a refusal, so the emit is
    discarded and the chain moves to the next emitter exactly as it does for a
    gate-blocked one, and `try_emit_ex` reports the reason instead of a bare
    handover.
    """
    # Rule 0 — a SYNTAX invariant, ahead of both rules and independent of
    # `check`: a module header that repeats a port name is not legal Verilog,
    # so no oracle or gate verdict can rehabilitate the emit. Costs one regex.
    dups = _duplicate_header_port_names(rtl)
    if dups:
        return ["duplicate-header-port: the module header declares "
                + ", ".join(sorted(dups))
                + " more than once — not legal Verilog, no compiler accepts it"]
    if verify is not None:
        try:
            if not verify(rtl):
                return ["verify: candidate failed the caller's oracle"]
        except Exception as exc:                       # noqa: BLE001
            return [f"verify raised ({type(exc).__name__}): treated as a failure"]
    if not check:
        return []
    look = emit_block_report(prompt_text, rtl)
    if not look.measured:
        return [f"{NOT_MEASURED}: {look.why_not} — an emit that nothing "
                f"examined is not an emit this chain will stand behind"]
    return list(look.rules)


NOT_MEASURED = "conformance-not-measured"
"""The marker a NOT-MEASURED look carries. NEVER a conformance rule name.

It has to be distinguishable from both of the other two answers and it must not
be mistakable for one. A rule name would be a FABRICATED FINDING — a claim about
the RTL that no checker made — which is the failure `#1437` names as worse than
the traceback it replaced ("turning an absent compiler into a finding about the
design"). This marker makes the opposite claim: that nothing was examined.
"""


class ConformanceLook(NamedTuple):
    """What a look at the conformance gate ACTUALLY produced. Three states.

    `measured` is the load-bearing field. `rules` is meaningful only when it is
    True; `why_not` is populated only when it is False. Reading `rules` without
    reading `measured` reproduces the exact defect this type exists to end —
    an empty tuple then means "clean" whether or not anything looked.
    """
    measured: bool
    rules: Tuple[str, ...]
    why_not: str


def emit_block_report(prompt_text: str, rtl: str,
                      timeout: int = 60) -> ConformanceLook:
    """MEASURED + the rules tripped, or NOT MEASURED + why nothing was examined.

    THE PRIMITIVE, AND WHY IT REPLACED A BARE LIST. Every error path in this
    function used to `return []`, and `[]` is also the answer for RTL the gate
    read and cleared. So an absent `spec_conformance_check`, a checker that
    wrote no report, a report that would not parse, and a spawn that timed out
    were all INDISTINGUISHABLE from a clean bill of health — and indistinguishable
    in the PERMISSIVE direction, because `_refusals` accepts an empty list.
    "The checker broke" and "the tree is clean" were one observable.

    That is the same defect the landing gate states as a rule (rc=2 "could not
    measure" must never reach the stamp as "I measured and it was clean") and
    the same one `_gate_dispatch.sh` encodes as a distinct NOT_CHECKED state
    rather than folding it into PASS. This module was on the wrong side of both.

    WHAT THE OLD BEHAVIOUR WAS PROTECTING, AND HOW THAT IS KEPT. The docstring's
    stated reason was "a missing checker must never manufacture a block and
    demote a real solve" — do not invent a FINDING ABOUT THE DESIGN out of a
    tool failure. That invariant is kept exactly: this never puts a rule name in
    `rules` that no checker produced. What it stops doing is inventing a CLEAN
    BILL out of the same tool failure, which was the other half of the same
    mistake and the dangerous half, because acceptance is the permissive
    direction and a demoted solve is merely a waive to the AI backup.

    A caller that genuinely wants the old fail-open behaviour still has one
    line for it — `look.measured or not look.rules` — but it now has to write
    that line, and a reader can see it.
    """
    if not (rtl or "").strip():
        return ConformanceLook(False, (), "no RTL was supplied to examine")
    if not (prompt_text or "").strip():
        return ConformanceLook(
            False, (), "no spec text was supplied, so no rule could be applied")
    try:
        from spec_conformance_check import (                # noqa: PLC0415
            EMIT_BLOCKING_CONFORMANCE_RULES as _BLOCK)
    except Exception as exc:                                # noqa: BLE001
        return ConformanceLook(
            False, (), f"spec_conformance_check is not importable "
                       f"({type(exc).__name__}): {exc}")
    import json as _json                                    # noqa: PLC0415
    import subprocess as _sp                                # noqa: PLC0415
    import tempfile as _tf                                  # noqa: PLC0415
    with _tf.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "TopModule.sv").write_text(rtl)
        spec = tdp / "spec.txt"
        spec.write_text(prompt_text)
        outj = tdp / "conf.json"
        try:
            # ADVISORY spawn: the checker's verdict is read from `--json`, never
            # from its exit code — a rule that FIRED and a checker that DIED
            # both leave a non-zero status, so the status cannot separate them.
            # The report can: it exists and parses, or it does not.
            proc = _sp.run(
                [sys.executable, str(_HERE / "spec_conformance_check.py"),
                 "--rtl-dir", str(tdp), "--spec", str(spec),
                 "--top", "TopModule", "--json", str(outj)],
                capture_output=True, text=True, timeout=timeout)
        except Exception as exc:                            # noqa: BLE001
            # TimeoutExpired, FileNotFoundError, OSError — the checker never
            # reached a verdict, which is not a verdict of "clean".
            return ConformanceLook(
                False, (), f"the conformance checker could not be run "
                           f"({type(exc).__name__}): {exc}")
        if not outj.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            return ConformanceLook(
                False, (), f"the conformance checker wrote no --json report "
                           f"(rc={proc.returncode})"
                           + (f": {tail[-1][:160]}" if tail else ""))
        try:
            # The checker writes a LIST of finding dicts. (Read off the working
            # implementation rather than guessed — the guessed shape,
            # `data.get("findings")`, raised AttributeError on the first call.)
            findings = _json.loads(outj.read_text(errors="replace"))
        except Exception as exc:                            # noqa: BLE001
            return ConformanceLook(
                False, (), f"the conformance report did not parse "
                           f"({type(exc).__name__}): {exc}")
    if not isinstance(findings, list):
        return ConformanceLook(
            False, (), f"the conformance report is a {type(findings).__name__}, "
                       f"not the list of findings this reads")
    return ConformanceLook(True, tuple(sorted(
        {f.get("rule") for f in findings
         if isinstance(f, dict) and f.get("rule") in _BLOCK})), "")


def emit_would_be_blocked(prompt_text: str, rtl: str,
                          timeout: int = 60) -> List[str]:
    """The EMIT-BLOCKING conformance rules this RTL trips, [] if it is clean.

    THE PARITY THAT KEEPS A DETERMINISTIC EMIT HONEST. An emit can compile,
    simulate and still be wrong in a way the real gate catches: answer a
    "logical right shifter" spec with a pure rotate and iverilog is perfectly
    happy. Counting that as program-solved reports a capability the blind run
    does not have — the gate would refuse to emit it.

    So a deterministic emit is only genuinely a solve when THIS returns []. The
    rule set is `spec_conformance_check.EMIT_BLOCKING_CONFORMANCE_RULES`, the
    same one the gate consults, so the two cannot drift.

    Was duplicated in `verilogeval_tier_pipeline` and
    `verilogeval_human_tier_pipeline` — two copies of a check with no benchmark
    content, reachable only by importing a benchmark's pipeline. It takes prompt
    TEXT rather than a problem object so nothing about it is dataset-shaped.

    ON A FAILURE TO LOOK IT RETURNS A NOT-MEASURED MARKER, NOT `[]`. `[]` is
    reserved for "the gate ran and refused nothing", which is what the sentence
    above promises a caller. Ask `emit_block_report` when you want the three
    states apart without string-matching; this shape exists for the callers and
    tests that ask "which rules?", and for them a NOT-MEASURED entry is the
    honest answer to a question nothing answered. The marker is `NOT_MEASURED`
    and is never a conformance rule name.
    """
    look = emit_block_report(prompt_text, rtl, timeout=timeout)
    if not look.measured:
        return [f"{NOT_MEASURED}: {look.why_not}"]
    return list(look.rules)


def which_emitters() -> List[str]:
    """The chain, in order. For tests that pin the order rather than assume it."""
    return [n for n, _ in EMITTERS]


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Run the deterministic emit chain on a prompt.")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--ifc-file", default=None)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    prompt = Path(a.prompt_file).read_text(errors="replace")
    ifc = Path(a.ifc_file).read_text(errors="replace") if a.ifc_file else ""
    kind, rtl = try_emit(prompt, ifc, a.top)
    if not rtl:
        print("no deterministic emitter fired — this is a WAIVE to the AI backup")
        return 1
    print(f"fired: {kind}")
    if a.out:
        import _atomic_artefact as _atomic  # noqa: PLC0415
        _atomic.write_text(Path(a.out), rtl)
        print(f"wrote {a.out}")
    else:
        print(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
