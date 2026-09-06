#!/usr/bin/env python3
"""
Generic Vibe-IC skill compliance checker.

Every Vibe-IC skill ships a `compliance.yaml` file listing the required
elements its output must contain. This driver reads that YAML and audits
agent output uniformly across all 47+ skills, ensuring different agents
produce content-deterministic results (same required elements, even if
the prose inside varies).

WHY THIS EXISTS:
  Different agents executing the same SKILL.md sometimes skip required
  sections (e.g., forget to record tool provenance, omit hand-off block).
  Missing elements are the largest source of execution non-determinism.
  This checker catches them deterministically — same input report always
  produces the same audit verdict.

USAGE:
  python3 skill_compliance_check.py --requirements path/to/compliance.yaml <agent_output.md>
  python3 skill_compliance_check.py --requirements compliance.yaml --json report.json <agent_output.md>

YAML schema (see plugins/_shared/compliance_schema.md):

    skill: <skill-name>
    requirements:
      - id: R1_section_x
        description: Human-readable description
        pattern: regex
        required: true              # optional, default true
        skill_section: §Output format   # optional, points reader to SKILL.md
    cross_checks:
      - id: C1_name
        description: <why>
        rule: <name of a cross-check implemented in this driver>
        # Additional rule-specific fields follow

Implemented cross-check rules:
  score_formula           — counts + closed-form score must be consistent
  row_count_vs_counts     — number of rows in each findings table matches Counts line
  crc_gen_if_declared     — if Phase-1 JSON declares CRC sub-block, generator must be invoked
  postcheck_pass_only     — RTL header must record post-checks = PASS.
                            LEGITIMATE ONLY on `output_type: rtl` (see below)
  text_only_report        — prose-report skill: must NOT claim an RTL
                            post-check verdict it never measured
  audit_receipt_evidence  — a named audit's own measured receipt must exist,
                            name the right subject, and carry a PASS verdict
    (takes `auditor: <program name>`, optional `receipt_dir:`, optional
     `subject: {key: value}`)
  no_forbidden_patterns   — reject certain regex matches
    (takes `patterns: [list]`)
  pattern_requires_tool   — if a phrase appears, a tool invocation must also appear
    (takes `if_phrase_matches: regex`, `tool_must_match: regex`)

OUTPUT TYPE — why two rules that look contradictory are not (#2048):

    output_type: rtl | report     # optional top-level field

`postcheck_pass_only` DEMANDS a `// Post-checks:` header; `text_only_report`
REJECTS the same header. Read as free-floating rules they contradict each
other, and the contradiction is what let a defect live: three named audit
checks in `skills/rtl-review/compliance.yaml` selected `postcheck_pass_only`
on a Markdown review report, so the report PASSED all three by carrying a
header nobody had measured and FAILED all three without it — while inspecting
evidence from none of the three audits it named.

The two rules stop contradicting each other because each is bound to an
output type, and the types are disjoint:

  * `output_type: rtl`    — the deliverable is RTL source that carries the
                            header. `postcheck_pass_only` is the contract.
  * `output_type: report` — the deliverable is a document. The header cannot
                            legitimately appear (`text_only_report`), and an
                            obligation to run a named audit is discharged by
                            that audit's OWN receipt (`audit_receipt_evidence`),
                            never by a string in the prose.

Selecting `postcheck_pass_only` under `output_type: report` is a configuration
error and is reported as one, so the misbinding cannot silently return to
checking a string. An ABSENT `output_type` is undeclared, not assumed: the
rules behave exactly as they did before, because guessing a skill's output
type is the same class of unmeasured claim this field exists to stop.

EVIDENCE STATES — a check that did not run is reported, never counted as a
pass. `audit_receipt_evidence` reports three, mirroring ruling F2036-H in
`docs/decisions/2026-09-06-rtl-review-producer-json.md`:

  PASS          receipt present, is this auditor's report, examined something,
                subject matches, verdict PASS.        (INFO finding, carries
                the receipt path + sha256 so the verdict is traceable)
  FAIL          receipt present and says FAIL, or names a different subject.
  NOT_MEASURED  no receipt, unreadable receipt, a receipt belonging to another
                producer, a SKIP, or a receipt that examined nothing. Named,
                and BLOCKING — absence of evidence is not evidence of a pass.

EXIT CODES: 0 = PASS, 1 = FAIL, 2 = ERROR
"""
from __future__ import annotations
import argparse
import inspect
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from hashlib import sha256
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional


# ---------------------------------------------------------------------------
# Minimal YAML reader — avoids PyYAML dependency
# Supports: key: value, nested keys, lists of strings, lists of dicts,
#           block scalars (| and >), inline strings.
# For the compliance.yaml format, this is sufficient. Falls back to PyYAML
# if available for maximum compatibility.
# ---------------------------------------------------------------------------
def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml as _yaml   # type: ignore
        return _yaml.safe_load(path.read_text()) or {}
    except ImportError:
        pass
    # Minimal parser for our schema (lightweight fallback)
    return _minimal_yaml_parse(path.read_text())


