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
  postcheck_pass_only     — RTL header must record post-checks = PASS
  text_only_report        — prose-report skill: must NOT claim an RTL
                            post-check verdict it never measured
  no_forbidden_patterns   — reject certain regex matches
    (takes `patterns: [list]`)
  pattern_requires_tool   — if a phrase appears, a tool invocation must also appear
    (takes `if_phrase_matches: regex`, `tool_must_match: regex`)

EXIT CODES: 0 = PASS, 1 = FAIL, 2 = ERROR
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Any, Callable


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


def _cc_postcheck_pass_only(spec: Dict[str, Any], text: str) -> List[Finding]:
    """Strictly require an `// Post-checks:` header reporting PASS for both
    rtl_hygiene_lint and fsm_error_invariant.

    Earlier versions silently returned [] when the header was absent, which
    let agents bypass the check by simply omitting the comment. The fix
    treats a missing header as the failure state it always should have been.
    """
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


def _cc_text_only_report(spec: Dict[str, Any], text: str) -> List[Finding]:
    """For a skill whose deliverable is a PROSE REPORT, not RTL.

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
    'no_forbidden_patterns': _cc_no_forbidden_patterns,
    'pattern_requires_tool': _cc_pattern_requires_tool,
    'no_volatile_paths':     _cc_no_volatile_paths,
}


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------
def audit(text: str, compliance: Dict[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
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
        findings += CROSS_CHECK_RULES[rule](cc, text)
    return findings


def main():
    ap = argparse.ArgumentParser(description='Vibe-IC generic skill compliance checker')
    ap.add_argument('output_file', help='Agent-produced markdown report')
    ap.add_argument('--requirements', required=True,
                    help='Path to compliance.yaml for this skill')
    ap.add_argument('--json', help='Write JSON audit report here')
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
    findings = audit(text, compliance)

    total = len(compliance.get('requirements', []) or [])
    fails = [f for f in findings if f.severity == 'FAIL']
    req_fails = [f for f in fails
                 if any(r['id'] == f.id
                        for r in compliance.get('requirements', []) or [])]
    passed = total - len(req_fails)
    verdict = 'PASS' if not fails else 'FAIL'

    skill = compliance.get('skill', 'unknown')
    print(f"skill_compliance_check ({skill}): {verdict}")
    print(f"  Required elements: {passed}/{total} present")
    print(f"  Failures: {len(fails)}")
    print('-' * 70)
    for f in findings:
        print(f"  [{f.severity}] {f.id}: {f.description}")
        if f.detail:
            print(f"           ↳ {f.detail}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            'skill': skill,
            'verdict': verdict,
            'total_requirements': total,
            'passed': passed,
            'findings': [asdict(f) for f in findings],
        }, indent=2))

    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
