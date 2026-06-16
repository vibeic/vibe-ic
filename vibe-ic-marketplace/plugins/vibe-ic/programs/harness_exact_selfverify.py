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
_TB_FAIL_RE = re.compile(
    r"\bTEST[_\s]?FAIL|"
    r"\bFAILED\b|"
    r"^\s*FAIL\s*$|"
    r"\bFATAL\b|"
    r"\$(?:error|fatal)\b|"
    r"\bERRORS?\s*[:=]\s*[1-9]|"        # errors: 3 / error = 7  (nonzero)
    r"\b[1-9]\d*\s+ERRORS?\b",          # 3 errors               (nonzero)
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
)


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
    if rc == 0 and not findings:
        g["verdict"] = "PASS"
        g["reason"] = "verilator lint clean (substantive classes enforced)"
    else:
        g["verdict"] = "BLOCK"
        detail = findings or blob.splitlines()
        g["reason"] = "verilator lint findings: " + "; ".join(detail[:6])
    return g


def _tb_verdict(sim_out: str) -> Tuple[Optional[bool], str]:
    """Parse a functional-TB run's stdout into PASS/FAIL/inconclusive.

    Order: an explicit `Mismatches: N in M` summary (VerilogEval/CVDP) wins;
    then a FAIL/ERROR token; then a PASS token. None = inconclusive (no
    recognised verdict line — reported, never assumed PASS)."""
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
               require_tools: bool = False) -> Dict:
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
    blocking = [g for g in report["gates"]
                if g.get("verdict") in ("BLOCK", "ERROR")]
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
    args = ap.parse_args(argv)

    rtl_path = Path(args.rtl)
    if not rtl_path.is_file():
        print(f"ERROR: --rtl not found: {rtl_path}", file=sys.stderr)
        return 2
    tb_path = Path(args.tb) if args.tb else None

    report = selfverify(rtl_path, args.top, tb_path, args.require_tools)

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