def _minimal_yaml_parse(text: str) -> Dict[str, Any]:
    """Parser for the compliance.yaml subset we actually use.

    Supported:
      top: scalar
      top:
        - list_item_scalar
        - key1: v1
          key2: v2
      top:
        sub: scalar
    """
    lines = text.splitlines()
    # Strip comments (but not inside strings)
    def strip_comment(ln: str) -> str:
        # Keep # inside quotes
        out, in_s = [], None
        for ch in ln:
            if in_s:
                if ch == in_s:
                    in_s = None
                out.append(ch)
            else:
                if ch in ('"', "'"):
                    in_s = ch; out.append(ch)
                elif ch == '#':
                    break
                else:
                    out.append(ch)
        return ''.join(out).rstrip()
    lines = [strip_comment(ln) for ln in lines]

    def parse_value(v: str):
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        if v.lower() in ('true',): return True
        if v.lower() in ('false',): return False
        if v == '': return None
        try: return int(v)
        except ValueError: pass
        try: return float(v)
        except ValueError: pass
        return v

    def indent_of(ln: str) -> int:
        return len(ln) - len(ln.lstrip(' '))

    # Parse recursively by indentation
    idx = [0]
    def parse_block(base_indent: int):
        result: Any = None
        while idx[0] < len(lines):
            ln = lines[idx[0]]
            if not ln.strip():
                idx[0] += 1; continue
            ind = indent_of(ln)
            if ind < base_indent:
                return result
            if ind > base_indent and result is None:
                # unexpected deeper content
                idx[0] += 1; continue
            stripped = ln.strip()
            if stripped.startswith('- '):
                if result is None: result = []
                item_text = stripped[2:]
                if ':' in item_text and not item_text.startswith('"'):
                    # list of dicts — first key inline
                    key, _, val = item_text.partition(':')
                    d = {key.strip(): parse_value(val)}
                    idx[0] += 1
                    # continue reading sibling keys at ind+2
                    while idx[0] < len(lines):
                        ln2 = lines[idx[0]]
                        if not ln2.strip():
                            idx[0] += 1; continue
                        ind2 = indent_of(ln2)
                        if ind2 <= ind:
                            break
                        s2 = ln2.strip()
                        if s2.startswith('- '):
                            break
                        if ':' in s2:
                            k2, _, v2 = s2.partition(':')
                            v2 = v2.strip()
                            if v2.startswith('|') or v2.startswith('>'):
                                # block scalar
                                fold = v2.startswith('>')
                                idx[0] += 1
                                block_lines = []
                                while idx[0] < len(lines):
                                    ln3 = lines[idx[0]]
                                    if not ln3.strip():
                                        block_lines.append('')
                                        idx[0] += 1; continue
                                    i3 = indent_of(ln3)
                                    if i3 <= ind2: break
                                    block_lines.append(ln3[ind2+2:])
                                    idx[0] += 1
                                d[k2.strip()] = ('\n' if not fold else ' ').join(
                                    block_lines).strip()
                            elif v2 == '':
                                # nested
                                idx[0] += 1
                                nested = parse_block(ind2 + 2)
                                d[k2.strip()] = nested
                            else:
                                d[k2.strip()] = parse_value(v2)
                                idx[0] += 1
                    result.append(d)
                else:
                    result.append(parse_value(item_text))
                    idx[0] += 1
            elif ':' in stripped:
                if result is None: result = {}
                k, _, v = stripped.partition(':')
                v = v.strip()
                if v.startswith('|') or v.startswith('>'):
                    fold = v.startswith('>')
                    idx[0] += 1
                    block_lines = []
                    while idx[0] < len(lines):
                        ln3 = lines[idx[0]]
                        if not ln3.strip():
                            block_lines.append(''); idx[0] += 1; continue
                        i3 = indent_of(ln3)
                        if i3 <= ind: break
                        block_lines.append(ln3[ind+2:])
                        idx[0] += 1
                    result[k.strip()] = ('\n' if not fold else ' ').join(
                        block_lines).strip()
                elif v == '':
                    idx[0] += 1
                    nested = parse_block(ind + 2)
                    result[k.strip()] = nested
                else:
                    result[k.strip()] = parse_value(v)
                    idx[0] += 1
            else:
                idx[0] += 1
        return result
    parsed = parse_block(0)
    return parsed or {}


# ---------------------------------------------------------------------------
# Core audit engine
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    id: str
    severity: str   # FAIL / WARN / INFO
    description: str
    detail: str = ''
    # Evidence state for rules that resolve a measured receipt (#2048).
    # '' for pattern findings and configuration errors; otherwise exactly one
    # of PASS / FAIL / NOT_MEASURED. `severity` stays the blocking axis:
    # NOT_MEASURED is severity FAIL because a check that did not run is
    # reported, never counted as a pass.
    state: str = ''


OUTPUT_TYPE_RTL = 'rtl'
OUTPUT_TYPE_REPORT = 'report'
_KNOWN_OUTPUT_TYPES = (OUTPUT_TYPE_RTL, OUTPUT_TYPE_REPORT)

STATE_PASS = 'PASS'
STATE_FAIL = 'FAIL'
STATE_NOT_MEASURED = 'NOT_MEASURED'


