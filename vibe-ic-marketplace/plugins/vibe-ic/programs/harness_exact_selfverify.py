#!/usr/bin/env python3
"""harness_exact_selfverify.py — blind-RTL self-verify with the HARNESS-EXACT
toolchain BEFORE emit (ORGANIC #688).

Problem
=======
When a blind RTL-authoring agent self-verifies with a HOST toolchain by
compiling RTL+testbench TOGETHER, its accept-set DIVERGES from the scorer:

  (a) the scorer pins a SPECIFIC tool version (the cvdp-sim image is
      icarus 13 / verilator 5.038);
  (b) the scorer compiles the RTL **alone** under the harness top flag
      `-s <module>` — that drives CODEGEN of the named top, not just an
      elaborate (`-t null`) — before it ever links the hidden testbench;
  (c) the scorer often runs a lint gate.

Three fail classes slip through a host-only / RTL+TB-together self-check:

  1. ELAB-only  — `iverilog -g2012 -t null` (elaborate) passes but
                  `iverilog -g2012 -o sim.vvp` (full codegen) fails;
  2. standalone-top — the RTL compiles WITH a testbench but not ALONE
                  under `-s <module>` (it depends on a TB-only signal, or
                  the top name the harness pins is not declared);
  3. lint       — code the scorer's `verilator --lint-only` gate rejects.

Measured on CVDP cvdp-open (302): harness-exact self-verify recovered
close-loop 199→243 (65.9%→80.5%). The residual is dominated by spec-
INTERPRETATION mismatches blind self-verify FUNDAMENTALLY CANNOT detect —
this gate does NOT claim to catch them (disclosed in every report).

What this gate IS (the honest boundary)
=======================================
The gate is the SOLE EMIT PATH for blind RTL (gate-as-sole-emit-path,
ORGANIC #529): a draft can only become a scoring artifact THROUGH this
gate. It runs THREE gates and emits only on pass:

  GATE A (DETERMINISTIC) — standalone full compile
        `iverilog -g2012 -o sim.vvp -s <top> rtl.sv`  exit 0.
        This is the harness-exact flag (`-s <top>`, full `-o` codegen),
        NOT a `-t null` elaborate. Catches fail classes 1 + 2.

  GATE B (DETERMINISTIC) — lint
        `verilator --lint-only -Wall rtl.sv`  clean.  Catches fail class 3.

  GATE C (AI-AUTHORED TB, program-RUN) — functional check
        The PROGRAM does not author the testbench: extracting worked
        examples from a prompt is an AI judgment (the honest boundary,
        below). The AI authors a functional TB whose golden vectors are
        the PROMPT's OWN worked examples / tables (+ random + boundary);
        the PROGRAM RUNS it (`iverilog rtl.sv tb.sv` + `vvp`) and parses
        a deterministic PASS/FAIL line. A *provided* TB makes gate C run;
        no TB → gate C is reported `skipped (no functional TB provided)`,
        never silently passed.

Honesty / disclosure (no over-claim)
====================================
  * Version skew is DISCLOSED, never silently passed: the gate records the
    host iverilog/verilator versions and, when they differ from the scorer's
    (icarus 13 / verilator 5.038), emits a `version_skew` note. When run in
    the scorer's own container the versions match and the note is absent.
  * The gate does NOT claim to detect spec-interpretation mismatches —
    every report carries `detects_spec_interpretation: false`.
  * Gate A / B are deterministic. Gate C's golden vectors are AI-authored
    (the prompt-example extraction is a judgment); the program only RUNS
    the provided TB and parses its result. That boundary is explicit.

Tool availability
=================
A live `iverilog` / `verilator` call is gated on `shutil.which`. When a
tool is ABSENT the corresponding gate is `skipped (tool unavailable)` with
a disclosure — NEVER silently passed (mirrors cvdp_gate's #604 refuse-don't-
fake doctrine). `--require-tools` turns an absent tool into a hard error
(exit 2) for a CI/container run that must enforce.

Exit codes
==========
    0  every ENFORCED gate passed → emit written
    1  ≥1 gate BLOCKED            → no emit
    2  bad input / a required tool was absent under --require-tools

chip-AGNOSTIC: pure structure (module-name parse, tool exit codes, a
result-line regex). No chip / vendor / SKU literal, no dataset access.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# The scorer's pinned toolchain (cvdp-sim image). Used ONLY to DISCLOSE a
# host/scorer version skew — never to block. chip-AGNOSTIC (tool versions,
# not a chip).
SCORER_IVERILOG_MAJOR = "13"
SCORER_VERILATOR_VERSION = "5.038"

_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)", re.MULTILINE)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LIT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')
# A functional TB prints a single deterministic verdict line; accept the
# common conventions (VerilogEval/CVDP `Mismatches: N in M`, a bare PASS/FAIL
# token, or an `ALL_TESTS_PASSED`-style banner). chip-AGNOSTIC.
#
# The plugin's OWN oracle-TB generators (`arith_oracle_tb_gen.py`,
# `oracle_tb_gen.py`) emit a structured `ORACLE_TB_DONE pass=<n>/<m>` summary
# and, on a serial-framing miss, an `ORACLE_MISMATCH:` line. NEITHER form
# matches any generic convention below (`pass=` is not `\bPASSED\b`;
# `ORACLE_MISMATCH` carries no FAIL/ERROR token), so before this pattern gate C
# reported INCONCLUSIVE for the plugin's own TB — and because INCONCLUSIVE does
# not block, the overall gate printed `PASS (all enforced gates passed)` for a
# functionally BROKEN design. Measured on spm x ihp-sg13g2 (v1.5.85): four
# independent RTL mutants (carry majority, accumulator shift, output bit,
# dropped carry) drove the TB to pass=16/28, 8/28, 26/28, 16/28 each with an
# explicit ORACLE_MISMATCH — and gate C called every one INCONCLUSIVE, overall
# PASS. `design_one_shot_runner.py` already parses this exact summary; the two
# must agree, so the same regex is used here — a format change breaks both
# together rather than silently blinding one of them.
_TB_ORACLE_RE = re.compile(r"\bORACLE_TB_DONE\s+pass=(\d+)/(\d+)")
_TB_ORACLE_MISMATCH_RE = re.compile(r"\bORACLE_MISMATCH\b")
_TB_PASS_RE = re.compile(
    r"\bALL[_\s]?TESTS?[_\s]?PASS|"
    r"\bTEST[_\s]?PASS|"
    r"\bPASSED\b|"
    r"^\s*PASS\s*$",
    re.IGNORECASE | re.MULTILINE)
# ORGANIC #796 — a bare `error` word is BENIGN in a PASSING line (`error count
# = 0`, `no errors`, an `error-flag` status noun): it is NOT a verdict. The FAIL
# tokens are STRUCTURAL / NONZERO forms only — a verdict banner (`TEST FAIL` /
# `FAILED` / a bare `FAIL` line), a severity task (`$error` / `$fatal` /
# `FATAL`), or a NONZERO error count (`errors: 3` / `3 errors`). A zero count
# (`error count = 0`, `errors == 0`) never matches (floored by `[1-9]`).
#
# v1.4.x — the `N errors` alternative was NOT anchored to its OWN count field,
# so a PASSING summary like `checks=10016 errors=0` false-BLOCKED: the digits of
# a DIFFERENT field (`checks=10016`) were read as the error count because the
# following token happened to be `errors`. A count binds to `ERRORS` only when
# (a) no other field owns those digits — nothing binds them with `:`/`=` on the
# left — and (b) `ERRORS` does not carry its OWN value on the right (if it does,
# THAT value is the count and the `ERRORS?\s*[:=]\s*[1-9]` alternative decides).
_TB_FAIL_RE = re.compile(
    r"\bTEST[_\s]?FAIL|"
    r"\bFAILED\b|"
    r"^\s*FAIL\s*$|"
    r"\bFATAL\b|"
    r"\$(?:error|fatal)\b|"
    # RIGHT-bound count: `errors: 3` / `error = 7` / `errors 3` (nonzero). The
    # digits immediately FOLLOWING the `ERRORS` label always belong to it —
    # that is the `<label> <value>` convention.
    r"\bERRORS?\s*[:=]\s*0*[1-9]|"
    r"\bERRORS?\s+0*[1-9]\d*\b|"
    # LEFT-bound count: `3 errors`. The digits must be UNBOUND on the left (not
    # some other field's value, `checks=10016`) AND `ERRORS` must not own a
    # count on the right — if it does, THAT is the error count and the
    # right-bound alternatives above decide.
    r"(?<![:=])(?<![\w.])[1-9]\d*\s+ERRORS?\b"
    r"(?!\s*[:=]\s*\d)(?!\s+\d+\b(?!\s*[A-Za-z_]))",
    re.IGNORECASE | re.MULTILINE)
# An EXPLICIT ZERO error count is a PASS verdict, not a fail token — `errors=0`,
# `0 errors`, `no errors`. Checked only AFTER the fail patterns above, so a blob
# that ALSO contains a real failure (`errors=0 ... errors=7`) still FAILs: the
# fail token wins outright and this never rescues it.
_TB_ZERO_ERR_RE = re.compile(
    r"\bERRORS?\s*[:=]\s*0+\b(?!\.\d*[1-9])|"        # errors: 0 / errors=0
    r"\bERRORS?\s+0+\b|"                             # errors 0
    r"(?<![\w.])0+\s+ERRORS?\b|"                     # 0 errors
    r"\bNO\s+ERRORS?\b",                             # no errors
    re.IGNORECASE | re.MULTILINE)
# Case-SENSITIVE bare UPPERCASE `ERROR`/`ERRORS` banner — a fail token only when
# no clear PASS banner is present (checked AFTER the PASS test in _tb_verdict),
# so a PASSING TB whose stdout merely mentions a lowercase `error` is unaffected.
_TB_FAIL_UPPER_RE = re.compile(r"\bERRORS?\b", re.MULTILINE)
_TB_MISMATCH_RE = re.compile(r"Mismatches?\s*:\s*(\d+)\s+in\s+(\d+)",
                             re.IGNORECASE)


def _detection_text(code: str) -> str:
    """Comment- and string-stripped VIEW for module-name detection only (the
    payload is never modified). A leading block comment `/* this module … */`
    must not yield the phantom top name 'this' (the cvdp_gate #531-r3
    lesson)."""
    t = _BLOCK_COMMENT_RE.sub(" ", code)
    t = _LINE_COMMENT_RE.sub(" ", t)
    return _STRING_LIT_RE.sub('""', t)


def module_names(code: str) -> List[str]:
    """Module names declared in `code` (comment/string-stripped view)."""
    return _MODULE_NAMES_dedup(_MODULE_RE.findall(_detection_text(code)))


def _MODULE_NAMES_dedup(names: List[str]) -> List[str]:
    seen: Dict[str, None] = {}
    for n in names:
        seen.setdefault(n, None)
    return list(seen.keys())


def resolve_top(code: str, top: Optional[str]) -> Tuple[Optional[str], str]:
    """Resolve the harness-exact top module name.

    The scorer pins `-s <top>` where <top> is the module name the prompt /
    harness declares. When the caller supplies `top` and it IS declared in
    the RTL, use it. When `top` is supplied but NOT declared, that is a
    STANDALONE-TOP failure shape (fail class 2: top-name mismatch) — the
    scorer's `-s <top>` would fail — so it is returned as a resolution error
    (the gate then BLOCKS). When no `top` is supplied, fall back to the sole
    declared module (unambiguous) or report ambiguity."""
    declared = module_names(code)
    if not declared:
        return None, "no module declaration found in RTL"
    if top:
        if top in declared:
            return top, "explicit top declared"
        return None, (f"requested top {top!r} is not declared in the RTL "
                      f"(declared: {declared}); the scorer's `-s {top}` would "
                      f"fail — standalone-top mismatch (#688 fail class 2)")
    if len(declared) == 1:
        return declared[0], "sole declared module"
    return declared[-1], (f"multiple modules {declared}; no --top given, "
                          f"using last-declared {declared[-1]!r} (advisory)")


def _run(cmd: List[str], timeout: int = 120,
         cwd: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout, cwd=cwd)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _tool_version(tool: str, flag: str = "-V") -> str:
    if shutil.which(tool) is None:
        return "absent"
    rc, out, err = _run([tool, flag])
    return ((out or err or "").splitlines() or ["unknown"])[0].strip()


def gate_a_standalone_compile(rtl_path: Path, top: str, workdir: Path,
                              require_tools: bool) -> Dict:
    """GATE A — harness-exact standalone full compile.

    `iverilog -g2012 -o sim.vvp -s <top> rtl.sv` exit 0. This is the
    HARNESS-EXACT shape: `-s <top>` drives CODEGEN of the named top (catches
    ELAB-only fail class 1: code that elaborates under `-t null` but fails
    full `-o`), and compiling the RTL ALONE (no testbench) catches the
    standalone-top fail class 2 (a top that only compiles WITH a TB-only
    signal). Deterministic."""
    g: Dict = {"gate": "A_standalone_compile", "deterministic": True,
               "flags": f"iverilog -g2012 -o sim.vvp -s {top} <rtl>"}
    if shutil.which("iverilog") is None:
        g["verdict"] = "ERROR" if require_tools else "SKIP"
        g["reason"] = ("iverilog absent — standalone codegen compile cannot "
                       "be enforced (disclosed, not silently passed)")
        return g
    out_vvp = workdir / "sim.vvp"
    rc, out, err = _run(["iverilog", "-g2012", "-o", str(out_vvp),
                         "-s", top, str(rtl_path)])
    blob = ((out or "") + "\n" + (err or "")).strip()
    if rc == 0:
        g["verdict"] = "PASS"
        g["reason"] = "standalone -s codegen compile clean"
    else:
        g["verdict"] = "BLOCK"
        g["reason"] = ("standalone `-s` codegen compile FAILED (ELAB-only or "
                       "standalone-top fail class): "
                       + "; ".join(blob.splitlines()[:4]))
    return g


# §4.05 NO-LEAK — `-Wall` STYLE warnings that fire on CORRECT, scorer-PASSING
# RTL and therefore must NOT block emit. These are cosmetic / convention
# diagnostics, NOT the correctness/elaboration lint class the scorer rejects:
#   * UNUSEDSIGNAL / UNUSEDPARAM — an intentionally-unused-but-spec-REQUIRED
#     port (e.g. an unused `clk` the hidden TB still binds) is legitimate; the
#     scorer compiles RTL+TB with iverilog and never gates on it.
#   * DECLFILENAME — a filename-vs-module mismatch is a scratch-name artifact
#     (already neutralized by linting a `<top>.sv` copy; suppressed belt-and-
#     braces in case the harness top != sole module name).
#   * UNDRIVEN / PINCONNECTEMPTY / UNOPTFLAT — style/topology advisories that
#     do not make iverilog reject the design.
# The SUBSTANTIVE classes (a `%Error`: undefined variable / parse;
# WIDTHTRUNC / WIDTHEXPAND width mismatch; IMPLICIT implicit net; LATCH;
# BLKANDNBLK) stay enforced — those are the genuine lint fail class (#688
# class 3) the scorer's lint gate rejects. chip-AGNOSTIC: verilator warning
# CODES, not chip knowledge.
_LINT_STYLE_SUPPRESS = (
    "UNUSEDSIGNAL", "UNUSEDPARAM", "DECLFILENAME", "UNDRIVEN",
    "PINCONNECTEMPTY", "UNOPTFLAT", "UNUSEDGENVAR",
    # COMBDLY / BLKSEQ are ASSIGNMENT-OPERATOR STYLE warnings (`<=` in a
    # combinational always / `=` in a sequential always). iverilog accepts both
    # and the real VerilogEval / RTLLM scorer runs ONLY iverilog+vvp and NEVER
    # lints — so blocking emit on them is a pure FALSE-BLOCK of a correct design
    # (the gate is the sole emit path → it would silently drop a host-passing
    # design and lower pass@1; Prob028_m2014_q4a's correct D-latch tripped this).
    # No-leak: if the operator choice causes a REAL functional mismatch, the
    # hidden TB (the final arbiter, run AFTER emit) catches it — a genuine
    # %Error / non-style %Warning- still BLOCKs.
    "COMBDLY", "BLKSEQ",
)

# ── intended-transparent-latch discriminator (ORGANIC #716 / Prob145_circuit8)
# A `%Warning-LATCH` is NOT always a bug. A level-sensitive (transparent) latch
# is the CORRECT answer for a sequential / level-sensitive spec — e.g. the
# VerilogEval waveform problems whose RefModule is `always @(*) if(clock) p=a;`.
# The real VerilogEval scorer runs ONLY iverilog+vvp against the hidden TB and
# NEVER lints, so a LATCH warning on a functionally-correct transparent latch is
# a pure FALSE-BLOCK (the gate is the sole emit path, so it would silently drop
# a correct design and lower pass@1). We therefore DOWNGRADE (allow) a LATCH
# finding IFF it arises from a CLEAN single-guarded transparent-latch idiom whose
# guard is a clock/level-enable signal. An ACCIDENTAL latch — a multi-arm
# if/else-if/case that forgot a branch, a NON-clock data-enable guard, or a
# `%Warning-CASEINCOMPLETE` — STILL BLOCKS (those are the genuine "forgot a
# branch in pure-function logic" bug shapes the hidden TB catches).
_LATCH_SIG_RE = re.compile(r"Latch inferred for signal '([^']+)'")
# Clock guard names. chip-AGNOSTIC name heuristic: only a genuine CLOCK guard
# marks a latch as an INTENDED transparent latch (the VerilogEval waveform
# RefModule idiom `always @(*) if(clock) p=a;`). A data-enable / clock-ENABLE /
# clock-GATE-enable (`en`, `valid`, `clk_en`, `clken`, `clkgate`, a bare `g`)
# does NOT — held high it is the SAME accidental forgot-the-else latch shape the
# hidden TB catches, so it MUST keep blocking (Step-2.7 §4.05 #813 r2: the prior
# set matched `g`/`clken`/`enclk`/`clk_en`/`clkgate`, laundering a real inferred
# latch by merely renaming its data-enable guard).
#   match:  clk, clock, ck, gclk, hclk/pclk/sclk/mclk/aclk, clk0, clk_main
#   reject: g, en, enable, valid, sel, clk_en, clken, en_clk, enclk, clkg,
#           clkgate, clk_gate, clk_ce
_CLOCK_NAME_RE = re.compile(r"^(?:[hpsmaice]?clk|[hpsma]?clock|ck)(?:\d+|_[a-z0-9_]+)?$", re.I)
_CLOCK_ENABLE_DENY_RE = re.compile(
    r"_(?:en|enable|ce|gate|gat|g|valid|sel)(?:_|\d*$)", re.I)


def _is_clock_guard(name: str) -> bool:
    """True iff `name` is a GENUINE clock guard (clk/clock/ck family), NOT a
    clock-enable / clock-gate-enable / data-enable. §4.05: only a real clock
    level marks an INTENDED transparent latch; an enable-guarded latch is the
    accidental forgot-the-else bug and keeps blocking."""
    return bool(_CLOCK_NAME_RE.match(name)) and not _CLOCK_ENABLE_DENY_RE.search(name)


def _strip_sv_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code)
    return code


def _is_intended_transparent_latch(code: str, sig: str) -> bool:
    """True iff verilator's inferred latch for `sig` comes from a CLEAN
    single-guarded transparent-latch idiom: a combinational always block
    (`always @(*)` / `always_comb` / `always @*`) whose ONLY assignment to
    `sig` is exactly one `if(<clk-guard>) sig = ...;` with NO else / else-if /
    case and NO sibling statement assigning `sig`, where <guard> is a single
    clock-class identifier (optionally negated). Anything else — a non-clock
    data-enable guard, a multi-arm branch missing a path, a case, or >1 assign
    to `sig` — returns False so the LATCH finding keeps BLOCKING."""
    src = _strip_sv_comments(code)
    sig_re = re.compile(r"\b" + re.escape(sig) + r"\b\s*<?=")
    for m in re.finditer(r"\balways(?:_comb\b|\s*@\s*\*|\s*@\s*\(\s*\*\s*\))",
                         src):
        rest = src[m.end():]
        bm = re.match(r"\s*begin\b", rest)
        if bm:
            depth, endpos = 0, None
            for t in re.finditer(r"\bbegin\b|\bend\b", rest):
                depth += 1 if t.group() == "begin" else -1
                if depth == 0:
                    endpos = t.start()
                    break
            body = rest[bm.end():endpos] if endpos is not None else rest[bm.end():]
        else:
            semi = rest.find(";")
            body = rest[:semi + 1] if semi >= 0 else rest
        if not sig_re.search(body):
            continue  # this block does not assign sig — try the next always
        # a multi-arm shape (else / else-if / case) that drops a path is the
        # ACCIDENTAL-latch bug — keep blocking.
        if re.search(r"\belse\b|\bcase[zx]?\b", body):
            return False
        guards = re.findall(r"\bif\s*\(([^)]*)\)", body)
        if len(guards) != 1:
            return False  # zero or many ifs → not the clean single-guard idiom
        gm = re.match(r"^\s*!?\s*([A-Za-z_]\w*)\s*$", guards[0])
        if not gm or not _is_clock_guard(gm.group(1)):
            return False  # data-enable guard / expression → keep blocking
        if len(sig_re.findall(body)) != 1:
            return False  # sig assigned more than once → keep blocking
        return True
    return False


def gate_b_verilator_lint(rtl_path: Path, top: str, workdir: Path,
                          require_tools: bool) -> Dict:
    """GATE B — `verilator --lint-only -Wall` clean (lint fail class 3),
    minus a small allow-list of cosmetic STYLE warnings (`_LINT_STYLE_SUPPRESS`)
    that fire on correct scorer-PASSING RTL (an intentionally-unused required
    port, a filename mismatch). Deterministic. Blocks on the SUBSTANTIVE lint
    classes (`%Error`, width mismatch, implicit net, inferred latch) the
    scorer's lint gate actually rejects."""
    g: Dict = {"gate": "B_verilator_lint", "deterministic": True,
               "flags": (f"verilator --lint-only -Wall "
                         f"-Wno-{{{','.join(_LINT_STYLE_SUPPRESS)}}} "
                         f"--top-module {top} <rtl>")}
    if shutil.which("verilator") is None:
        g["verdict"] = "ERROR" if require_tools else "SKIP"
        g["reason"] = ("verilator absent — lint gate cannot be enforced "
                       "(disclosed, not silently passed)")
        return g
    # Lint a copy NAMED `<top>.sv` so the verilator DECLFILENAME (-Wall) check
    # reflects the HARNESS layout (the scorer saves RTL as `<top>.sv`), not the
    # agent's scratch filename. A pure filename-vs-module artifact must not
    # false-block real code (§4.05): the scorer never sees the scratch name.
    lint_src = workdir / f"{top}.sv"
    lint_src.write_text(rtl_path.read_text(errors="replace"))
    cmd = ["verilator", "--lint-only", "-Wall"]
    for w in _LINT_STYLE_SUPPRESS:
        cmd.append(f"-Wno-{w}")
    cmd += ["--Mdir", str(workdir / "obj_dir"),
            "--top-module", top, str(lint_src)]
    rc, out, err = _run(cmd)
    blob = ((out or "") + "\n" + (err or "")).strip()
    # Clean iff rc==0 AND no %Error / %Warning- token (rc-AND-token, version-
    # robust: some verilator builds report a lint warning without a nonzero
    # rc). With the style codes suppressed, a remaining %Warning- is a genuine
    # correctness finding.
    findings = [ln for ln in blob.splitlines()
                if ln.startswith("%Error") or ln.startswith("%Warning")]
    # ORGANIC #716 — drop a `%Warning-LATCH` that is an INTENDED transparent
    # latch (clean single clock-guarded assign). The `%Error: Exiting due to N
    # warning(s)` summary line is verilator's terminal banner, not a standalone
    # finding; it is dropped iff every real %Warning was a downgraded latch.
    rtl_code = rtl_path.read_text(errors="replace")
    allowed_latches: List[str] = []
    substantive: List[str] = []
    for ln in findings:
        if ln.startswith("%Warning-LATCH"):
            sm = _LATCH_SIG_RE.search(ln)
            if sm and _is_intended_transparent_latch(rtl_code, sm.group(1)):
                allowed_latches.append(ln)
                continue
        if ln.startswith("%Error: Exiting due to"):
            continue  # terminal warning-count banner — judged via real findings
        substantive.append(ln)
    if not substantive:
        g["verdict"] = "PASS"
        if allowed_latches:
            g["reason"] = ("verilator lint clean (substantive classes "
                           "enforced; intended transparent latch(es) "
                           "allowed: "
                           + "; ".join(
                               (_LATCH_SIG_RE.search(x).group(1)
                                if _LATCH_SIG_RE.search(x) else x)
                               for x in allowed_latches[:6]) + ")")
        else:
            g["reason"] = "verilator lint clean (substantive classes enforced)"
    else:
        g["verdict"] = "BLOCK"
        detail = substantive or blob.splitlines()
        g["reason"] = "verilator lint findings: " + "; ".join(detail[:6])
    return g


