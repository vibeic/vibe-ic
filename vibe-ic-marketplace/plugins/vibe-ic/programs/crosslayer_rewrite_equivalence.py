#!/usr/bin/env python3
"""crosslayer_rewrite_equivalence.py — REWRITE-FIDELITY gate for a cross-layer
PPA search (candidate RTL  ==  BASELINE RTL).

WHY THIS EXISTS — a measured hole, not a hypothetical one
---------------------------------------------------------
A cross-layer PPA search lets an agent REWRITE the design (pipelining,
resource sharing, FSM encoding, arithmetic architecture, module hierarchy) to
win a PPA objective.  The flow's step 13 is
`Equivalence check (RTL == post-DFT netlist)`, and it is the check the search
would naturally be gated on.  It cannot serve that role, and this is MEASURED,
not argued:

    Three arms were built from one published baseline RTL, differing in a
    single line -- the carry-save majority term of a serial multiplier:

        base       (m & s) | (m & c) | (s & c)     the baseline
        cand_bad   (m & s)           | (s & c)     ONE TERM DROPPED
        cand_good  (m & (s | c))     | (s & c)     Boolean-identical

    Synthesised with one recipe, `cand_bad` is 6.12% SMALLER than the
    baseline (2419.82 um2 vs 2577.47 um2) -- it WINS the area objective
    because it computes a different function.  Step 13 (`lec_run.py` +
    `lec_equivalence_check.py`) returns exit 0 -- PASS, 66/66 points proven --
    on ALL THREE arms.

Step 13 is not defective.  It answers "did synthesis and DFT preserve THIS
RTL's semantics?", and for a rewritten candidate the answer is legitimately
yes.  It never compares the candidate to the design the specification
describes, so it cannot reject a candidate that is a DIFFERENT CHIP.

This program supplies the missing relation, and only that relation:

    step 13                    candidate RTL  ==  candidate post-DFT netlist
    crosslayer_rewrite_equiv   candidate RTL  ==  BASELINE RTL          <-- here

Both are required for a search that rewrites RTL.  Neither replaces the other,
and nothing here weakens, narrows or excludes anything step 13 checks.

THE EQUIVALENCE RELATION, AND WHY LATENCY IS A DECLARED INPUT
-------------------------------------------------------------
Default mode is `cycle_exact`: for every cycle and every output port, the
candidate must produce what the baseline produces.  That admits the levers
that do not move the port timing -- resource sharing, arithmetic architecture,
FSM re-encoding, hierarchy changes, synthesis strategy -- and refuses anything
that changes observable behaviour.

Pipelining does not preserve cycle-exactness: it changes latency by
construction, so a cycle-exact miter refuses every pipelined candidate.  A
`latency_offset` mode therefore exists, comparing the candidate at cycle t+N
against the baseline at cycle t.  It is DECLARED, never inferred, and it is
REFUSED unless the caller passes the sentence in the design's own input
documents that leaves latency free (`--latency-free-evidence PATH:LINE`).
That guard is the whole point: an offset chosen to make a mismatch disappear
is a cheat, and an offset the specification authorises is a legitimate search
dimension.  A specification that PINS latency simply does not get this mode,
and pipelining is then not in the search space at all.

NOT_MEASURED IS NOT CLEAN
-------------------------
"the tool could not run" and "the tool ran and found nothing wrong" never
produce the same verdict here.  Every path that fails to compare something
reports its own status and exits NON-ZERO:

    rc 0  PASS              equivalent, >0 points compared, 0 non-equivalent,
                            0 unproven
    rc 1  FAIL              measured: the candidate is not the baseline
    rc 2  NOT_MEASURED      nothing was compared -- container absent, inputs
                            missing, frontend abort, vacuous miter, an
                            undeclared latency offset, a SAT engine that could
                            not decide.  BLOCKING, exactly like rc 1.

The Yosys recipe and the verdict parser are REUSED from `lec_run.py`
(`build_equiv_script`'s pass list, and `parse_equiv_output` verbatim), so this
gate inherits that module's anti-fabrication behaviour -- vacuous-miter
detection, induction non-convergence, frontend-abort classification -- rather
than growing a second, weaker copy of it.

Chip-AGNOSTIC and PDK-AGNOSTIC: no Liberty is read (both sides are RTL), no
design literal appears, and the top module is an argument.

CLI
    python3 crosslayer_rewrite_equivalence.py <project_dir> \
        --baseline-rtl-dir <dir>  --candidate-rtl-dir <dir> \
        --top <top_module> [--container <name>] \
        [--latency-offset N --latency-free-evidence PATH:LINE] \
        [--json reports/crosslayer_rewrite_equivalence.json]
    main(argv) -> int   0 PASS / 1 FAIL / 2 NOT_MEASURED
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _design_module_set import (  # noqa: E402 — vibe-ic#712 comment strip
    strip_comments as _strip_hdl_comments,
)
from lec_run import (  # noqa: E402 — the ONE mature equiv recipe + parser
    parse_equiv_output as _parse_equiv_output,
    run_yosys_equiv as _run_yosys_equiv,
    _container_available as _container_available,
    _resolve_gold_files as _resolve_rtl_files,
)
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082/#1470

PROGRAM = "crosslayer_rewrite_equivalence"

DEFAULT_CONTAINER = "vibeic-eda"
DEFAULT_JSON_REL = "reports/crosslayer_rewrite_equivalence.json"
DEFAULT_RPT_REL = "reports/crosslayer_rewrite_equivalence.rpt"
DEFAULT_TIMEOUT_S = 1800

STATUS_PASS = "PASS"
STATUS_FAIL = "NOT_EQUIVALENT"
STATUS_NOT_PROVEN = "NOT_PROVEN_EQUIVALENT"
STATUS_NOT_MEASURED = "NOT_MEASURED"

MODE_CYCLE_EXACT = "cycle_exact"
MODE_LATENCY_OFFSET = "latency_offset"

# `PATH:LINE` — the citation shape the search space emits and this gate demands
# before it will compare under a latency offset.
_EVIDENCE_RE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)$")

# One `module` declaration, captured with its port list. Deliberately the same
# shallow Verilog-2005/SV-subset shape lec_run's own port reader uses: a real
# elaboration happens in Yosys, this is only for building the delay wrapper.
_MODULE_RE = re.compile(
    r"\bmodule\s+(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\s*"
    r"(?:#\s*\((?P<params>.*?)\))?\s*\((?P<ports>.*?)\)\s*;",
    re.DOTALL)

_PORT_RE = re.compile(
    r"\b(?P<dir>input|output|inout)\b\s*(?:wire|reg|logic)?\s*"
    r"(?P<signed>signed\s+)?(?P<range>\[[^\]]*\]\s*)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_$]*)")


# ---------------------------------------------------------------------------
# pure helpers (the tests call these directly — no Docker, no filesystem)
# ---------------------------------------------------------------------------
def parse_evidence(text: Optional[str]) -> Optional[Dict[str, object]]:
    """`"docs/L2.md:64"` -> {"path": "docs/L2.md", "line": 64}; else None.

    A malformed citation is None, and None is refused by the caller. There is
    deliberately no "close enough" parse: the whole value of the evidence is
    that a reader can go and look at that line."""
    if not text:
        return None
    m = _EVIDENCE_RE.match(text.strip())
    if not m:
        return None
    return {"path": m.group("path"), "line": int(m.group("line"))}


def module_params(rtl_text: str, top: str) -> str:
    r"""The ANSI parameter header text of module `top` (`""` when it has none).

    The delay wrapper MUST carry it. A port declared `[size-1:0]` refers to the
    inner module's parameter, and a wrapper that copies the range text without
    the parameter is rejected by the frontend with `Non-constant range in
    declaration` — measured on a parameterised multiplier before this was
    added, where it turned the whole latency-offset mode into a silent
    0-points-compared NOT_MEASURED.

    COMMENTS ARE STRIPPED FIRST. `_MODULE_RE` matches `module\s+(\w+)`, and a
    commented-out or merely DESCRIBED module — `// module mul_pipelined(...)` in
    a header block, or a `/* ... */` note quoting an older header — mints a
    module that does not exist. The strip is applied to the value that REACHES
    the scan, not to a sibling."""
    rtl_text = _strip_hdl_comments(rtl_text)
    for m in _MODULE_RE.finditer(rtl_text):
        if m.group("name") == top:
            return (m.group("params") or "").strip()
    return ""


def param_names(params_txt: str) -> List[str]:
    """The parameter identifiers in an ANSI parameter header, in order."""
    return re.findall(
        r"\bparameter\b\s*(?:\w+\s+)?(?:signed\s+)?(?:\[[^\]]*\]\s*)?"
        r"([A-Za-z_][A-Za-z0-9_$]*)\s*=", params_txt or "")


def module_ports(rtl_text: str, top: str) -> List[Tuple[str, str, str]]:
    """`[(direction, range_or_empty, name), ...]` for module `top`.

    Handles both the ANSI header form (`module m(input wire [7:0] a, ...)`)
    and the non-ANSI form (`module m(a, b); input [7:0] a;`). Returns [] when
    the module is not found — the caller turns that into NOT_MEASURED, never
    into an empty-but-fine wrapper.

    COMMENTS ARE STRIPPED FIRST, for the same reason as `module_params`: a
    commented-out header would otherwise supply this function's port list, and
    the wrapper it builds is compared against the real design."""
    rtl_text = _strip_hdl_comments(rtl_text)
    for m in _MODULE_RE.finditer(rtl_text):
        if m.group("name") != top:
            continue
        ports_txt = m.group("ports")
        found = [(p.group("dir"), (p.group("range") or "").strip(),
                  p.group("name")) for p in _PORT_RE.finditer(ports_txt)]
        if found:
            return found
        # non-ANSI: the directions live in the body after the header
        body = rtl_text[m.end():]
        names = [n.strip() for n in ports_txt.split(",") if n.strip()]
        decls: Dict[str, Tuple[str, str]] = {}
        for p in _PORT_RE.finditer(body):
            decls.setdefault(p.group("name"),
                             (p.group("dir"), (p.group("range") or "").strip()))
        out = []
        for n in names:
            if n in decls:
                out.append((decls[n][0], decls[n][1], n))
        return out
    return []


def build_delay_wrapper(top: str, ports: List[Tuple[str, str, str]],
                        inner: str, wrapper: str, depth: int,
                        clk: str, params_txt: str = "",
                        reset: str = "", reset_active_low: bool = False) -> str:
    """Verilog for a wrapper that instantiates `inner` and delays EVERY output
    by `depth` clock edges.

    This is how the baseline is aligned to a pipelined candidate: the baseline
    answers at cycle t, the candidate at cycle t+N, so the baseline's outputs
    are pushed through an N-deep register chain and the two are then compared
    cycle-for-cycle by the SAME miter as the cycle-exact mode. Nothing is
    excluded from the comparison and no signal is masked — the alignment is the
    only change, and its N is a declared, cited input.

    EVERY output is delayed by the SAME depth. A per-port offset would let a
    caller realign one signal at a time until a mismatch disappeared, which is
    the cheat this whole gate exists to refuse.

    `depth == 0` builds a PASS-THROUGH wrapper that changes nothing electrically
    and exists only to give the candidate side the SAME `flatten` prefix the
    gold side acquires from its delay wrapper. Without it `equiv_make`, which
    matches wires BY NAME, sees `u_inner.s` on one side and `s` on the other and
    builds ONE key point (the output port) instead of one per state bit — and a
    32-bit sequential miter reduced to a single point is not decomposable, so
    induction runs to the wall clock and the candidate lands NOT_PROVEN. MEASURED
    on a +1-latency multiplier: 1 compared point, 895s, no verdict. This is the
    same prefix-matching trick `lec_run.build_scan_wrappers` uses for exactly the
    same reason on the scan path.

    `reset` is not decoration. A pipelined candidate FLUSHES its extra stages
    when the design resets, so an alignment chain that does not reset diverges
    from it for exactly `depth` cycles after every reset — and that divergence
    is real, and the miter correctly refutes on it. MEASURED: a +1-latency
    rewrite of a synchronous-reset multiplier, aligned by an unreset 1-deep
    chain, produced a counterexample at the reset edge and nowhere else. So the
    reset port is a DECLARED input; when it is not given, the chain is
    reset-less and a design that flushes on reset will (correctly, and
    conservatively) be refused."""
    outs = [(rng, name) for d, rng, name in ports if d == "output"]
    ins = [(d, rng, name) for d, rng, name in ports if d != "output"]

    def _rng(r: str) -> str:
        r = (r or "").strip()
        return f"{r} " if r else ""

    hdr = f"module {wrapper}"
    if params_txt:
        hdr += f" #({params_txt})"
    decl = ",\n".join(
        [f"    {d} wire {_rng(rng)}{name}" for d, rng, name in ins] +
        [f"    output wire {_rng(rng)}{name}" for rng, name in outs])
    body = [f"{hdr} (\n{decl}\n);"]
    for rng, name in outs:
        body.append(f"    wire {_rng(rng)}{name}__u;")
    pnames = param_names(params_txt)
    pmap = (" #(" + ", ".join(f".{n}({n})" for n in pnames) + ")") if pnames else ""
    conns = ", ".join(
        [f".{n}({n})" for _, _, n in ins] +
        [f".{n}({n}__u)" for _, n in outs])
    body.append(f"    {inner}{pmap} u_inner ({conns});")
    if depth == 0:
        for rng, name in outs:
            body.append(f"    assign {name} = {name}__u;")
        body.append("endmodule")
        return "\n".join(body) + "\n"
    for i in range(depth):
        for rng, name in outs:
            body.append(f"    reg {_rng(rng)}{name}__d{i};")
    body.append(f"    always @(posedge {clk}) begin")
    if reset:
        cond = f"!{reset}" if reset_active_low else reset
        body.append(f"        if ({cond}) begin")
        for i in range(depth):
            for _rng_, name in outs:
                body.append(f"            {name}__d{i} <= 0;")
        body.append("        end else begin")
        ind = "            "
    else:
        ind = "        "
    for i in range(depth):
        for _rng_, name in outs:
            src = f"{name}__u" if i == 0 else f"{name}__d{i - 1}"
            body.append(f"{ind}{name}__d{i} <= {src};")
    if reset:
        body.append("        end")
    body.append("    end")
    for rng, name in outs:
        body.append(f"    assign {name} = {name}__d{depth - 1};")
    body.append("endmodule")
    return "\n".join(body) + "\n"


def build_rewrite_equiv_script(baseline_files: List[str],
                               candidate_files: List[str],
                               top: str,
                               wrapper_v: str = "",
                               wrapper_top: str = "",
                               cand_wrapper_v: str = "",
                               cand_wrapper_top: str = "") -> str:
    """The RTL==RTL Yosys script.

    The pass list is PORTED from `lec_run.build_equiv_script` and each pass is
    there for a reason measured in that module, not for symmetry:

      prep -top      elaborate and pick the comparison top
      memory_map     legalize $mem/$mem_v2 to flops+decode so equiv_induct's
                     satgen can model a memory-bearing design; MUST precede
                     flatten (measured 0/8 vs 136/0 the other way round)
      flatten        equiv compares two flat cones; a hierarchical instance
                     aborts equiv_make
      async2sync     an async-reset FF has no SAT model; this converts the
                     async control into synchronous D-input logic. Applied
                     IDENTICALLY to both sides, so an equivalent design stays
                     equivalent and a real reset-behaviour difference still
                     surfaces as unproven
      opt_clean      drop the unused
      splitnets      per-bit ports so equiv_make can match points by name
      equiv_struct   SAT-FREE structural pre-reduction; it can only collapse
                     provably-identical structure, so it cannot launder a
                     mismatch into a proof
      equiv_simple / equiv_induct -seq 4/16/64 / equiv_status

    The two sides are read by the SAME frontend with the SAME passes, which is
    what makes the comparison symmetric: there is no transform applied to one
    side that could hide a difference on the other."""
    base_read = " ".join(shlex.quote(f) for f in baseline_files)
    cand_read = " ".join(shlex.quote(f) for f in candidate_files)
    gold_top = wrapper_top or top
    cand_top = cand_wrapper_top or top
    gold_extra = (f"read_verilog -sv {shlex.quote(wrapper_v)}\n"
                  if wrapper_v else "")
    cand_extra = (f"read_verilog -sv {shlex.quote(cand_wrapper_v)}\n"
                  if cand_wrapper_v else "")
    # The SAME normalisation on both sides. Asymmetry here is how a filter
    # stops discriminating, so there is exactly one string and it is used twice.
    common = ("memory_map\n"
              "flatten\n"
              "async2sync\n"
              "opt_clean\n"
              "splitnets -ports\n")
    return (
        f"# {PROGRAM} — candidate RTL == baseline RTL\n"
        f"read_verilog -sv {base_read}\n"
        f"{gold_extra}"
        f"prep -top {gold_top}\n"
        f"{common}"
        f"design -stash gold\n"
        f"read_verilog -sv {cand_read}\n"
        f"{cand_extra}"
        f"prep -top {cand_top}\n"
        f"{common}"
        f"design -stash gate\n"
        f"design -copy-from gold -as gold {gold_top}\n"
        f"design -copy-from gate -as gate {cand_top}\n"
        f"equiv_make gold gate equiv\n"
        f"hierarchy -top equiv\n"
        f"equiv_struct\n"
        f"equiv_simple\n"
        f"equiv_induct -seq 4\n"
        f"equiv_induct -seq 16\n"
        f"equiv_induct -seq 64\n"
        f"equiv_status\n"
    )


# Yosys `sat` verdict wording, measured against yosys 0.68+ in
# ghcr.io/vibeic/vibeic-eda:0.3.15 (NOT recalled — see the RESULT notes).
_SAT_MODEL_FOUND = re.compile(r"SAT proof finished\s*-\s*model found:\s*FAIL")
_SAT_NO_MODEL = re.compile(r"SAT proof finished\s*-\s*no model found:\s*SUCCESS")

# A refutation trace is only as good as its bound; this is the default depth of
# the bounded search and it is an argument, not a constant anybody has to guess.
DEFAULT_SAT_SEQ = 12


def build_refutation_script(baseline_files: List[str],
                            candidate_files: List[str],
                            top: str, seq: int,
                            wrapper_v: str = "",
                            wrapper_top: str = "",
                            cand_wrapper_v: str = "",
                            cand_wrapper_top: str = "") -> str:
    """The BOUNDED refutation script: a miter plus `sat -seq N`.

    Stage 1 (`build_rewrite_equiv_script`) is an UNBOUNDED induction proof, and
    when it leaves points unproven Yosys cannot say which of two very different
    things happened -- the designs differ, or the engine could not decide.
    `lec_run.build_report` records that limitation in its own comment: *"Yosys
    equiv_status does not emit a distinct proven-non-equivalent count; a genuine
    difference surfaces as `unproven`"*.

    This stage supplies the missing POSITIVE evidence. `sat -seq N
    -prove-asserts -verify` searches for a concrete N-cycle input trace that
    drives the two designs' outputs apart; a model found IS a difference, and no
    model found within N is honestly reported as such and never as a proof.

    `-set-init-zero` is LOAD-BEARING and was added from a measurement, not from
    caution: without it the initial register state is unconstrained, and the
    solver "refutes" a perfectly correct candidate by starting the two designs
    in different states. Zero-init is applied IDENTICALLY to both sides, so a
    model found is a real divergence from a COMMON start state. If that state
    were unreachable in the real system the consequence is an over-rejected
    candidate -- never an admitted bad one, which is the direction a filter is
    allowed to be wrong in."""
    base_read = " ".join(shlex.quote(f) for f in baseline_files)
    cand_read = " ".join(shlex.quote(f) for f in candidate_files)
    gold_top = wrapper_top or top
    cand_top = cand_wrapper_top or top
    gold_extra = (f"read_verilog -sv {shlex.quote(wrapper_v)}\n"
                  if wrapper_v else "")
    cand_extra = (f"read_verilog -sv {shlex.quote(cand_wrapper_v)}\n"
                  if cand_wrapper_v else "")
    common = ("memory_map\n"
              "flatten\n"
              "async2sync\n"
              "opt_clean\n")
    return (
        f"# {PROGRAM} — bounded refutation (sat -seq {seq})\n"
        f"read_verilog -sv {base_read}\n"
        f"{gold_extra}"
        f"prep -top {gold_top}\n"
        f"{common}"
        f"rename {gold_top} gold\n"
        f"design -stash gold\n"
        f"read_verilog -sv {cand_read}\n"
        f"{cand_extra}"
        f"prep -top {cand_top}\n"
        f"{common}"
        f"rename {cand_top} gate\n"
        f"design -stash gate\n"
        f"design -copy-from gold -as gold gold\n"
        f"design -copy-from gate -as gate gate\n"
        f"miter -equiv -flatten -make_assert -make_outputs gold gate miter\n"
        f"hierarchy -top miter\n"
        f"sat -seq {seq} -prove-asserts -set-init-zero "
        f"-show-inputs -show-outputs -verify miter\n"
    )


def parse_refutation(raw: str) -> Optional[bool]:
    """True = counterexample found, False = none within the bound, None = the
    run said neither, which is NOT evidence of anything."""
    if not raw:
        return None
    if _SAT_MODEL_FOUND.search(raw):
        return True
    if _SAT_NO_MODEL.search(raw):
        return False
    return None


def classify(parsed: Dict, refuted: Optional[bool] = None) -> Tuple[str, int, str]:
    """(status, rc, explanation) from `lec_run.parse_equiv_output`'s dict.

    `parse_equiv_output` reports `total` / `proven` / `unproven`; Yosys's
    equiv flow emits no separate proven-non-equivalent count (a real difference
    surfaces as an unproven point), which is exactly why `refuted` is passed in
    from the SECOND, bounded stage rather than scraped out of the first one's
    log. `refuted is None` means that stage produced no verdict, and it is then
    treated as no evidence at all.

    The four outcomes are kept apart on purpose. `total == 0` is the one that
    has bitten this repository repeatedly: a miter that built nothing looks
    identical to a proof if you only read the boolean."""
    total = parsed.get("total")
    proven = parsed.get("proven") or 0
    unproven = parsed.get("unproven") or 0
    total = int(total or 0)

    if total == 0 and proven == 0:
        return (STATUS_NOT_MEASURED, 2,
                "the miter compared ZERO points — nothing was measured, so "
                "this is not a clean result. Yosys built no $equiv cell "
                "(frontend abort, unresolved hierarchy, or a port mismatch "
                "between baseline and candidate).")
    if unproven > 0 and refuted is True:
        return (STATUS_FAIL, 1,
                f"{unproven} of {total} point(s) were left unproven by "
                f"induction, and the bounded miter then produced a CONCRETE "
                f"counterexample trace — the candidate is measurably a "
                f"different design from the baseline.")
    if unproven > 0:
        return (STATUS_NOT_PROVEN, 2,
                f"{unproven} of {total} compared point(s) are UNPROVEN and no "
                f"counterexample was produced — the engine neither proved nor "
                f"refuted them. Unproven is not proven; this candidate is NOT "
                f"admitted, and this is NOT a report that it is wrong.")
    if not parsed.get("equivalent"):
        return (STATUS_NOT_MEASURED, 2,
                f"{proven} point(s) proven with none left unproven, but Yosys "
                f"never reported equivalence. Refusing to read that as a proof.")
    return (STATUS_PASS, 0,
            f"all {proven}/{total} compared point(s) proven — the candidate is "
            f"cycle-for-cycle the baseline at every port.")


def build_report(parsed: Dict, *, top: str, mode: str, offset: int,
                 evidence: Optional[Dict[str, object]],
                 baseline_files: List[str], candidate_files: List[str],
                 status: str, rc: int, explanation: str,
                 elapsed: float, refuted: Optional[bool] = None,
                 sat_seq: int = DEFAULT_SAT_SEQ) -> Dict:
    return {
        "program": PROGRAM,
        "relation": "candidate_rtl == baseline_rtl",
        "not_the_same_check_as": (
            "flow step 13 (candidate RTL == candidate post-DFT netlist); "
            "step 13 passes on a rewritten candidate by construction and "
            "cannot reject one"),
        "top": top,
        "mode": mode,
        "latency_offset_cycles": offset,
        "latency_freedom_evidence": evidence,
        "status": status,
        "exit_code": rc,
        "equivalent": status == STATUS_PASS,
        "compared_points": int(parsed.get("total") or 0),
        "proven_points": int(parsed.get("proven") or 0),
        "unproven_points": int(parsed.get("unproven") or 0),
        "counterexample": status == STATUS_FAIL,
        "bounded_refutation": refuted,
        "bounded_refutation_depth": sat_seq,
        "explanation": explanation,
        "baseline_rtl_files": [Path(f).name for f in baseline_files],
        "candidate_rtl_files": [Path(f).name for f in candidate_files],
        "tool": "yosys equiv_make+equiv_struct+equiv_simple+equiv_induct",
        "elapsed_sec": round(elapsed, 2),
    }


def _not_measured(reason: str, *, top: str, mode: str, offset: int,
                  evidence, baseline_files, candidate_files) -> Dict:
    return build_report({}, top=top, mode=mode, offset=offset,
                        evidence=evidence,
                        baseline_files=baseline_files or [],
                        candidate_files=candidate_files or [],
                        status=STATUS_NOT_MEASURED, rc=2,
                        explanation=reason, elapsed=0.0)


def _write(project: Path, rel: str, payload: Dict) -> Path:
    out = project / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rewrite-fidelity gate: candidate RTL == baseline RTL.")
    ap.add_argument("project_dir")
    ap.add_argument("--baseline-rtl-dir", required=True)
    ap.add_argument("--candidate-rtl-dir", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--latency-offset", type=int, default=0,
                    help="Compare candidate(t+N) against baseline(t). "
                         "REQUIRES --latency-free-evidence.")
    ap.add_argument("--latency-free-evidence", default=None,
                    help="PATH:LINE of the sentence in the design's own input "
                         "documents that leaves latency unconstrained.")
    ap.add_argument("--clock", default="clk",
                    help="Clock port name used by the latency-offset wrapper.")
    ap.add_argument("--reset", default="",
                    help="Reset port name. The latency-offset alignment chain "
                         "resets with the design; without this a candidate "
                         "that flushes its pipeline on reset is (correctly, "
                         "and conservatively) refused.")
    ap.add_argument("--reset-active-low", action="store_true",
                    help="The --reset port is active low.")
    ap.add_argument("--sat-seq", type=int, default=DEFAULT_SAT_SEQ,
                    help="Bounded-refutation depth in cycles. The "
                         "bound is REPORTED; a clean bounded search "
                         "is never presented as a proof.")
    ap.add_argument("--json", default=DEFAULT_JSON_REL)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    offset = max(0, int(args.latency_offset))
    mode = MODE_LATENCY_OFFSET if offset else MODE_CYCLE_EXACT
    evidence = parse_evidence(args.latency_free_evidence)

    def fail_not_measured(reason: str, base=None, cand=None) -> int:
        rep = _not_measured(reason, top=args.top, mode=mode, offset=offset,
                            evidence=evidence, baseline_files=base,
                            candidate_files=cand)
        p = _write(project, args.json, rep)
        print(f"[{PROGRAM}] NOT_MEASURED: {reason}", file=sys.stderr)
        print(f"[{PROGRAM}] report: {p}", file=sys.stderr)
        return 2

    # --- the latency-offset authorisation, checked BEFORE any tool runs -----
    if offset and evidence is None:
        return fail_not_measured(
            f"--latency-offset {offset} was requested with no "
            f"--latency-free-evidence PATH:LINE. A latency offset changes what "
            f"is compared, so it is only admissible when the design's own "
            f"specification leaves latency unconstrained. Refusing to compare "
            f"under an offset nobody authorised.")
    if evidence is not None:
        cited = (project / str(evidence["path"]))
        if not cited.is_file():
            cited = Path(str(evidence["path"]))
        if not cited.is_file():
            return fail_not_measured(
                f"--latency-free-evidence cites {evidence['path']}:"
                f"{evidence['line']} and that file cannot be read from "
                f"{project}. An uncheckable citation is not a citation.")
        lines = cited.read_text(encoding="utf-8", errors="replace").splitlines()
        idx = int(evidence["line"]) - 1
        if idx < 0 or idx >= len(lines):
            return fail_not_measured(
                f"--latency-free-evidence cites line {evidence['line']} of "
                f"{evidence['path']}, which has {len(lines)} line(s).")
        evidence["literal"] = lines[idx].strip()

    base_dir = (project / args.baseline_rtl_dir)
    cand_dir = (project / args.candidate_rtl_dir)
    for label, d in (("baseline", base_dir), ("candidate", cand_dir)):
        if not d.is_dir():
            return fail_not_measured(
                f"{label} RTL directory {d} does not exist — nothing to "
                f"compare. This is NOT a clean result.")
    try:
        baseline_files = _resolve_rtl_files(base_dir)
        candidate_files = _resolve_rtl_files(cand_dir)
    except Exception as exc:                       # noqa: BLE001
        return fail_not_measured(f"could not resolve RTL sources: {exc}")
    if not baseline_files:
        return fail_not_measured(f"no RTL sources under {base_dir}.")
    if not candidate_files:
        return fail_not_measured(f"no RTL sources under {cand_dir}.")

    wrapper_v = ""
    wrapper_top = ""
    cand_wrapper_v = ""
    cand_wrapper_top = ""
    if offset:
        merged = "\n".join(
            Path(f).read_text(encoding="utf-8", errors="replace")
            for f in baseline_files)
        ports = module_ports(merged, args.top)
        if not ports:
            return fail_not_measured(
                f"latency-offset mode needs the baseline port list of module "
                f"'{args.top}' to build the {offset}-cycle alignment wrapper, "
                f"and no such module declaration was found in the baseline "
                f"RTL.", baseline_files, candidate_files)
        if not any(n == args.clock for _d, _r, n in ports):
            return fail_not_measured(
                f"latency-offset mode needs a clock port; '{args.clock}' is "
                f"not a port of '{args.top}'. Pass --clock.",
                baseline_files, candidate_files)
        wrapper_top = f"{args.top}__delay{offset}"
        # EVERY generated artefact is named from the report stem, never from
        # the program name. MEASURED: three candidates evaluated concurrently
        # all wrote `<PROGRAM>.ys` and each yosys then ran whichever script had
        # last won the race — the same defect as one design reading as both
        # passing and failing because two artefacts wore one name. A search
        # runs many candidates by construction, so a shared filename here is
        # not a tidiness question.
        wrapper_v = str((project / args.json).with_name(
            Path(args.json).stem + "_delay_wrapper.v"))
        Path(wrapper_v).parent.mkdir(parents=True, exist_ok=True)
        params_txt = module_params(merged, args.top)
        atomic_write_text(Path(wrapper_v),
                          build_delay_wrapper(args.top, ports, args.top, wrapper_top,
                                offset, args.clock, params_txt,
                                reset=args.reset,
                                reset_active_low=args.reset_active_low),
                          encoding="utf-8")
        # The CANDIDATE gets a 0-deep pass-through wrapper with the SAME inner
        # instance name. It changes nothing electrically and exists only so
        # that `flatten` stamps the same `u_inner.` prefix on both sides:
        # `equiv_make` matches wires BY NAME, and without this it sees
        # `u_inner.s` against `s` and builds ONE key point (the output port)
        # instead of one per state bit. MEASURED on a +1-latency multiplier
        # WITHOUT it — 1 compared point, 895s, NOT_PROVEN, no verdict either
        # way. Same prefix-matching trick `lec_run.build_scan_wrappers` uses,
        # for the same reason.
        cand_ports = module_ports(
            "\n".join(Path(f).read_text(encoding="utf-8", errors="replace")
                      for f in candidate_files), args.top)
        if cand_ports:
            cand_wrapper_top = f"{args.top}__align0"
            cand_wrapper_v = str((project / args.json).with_name(
                Path(args.json).stem + "_align_wrapper.v"))
            atomic_write_text(Path(cand_wrapper_v),
                              build_delay_wrapper(args.top, cand_ports, args.top,
                                    cand_wrapper_top, 0, args.clock,
                                    params_txt),
                              encoding="utf-8")

    if not _container_available(args.container):
        return fail_not_measured(
            f"the EDA container '{args.container}' is not available, so no "
            f"equivalence was run. Absence of a tool is never a pass.",
            baseline_files, candidate_files)

    script = build_rewrite_equiv_script(baseline_files, candidate_files,
                                        args.top, wrapper_v=wrapper_v,
                                        wrapper_top=wrapper_top,
                                        cand_wrapper_v=cand_wrapper_v,
                                        cand_wrapper_top=cand_wrapper_top)
    ys_host = (project / args.json).with_name(Path(args.json).stem + ".ys")
    ys_host.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(ys_host, script, encoding="utf-8")

    t0 = time.time()
    launched, raw = _run_yosys_equiv(args.container, str(ys_host.resolve()),
                                     timeout=args.timeout,
                                     workdir=str(Path(baseline_files[0]).parent))
    elapsed = time.time() - t0
    rpt_host = (project / args.json).with_suffix(".rpt")
    rpt_host.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(rpt_host, raw or "", encoding="utf-8")

    if not launched:
        return fail_not_measured(
            "Yosys could not be launched in the container, so nothing was "
            "compared.", baseline_files, candidate_files)

    parsed = _parse_equiv_output(raw)

    # SECOND STAGE — only when induction left something unproven. A proven
    # candidate needs no refutation search, and a miter that compared nothing
    # would only produce a second uninformative artefact.
    refuted: Optional[bool] = None
    sat_seq = int(args.sat_seq)
    if (parsed.get("unproven") or 0) > 0 and (parsed.get("total") or 0) > 0:
        ref_script = build_refutation_script(baseline_files, candidate_files,
                                             args.top, sat_seq,
                                             wrapper_v=wrapper_v,
                                             wrapper_top=wrapper_top,
                                             cand_wrapper_v=cand_wrapper_v,
                                             cand_wrapper_top=cand_wrapper_top)
        ref_ys = ys_host.with_name(Path(args.json).stem + "_refute.ys")
        atomic_write_text(ref_ys, ref_script, encoding="utf-8")
        _launched2, raw2 = _run_yosys_equiv(
            args.container, str(ref_ys.resolve()), timeout=args.timeout,
            workdir=str(Path(baseline_files[0]).parent))
        atomic_write_text((project / args.json).with_name(
            Path(args.json).stem + "_refute.rpt"),
                          raw2 or "",
                          encoding="utf-8")
        refuted = parse_refutation(raw2) if _launched2 else None

    status, rc, explanation = classify(parsed, refuted)
    rep = build_report(parsed, top=args.top, mode=mode, offset=offset,
                       evidence=evidence, baseline_files=baseline_files,
                       candidate_files=candidate_files, status=status, rc=rc,
                       explanation=explanation, elapsed=elapsed,
                       refuted=refuted, sat_seq=sat_seq)
    p = _write(project, args.json, rep)
    print(json.dumps(rep, indent=2))
    print(f"[{PROGRAM}] {status} (rc={rc}) → {p}", file=sys.stderr)
    return rc


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