@dataclass
class CheckContext:
    """What a cross-check may know about the artefact beyond its text.

    Every cross-check rule takes this as an OPTIONAL third argument. Rules
    that only read text ignore it, and calling any rule with two arguments
    keeps working — which is deliberate: the two-argument shape is how the
    #2048 reproducer probes the handlers directly, and it must keep
    reproducing rather than raise a TypeError that hides the behaviour.

    `output_path` is the audited document. It is the anchor for the default
    receipt search roots, so a receipt is looked for beside the report that
    claims it rather than anywhere on the filesystem.
    """
    output_type: str = ''
    output_path: Optional[Path] = None
    evidence_dirs: List[Path] = field(default_factory=list)

    def receipt_roots(self, extra: Optional[str] = None) -> List[Path]:
        """Ordered, de-duplicated directories to look for a receipt in.

        Explicit beats derived: a `receipt_dir` on the check itself, then
        `--evidence-dir` from the caller, then the report's own directory and
        the conventional `reports/` beside it. Nothing outside this list is
        searched — a receipt found by wandering the filesystem is not
        evidence that THIS report is backed.
        """
        roots: List[Path] = []
        base = self.output_path.parent if self.output_path else None
        if extra:
            e = Path(extra)
            roots.append(e if e.is_absolute() else ((base / e) if base else e))
        roots.extend(self.evidence_dirs)
        if base is not None:
            roots.extend([base, base / 'reports', base.parent / 'reports'])
        seen: List[Path] = []
        for r in roots:
            try:
                rr = r.resolve()
            except OSError:
                continue
            if rr not in seen:
                seen.append(rr)
        return seen


@dataclass
class Requirement:
    id: str
    description: str
    pattern: str
    required: bool = True
    skill_section: str = ''


def _requirement_check(req: Requirement, text: str) -> List[Finding]:
    if re.search(req.pattern, text, re.MULTILINE | re.IGNORECASE | re.DOTALL):
        return []
    return [Finding(
        req.id,
        'FAIL' if req.required else 'WARN',
        f'Missing: {req.description}',
        f'SKILL.md §{req.skill_section} — pattern: {req.pattern}')]


# ---------------------------------------------------------------------------
# Cross-check rules (named, YAML-addressable)
# ---------------------------------------------------------------------------
def _cc_score_formula(spec: Dict[str, Any], text: str) -> List[Finding]:
    """counts errors/warnings → closed-form score = 10 - min(10, 3E + W)."""
    out: List[Finding] = []
    status = re.search(r'\*\*STATUS\*\*:\s*(\w+)', text)
    score = re.search(r'\*\*Score\*\*:\s*(\d+)', text)
    counts = re.search(
        r'\*\*Counts\*\*:\s*errors=(\d+),\s*warnings=(\d+),\s*infos=(\d+)', text)
    if not (status and score and counts):
        return out
    if status.group(1) != 'OK':
        return out
    e, w, _ = map(int, counts.groups())
    expected = 10 - min(10, 3 * e + 1 * w)
    got = int(score.group(1))
    if got != expected:
        out.append(Finding(
            spec.get('id', 'score_formula'), 'FAIL',
            spec.get('description', 'Score does not match closed-form'),
            f'counts=(E={e},W={w}) expected score={expected}, got {got}'))
    return out


def _cc_row_count_vs_counts(spec: Dict[str, Any], text: str) -> List[Finding]:
    out: List[Finding] = []
    counts = re.search(
        r'\*\*Counts\*\*:\s*errors=(\d+),\s*warnings=(\d+),\s*infos=(\d+)', text)
    if not counts:
        return out
    ed, wd, id_ = map(int, counts.groups())
    def rows(section: str) -> int:
        m = re.search(
            rf'##\s+Findings\s*\({section}\)(.*?)(?=^##|\Z)',
            text, re.DOTALL | re.MULTILINE)
        if not m: return 0
        c = 0
        for line in m.group(1).splitlines():
            if not line.startswith('|'): continue
            cells = [x.strip() for x in line.split('|')[1:-1]]
            if not cells: continue
            if cells[0].lower() in ('file',) or all(
                    re.match(r'^-+$', x) for x in cells):
                continue
            c += 1
        return c
    for sev, d in (('ERROR', ed), ('WARN', wd), ('INFO', id_)):
        a = rows(sev)
        if a != d:
            out.append(Finding(
                f"{spec.get('id','row_count')}_{sev.lower()}", 'FAIL',
                f'Findings ({sev}) row count != Counts declaration',
                f'Counts says {d}, table has {a}'))
    return out


def _cc_crc_gen_if_declared(spec: Dict[str, Any], text: str) -> List[Finding]:
    if not re.search(r'"kind"\s*:\s*"crc"', text, re.IGNORECASE):
        return []
    if re.search(r'crc_vector_gen\.py', text):
        return []
    return [Finding(
        spec.get('id', 'crc_hand_written'), 'FAIL',
        'Phase-1 JSON declares a CRC sub-block but crc_vector_gen.py '
        'was not invoked — hand-written CRC is forbidden.',
        '')]