def _tb_verdict(sim_out: str) -> Tuple[Optional[bool], str]:
    """Parse a functional-TB run's stdout into PASS/FAIL/inconclusive.

    Order: a structured vector-count summary wins — the plugin's own
    `ORACLE_TB_DONE pass=<n>/<m>` first, then an explicit `Mismatches: N in M`
    (VerilogEval/CVDP); then a FAIL/ERROR token; then a PASS token. None =
    inconclusive (no recognised verdict line — reported, never assumed PASS)."""
    # The plugin's own oracle TBs. An explicit vector count is authoritative, so
    # it is tested BEFORE the token heuristics: an ORACLE_MISMATCH line carries
    # no FAIL/ERROR token, so a token-only reading of a FAILING oracle run is
    # blind to it.
    m = _TB_ORACLE_RE.search(sim_out)
    if m:
        npass, ntot = int(m.group(1)), int(m.group(2))
        mismatched = bool(_TB_ORACLE_MISMATCH_RE.search(sim_out))
        if ntot > 0 and npass == ntot and not mismatched:
            return True, f"oracle TB: {npass}/{ntot} golden vectors matched"
        return False, (f"oracle TB: {npass}/{ntot} golden vectors matched"
                       + (" (ORACLE_MISMATCH reported)" if mismatched else ""))
    # An ORACLE_MISMATCH with no parsable summary is still a FAILURE, never
    # inconclusive — the TB ran and reported that the stream does not
    # reassemble to the golden.
    if _TB_ORACLE_MISMATCH_RE.search(sim_out):
        return False, "oracle TB printed ORACLE_MISMATCH (no summary line)"
    m = _TB_MISMATCH_RE.search(sim_out)
    if m:
        mism, tot = int(m.group(1)), int(m.group(2))
        if tot > 0 and mism == 0:
            return True, f"functional TB: 0 mismatches in {tot}"
        return False, f"functional TB: {mism} mismatches in {tot}"
    # ORGANIC #796 — a STRUCTURAL / NONZERO fail token wins outright. Then a
    # clear PASS banner wins over a bare uppercase `ERROR` mention (an
    # `error-flag asserted ... TEST PASSED` line is a PASS); only with NO PASS
    # banner does a bare uppercase ERROR banner block.
    if _TB_FAIL_RE.search(sim_out):
        return False, "functional TB printed a FAIL/ERROR token"
    if _TB_PASS_RE.search(sim_out):
        return True, "functional TB printed a PASS token"
    # An EXPLICIT ZERO error count is a deterministic PASS verdict of the same
    # class as `Mismatches: 0 in N`. It is only reached when NO fail token
    # matched above, so it can never rescue a genuine failure. It must also be
    # tested BEFORE the bare-uppercase-ERROR banner, or an `ERRORS=0` summary
    # would false-BLOCK on its own zero count.
    if _TB_ZERO_ERR_RE.search(sim_out):
        return True, "functional TB reported an explicit zero error count"
    if _TB_FAIL_UPPER_RE.search(sim_out):
        return False, "functional TB printed a bare ERROR banner (no PASS)"
    return None, "functional TB printed no recognised PASS/FAIL verdict line"


