#!/usr/bin/env python3
"""reset_dependency_check.py — deterministic compliance check derived from <chip-class> v040 debug.

Detects circular reset dependencies: module A's reset depends on a signal
produced by module B, but that signal is produced by a register that itself
is reset by A's reset (or something derived from it). The whole chain never
releases reset, or releases it non-deterministically.

Heuristic (two passes):
  1. Parse module instances at the top level and record their
     .rstn(...) / .rst(...) / .reset(...) connections.
  2. Find `assign <reset_sig> = ... & <something>_done;` style reset
     combining expressions. If `<something>_done` is produced by a module
     that is itself reset by `<reset_sig>`, flag a circular dependency.

A graph of (instance → reset_source_signal) is also built, and any direct
cycle in that graph is reported.

Exit: 0 = PASS (no circular deps), 1 = FAIL,
      2 = VACUOUS_PASS (zero RTL files were examined — see `_verdict_for`).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _vacuous_exit as _vx  # noqa: E402


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    # ORGANIC #887 — see `_verdict_for`. Defaulted so every existing
    # construction site, here and in any caller, is unchanged.
    verdict: str = "PASS"


#: ORGANIC #887 — the verdict word for "I ran, but the input I audit was not
#: there". Spelled the way `_flow_verdict_tiers.normalize` reads it.
_VACUOUS_VERDICT = "VACUOUS_PASS"

#: The gate's OWN machine-readable skip-reason token, and a TOKEN on purpose:
#: it is the only variable part of the disclosure line, so the line's length is
#: fixed at import time and cannot be grown by anything a caller supplies.
_VACUOUS_REASON = "zero-rtl-files-examined"


def _verdict_for(result: AuditResult) -> str:
    """PASS / FAIL / VACUOUS_PASS for a completed audit.

    ORGANIC #887. A scan that read ZERO files has not cleared the design — it
    never looked at it. `passed=True` written beside `files_scanned=0`, with
    nothing said on either stream, is what let an EMPTY tree be certified in
    silence: the step was scored a plain PASS and stayed in the published
    executed-PASS numerator, while two of its siblings on the SAME step-3
    `all_of` answered the identical tree with rc 1 (`cdc_crossing_check`) and
    rc 2 (`clock_domain_reg_crossing_check`).

    THE PREDICATE IS `files_scanned`, NOT `files_scanned + files_skipped`. A
    tree whose every RTL file was EXCLUDED by the #615 scan-scope policy
    (synth/PnR outputs, vendor staging, sim intermediates) also examined
    nothing authoritative, and that is equally a vacuous result rather than a
    clean one.

    NOTE this gate's `summary["skipped"]` is a #615 transparency LIST of the
    files the scan excluded — a population, not a flag — so
    `_vacuous_exit.summary_is_skipped` must NOT be used on it. The boolean is
    derived here, from the count that actually decides the question.

    Chip-AGNOSTIC: the predicate is "how many files did I read" — nothing about
    any design, PDK, vendor or cell.
    """
    if not result.passed:
        return "FAIL"
    if int(result.summary.get("files_scanned", 0) or 0) == 0:
        return _VACUOUS_VERDICT
    return "PASS"


def _emit_vacuous_disclosure(stream=None) -> None:
    """Disclose a zero-file scan so the FLOW, not only a human, can read it.

    WHY THIS FUNCTION TAKES NO PROJECT PATH. That omission is the fix.

    `flow_compliance_check.output_snippet` hands every consumer a FIXED-WIDTH
    TAIL of each stream (`_OUTPUT_SNIPPET_CHARS`, 300 characters) and
    `_stdout_signals_vacuous` matches the sentinel AT LINE START. A disclosure
    therefore survives only if it sits inside that trailing window with its
    first character intact.

    The FIRST attempt at this fix printed one line that interpolated the
    resolved project path. MEASURED on this tree — one gate, one empty project,
    one variable:

        project path 131 chars -> disclosure SEEN
        project path 132 chars -> disclosure GONE; rc 0, scored a plain PASS

    (`cdc_async_input_check` flipped at 123/124.) Whether a blocking gate told
    the truth was a function of how deep the checkout happened to sit — the
    same path-length lottery `flow_compliance_check._CRASH_HINT_PREFIX` was
    introduced to end one defect class earlier, reintroduced one layer down,
    and invisible to any test written against a short `tmp_path`.

    So the stream that carries the sentinel carries NOTHING ELSE, and every
    character on it comes from a module constant. Its total length is fixed at
    import time, is far below the window, and cannot be moved by the caller —
    which makes the tail cut a no-op on it at every checkout depth rather than
    a cut this line happens to fit under today.

    The path is not lost: it is in the JSON report the clause already writes,
    and in the step line's own command. It is simply not allowed onto the
    channel whose width is fixed.

    stderr, per `_vacuous_exit`: `--json -` puts the report document on stdout
    and a sentinel mixed into it would not parse. `output_snippet` concatenates
    both streams, so the token is read either way.
    """
    _vx.announce_vacuous("reset_dependency_check", _VACUOUS_REASON,
                         stream=stream if stream is not None else sys.stderr)


def strip_comments(src: str) -> str:
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i+2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


# ORGANIC #615 — circular-reset is a STRUCTURAL-RTL concern. A flat
# gate-level netlist (post-synth / post-PnR) instantiates library leaf cells,
# not the design's reset-graph modules, so re-parsing the multi-MB netlist
# carries no module-instance reset hierarchy worth checking — the design RTL
# already holds the full reset structure. Scanning those netlists was the
# entire 380s/invocation cost. Skip them (and any machine-generated multi-MB
# file) so the gate stays fast; skips are LOGGED (no silent cap).
_SYNTH_PNR_DIR_PARTS = {"synth", "pnr", "cts"}
# machine-emitted netlist filename stems (the token must END the stem so a
# design file like `my_synthesizer.v` is NOT mistaken for a `_synth` netlist).
_NETLIST_STEM_SUFFIXES = ("_synth", "_pnr", "_sv2v", "_route", "_routed",
                          "_postroute")
_SIZE_FLOOR_BYTES = 2_000_000  # 2 MB — only flat gate-level netlists reach this


def _is_netlist_name(name: str) -> bool:
    """True iff `name` is a machine-emitted netlist filename: it contains
    `netlist` (netlist.v / netlist_yosys.v) or its stem ends in a synth/PnR
    suffix (chip_top_synth.v / top_pnr.v / chip_top_sv2v.v). The end-anchored
    suffix check avoids matching a design file such as `my_synthesizer.v`."""
    n = name.lower()
    if not n.endswith((".v", ".sv")):
        return False
    if "netlist" in n:
        return True
    stem = n.rsplit(".", 1)[0]
    return stem.endswith(_NETLIST_STEM_SUFFIXES)


def _is_synth_or_pnr_output(path: Path, root: Path) -> bool:
    """True iff `path` is a synthesis / PnR output (a backend-stage dir or a
    netlist-named file), i.e. NOT hand-written design RTL. Chip-AGNOSTIC:
    flow-stage directory names + machine-emitted netlist filename conventions,
    no chip-specific literal."""
    try:
        parts = [p.lower() for p in path.relative_to(root).parts[:-1]]
    except ValueError:
        parts = [p.lower() for p in path.parts[:-1]]
    if _SYNTH_PNR_DIR_PARTS.intersection(parts):
        return True
    return _is_netlist_name(path.name)


def find_rtl_files(project_dir: Path,
                   _skipped: "Optional[List[Tuple[str, str]]]" = None
                   ) -> List[Path]:
    files = []
    for ext in ('*.v', '*.sv'):
        files.extend(project_dir.rglob(ext))
    kept: List[Path] = []
    for f in files:
        if not f.is_file():
            continue
        reason = None
        if _is_synth_or_pnr_output(f, project_dir):
            reason = "synth/pnr output (no design reset hierarchy)"
        else:
            try:
                if f.stat().st_size > _SIZE_FLOOR_BYTES:
                    reason = f"size>{_SIZE_FLOOR_BYTES}B (machine-generated)"
            except OSError:
                pass
        if reason is not None:
            if _skipped is not None:
                _skipped.append((str(f), reason))
            continue
        kept.append(f)
    return kept


# Module instance: <TypeName> <inst_name> ( .port(sig), ... );
INSTANCE_RE = re.compile(
    r'\b([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(\s*((?:\.\w+\s*\([^)]*\)\s*,?\s*)+)\)\s*;',
    re.MULTILINE,
)
# Reset port names of interest
RESET_PORT_RE = re.compile(r'\.(rstn|rst_n|rst|reset|resetn|rst_sync|rstn_sync)\s*\(\s*([^)]+)\s*\)')
# Reset-combining assign: `assign foo_rstn = a & b;`
RESET_ASSIGN_RE = re.compile(
    r'\bassign\s+(\w*(?:rst|reset)\w*)\s*=\s*([^;]+);'
)
# Done-style producer signal extraction (tokens in RHS)
TOKEN_RE = re.compile(r'\b([a-zA-Z_]\w*)\b')


def collect_instances(src: str) -> List[Tuple[str, str, Dict[str, str], int]]:
    """Return [(module_type, inst_name, port_map, lineno)]."""
    out = []
    for m in INSTANCE_RE.finditer(src):
        mtype, iname, ports = m.group(1), m.group(2), m.group(3)
        if mtype in ('module', 'endmodule', 'assign', 'wire', 'reg', 'logic',
                     'input', 'output', 'inout', 'parameter', 'localparam',
                     'always', 'always_ff', 'always_comb', 'begin', 'end',
                     'if', 'else', 'for', 'case', 'endcase', 'generate',
                     'endgenerate', 'function', 'endfunction', 'task', 'endtask',
                     'initial', 'return'):
            continue
        port_map: Dict[str, str] = {}
        for pm in re.finditer(r'\.(\w+)\s*\(\s*([^)]*)\s*\)', ports):
            port_map[pm.group(1)] = pm.group(2).strip()
        lineno = src[:m.start()].count('\n') + 1
        out.append((mtype, iname, port_map, lineno))
    return out


def reset_connection(port_map: Dict[str, str]) -> str:
    for pname in ('rstn', 'rst_n', 'rst', 'reset', 'resetn', 'rst_sync', 'rstn_sync'):
        if pname in port_map:
            # Take the first identifier in the expression
            expr = port_map[pname]
            tok = TOKEN_RE.search(expr)
            if tok:
                return tok.group(1)
    return ''


def output_signals(port_map: Dict[str, str]) -> Set[str]:
    """
    Without knowing port directions, treat every non-reset / non-clk port's
    connected signal as a potential output. Works as a conservative set.
    """
    skip = {'rstn', 'rst_n', 'rst', 'reset', 'resetn', 'rst_sync', 'rstn_sync',
            'clk', 'clock', 'clk_in', 'clk_sys'}
    out: Set[str] = set()
    for p, expr in port_map.items():
        if p in skip:
            continue
        tok = TOKEN_RE.search(expr)
        if tok:
            out.add(tok.group(1))
    return out


def find_done_producers_per_instance(
    instances: List[Tuple[str, str, Dict[str, str], int]]
) -> Dict[str, str]:
    """Return map done_signal -> inst_name (instance that produces it)."""
    mapping: Dict[str, str] = {}
    for mtype, iname, pmap, _ in instances:
        for sig in output_signals(pmap):
            # "done-ish" output names
            if re.search(r'(done|ready|valid|ok|ack|ready_out)$', sig):
                mapping[sig] = iname
    return mapping


def audit_file(path: Path, project_root: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        raw = path.read_text(errors='replace')
    except Exception:
        return findings
    src = strip_comments(raw)

    rel = str(path.relative_to(project_root)) if path.is_relative_to(project_root) else str(path)

    instances = collect_instances(src)
    if not instances:
        return findings

    inst_reset: Dict[str, str] = {iname: reset_connection(pmap)
                                  for _, iname, pmap, _ in instances}
    inst_line: Dict[str, int] = {iname: ln for _, iname, _, ln in instances}
    done_producer = find_done_producers_per_instance(instances)

    # Pattern A: reset-combining assign brings a done-signal into a reset,
    # and that done-signal's producer is reset by the same combined reset.
    for m in RESET_ASSIGN_RE.finditer(src):
        rst_sig = m.group(1)
        rhs = m.group(2)
        rhs_tokens = set(TOKEN_RE.findall(rhs))
        lineno = src[:m.start()].count('\n') + 1
        for tok in rhs_tokens:
            if tok not in done_producer:
                continue
            producer_inst = done_producer[tok]
            producer_rstn = inst_reset.get(producer_inst, '')
            if producer_rstn == rst_sig:
                findings.append(Finding(
                    rule='CIRCULAR_RESET_DEPENDENCY',
                    severity='ERROR',
                    message=(f"reset '{rst_sig}' combines '{tok}', which is "
                             f"produced by instance '{producer_inst}' whose "
                             f"own reset is '{producer_rstn}' — circular: "
                             f"{rst_sig} <- {tok} <- {producer_inst} <- {rst_sig}"),
                    file=rel,
                    line=lineno,
                ))

    # Pattern B: direct 2-node cycle via instance reset graph.
    # A.rstn = sig_from_B; B.rstn = sig_from_A.
    # ORGANIC #548 (b) — pre-indexed for O(N·M) instead of O(N²·M):
    #   reset_from[sig]  = {instances that use `sig` as their reset}
    #   inst_portmap[nm] = the port-map dict (avoids a linear search per pair)
    #   inst_outs_cache  = memoised output_signals per instance
    # The old triple-loop (O(N²·M), ~10^8 iters for a 10k-cell flat
    # netlist) caused >300s on 10MB post-synth Verilog; this version is
    # typically O(N·avg_fanin_of_reset_sinks) ≈ O(N).
    reset_from: Dict[str, List[str]] = {}
    for iname, rsig in inst_reset.items():
        if rsig:
            reset_from.setdefault(rsig, []).append(iname)

    inst_portmap: Dict[str, Dict[str, str]] = {
        iname: pmap for _, iname, pmap, _ in instances
    }
    inst_outs_cache: Dict[str, Set[str]] = {}

    def _outs(nm: str) -> Set[str]:
        if nm not in inst_outs_cache:
            inst_outs_cache[nm] = output_signals(inst_portmap.get(nm, {}))
        return inst_outs_cache[nm]

    seen_b_pairs: Set[tuple] = set()
    for _, ia, pa, _ in instances:
        rstn_a = inst_reset.get(ia, '')
        if not rstn_a:
            continue
        for outa in _outs(ia):
            for ib in reset_from.get(outa, []):
                if ib == ia:
                    continue
                pair = (min(ia, ib), max(ia, ib))
                if pair in seen_b_pairs:
                    continue
                if rstn_a in _outs(ib):
                    seen_b_pairs.add(pair)
                    findings.append(Finding(
                        rule='CIRCULAR_RESET_DEPENDENCY',
                        severity='ERROR',
                        message=(f"2-node reset cycle: '{ia}' reset '{rstn_a}' "
                                 f"sourced from '{ib}', which is reset by "
                                 f"'{inst_reset[ib]}' sourced from '{ia}'."),
                        file=rel,
                        line=inst_line.get(ia, 0),
                    ))
    return findings


def audit(project_dir: str) -> AuditResult:
    root = Path(project_dir).resolve()
    result = AuditResult(program='reset_dependency_check', passed=True)
    if not root.exists():
        result.findings.append(Finding(
            rule='PROJECT_DIR_MISSING', severity='ERROR',
            message=f"project_dir not found: {project_dir}"))
        result.passed = False
        result.summary = {'files_scanned': 0, 'violations': 1}
        result.verdict = 'FAIL'
        return result

    skipped: List[Tuple[str, str]] = []
    files = find_rtl_files(root, _skipped=skipped)
    # de-duplicate findings by (rule, file, line, message)
    seen: Set[Tuple[str, str, int, str]] = set()
    for f in files:
        for fd in audit_file(f, root):
            key = (fd.rule, fd.file, fd.line, fd.message)
            if key in seen:
                continue
            seen.add(key)
            result.findings.append(fd)

    result.passed = len(result.findings) == 0
    result.summary = {
        'files_scanned': len(files),
        'violations': len(result.findings),
        # ORGANIC #615 — transparency: report (not silently drop) the
        # synth/PnR-output + multi-MB files excluded from the structural scan.
        'files_skipped': len(skipped),
        'skipped': [{'file': fp, 'reason': rsn}
                    for fp, rsn in skipped[:50]],
    }
    result.verdict = _verdict_for(result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", nargs="?", const="-", default=None,
                   help="Emit JSON. With no value → stdout. With a path → write file.")
    args = p.parse_args()
    result = audit(args.project_dir)
    # ORGANIC #887 — say it BEFORE the report is emitted, on the stream whose
    # width is fixed. See `_emit_vacuous_disclosure`.
    if result.verdict == _VACUOUS_VERDICT:
        _emit_vacuous_disclosure()
    if args.json is not None:
        payload = json.dumps(asdict(result), indent=2)
        if args.json == "-":
            print(payload)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(payload)
    else:
        for f in result.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity}] {f.rule} ({loc}): {f.message}")
        # ORGANIC #887 — the WORD comes from `result.verdict`, derived from the
        # same `files_scanned` the line prints right beside it. Printing "PASS"
        # next to `files_scanned: 0` was the machine defect stated in human,
        # out of two numbers this object had in hand the whole time.
        print(f"\n{result.verdict} — {result.summary}")
    # ORGANIC #887 — rc 2, from the SHARED router, not a local literal. See the
    # matching note in `cdc_async_input_check.main`: the P0 structural-RTL
    # umbrella classifies rc 0 as a plain PASS record without reading either
    # stream, so a printed sentinel alone leaves that consumer misinformed.
    sys.exit(_vx.exit_code(result.passed,
                           result.verdict == _VACUOUS_VERDICT))


if __name__ == "__main__":
    main()