def _cc_postcheck_pass_only(spec: Dict[str, Any], text: str,
                            ctx: Optional[CheckContext] = None
                            ) -> List[Finding]:
    """Strictly require an `// Post-checks:` header reporting PASS for both
    rtl_hygiene_lint and fsm_error_invariant.

    Earlier versions silently returned [] when the header was absent, which
    let agents bypass the check by simply omitting the comment. The fix
    treats a missing header as the failure state it always should have been.

    BOUND TO `output_type: rtl` (#2048). This rule and `text_only_report` are
    exact opposites about the same string — one demands the header, the other
    rejects it — and they are both correct, because they apply to different
    deliverables. RTL source can carry a header that two tools really wrote;
    a Markdown document cannot, so on a document the only way to satisfy this
    rule is to type the header, which measures nothing. Under a declared
    `output_type: report` the misbinding is reported as the configuration
    error it is, rather than quietly checking a string. An UNDECLARED
    output_type keeps the historical behaviour: the field is a statement, and
    its absence is not one.
    """
    if ctx is not None and ctx.output_type == OUTPUT_TYPE_REPORT:
        return [Finding(
            f"{spec.get('id', 'postcheck')}_rule_misbound", 'FAIL',
            'Rule `postcheck_pass_only` is selected on a spec declaring '
            '`output_type: report`, where the RTL `// Post-checks:` header '
            'it looks for can only ever be typed, not measured.',
            f"{spec.get('description', '')} — bind this check to the "
            'evidence it names: `rule: audit_receipt_evidence` with an '
            '`auditor:`, or move it to a spec whose `output_type` is rtl.')]
    m = re.search(
        r'//\s*Post-checks:\s*rtl_hygiene_lint=(PASS|FAIL),\s*'
        r'fsm_error_invariant=(PASS|FAIL)', text)
    if not m:
        return [Finding(
            spec.get('id', 'postcheck_header_missing'), 'FAIL',
            spec.get('description',
                'Required `// Post-checks: rtl_hygiene_lint=..., '
                'fsm_error_invariant=...` header is missing'),
            'Add the header to the RTL/output before shipping; both fields '
            'must report PASS.')]
    if m.group(1) == 'PASS' and m.group(2) == 'PASS':
        return []
    return [Finding(
        spec.get('id', 'postcheck_not_passed'), 'FAIL',
        'Post-checks did not PASS before shipping',
        f'Header says: lint={m.group(1)}, fei={m.group(2)}')]


# ---------------------------------------------------------------------------
# #2048 — audit receipts. A named audit obligation is discharged by that
# audit's OWN report artefact, not by a sentence in the report that claims it.
#
# Each entry below is READ OFF the producing program's emission, not invented
# here; the `emitted_by` line names the source line so a drifting contract is
# a diff, not a mystery. A producer NOT in this table is reported as unknown —
# never assumed to have passed, and never guessed at from a filename alone.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReceiptSpec:
    auditor: str
    filename: str
    emitted_by: str
    # Is this payload THIS producer's report? Guards against a receipt that
    # merely has the right filename (§1 of the producer-contract decision:
    # "the payload is not this producer's report at all" is NO EVIDENCE).
    identify: Callable[[Dict[str, Any]], bool]
    # The producer's own verdict, in the producer's own terms.
    verdict: Callable[[Dict[str, Any]], str]
    # What the audit was about, so a stale receipt from another subject is
    # not read as backing for this one.
    subject: Callable[[Dict[str, Any]], Dict[str, Any]]
    # How many things the audit actually looked at. Zero is not a clean
    # audit; it is an audit that examined nothing.
    examined: Callable[[Dict[str, Any]], int]


def _d(obj: Any, *keys: str, default: Any = None) -> Any:
    """Nested .get that never raises on a wrong-shaped payload."""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