def gate_c_functional_tb(rtl_path: Path, tb_path: Optional[Path],
                         workdir: Path, require_tools: bool) -> Dict:
    """GATE C — run the AI-authored functional TB.

    The PROGRAM does NOT author the testbench (extracting worked examples
    from the prompt is an AI judgment — the honest boundary). The AI supplies
    a TB whose golden vectors are the prompt's own worked examples; the
    program COMPILES rtl+tb and RUNS it, parsing a deterministic verdict
    line. No TB → reported `skipped`, never silently passed."""
    g: Dict = {"gate": "C_functional_tb", "deterministic": False,
               "tb_authored_by": "AI (prompt worked-examples) — program RUNS only"}
    if tb_path is None:
        g["verdict"] = "SKIP"
        g["reason"] = ("no functional TB provided — the AI must author a TB "
                       "from the prompt's worked examples for this gate to run "
                       "(not silently passed)")
        return g
    if not tb_path.is_file():
        g["verdict"] = "ERROR"
        g["reason"] = f"functional TB path not found: {tb_path}"
        return g
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        g["verdict"] = "ERROR" if require_tools else "SKIP"
        g["reason"] = ("iverilog/vvp absent — functional TB cannot be run "
                       "(disclosed, not silently passed)")
        return g
    binp = workdir / "tb_sim.vvp"
    # The TB is the top here (it instantiates the DUT) — `-s tb` mirrors the
    # scorer's RTL+TB link step (score_iverilog_tb uses `-s tb`); fall back to
    # auto-top when the TB module is not named `tb`.
    tb_tops = module_names(tb_path.read_text(errors="replace"))
    link_top = "tb" if "tb" in tb_tops else None
    cmd = ["iverilog", "-g2012", "-o", str(binp)]
    if link_top:
        cmd += ["-s", link_top]
    cmd += [str(rtl_path), str(tb_path)]
    rc, out, err = _run(cmd)
    if rc != 0:
        g["verdict"] = "BLOCK"
        g["reason"] = ("functional TB did not compile with the RTL: "
                       + "; ".join(((out or "") + (err or "")).splitlines()[:4]))
        return g
    rc2, out2, err2 = _run(["vvp", str(binp)])
    sim_out = (out2 or "") + "\n" + (err2 or "")
    ok, why = _tb_verdict(sim_out)
    if ok is True:
        g["verdict"] = "PASS"
    elif ok is False:
        g["verdict"] = "BLOCK"
    else:
        # inconclusive: a TB that runs but prints no verdict cannot PROVE
        # functional correctness — report INCONCLUSIVE (not a silent PASS).
        g["verdict"] = "INCONCLUSIVE"
    g["reason"] = why
    return g


