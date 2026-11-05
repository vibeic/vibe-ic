#!/usr/bin/env python3
"""sdc_exception_correlation_check.py — Step 8 SDC EXCEPTION
justification screen (v2.3, advisory).

Timing exceptions silently waive real paths — a wrong false_path is a
silicon bug STA can never see. This screen correlates every exception
in the SDC against the design's own evidence:

  * `set_false_path` — justified when its -from/-to clocks correspond
    to a CDC crossing (reports/phase2/cdc/crossing.json, step 3's
    declared output) or an L8 asynchronous-relation entry; otherwise
    SDC_EXCEPTION_UNJUSTIFIED (WARNING — review, this screen never
    blocks). When NEITHER evidence source could be read the finding is
    SDC_EXCEPTION_UNVERIFIABLE instead: an empty known-async set produced
    by an unread file is not evidence that the SDC is wrong.
    A verdict may only cite what was actually read, so the message
    enumerates the sources consulted, each finding carries
    `evidence_read` / `evidence_unread`, and ANY unread source raises one
    SDC_EXCEPTION_EVIDENCE_UNREAD disclosure naming it and its status —
    including the common PARTIAL case (the Phase-1 L8 doc present, step
    3's `crossing.json` absent), which previously produced a bare
    SDC_EXCEPTION_UNJUSTIFIED asserting "no matching CDC crossing" about
    a file the checker never opened;
  * `set_multicycle_path` — multiplier sanity: N > 4 is flagged
    (WARNING) — large multipliers usually mean a missing clock
    definition rather than a real N-cycle path;
  * wildcard breadth — a bare `*` (or `{*}`) in -from/-to waives
    entire clock domains at once: SDC_EXCEPTION_TOO_BROAD (WARNING).

Exit codes: 0 (advisory — findings reported, never blocks),
1 SDC unreadable, 2 no SDC yet (vacuous).
chip-AGNOSTIC: SDC syntax + structural correlation only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

_FP_RE = re.compile(r"^\s*set_false_path\b(.*)$", re.MULTILINE)
_MC_RE = re.compile(r"^\s*set_multicycle_path\s+(\d+)\b(.*)$", re.MULTILINE)
_CLK_TOK_RE = re.compile(r"get_clocks\s+\{?\s*([\w*]+)")
_BROAD_RE = re.compile(r"-(?:from|to|through)\s+(?:\{\s*\*\s*\}|\*)(?:\s|$)")

_MC_SANE_MAX = 4


def _sdc_files(project: Path):
    return sorted((project / "phase2" / "stage2" / "constraints").glob("*.sdc"))


def _read_evidence(path: Path):
    """(parsed_json, status) for one evidence source.

    ``status`` is one of ``READ`` / ``ABSENT`` / ``UNREADABLE``. UNMEASURED IS
    NOT ZERO: the two failure statuses are returned, never swallowed, so the
    caller cannot present "no async pair found" and "the evidence was never
    read" as the same fact.
    """
    try:
        return json.loads(path.read_text(errors="replace")), "READ"
    except FileNotFoundError:
        return None, "ABSENT"
    except (OSError, ValueError) as exc:
        return None, f"UNREADABLE ({exc.__class__.__name__})"


def _known_async_pairs(project: Path):
    """(pairs, evidence) — clock-name pairs the design's own evidence marks
    asynchronous, plus the per-source read status behind that set.

    The CDC half is step 3's declared ``reports/phase2/cdc/crossing.json``; the
    L8 half is step D1's. Both used to be read under a bare
    ``except (OSError, ValueError): pass``, so an ABSENT or corrupt report
    silently produced an EMPTY known-async set and every legitimate CDC
    false_path was then reported ``SDC_EXCEPTION_UNJUSTIFIED`` — a verdict
    about the SDC attributed to a file the checker never opened.
    """
    pairs = set()
    evidence = {}
    cdc = project / "reports" / "phase2" / "cdc" / "crossing.json"
    doc, evidence["reports/phase2/cdc/crossing.json"] = _read_evidence(cdc)
    if isinstance(doc, dict):
        for c in (doc.get("crossings") or []):
            a, b = c.get("from_clock"), c.get("to_clock")
            if a and b:
                pairs.add(frozenset((str(a), str(b))))
    l8 = project / "phase1" / "generated_docs" / "L8_TIMING_WAVEFORM.json"
    doc, evidence["phase1/generated_docs/L8_TIMING_WAVEFORM.json"] = (
        _read_evidence(l8))
    if doc is not None:
        blob = json.dumps(doc).lower()
        for m in re.finditer(r'"async[\w_]*"\s*:\s*\[([^\]]*)\]', blob):
            toks = re.findall(r'"(\w+)"', m.group(1))
            if len(toks) >= 2:
                pairs.add(frozenset(toks[:2]))
    return pairs, evidence


def audit(project: Path, *, sdc_path: Optional[Path]) -> dict:
    explicit = sdc_path is not None
    sdcs = [Path(sdc_path)] if explicit else _sdc_files(project)
    if not sdcs:
        return {'verdict': 'SKIP', 'rc': 2, 'reason': 'no SDC under phase2/stage2/constraints yet', 'sdc_files_checked': []}
    findings = []
    (async_pairs, evidence) = _known_async_pairs(project)
    evidence_read = sorted((p for (p, st) in evidence.items() if st == 'READ'))
    evidence_unread = sorted((p for (p, st) in evidence.items() if st != 'READ'))
    consulted = ', '.join(evidence_read) if evidence_read else 'nothing'
    n_fp = n_mc = 0
    for sdc in sdcs:
        try:
            txt = sdc.read_text(errors='replace')
        except OSError:
            return {'verdict': 'FAIL', 'rc': 1, 'reason': f'unreadable SDC: {sdc.name}', 'sdc_files_checked': [str(p) for p in sdcs]}
        rel = sdc.name
        for m in _FP_RE.finditer(txt):
            n_fp += 1
            args = m.group(1)
            clks = _CLK_TOK_RE.findall(args)
            if _BROAD_RE.search(args) or '*' in clks:
                findings.append({'severity': 'WARNING', 'category': 'SDC_EXCEPTION_TOO_BROAD', 'message': f'{rel}: false_path with bare wildcard -from/-to waives whole domains at once — scope it: `{m.group(0).strip()[:100]}`'})
            elif len(clks) >= 2 and frozenset(clks[:2]) not in async_pairs:
                findings.append({'severity': 'WARNING', 'category': 'SDC_EXCEPTION_UNJUSTIFIED' if evidence_read else 'SDC_EXCEPTION_UNVERIFIABLE', 'evidence_read': list(evidence_read), 'evidence_unread': list(evidence_unread), 'message': f'{rel}: false_path between clocks {clks[0]!r}↔{clks[1]!r} has no matching async relation in the evidence actually read ({consulted})' + (f"; NOT correlated against {', '.join(evidence_unread)} (unread) — justify or remove, but re-run this screen once that source exists" if evidence_unread else ' — justify or remove') if evidence_read else f'{rel}: false_path between clocks {clks[0]!r}↔{clks[1]!r} could not be correlated: no CDC/L8 evidence was readable, so this is NOT a finding about the SDC'})
        for m in _MC_RE.finditer(txt):
            n_mc += 1
            mult = int(m.group(1))
            if mult > _MC_SANE_MAX:
                findings.append({'severity': 'WARNING', 'category': 'SDC_MULTICYCLE_SUSPECT', 'message': f'{rel}: multicycle multiplier {mult} > {_MC_SANE_MAX} — large multipliers usually mask a missing clock definition; verify the real path latency'})
            if _BROAD_RE.search(m.group(2)):
                findings.append({'severity': 'WARNING', 'category': 'SDC_EXCEPTION_TOO_BROAD', 'message': f'{rel}: multicycle with bare wildcard scope — scope it'})
    correlation_categories = {'SDC_EXCEPTION_UNJUSTIFIED', 'SDC_EXCEPTION_UNVERIFIABLE'}
    if evidence_unread and any((f['category'] in correlation_categories for f in findings)):
        status_blob = '; '.join((f'{src}: {st}' for (src, st) in sorted(evidence.items())))
        if not evidence_read:
            detail = 'no correlation evidence could be read (' + status_blob + ') — the false_path finding(s) below are reported UNVERIFIABLE, not unjustified: the known-async set is EMPTY BECAUSE NOTHING WAS READ, not because the design has no async crossing'
        else:
            detail = 'correlation evidence is INCOMPLETE (' + status_blob + ') — the false_path finding(s) below were correlated ONLY against ' + ', '.join(evidence_read) + '. `known_async_pairs` therefore carries no information from ' + ', '.join(evidence_unread) + ': a pair absent from it may be declared async by a source that was never opened'
        findings.insert(0, {'severity': 'WARNING', 'category': 'SDC_EXCEPTION_EVIDENCE_UNREAD', 'evidence_read': list(evidence_read), 'evidence_unread': list(evidence_unread), 'message': detail})
    return {'verdict': 'REVIEW' if any((f['severity'] == 'WARNING' for f in findings)) else 'PASS', 'rc': 0, 'false_paths': n_fp, 'multicycle_paths': n_mc, 'known_async_pairs': [sorted(p) for p in async_pairs], 'correlation_evidence': evidence, 'correlation_evidence_read': list(evidence_read), 'correlation_evidence_unread': list(evidence_unread), 'findings': findings, 'sdc_files_checked': [str(p) for p in sdcs]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    rep = {"program": "sdc_exception_correlation_check",
           "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