AUDIT_RECEIPTS: Dict[str, ReceiptSpec] = {
    # programs/interface_encoding_audit.py — main() writes
    #   out_dir/'encoding_audit_report.json' with {'summary': {...},
    #   'interfaces': [...]} and exits 1 when mismatches > 0.
    'interface_encoding_audit': ReceiptSpec(
        auditor='interface_encoding_audit',
        filename='encoding_audit_report.json',
        emitted_by="programs/interface_encoding_audit.py::main",
        identify=lambda d: (isinstance(d.get('summary'), dict)
                            and 'mismatches' in d['summary']
                            and isinstance(d.get('interfaces'), list)),
        verdict=lambda d: (STATE_FAIL if _d(d, 'summary', 'mismatches',
                                            default=0) else STATE_PASS),
        subject=lambda d: {
            'top_module': _d(d, 'summary', 'top_module', default=''),
            'rtl_dir': _d(d, 'summary', 'rtl_dir', default=''),
        },
        examined=lambda d: int(_d(d, 'summary', 'total_interfaces',
                                  default=0) or 0),
    ),
    # programs/crc_bitorder_check.py — main() writes
    #   out_dir/'crc_bitorder_report.json' = asdict(AuditReport). Its
    #   summary_status is PASS | WARN | INFO, and INFO is the "no CRC loading
    #   pattern found" case, which build_report() reaches with zero findings —
    #   examined nothing, so it is NOT_MEASURED here rather than a pass.
    'crc_bitorder_check': ReceiptSpec(
        auditor='crc_bitorder_check',
        filename='crc_bitorder_report.json',
        emitted_by="programs/crc_bitorder_check.py::main",
        identify=lambda d: ('crc_signal' in d
                            and isinstance(d.get('files_scanned'), list)
                            and 'summary_status' in d),
        verdict=lambda d: (STATE_PASS if d.get('summary_status') == 'PASS'
                           else STATE_FAIL),
        subject=lambda d: {
            'crc_signal': d.get('crc_signal', ''),
            'files_scanned': sorted(d.get('files_scanned') or []),
        },
        examined=lambda d: len(d.get('findings') or []),
    ),
    # programs/phy_counter_audit.py — main() writes
    #   out_dir/'phy_counter_audit_report.json' = generate_report(), which
    #   stamps {'tool': 'phy_counter_audit', 'summary': {'verdict': ...}}.
    'phy_counter_audit': ReceiptSpec(
        auditor='phy_counter_audit',
        filename='phy_counter_audit_report.json',
        emitted_by="programs/phy_counter_audit.py::generate_report",
        identify=lambda d: (d.get('tool') == 'phy_counter_audit'
                            and isinstance(d.get('summary'), dict)
                            and 'verdict' in d['summary']),
        verdict=lambda d: (STATE_PASS
                           if _d(d, 'summary', 'verdict') == 'PASS'
                           else STATE_FAIL),
        subject=lambda d: {
            'files': sorted({f['file'] for f in (d.get('findings') or [])
                             if isinstance(f, dict) and 'file' in f}),
        },
        examined=lambda d: int(_d(d, 'summary', 'total_counters_analyzed',
                                  default=0) or 0),
    ),
    # programs/mcp_execution_verify.py — main() writes
    #   out_dir/'mcp_execution_verify_report.json' with
    #   {'program': 'mcp_execution_verify', 'summary': {'verdict': ...}}.
    #   Its verdict is already three-state; INCONCLUSIVE is not a pass and is
    #   not a finding about the design either, so it lands as NOT_MEASURED.
    'mcp_execution_verify': ReceiptSpec(
        auditor='mcp_execution_verify',
        filename='mcp_execution_verify_report.json',
        emitted_by="programs/mcp_execution_verify.py::main",
        identify=lambda d: (d.get('program') == 'mcp_execution_verify'
                            and isinstance(d.get('summary'), dict)
                            and 'verdict' in d['summary']),
        verdict=lambda d: (STATE_PASS
                           if _d(d, 'summary', 'verdict') == 'PASS'
                           else STATE_FAIL),
        subject=lambda d: {
            'steps': sorted({r['step'] for r in (d.get('steps') or [])
                             if isinstance(r, dict) and 'step' in r}),
        },
        examined=lambda d: (0 if _d(d, 'summary', 'verdict') == 'INCONCLUSIVE'
                            else int(_d(d, 'summary', 'total_required',
                                        default=0) or 0)),
    ),
    # programs/fpga_pullup_lint.py — both write sites emit
    #   out_dir/'fpga_pullup_lint.json' = asdict(Result). The early-return
    #   site at "no inout ports in top module" emits status PASS with an EMPTY
    #   inout_signals, which is a pass over an empty population; counting the
    #   signals it actually examined is what separates the two.
    'fpga_pullup_lint': ReceiptSpec(
        auditor='fpga_pullup_lint',
        filename='fpga_pullup_lint.json',
        emitted_by="programs/fpga_pullup_lint.py::main",
        identify=lambda d: ('status' in d
                            and isinstance(d.get('findings'), list)
                            and isinstance(d.get('inout_signals'), list)),
        verdict=lambda d: (STATE_PASS if d.get('status') == 'PASS'
                           else STATE_FAIL),
        subject=lambda d: {'inout_signals': sorted(d.get('inout_signals') or [])},
        examined=lambda d: len(d.get('inout_signals') or []),
    ),
}

# Auditors that a compliance.yaml legitimately names but whose receipt
# contract cannot be registered yet, with the measured reason. They are NOT
# given a guessed entry above: `audit_receipt_evidence` reports an
# unregistered auditor as a blocking configuration error that says what is
# missing, which is the honest state. Inventing a receipt filename here would
# be the same unmeasured claim this module exists to remove.
#
#   gds_size_check                       --json PATH, caller-chosen; no
#   synth_netlist_check                    filename convention exists in this
#   fpga_async_input_synchronizer_check    tree to read off.
#   tapeout_signoff_check                22-line shim over `signoff_audit
#                                          --mode tapeout`; the receipt is
#                                          whatever the caller's --json says.
UNREGISTERED_AUDITORS = (
    'gds_size_check',
    'synth_netlist_check',
    'fpga_async_input_synchronizer_check',
    'tapeout_signoff_check',
)


