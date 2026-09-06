#!/usr/bin/env python3
"""cdc_async_input_check.py — deterministic compliance check derived from <chip-class> v040 debug.

Verifies that asynchronous inputs (external pads, GPIO inputs, or PORTS named
*_pad / *_async / *_raw) pass through at least a 2-stage synchronizer flop
chain before being consumed by synchronous logic.

Heuristic (no full CDC analysis):
  - Find top-level module input/inout ports.
  - Among THOSE PORTS, flag the ones named *_pad / *_async / *_raw / *_ext or
    carrying a physical-pin name. An INTERNAL wire/reg is never an async input
    however it is spelled (RB2-06, #2063) — it has no clock domain to cross.
  - For each such signal, look for direct usage inside always @(posedge ...)
    blocks.
  - If the signal is not staged through at least 2 sequential `<=` assignments
    (a typical `_sync1 <= raw; _sync2 <= _sync1;` pattern), flag it.

Exit: 0 = PASS (no unsynchronized async inputs), 1 = FAIL,
      2 = VACUOUS_PASS (zero RTL files were examined — see `_verdict_for`).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtl_scan_scope as _scan_scope  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


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

        project path 123 chars -> disclosure SEEN
        project path 124 chars -> disclosure GONE; rc 0, scored a plain PASS

    (`reset_dependency_check` flipped at 131/132.) Whether a blocking gate told
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
    _vx.announce_vacuous("cdc_async_input_check", _VACUOUS_REASON,
                         stream=stream if stream is not None else sys.stderr)


def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, preserving newlines."""
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


def find_rtl_files(project_dir: Path) -> List[Path]:
    """Find authoritative RTL via the shared scan-scope policy (ORGANIC #545).

    The old local exclusion set matched a path component by EXACT equality
    (so `sim_full_stack` slipped past the `sim` entry) and did not exclude
    `input/` vendor staging or dot-dirs (`.fpga_stash`) — runner-generated
    sv2v-flattened intermediates and staged vendor RTL were then scanned as
    authoritative and produced ASYNC_INPUT_NO_SYNC false positives. The
    shared helper excludes by component PREFIX (sim*) + dot-dir + input/
    + oracle_run + build dirs."""
    return _scan_scope.authoritative_rtl_files(project_dir)


def find_input_ports(src: str) -> List[Tuple[str, int]]:
    """Return list of (signal_name, lineno) for input/inout ports."""
    ports = []
    for m in re.finditer(
        r'\b(input|inout)\s+(?:wire\s+|reg\s+|logic\s+)?'
        r'(?:signed\s+|unsigned\s+)?(?:\[[^\]]+\]\s*)?(\w+)',
        src
    ):
        name = m.group(2)
        lineno = src[:m.start()].count('\n') + 1
        ports.append((name, lineno))
    return ports


def find_suspicious_named_signals(src: str) -> List[Tuple[str, int]]:
    """Find signals named *_pad, *_async, *_raw."""
    sigs = []
    seen = set()
    for m in re.finditer(
        r'\b(?:input|inout|wire|reg|logic)\s+(?:\[[^\]]+\]\s*)?'
        r'(\w+_(?:pad|async|raw))\b',
        src
    ):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        lineno = src[:m.start()].count('\n') + 1
        sigs.append((name, lineno))
    return sigs


def is_synchronized(src: str, signal: str) -> bool:
    """
    Check if signal has at least a 2-stage synchronizer.
    Recognises:
      (a) direct 2-flop chain: `sync1 <= signal;` then `sync2 <= sync1;`
      (b) concatenation-based shift chain: `sync_q <= {sync_q[0], signal};`
          (common compact 2FF synchroniser).
      (c) signal used ONLY as async reset/clock in sensitivity lists
          (`always @(posedge clk or negedge signal)` — signal IS the reset
          and doesn't need further synchronising).
    Updated 2026-04-22 per LL feedback_plugin_usage_discipline.md to handle
    patterns (b) and (c) which were producing false positives.
    """
    # (c) used as async reset or clock in a sensitivity list
    sens_pat = re.compile(
        r'always\s*@\s*\([^)]*(?:posedge|negedge)\s+' + re.escape(signal) + r'\b'
    )
    if sens_pat.search(src):
        # It IS the clock/reset; no further sync required
        return True

    # (a) direct chain
    stage1_pat = re.compile(
        r'\b(\w+)\s*<=\s*' + re.escape(signal) + r'\s*;'
    )
    stage1_targets = set(m.group(1) for m in stage1_pat.finditer(src))

    # (b) concat shift: sync_q <= {sync_q[0], signal}; (or similar)
    concat_pat = re.compile(
        r'(\w+)\s*<=\s*\{[^}]*\b' + re.escape(signal) + r'\b[^}]*\}\s*;'
    )
    stage1_targets.update(m.group(1) for m in concat_pat.finditer(src))

    if not stage1_targets:
        return False

    # stage 2: something_else <= stage1_target (direct or via indexed bit)
    for t1 in stage1_targets:
        stage2_pat = re.compile(
            r'\b\w+\s*<=\s*(?:' + re.escape(t1) + r'|\{[^}]*\b' + re.escape(t1) + r'\b[^}]*\})'
        )
        if stage2_pat.search(src):
            return True
        # A shift-register `sync_q <= {sync_q[0], signal}` has sync_q[1] =
        # second stage by construction (width ≥ 2). Accept it as 2-stage.
        width_decl_pat = re.compile(
            r'\b(?:reg|logic|wire)\s*\[\s*(\d+)\s*:\s*0\s*\]\s*' + re.escape(t1) + r'\b'
        )
        m = width_decl_pat.search(src)
        if m and int(m.group(1)) >= 1:
            return True
    return False


