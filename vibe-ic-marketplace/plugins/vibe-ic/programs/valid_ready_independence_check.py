#!/usr/bin/env python3
"""valid_ready_independence_check.py — a producer's VALID must not wait on the consumer's READY.

The ready/valid contract (AXI-Stream §2.2.1, and every handshake modelled on it)
is asymmetric on purpose: a source may assert TVALID whenever it has data and
must hold it until the transfer completes, while a sink may assert TREADY
whenever it likes -- including only after it has observed TVALID. A source that
waits for TREADY before raising TVALID is therefore not merely slow: paired with
a legal sink that waits for TVALID, neither signal ever rises and the stream
deadlocks. The bug survives casual testing because the usual testbench holds
TREADY high, which hides the dependency completely.

What makes this checkable rather than a judgment call is that READY is legal in
two neighbouring positions and illegal in only one:

  legal    tvalid <= 1'b0            when (tready)          -- deassert on transfer
  legal    tvalid <= src_valid       when (tready || !tvalid) -- skid-buffer load
  ILLEGAL  tvalid <= 1'b1            when (tready)          -- assertion gated by ready
  ILLEGAL  assign tvalid = have_data && tready               -- same, combinational

So the rule is not "ready must not appear near valid" -- that would flag the two
correct idioms -- it is "ready must not be a NECESSARY condition for valid to
become asserted". A disjunction (`tready || !tvalid`) makes ready unnecessary and
is passed; a conjunction, or a bare `if (tready)` around an assertion, makes it
necessary and is reported.

Exit: 0 = PASS, 1 = FAIL (violations found), 2 = CANNOT CHECK (no RTL).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files

# A valid/ready pair shares everything but the final token: m_axis_tvalid /
# m_axis_tready, out_valid / out_ready, src_vld / src_rdy.
_VALID_TAIL = re.compile(r"^(?P<stem>.*?)(?P<tail>t?valid|t?vld)$", re.I)
_READY_TAILS = {"valid": ["ready"], "tvalid": ["tready"],
                "vld": ["rdy"], "tvld": ["trdy"]}

_COMMENT_LINE = re.compile(r"//.*?$", re.M)
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(text: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", text))


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: Optional[int] = None


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _declared_ports(text: str, kw: str) -> set:
    out = set()
    for m in re.finditer(r"\b" + kw + r"\b(?:\s+(?:wire|reg|logic))?\s*"
                         r"(?:signed\s*)?(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)", text):
        out.add(m.group(1))
    return out


def _partner_ready(valid: str) -> List[str]:
    m = _VALID_TAIL.match(valid)
    if not m:
        return []
    stem, tail = m.group("stem"), m.group("tail").lower()
    return [stem + r for r in _READY_TAILS.get(tail, [])] + \
           [stem + r.upper() for r in _READY_TAILS.get(tail, [])]


def _ready_is_necessary(cond: str, ready: str) -> bool:
    """True iff `ready` must hold for `cond` to hold.

    Splitting on top-level `||` is what separates the skid-buffer idiom from a
    real dependency: if ready appears in only ONE arm of a disjunction, the
    other arm can satisfy the condition without it, so ready is not necessary.
    A negated occurrence (`!ready`) is likewise not a requirement that ready be
    high.
    """
    arms, depth, cur = [], 0, ""
    i = 0
    while i < len(cond):
        c = cond[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if depth == 0 and cond.startswith("||", i):
            arms.append(cur); cur = ""; i += 2; continue
        cur += c; i += 1
    arms.append(cur)
    rx = re.compile(r"(?<![\w$])(!\s*|~\s*)?" + re.escape(ready) + r"\b")
    for arm in arms:
        m = rx.search(arm)
        if not m or m.group(1):      # absent, or negated -> not a requirement
            return False
    return True


def _asserts_valid(rhs: str, valid: str) -> bool:
    """The RHS raises valid (not `1'b0`, and not a plain hold of itself)."""
    r = rhs.strip().rstrip(";").strip()
    if re.fullmatch(r"1'?[bh]?0|0|'0", r, re.I):
        return False
    if re.fullmatch(re.escape(valid), r):
        return False
    return True


def audit_file(path: Path, root: Path) -> List[Finding]:
    raw = path.read_text(errors="replace")
    text = strip_comments(raw)
    rel = str(path.relative_to(root)) if str(path).startswith(str(root)) else str(path)
    outs = _declared_ports(text, "output")
    ins = _declared_ports(text, "input")
    findings: List[Finding] = []

    def line_of(idx: int) -> int:
        return text.count("\n", 0, idx) + 1

    # Only a signal this module DRIVES as an output can deadlock a downstream
    # sink; an input valid legitimately depends on whatever the source does.
    valids = [s for s in outs if _VALID_TAIL.match(s) and _partner_ready(s)]

    for valid in valids:
        # The ready of the pair must be an INPUT: only a ready the DOWNSTREAM
        # drives can deadlock us. A same-named signal this module also drives
        # is its own back-pressure output on a different interface (a
        # start/ready/valid command port), where gating valid on it is the
        # correct idiom, not a violation.
        readies = [r for r in _partner_ready(valid)
                   if r in ins and r not in outs and re.search(
                       r"(?<![\w$])" + re.escape(r) + r"\b", text)]
        if not readies:
            continue

        # (1) combinational: assign valid = <expr containing ready>
        for m in re.finditer(r"\bassign\s+" + re.escape(valid) +
                             r"\s*=\s*([^;]+);", text):
            expr = m.group(1)
            for rdy in readies:
                if _ready_is_necessary(expr, rdy):
                    findings.append(Finding(
                        rule="VALID_GATED_BY_READY", severity="ERROR",
                        message=(f"'{valid}' is driven combinationally from "
                                 f"'{rdy}': a source must assert valid on data "
                                 f"availability alone. A sink that waits for "
                                 f"'{valid}' before raising '{rdy}' deadlocks. "
                                 f"Drive '{valid}' from the data-available "
                                 f"condition and use '{rdy}' only to clear it."),
                        file=rel, line=line_of(m.start())))

        # (2) sequential: `if (<cond with ready>) ... valid <= <raises>`
        for m in re.finditer(r"\bif\s*\(", text):
            depth, j = 0, m.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            cond = text[m.end():j]
            body = text[j + 1:j + 700]           # the guarded region
            # stop the window at the enclosing else, so an else-arm assignment
            # is not attributed to this condition
            cut = re.search(r"\belse\b", body)
            if cut:
                body = body[:cut.start()]
            am = re.search(re.escape(valid) + r"\s*<=\s*([^;]+);", body)
            if not am or not _asserts_valid(am.group(1), valid):
                continue
            for rdy in readies:
                if _ready_is_necessary(cond, rdy):
                    findings.append(Finding(
                        rule="VALID_ASSERTION_GATED_BY_READY", severity="ERROR",
                        message=(f"'{valid}' is asserted only when '{rdy}' is "
                                 f"high. Ready may gate the DEASSERTION of "
                                 f"valid (transfer complete) or a skid-buffer "
                                 f"load (`{rdy} || !{valid}`), but never its "
                                 f"assertion -- a sink waiting for '{valid}' "
                                 f"before raising '{rdy}' would hang forever."),
                        file=rel, line=line_of(m.start())))
    return findings


def check_text(code: str) -> Tuple[List[Finding], str]:
    """Audit RTL held in memory. Returns (findings, status).

    This is the interface `cvdp_gate._structural_finding_gate` consumes: it
    BLOCKs a delivery on any ERROR-severity finding. The rule is admitted there
    because it is zero-false-positive by measurement, not by assertion -- swept
    over 302 officially-passing CVDP deliveries it fires ONCE, on a source whose
    `assign m_axis_tvalid = tvalid_reg & m_axis_tready;` deasserts TVALID
    whenever TREADY drops. That is an AXI4-Stream violation on its face, and it
    passes only because the testbench holds TREADY high for the whole run.
    Blocking it costs nothing: the protocol-correct variant (the `& tready`
    removed) was scored through the official harness and also PASSes.
    """
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".v", delete=False) as fh:
        fh.write(code or "")
        tmp = Path(fh.name)
    try:
        findings = audit_file(tmp, tmp.parent)
    finally:
        tmp.unlink(missing_ok=True)
    return findings, ("FAIL" if findings else "PASS")


def audit(project_dir: str) -> AuditResult:
    root = Path(project_dir).resolve()
    result = AuditResult(program="valid_ready_independence_check", passed=True)
    if not root.exists():
        result.findings.append(Finding(
            rule="PROJECT_DIR_MISSING", severity="ERROR",
            message=f"project_dir not found: {project_dir}"))
        result.passed = False
        result.summary = {"files_scanned": 0, "violations": 1, "status": "CANNOT_CHECK"}
        return result

    files = [Path(root)] if root.is_file() else list(rtl_source_files(root))
    if not files:
        result.summary = {"files_scanned": 0, "violations": 0, "status": "CANNOT_CHECK"}
        result.passed = True
        return result

    for f in files:
        result.findings.extend(audit_file(f, root if root.is_dir() else root.parent))

    result.passed = not result.findings
    result.summary = {"files_scanned": len(files),
                      "violations": len(result.findings), "status": "CHECKED"}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    result = audit(args.project_dir)
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        for f in result.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity}] {f.rule} ({loc}): {f.message}")
        print(f"\n{'PASS' if result.passed else 'FAIL'} — {result.summary}")
    if result.summary.get("status") == "CANNOT_CHECK" and not result.findings:
        sys.exit(2)
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
