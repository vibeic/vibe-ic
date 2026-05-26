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