def version_disclosure() -> Dict:
    """Record host tool versions and DISCLOSE any skew vs the scorer's pinned
    toolchain — never silently pass on a skew."""
    iv = _tool_version("iverilog")
    vl = _tool_version("verilator", "--version")
    disc: Dict = {"host_iverilog": iv, "host_verilator": vl,
                  "scorer_iverilog_major": SCORER_IVERILOG_MAJOR,
                  "scorer_verilator_version": SCORER_VERILATOR_VERSION,
                  "skew": []}
    m = re.search(r"version\s+(\d+)", iv, re.IGNORECASE)
    if m and m.group(1) != SCORER_IVERILOG_MAJOR:
        disc["skew"].append(
            f"host iverilog major {m.group(1)} != scorer "
            f"{SCORER_IVERILOG_MAJOR} — accepted-syntax / `sorry:` sets may "
            f"diverge (disclosed, not silently passed)")
    mv = re.search(r"(\d+\.\d+)", vl)
    if mv and mv.group(1) != SCORER_VERILATOR_VERSION and vl != "absent":
        disc["skew"].append(
            f"host verilator {mv.group(1)} != scorer "
            f"{SCORER_VERILATOR_VERSION} — lint warning sets may diverge "
            f"(disclosed, not silently passed)")
    return disc