def _receipt_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _cc_audit_receipt_evidence(spec: Dict[str, Any], text: str,
                               ctx: Optional[CheckContext] = None
                               ) -> List[Finding]:
    """Bind ONE named audit obligation to that audit's OWN measured receipt.

    THIS RULE NEVER READS THE `// Post-checks:` HEADER, and never reads the
    report text at all. That is the whole point of it. Before #2048 the three
    named audits in `skills/rtl-review/compliance.yaml` were bound to
    `postcheck_pass_only`, so the sentence

        // Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS

    pasted into a Markdown review made `X_interface_encoding_audit`,
    `X_crc_bitorder_check` and `X_phy_counter_audit` all PASS — three audits
    discharged by a string naming two OTHER tools, with no receipt from any of
    the three anywhere on disk. Removing the string made all three FAIL. A
    check that passes on a header nobody measured, and fails on the absence of
    that header, is checking the header.

    The obligation is now discharged the only way it can be: the audit's
    report artefact is located, confirmed to be that producer's report,
    confirmed to have examined something, its subject is compared against what
    the check declares it should be, and its own verdict is read.

    Returns exactly one finding, always, so the state is visible in the JSON
    report whichever way it went:

      * PASS         -> severity INFO, state PASS. Non-blocking, and it
                        carries the receipt path and sha256 so a reader can
                        check which bytes the verdict came from.
      * FAIL         -> severity FAIL, state FAIL.
      * NOT_MEASURED -> severity FAIL, state NOT_MEASURED, naming the auditor,
                        the receipt filename and every directory searched.
                        Blocking, because absence of evidence is not a pass.

    A configuration error (no `auditor:`, or an auditor with no known receipt
    contract) is severity FAIL with an empty state: nothing was measured and
    nothing CAN be measured until the yaml is fixed. It is never a pass.
    """
    cid = spec.get('id', 'audit_receipt_evidence')
    desc = spec.get('description', '')
    auditor = spec.get('auditor')

    if not auditor:
        return [Finding(
            f'{cid}_no_auditor', 'FAIL',
            'Cross-check uses rule `audit_receipt_evidence` but declares no '
            '`auditor:` field, so no receipt can be resolved.',
            f'{desc} — add `auditor: <program name>` to this cross-check.')]

    rs = AUDIT_RECEIPTS.get(auditor)
    if rs is None:
        return [Finding(
            f'{cid}_unknown_auditor', 'FAIL',
            f'No receipt contract is registered for auditor `{auditor}`.',
            'Add its emission to AUDIT_RECEIPTS in '
            '_shared/skill_compliance_check.py, read off the producing '
            'program. An unregistered auditor is not assumed to have passed.')]

    ctx = ctx or CheckContext()
    roots = ctx.receipt_roots(spec.get('receipt_dir'))
    searched = ', '.join(str(r) for r in roots) or '(no evidence root available)'

    found: Optional[Path] = None
    for r in roots:
        cand = r / rs.filename
        if cand.is_file():
            found = cand
            break

    if found is None:
        return [Finding(
            cid, 'FAIL',
            f'NOT_MEASURED: no receipt from `{auditor}` for this report.',
            f'{desc} — looked for `{rs.filename}` (emitted by '
            f'{rs.emitted_by}) in: {searched}. Run the audit and place its '
            'report where this check can read it; do not assert the verdict '
            'in prose.',
            state=STATE_NOT_MEASURED)]

    try:
        payload = json.loads(found.read_text(errors='replace'))
    except (OSError, ValueError) as e:
        return [Finding(
            cid, 'FAIL',
            f'NOT_MEASURED: receipt from `{auditor}` could not be read.',
            f'{found}: {e.__class__.__name__}: {e}. Unreadable is not empty '
            'and not clean.',
            state=STATE_NOT_MEASURED)]

    digest = _receipt_digest(found)
    trace = f'receipt={found} sha256={digest[:16]}'

    if not isinstance(payload, dict):
        return [Finding(
            cid, 'FAIL',
            f'NOT_MEASURED: receipt at `{rs.filename}` is not an object.',
            f'{trace} — got {type(payload).__name__}. This is not '
            f'{auditor}\'s report.',
            state=STATE_NOT_MEASURED)]

    if payload.get('verdict') == 'SKIP':
        return [Finding(
            cid, 'FAIL',
            f'NOT_MEASURED: `{auditor}` reported SKIP.',
            f'{trace} — reason: {payload.get("reason", "(none given)")}. '
            'A skipped auditor is a fact about the invocation, not a pass.',
            state=STATE_NOT_MEASURED)]

    if not rs.identify(payload):
        return [Finding(
            cid, 'FAIL',
            f'NOT_MEASURED: the file at `{rs.filename}` is not '
            f'`{auditor}`\'s report.',
            f'{trace} — it does not carry the shape {rs.emitted_by} emits. '
            'A payload from another producer is no evidence at all.',
            state=STATE_NOT_MEASURED)]

    examined = rs.examined(payload)
    if examined <= 0:
        return [Finding(
            cid, 'FAIL',
            f'NOT_MEASURED: `{auditor}` examined nothing.',
            f'{trace} — the receipt records 0 examined items, so its verdict '
            'is about an empty population. A vacuous pass is not a pass.',
            state=STATE_NOT_MEASURED)]

    actual_subject = rs.subject(payload)
    declared = spec.get('subject')
    if isinstance(declared, dict):
        mismatched = {k: (v, actual_subject.get(k))
                      for k, v in declared.items()
                      if actual_subject.get(k) != v}
        if mismatched:
            return [Finding(
                cid, 'FAIL',
                f'`{auditor}` receipt names a different subject than this '
                'check declares.',
                f'{trace} — ' + '; '.join(
                    f'{k}: declared {d!r}, receipt has {a!r}'
                    for k, (d, a) in sorted(mismatched.items())),
                state=STATE_FAIL)]

    v = rs.verdict(payload)
    if v == STATE_PASS:
        return [Finding(
            cid, 'INFO',
            f'PASS: `{auditor}` receipt verdict PASS over {examined} '
            'examined item(s).',
            f'{trace} subject={actual_subject}',
            state=STATE_PASS)]
    return [Finding(
        cid, 'FAIL',
        f'`{auditor}` receipt verdict is {v}.',
        f'{trace} subject={actual_subject} — {desc}',
        state=STATE_FAIL)]