def is_used_in_always_posedge(src: str, signal: str) -> Tuple[bool, int]:
    """Check if signal is read inside an always @(posedge ...) block."""
    # Scan each always @(posedge ...) ... end block
    # Heuristic: find `always @(posedge` and then capture text until a line
    # that starts a new always/assign/endmodule.
    for m in re.finditer(r'always\s*@\s*\(\s*posedge\b', src):
        start = m.start()
        # Find the matching end: naive — until next always/endmodule
        tail = src[start:]
        # cap scan length to ~4000 chars to avoid swallowing whole file
        region_end = min(len(tail), 4000)
        nxt = re.search(r'\n\s*(always\b|endmodule\b|assign\b)', tail[10:region_end])
        region = tail[:10 + nxt.start()] if nxt else tail[:region_end]
        # Skip if signal appears only on LHS of <=
        pat = re.compile(r'\b' + re.escape(signal) + r'\b')
        for mm in pat.finditer(region):
            pos = mm.start()
            rest = region[pos:pos + 120]
            if re.match(r'^\w+\s*<=(?!=)', rest):
                continue  # LHS
            # Found a read
            lineno = src[:start + pos].count('\n') + 1
            return True, lineno
    return False, 0


def audit_file(path: Path, project_root: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        raw = path.read_text(errors='replace')
    except Exception:
        return findings
    src = strip_comments(raw)

    # Collect inputs + suspicious names (dedup)
    candidates: List[Tuple[str, int]] = []
    seen: Set[str] = set()
    # RB2-06 (#2063) — THE PREMISE OF THIS WHOLE GATE IS PORT-NESS. An
    # asynchronous input is, by definition, a signal that ENTERS the module
    # from another clock domain: a declared `input` / `inout`. The suffix
    # arms below (`_pad|_async|_raw|_ext`, and the physical-pin names) are a
    # way of recognising WHICH port is async — they were never a way of
    # recognising a port. Applied to an internal wire they answer a question
    # nobody asked: an internal `wire b_raw = op2sr[0];` is generated by this
    # module's own flops in this module's own clock domain and has no domain
    # to cross. MEASURED on the subservient cell (lane rbsub2, 2026-09-06):
    # that one internal wire was reported ERROR ASYNC_INPUT_NO_SYNC and was
    # the ENTIRE failed-gate list of the phase-2/3 completion audit; renaming
    # it `b_lsb`, with the logic byte-identical, turned the same tree PASS.
    # A verdict that moves with a spelling and not with the design is not a
    # verdict about the design.
    #
    # This TIGHTENS the classifier's premise; it does not loosen the rule. A
    # real async input port named `x_raw` is still classified and still
    # required to carry a 2-stage synchroniser — the negative control for
    # this change asserts exactly that.
    #
    # Port-ness is read per FILE, which is the scope every other predicate in
    # this module already uses (`is_synchronized`, `is_used_in_always_posedge`
    # both scan `src`). chip-AGNOSTIC: HDL grammar only.
    port_names = {nm for nm, _ln in find_input_ports(src)}
    for name, lineno in find_input_ports(src) + find_suspicious_named_signals(src):
        if name in seen:
            continue
        seen.add(name)
        if name not in port_names:
            continue
        # Skip reset/clock pins (typical synchronizer exception)
        if re.match(r'^(clk|clock|rst|rstn|reset|resetn)(_.*)?$', name, re.I):
            continue
        # Skip OpenTitan-style internal hierarchy ports: `<name>_i` is a
        # convention for same-clock inputs (the parent drives from the same
        # clock). Only flag names that match KNOWN async patterns: physical
        # pad / GPIO / external pin / explicit async suffix. This removes the
        # false-positive flood on same-clock module hierarchies.
        # Updated 2026-04-22 per LL feedback_plugin_usage_discipline.md —
        # prior version flagged ALL inputs, producing 20+ bogus findings per
        # OpenTitan-style design.
        # Skip common OpenTitan software-driven signal prefixes — these are
        # APB/TL-UL register-file outputs, NOT async inputs. Lowercase `sw_*`
        # in OpenTitan means "software-controlled", not "switch".
        if re.match(r'^(sw_|hw_|reg_|wdog_|wkup_|intr_)', name):
            continue

        is_probable_async = (
            # Explicit async markers in the name (lowercase suffix)
            re.search(r'_(pad|async|raw|ext)$', name) is not None
            # Physical FPGA pin names — require uppercase start to avoid
            # matching lowercase `sw_*` software signals
            or re.match(r'^(KEY|BUTTON|SW|GPIO|MISO|MOSI|SDA|SCL|SCK|CS_N|BUS_RX|UART_RX)(_.*)?$',
                        name) is not None
        )
        if not is_probable_async:
            continue
        candidates.append((name, lineno))

    rel = str(path.relative_to(project_root)) if path.is_relative_to(project_root) else str(path)

    for name, decl_line in candidates:
        used, use_line = is_used_in_always_posedge(src, name)
        if not used:
            continue
        if is_synchronized(src, name):
            continue
        findings.append(Finding(
            rule='ASYNC_INPUT_NO_SYNC',
            severity='ERROR',
            message=(f"async input '{name}' used in always @(posedge) without "
                     "a 2-stage synchronizer chain"),
            file=rel,
            line=use_line or decl_line,
        ))
    return findings


def audit(project_dir: str) -> AuditResult:
    root = Path(project_dir).resolve()
    result = AuditResult(program='cdc_async_input_check', passed=True)
    if not root.exists():
        result.findings.append(Finding(
            rule='PROJECT_DIR_MISSING', severity='ERROR',
            message=f"project_dir not found: {project_dir}"))
        result.passed = False
        result.summary = {'files_scanned': 0, 'violations': 1}
        result.verdict = 'FAIL'
        return result

    files = find_rtl_files(root)
    for f in files:
        result.findings.extend(audit_file(f, root))

    result.passed = len(result.findings) == 0
    result.summary = {
        'files_scanned': len(files),
        'violations': len(result.findings),
    }
    result.verdict = _verdict_for(result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", nargs="?", default=".")
    # Accept both `--json` (bool, print to stdout) and `--json PATH` (write to file).
    # Unified 2026-04-22 with other report_check programs per LL
    # feedback_plugin_usage_discipline.md (14 gate-signature bugs).
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
            atomic_write_text(_P(args.json), payload)
    else:
        for f in result.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity}] {f.rule} ({loc}): {f.message}")
        # ORGANIC #887 — the WORD comes from `result.verdict`, derived from the
        # same `files_scanned` the line prints right beside it. Printing "PASS"
        # next to `files_scanned: 0` was the machine defect stated in human,
        # out of two numbers this object had in hand the whole time.
        print(f"\n{result.verdict} — {result.summary}")
    # ORGANIC #887 — rc 2, from the SHARED router, not a local literal.
    #
    # WHY THE EXIT CODE MOVES AND THE DISCLOSURE LINE IS NOT ENOUGH ON ITS OWN.
    # This gate has TWO consumers in `flow_compliance_check`, and only one of
    # them ever reads a printed sentinel:
    #
    #   * step 3's `program_exit_zero` clause — `__check_program_exit_zero`
    #     reads the (TRUNCATED) snippet on the rc==0 path, and on the rc==2
    #     path returns `__VACUOUS_HINT__` WITHOUT CONSULTING THE OUTPUT AT ALL.
    #   * the P0 structural-RTL umbrella — `_eval_gate_worker` classifies rc 0
    #     as `_p0_gate_record(..., "PASS", ...)` and never looks at stdout or
    #     stderr. A zero-file scan left at rc 0 is recorded there as a plain
    #     PASS however loudly it announces itself.
    #
    # rc 2 is this repo's own "the artefact I audit is not here" convention
    # (`_vacuous_exit`), it is what `clock_domain_reg_crossing_check` — a
    # sibling on the SAME step-3 `all_of` and in the SAME P0 registry — already
    # answers to the identical empty tree, and #887's own suggested fix names
    # it. It fails nothing: rc 2 is `passed=True` for the clause and a SKIP
    # (skip_kind `input-missing`) for the umbrella.
    sys.exit(_vx.exit_code(result.passed,
                           result.verdict == _VACUOUS_VERDICT))


if __name__ == "__main__":
    main()