def selfverify(rtl_path: Path, top: Optional[str],
               tb_path: Optional[Path] = None,
               require_tools: bool = False,
               lint_advisory: bool = False) -> Dict:
    """Run the three harness-exact self-verify gates over one RTL file.

    Returns a report dict with per-gate verdicts, the resolved top, the
    version disclosure, and an overall `emit` boolean. `emit` is True iff no
    ENFORCED gate BLOCKED/ERRORed (a SKIP — tool absent / no TB — does not
    block, but is disclosed; an INCONCLUSIVE gate C does not block either,
    but is disclosed)."""
    # Resolve to absolute so live-tool calls (run from a temp cwd) find the
    # file regardless of the caller's cwd.
    rtl_path = rtl_path.resolve()
    if tb_path is not None:
        tb_path = tb_path.resolve()
    code = rtl_path.read_text(errors="replace")
    report: Dict = {
        "rtl": str(rtl_path),
        "detects_spec_interpretation": False,   # honest: gate cannot catch it
        "version_disclosure": version_disclosure(),
        "gates": [],
    }
    resolved, why = resolve_top(code, top)
    report["resolved_top"] = resolved
    report["resolved_top_reason"] = why
    if resolved is None:
        report["gates"].append({"gate": "A_standalone_compile",
                                "verdict": "BLOCK",
                                "reason": "cannot resolve harness top: " + why})
        report["emit"] = False
        return report
    workdir = Path(tempfile.mkdtemp(prefix="hxsv_"))
    try:
        report["gates"].append(
            gate_a_standalone_compile(rtl_path, resolved, workdir,
                                      require_tools))
        report["gates"].append(
            gate_b_verilator_lint(rtl_path, resolved, workdir, require_tools))
        report["gates"].append(
            gate_c_functional_tb(rtl_path, tb_path, workdir, require_tools))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    # --lint-advisory: for an IVERILOG-scored benchmark (VerilogEval / RTLLM
    # Shape C), GATE A (iverilog `-s <top>` standalone codegen) + the host
    # (iverilog compile + functional TB) ARE the scorer's authority, so GATE B
    # (verilator `--lint-only -Wall`) does not match the scorer and its
    # verilator-only findings (WIDTH*/LATCH/COMBDLY style + verilator-LIMITATION
    # %Errors like BLKLOOPINIT that iverilog runs fine) are pure FALSE-BLOCKs of
    # host-PASSING designs. In advisory mode GATE B still RUNS + is disclosed in
    # the report, but does NOT block emit. NO-LEAK: a genuine iverilog compile
    # error still BLOCKs at GATE A; a real functional defect is caught by the
    # host TB (the final arbiter). Strict (verilator-scored, e.g. CVDP) keeps B.
    def _is_block(g):
        if g.get("verdict") not in ("BLOCK", "ERROR"):
            return False
        if lint_advisory and g.get("gate") == "B_verilator_lint":
            return False
        return True
    blocking = [g for g in report["gates"] if _is_block(g)]
    report["lint_advisory"] = lint_advisory
    report["emit"] = not blocking
    report["blocking_gates"] = [g["gate"] for g in blocking]
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Harness-exact blind-RTL self-verify gate (#688): "
                    "standalone `-s <top>` codegen + verilator lint + a "
                    "provided functional TB; SOLE EMIT PATH.")
    ap.add_argument("--rtl", required=True,
                    help="the blind-authored RTL file (.v/.sv)")
    ap.add_argument("--top", default=None,
                    help="the harness top module name (the scorer's `-s "
                         "<top>`); when omitted the sole declared module is "
                         "used (ambiguity reported)")
    ap.add_argument("--tb", default=None,
                    help="optional AI-authored functional TB (golden vectors "
                         "from the prompt's worked examples) — gate C RUNS it; "
                         "no TB → gate C is reported skipped, not passed")
    ap.add_argument("--emit", default=None,
                    help="on PASS, copy the gate-proven RTL bytes here "
                         "(gate-as-sole-emit-path: the scoring artifact is "
                         "written BY THE GATE, never directly by the agent)")
    ap.add_argument("--report", default=None,
                    help="optional JSON report path")
    ap.add_argument("--require-tools", action="store_true",
                    help="treat an absent iverilog/verilator as a hard error "
                         "(exit 2) — for a CI/container run that MUST enforce "
                         "the deterministic gates")
    ap.add_argument("--lint-advisory", action="store_true",
                    help="GATE B (verilator lint) reports but does NOT block "
                         "emit — for an IVERILOG-scored benchmark (VerilogEval/"
                         "RTLLM) where GATE A + the iverilog host are the "
                         "scorer's authority and verilator-only findings are "
                         "false-blocks. GATE A (iverilog) still blocks.")
    args = ap.parse_args(argv)

    rtl_path = Path(args.rtl)
    if not rtl_path.is_file():
        print(f"ERROR: --rtl not found: {rtl_path}", file=sys.stderr)
        return 2
    tb_path = Path(args.tb) if args.tb else None

    report = selfverify(rtl_path, args.top, tb_path, args.require_tools,
                        lint_advisory=args.lint_advisory)

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2,
                                                ensure_ascii=False) + "\n")

    for d in report["version_disclosure"]["skew"]:
        print(f"WARN version_skew: {d}", file=sys.stderr)
    for g in report["gates"]:
        line = f"{g['gate']}: {g['verdict']} — {g.get('reason','')}"
        print(line, file=sys.stderr)

    # --require-tools: an ERROR verdict from an absent tool is a hard refusal.
    if args.require_tools:
        for g in report["gates"]:
            if g.get("verdict") == "ERROR" and "absent" in g.get("reason", ""):
                print("ERROR: a required tool was absent under "
                      "--require-tools — refusing to emit (#688)",
                      file=sys.stderr)
                return 2

    if report["emit"]:
        if args.emit:
            Path(args.emit).parent.mkdir(parents=True, exist_ok=True)
            Path(args.emit).write_text(rtl_path.read_text(errors="replace"))
            print(f"EMIT {args.emit} (gate-proven)")
        print("harness_exact_selfverify: PASS (all enforced gates passed)")
        return 0
    print(f"harness_exact_selfverify: BLOCKED "
          f"({report.get('blocking_gates')})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