def _cc_no_forbidden_patterns(spec: Dict[str, Any], text: str) -> List[Finding]:
    out: List[Finding] = []
    for pat in spec.get('patterns', []):
        if re.search(pat, text, re.MULTILINE):
            out.append(Finding(
                f"{spec.get('id', 'forbidden')}_{re.sub(r'[^a-z0-9]', '_', pat.lower())[:20]}",
                'FAIL',
                f"Forbidden pattern present: {pat}",
                spec.get('description', '')))
    return out


def _cc_pattern_requires_tool(spec: Dict[str, Any], text: str) -> List[Finding]:
    phrase = spec.get('if_phrase_matches')
    tool = spec.get('tool_must_match')
    if not phrase or not tool:
        return []
    if re.search(phrase, text, re.IGNORECASE) and not re.search(tool, text):
        return [Finding(
            spec.get('id', 'pattern_needs_tool'), 'FAIL',
            f"Pattern '{phrase}' present but required tool '{tool}' not invoked",
            spec.get('description', ''))]
    return []


# v1.6.53 — chip-AGNOSTIC volatile-path leak detector. Skill outputs
# (deep-review reports, audit summaries, RTL hand-off documents) often
# get committed alongside the project; if they reference a /tmp path
# the downstream `project_outputs_in_tree_check` gate fires the FAIL
# at burn time. Catching this in the skill layer means the agent fixes
# the report before it hits the next-stage audit.
#
# Detects ASCII/POSIX volatile mounts: /tmp, /var/tmp, /dev/shm, /run.
# A leading word boundary OR start-of-line is required so legitimate
# substrings like "settmpval" / "/var/log/tmp.log" are not flagged
# (note: `/var/log/tmp.log` is real persistent storage; only the
# enumerated mounts are volatile).
_VOLATILE_PATH_RE = re.compile(
    r"(?:^|[\s`'\"(\[])(/(?:tmp|var/tmp|dev/shm|run)/[^\s`'\")]+)",
    re.MULTILINE)


def _cc_no_volatile_paths(spec: Dict[str, Any], text: str) -> List[Finding]:
    """Reject skill output that names a volatile-storage path.
    A `project_outputs_in_tree_check` violation downstream is silent
    until burn time; surfacing it at skill compliance lets the
    author fix it before hand-off."""
    matches = _VOLATILE_PATH_RE.findall(text)
    if not matches:
        return []
    # Dedupe, preserve order, cap report length so a long doc with
    # one bad path does not flood the finding's hint.
    seen: List[str] = []
    for m in matches:
        if m not in seen:
            seen.append(m)
        if len(seen) >= 5:
            break
    return [Finding(
        spec.get('id', 'volatile_path_leak'),
        'FAIL',
        spec.get('description',
                 'Skill output references volatile-storage path(s); '
                 'these will trigger project_outputs_in_tree_check at '
                 'burn time.'),
        ('Replace with a project-relative path or describe the '
         'helper inline without an absolute path that resolves to '
         'a real file. Offending paths: ' + ', '.join(seen)))]


def _cc_text_only_report(spec: Dict[str, Any], text: str,
                        ctx: Optional[CheckContext] = None) -> List[Finding]:
    """For a skill whose deliverable is a PROSE REPORT, not RTL.

    The other half of the `output_type` pairing described in the module
    docstring and in `postcheck_pass_only`: this rule holds under
    `output_type: report`, that one holds under `output_type: rtl`, and they
    only look contradictory when read without the type they are bound to.
    Keeping this contract unchanged is deliberate — a fabricated RTL header
    in a Markdown report stays a failure (#2048).

    Such a skill emits markdown, so the `// Post-checks:` RTL header that
    `postcheck_pass_only` demands can never legitimately appear in its
    output — and requiring it made those skills unsatisfiable: every
    required element could be present and the audit still returned FAIL,
    with the only route to green being to paste a header asserting that
    `rtl_hygiene_lint` and `fsm_error_invariant` had passed on a document
    that neither tool had ever been run against.

    So this rule asserts the INVERSE, and keeps the teeth pointed at the
    behaviour that actually matters: a prose report must NOT claim an RTL
    post-check verdict. A markdown review cannot have run those tools on
    itself, so a header claiming it did is a fabricated result.
    """
    m = re.search(r'//\s*Post-checks:\s*rtl_hygiene_lint\s*=', text)
    if not m:
        return []
    return [Finding(
        spec.get('id', 'text_only_claims_rtl_postcheck'),
        'FAIL',
        spec.get('description',
                 'Prose-report skill output claims an RTL post-check '
                 'verdict.'),
        ('This skill produces a report, not RTL, so `rtl_hygiene_lint` / '
         '`fsm_error_invariant` were never run against this document. '
         'Remove the `// Post-checks:` header rather than asserting a '
         'verdict that was not measured.'))]


