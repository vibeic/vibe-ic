#!/usr/bin/env python3
"""spec_self_consistency_check.py — pre-RTL spec self-consistency lint.

since v0.1.5.

Every other Spec↔RTL gate (`spec_conformance_check`, `spec_rtl_port_fidelity_check`,
`reset_discipline_check`) needs the RTL to exist before it can fire. This one runs
on the SPEC / prompt ALONE — before a single line of RTL is generated — and flags a
spec that contradicts *itself*. Catching a garbled spec at the source is strictly
better than catching its RTL symptom downstream: you stop and clarify the spec
instead of generating a faithful implementation of a broken contract.

Two real benchmark misses motivate every rule here:

  • VerilogEval-v2 **Prob099** is a defective problem: the interface bullets declare
    outputs `Y1, Y3` while the prompt body says "implement the next-state signals
    *Y2 and Y4*". A blind generator faithfully emitted `Y1, Y3` (byte-for-byte the
    reference) yet the testbench wired `Y2/Y4` — so even the golden reference fails
    its own bench. `spec_conformance_check --spec <prompt>` PASSES it (RTL ports match
    the *extracted* interface) and `spec_rtl_port_fidelity_check` only sees the RTL-side
    index gap *after* generation. `body-port-gap` catches it from the prompt alone.

  • A CVDP arbiter spec said "Active-high **synchronous** reset" while its reference
    implemented an **asynchronous** reset. When a spec asserts BOTH reset modes (or
    both polarities) for the same reset, no downstream solution can be both spec- and
    bench-correct. `reset-mode-contradiction` / `reset-polarity-contradiction` catch
    the inconsistency inside the spec text.

Findings (verdict tiers):
  ERROR (fails the gate):
    reset-mode-contradiction     : spec asserts BOTH synchronous AND asynchronous reset.
    reset-polarity-contradiction : spec asserts BOTH active-high AND active-low reset.
  WARN (reported; fails only with --strict):
    body-port-gap   : the body references an indexed sibling (e.g. `Y2`) of a declared
                      numbered-port family (`Y1, Y3`) that is absent from the interface —
                      the garbled-spec (Prob099) signature, detected pre-RTL.
    duplicate-port  : the declared interface lists the same port name twice.
    handshake-consume-undeclared : the spec uses a valid/req handshake and its behaviour
                      prose gates on the RESULT being CONSUMED, but declares no
                      ready/ack/consume INPUT to observe it — a half-declared interface
                      insufficient to build the multi-cycle behaviour it describes
                      (RTLLM radix2_div signature: prose says "whether the result has been
                      consumed" yet no `res_ready`-style input is declared). Detected from
                      the spec ALONE — the behaviour prose vs the declared interface — never
                      from the testbench that happens to drive the missing port.

chip-AGNOSTIC: detection is purely textual/structural over the spec — no IC-, bus-,
or protocol-specific knowledge. Spec may be a natural-language prompt, a markdown
module header, or a `.v/.sv` header (parsing reused from `_specrtl_common`).

CLI:
    python3 spec_self_consistency_check.py <spec.txt|spec.md|spec.json|hdr.v> ...
    python3 spec_self_consistency_check.py --spec <file> [--strict] [--json OUT]

Exit codes:
    0 = PASS   1 = ERROR (or, with --strict, any WARN)   2 = no spec / parse error
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from _specrtl_common import Port, extract_spec_contract, strip_comments
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _specrtl_common import Port, extract_spec_contract, strip_comments


# An indexed port name:  Y1 → ("Y", 1) ;  out3 → ("out", 3) ;  data → None
_INDEXED = re.compile(r'^([A-Za-z_]\w*?)(\d+)$')

# Reset-mode / -polarity detection is PHRASE-BOUND: the qualifier must sit within
# ≤2 words of a reset noun (either order), or be implied by a reset's name. This
# avoids the false positive where "synchronous" qualifies a *load/enable* control
# signal in the same sentence as an (async) reset (VerilogEval Prob085 signature).
_ASYNC_RESET = re.compile(
    r'\basynchronous(?:ly)?[\s-]+(?:\w+[\s-]+){0,2}\b(?:reset|rst)\b'
    r'|\b(?:reset|rst)\b[\s,-]+(?:\w+[\s-]+){0,2}asynchronous(?:ly)?'
    r'|\b(?:areset|arst|nrst)\b', re.I)
_SYNC_RESET = re.compile(
    r'\b(?<!a)synchronous(?:ly)?[\s-]+(?:\w+[\s-]+){0,2}\b(?:reset|rst)\b'
    r'|\b(?:reset|rst)\b[\s,-]+(?:\w+[\s-]+){0,2}(?<!a)synchronous(?:ly)?'
    r'|\b(?:srst|sreset)\b', re.I)
_HI_RESET = re.compile(
    r'active[\s-]*high[\s-]+(?:\w+[\s-]+){0,2}\b(?:reset|rst)\b'
    r'|\b(?:reset|rst)\b[\s,-]+(?:\w+[\s-]+){0,2}active[\s-]*high', re.I)
_LO_RESET = re.compile(
    r'active[\s-]*low[\s-]+(?:\w+[\s-]+){0,2}\b(?:reset|rst)\b'
    r'|\b(?:reset|rst)\b[\s,-]+(?:\w+[\s-]+){0,2}active[\s-]*low', re.I)


@dataclass
class Finding:
    code: str
    severity: str          # ERROR | WARN
    message: str


def _families(names: List[str]) -> Dict[str, set]:
    """Group declared port names into numbered families: {prefix: {indices}}."""
    fams: Dict[str, set] = {}
    for n in names:
        m = _INDEXED.match(n)
        if m:
            fams.setdefault(m.group(1), set()).add(int(m.group(2)))
    return fams


# ── handshake-completeness detection ──────────────────────────────────────
# A spec that uses a valid/req handshake but describes behaviour that depends
# on the RESULT being CONSUMED, yet declares no ready/ack/consume input to
# observe that consumption, has a HALF-DECLARED interface: a builder cannot
# know when to retire the result. Detection is spec-INTERNAL — it compares the
# spec's OWN behaviour prose against the spec's OWN declared interface. It never
# consults a testbench, golden, or any oracle for the missing signal's name.
#
# A valid/req handshake is present (a *_valid / req / request signal, in the
# interface or the prose).
_HS_VALID = re.compile(r'(?<![A-Za-z0-9_])(\w*valid|req|request)(?![A-Za-z0-9_])', re.I)
# A declared INPUT that can serve as the consume/ready/ack side of the handshake.
_HS_READY_NAME = re.compile(
    r'ready|rdy|\back\b|ackn|accept|consum|\bdeq\b|\bpop\b|\btake\b'
    r'|rd_?en|read_?en|\bgrant\b', re.I)
# The behaviour prose references result CONSUMPTION / acceptance / acknowledge —
# an interaction the module must OBSERVE via an input it does not declare.
_CONSUME_PROSE = re.compile(
    r'\bconsum\w*\b'                                # consumed / consumes / consumption
    r'|\backnowledg\w*\b'                           # acknowledged / acknowledgement
    r'|\b(?:result|output|data)\b[^.\n]{0,40}\bbeen\s+read\b'
    r'|\bbeen\s+accepted\b', re.I)

# Interface-section heading of the RTLLM "Input ports:" colon form that
# extract_spec_contract (markdown/verilog oriented) does not parse.
_PORT_SECTION_HDR = re.compile(r'^[ \t]*(input|output|inout)[ \t]*ports?[ \t]*:?[ \t]*$', re.I)
# An indented `name : description` port line beneath such a heading.
_PORT_COLON_LINE = re.compile(r'^[ \t]+([A-Za-z_]\w*)[ \t]*:', re.I)


def _interface_signals(text: str, is_json: bool) -> Dict[str, set]:
    """Declared interface signal names, split by direction, ROBUST across the
    markdown/verilog forms extract_spec_contract handles AND the RTLLM
    `Input ports:` / `Output ports:` colon-section form it does not.

    Returns {'inputs': set, 'outputs': set, 'all': set}. Direction-less names
    (parser could not tell) land only in 'all'. Purely structural — no chip-,
    bus-, or protocol-specific knowledge."""
    inputs: set = set()
    outputs: set = set()
    alls: set = set()
    # (1) whatever the shared extractor recognises (markdown bullets / verilog)
    try:
        contract = extract_spec_contract(text, is_json=is_json)
        for p in contract.ports:
            d = (p.direction or "").lower()
            alls.add(p.name)
            if d == "input":
                inputs.add(p.name)
            elif d in ("output", "inout"):
                outputs.add(p.name)
    except Exception:
        pass
    # (2) RTLLM colon-section form (heading sets the direction for indented lines)
    if not is_json:
        cur: Optional[str] = None
        for line in text.splitlines():
            h = _PORT_SECTION_HDR.match(line)
            if h:
                cur = h.group(1).lower()
                continue
            if cur is not None:
                m = _PORT_COLON_LINE.match(line)
                if m:
                    name = m.group(1)
                    alls.add(name)
                    (inputs if cur == "input" else outputs).add(name)
                    continue
                # a non-indented, non-port line ends the current section
                if line.strip() and not line[:1].isspace():
                    cur = None
    return {"inputs": inputs, "outputs": outputs, "all": alls}




def check_spec(text: str, is_json: bool = False) -> List[Finding]:
    findings: List[Finding] = []
    contract = extract_spec_contract(text, is_json=is_json)
    declared = [p.name for p in contract.ports]
    declared_set = set(declared)

    # ── duplicate declared port ──────────────────────────────────────────────
    seen = set()
    for n in declared:
        if n in seen:
            findings.append(Finding(
                "duplicate-port", "WARN",
                f"interface declares port '{n}' more than once"))
        seen.add(n)

    # ── no-output-port (the Prob031 garbled-spec signature, pre-RTL) ──────────
    # An interface that declares inputs but ZERO output/inout ports is almost
    # always garbled — typically an output mis-declared as input (Prob031: a D
    # flip-flop whose `q` output was listed as `- input q`). A module that
    # produces nothing is meaningless, so this is a high-precision signal.
    if contract.ports:
        dirs = [(p.direction or "").lower() for p in contract.ports]
        n_in = sum(1 for d in dirs if d == "input")
        n_out = sum(1 for d in dirs if d in ("output", "inout"))
        if n_in >= 1 and n_out == 0:
            findings.append(Finding(
                "no-output-port", "WARN",
                f"interface declares {n_in} input(s) but ZERO output/inout ports — "
                "a module that produces no output is almost always a garbled spec "
                "(e.g. an output mis-declared as input; VerilogEval Prob031 signature). "
                "Confirm which port should be the output before generating RTL."))

    # ── body-port-gap (the Prob099 garbled-spec signature, pre-RTL) ───────────
    # For each declared numbered family (e.g. Y:{1,3}), scan the spec BODY for a
    # whole-word sibling token (Y2, Y4, …) that is NOT in the declared interface.
    fams = _families(declared)
    if fams:
        body = strip_comments(text) if not is_json else ""
        for prefix, idxs in fams.items():
            # tokens like <prefix><digits> appearing as whole words anywhere in the spec
            sib = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(prefix) + r'(\d+)(?![A-Za-z0-9_])')
            missing = sorted({int(m.group(1)) for m in sib.finditer(body)} - idxs)
            if missing:
                miss_names = ", ".join(f"{prefix}{i}" for i in missing)
                decl_names = ", ".join(f"{prefix}{i}" for i in sorted(idxs))
                findings.append(Finding(
                    "body-port-gap", "WARN",
                    f"spec body references {miss_names} — numbered sibling(s) of the "
                    f"declared '{prefix}*' family ({decl_names}) — that are NOT in the "
                    f"interface. Likely a garbled spec (VerilogEval Prob099 signature): "
                    f"confirm whether the interface or the body is authoritative."))

    # ── handshake-consume-undeclared (half-declared valid/ready interface) ────
    # A spec that (a) uses a valid/req handshake and (b) whose OWN behaviour prose
    # gates on the RESULT being CONSUMED, but (c) declares no ready/ack/consume
    # INPUT, has an interface insufficient to build what it describes: a builder
    # cannot know when the result is retired. Purely spec-internal — compares the
    # spec's behaviour prose against the spec's declared interface; never reads a
    # TB or golden for the missing signal. The honest verdict on an under-declared
    # multi-cycle interface is "name the gap", not "invent the port".
    if not is_json:
        body = strip_comments(text)
        sig = _interface_signals(text, is_json)
        has_valid = bool(_HS_VALID.search(body)) or any(
            _HS_VALID.search(n) for n in sig["all"])
        consume_ref = bool(_CONSUME_PROSE.search(body))
        has_ready_in = any(_HS_READY_NAME.search(n) for n in sig["inputs"])
        # If no directions were resolvable at all, fall back to the whole
        # declared set so a parser miss cannot manufacture a false gap.
        if consume_ref and not sig["inputs"] and sig["all"]:
            has_ready_in = any(_HS_READY_NAME.search(n) for n in sig["all"])
        if has_valid and consume_ref and not has_ready_in:
            findings.append(Finding(
                "handshake-consume-undeclared", "WARN",
                "spec uses a valid/req handshake and its behaviour references result "
                "CONSUMPTION ('...consumed/accepted/acknowledged...') — an interaction "
                "the module must OBSERVE — but the declared interface has no "
                "ready/ack/consume INPUT to signal it. The interface is half-declared: "
                "a builder cannot know when to retire the result. Name the missing "
                "consume/ready input (e.g. res_ready) or state the result is "
                "free-running / never back-pressured."))

    # ── reset-semantics contradictions inside the spec (phrase-bound) ─────────
    low = strip_comments(text).lower() if not is_json else ""
    if low and 'reset' in low or re.search(r'\b(areset|arst|nrst|srst|sreset)\b', low):
        if _ASYNC_RESET.search(low) and _SYNC_RESET.search(low):
            findings.append(Finding(
                "reset-mode-contradiction", "ERROR",
                "spec asserts BOTH synchronous and asynchronous reset for the same "
                "reset — no implementation can satisfy both; resolve before RTL."))
        if _HI_RESET.search(low) and _LO_RESET.search(low):
            findings.append(Finding(
                "reset-polarity-contradiction", "ERROR",
                "spec asserts BOTH active-high and active-low reset for the same "
                "reset — resolve the polarity before RTL."))

    return findings


def _read_spec(path: Path) -> Tuple[str, bool]:
    text = path.read_text(errors="replace")
    return text, path.suffix.lower() == ".json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="Spec file(s): .txt/.md prompt, .json contract, or .v/.sv header")
    ap.add_argument("--spec", help="Spec file (alternative to positional)")
    ap.add_argument("--strict", action="store_true", help="Fail on WARN findings too")
    ap.add_argument("--json", dest="json_out", help="Write findings as JSON to this path")
    a = ap.parse_args()

    specs = list(a.paths) + ([a.spec] if a.spec else [])
    files = [Path(s) for s in specs if Path(s).is_file()]
    if not files:
        print("spec_self_consistency_check: no spec file found", file=sys.stderr)
        return 2

    all_findings: List[dict] = []
    for f in files:
        try:
            text, is_json = _read_spec(f)
            for fd in check_spec(text, is_json=is_json):
                d = asdict(fd)
                d["spec"] = str(f)
                all_findings.append(d)
        except Exception as e:  # parse error on one spec shouldn't crash the batch
            all_findings.append({"code": "parse-error", "severity": "ERROR",
                                 "message": str(e), "spec": str(f)})

    n_err = sum(1 for d in all_findings if d["severity"] == "ERROR")
    n_warn = sum(1 for d in all_findings if d["severity"] == "WARN")
    fail = n_err > 0 or (a.strict and n_warn > 0)
    verdict = "FAIL" if fail else "PASS"
    print(f"spec_self_consistency_check: {verdict} — findings: {len(all_findings)} "
          f"({n_err} error, {n_warn} warn) [{len(files)} spec(s)]")
    for d in all_findings:
        print(f"  [{d['severity']}] {d['code']}: {d['message']}")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "errors": n_err, "warnings": n_warn,
             "findings": all_findings}, indent=2) + "\n")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