CROSS_CHECK_RULES: Dict[str, Callable[[Dict[str, Any], str], List[Finding]]] = {
    'score_formula':         _cc_score_formula,
    'row_count_vs_counts':   _cc_row_count_vs_counts,
    'crc_gen_if_declared':   _cc_crc_gen_if_declared,
    'postcheck_pass_only':   _cc_postcheck_pass_only,
    'text_only_report':      _cc_text_only_report,
    'audit_receipt_evidence': _cc_audit_receipt_evidence,
    'no_forbidden_patterns': _cc_no_forbidden_patterns,
    'pattern_requires_tool': _cc_pattern_requires_tool,
    'no_volatile_paths':     _cc_no_volatile_paths,
}


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------
def _dispatch(fn: Callable[..., List[Finding]], cc: Dict[str, Any],
              text: str, ctx: CheckContext) -> List[Finding]:
    """Call a cross-check rule, passing `ctx` only to rules that accept it.

    Rules keep their two-argument shape as a supported call: a rule is a
    plain function, and third-party probes (the #2048 reproducer among them)
    call them directly with `(spec, text)`. Widening every signature at once
    would have turned that probe into a TypeError, which hides behaviour
    instead of measuring it.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(cc, text)
    if len(params) >= 3:
        return fn(cc, text, ctx)
    return fn(cc, text)


def audit(text: str, compliance: Dict[str, Any],
          ctx: Optional[CheckContext] = None) -> List[Finding]:
    if ctx is None:
        ctx = CheckContext()
    declared = compliance.get('output_type')
    if declared is not None:
        declared = str(declared).strip().lower()
    if not ctx.output_type and declared:
        ctx.output_type = declared
    findings: List[Finding] = []
    if declared and declared not in _KNOWN_OUTPUT_TYPES:
        findings.append(Finding(
            'output_type_unknown', 'FAIL',
            f'compliance.yaml declares output_type: {declared!r}, which is '
            f'not one of {list(_KNOWN_OUTPUT_TYPES)}.',
            'An output type the engine does not know binds no rule to '
            'anything; fix the yaml rather than let the rules float free.'))
    for r in compliance.get('requirements', []) or []:
        req = Requirement(
            id=r['id'],
            description=r.get('description', ''),
            pattern=r['pattern'],
            required=bool(r.get('required', True)),
            skill_section=r.get('skill_section', ''))
        findings += _requirement_check(req, text)
    for cc in compliance.get('cross_checks', []) or []:
        rule = cc.get('rule')
        if rule not in CROSS_CHECK_RULES:
            findings.append(Finding(
                cc.get('id', rule or 'unknown'),
                'WARN',
                f"Unknown cross-check rule: {rule}"))
            continue
        findings += _dispatch(CROSS_CHECK_RULES[rule], cc, text, ctx)
    return findings


def main():
    ap = argparse.ArgumentParser(description='Vibe-IC generic skill compliance checker')
    ap.add_argument('output_file', help='Agent-produced markdown report')
    ap.add_argument('--requirements', required=True,
                    help='Path to compliance.yaml for this skill')
    ap.add_argument('--json', help='Write JSON audit report here')
    ap.add_argument('--evidence-dir', action='append', default=[],
                    metavar='DIR',
                    help='Directory to search for audit receipts (repeatable). '
                         'Searched before the report-relative defaults. '
                         'Receipts are never looked for outside these roots.')
    args = ap.parse_args()

    out_path = Path(args.output_file)
    if not out_path.exists():
        print(f"ERROR: output file not found: {out_path}", file=sys.stderr)
        return 2
    req_path = Path(args.requirements)
    if not req_path.exists():
        print(f"ERROR: requirements not found: {req_path}", file=sys.stderr)
        return 2

    compliance = _load_yaml(req_path)
    text = out_path.read_text(errors='replace')
    ctx = CheckContext(
        output_path=out_path.resolve(),
        evidence_dirs=[Path(d) for d in args.evidence_dir])
    findings = audit(text, compliance, ctx)

    total = len(compliance.get('requirements', []) or [])
    fails = [f for f in findings if f.severity == 'FAIL']
    req_fails = [f for f in fails
                 if any(r['id'] == f.id
                        for r in compliance.get('requirements', []) or [])]
    passed = total - len(req_fails)
    verdict = 'PASS' if not fails else 'FAIL'

    not_measured = [f for f in findings if f.state == STATE_NOT_MEASURED]

    skill = compliance.get('skill', 'unknown')
    print(f"skill_compliance_check ({skill}): {verdict}")
    print(f"  Required elements: {passed}/{total} present")
    print(f"  Failures: {len(fails)}")
    if not_measured:
        # Printed beside the verdict, never folded into it: a reader must not
        # be able to quote the number without its coverage (ruling F2036-H).
        print(f"  Not measured: {len(not_measured)} — "
              + ', '.join(f.id for f in not_measured))
    print('-' * 70)
    for f in findings:
        tag = f' <{f.state}>' if f.state else ''
        print(f"  [{f.severity}]{tag} {f.id}: {f.description}")
        if f.detail:
            print(f"           ↳ {f.detail}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            'skill': skill,
            'verdict': verdict,
            'total_requirements': total,
            'passed': passed,
            'not_measured': [f.id for f in not_measured],
            'findings': [asdict(f) for f in findings],
        }, indent=2))

    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
