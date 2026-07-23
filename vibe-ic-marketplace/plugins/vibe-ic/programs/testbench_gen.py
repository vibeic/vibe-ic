#!/usr/bin/env python3
"""testbench_gen.py — emit unit testbenches from L10 test_cases.

Reads `<project>/generated_docs/L10_TEST_CASES.json` and emits one .v TB
per test case under `<project>/sim/tb/`.

For AID-class chips, the canonical reference TB
`tools/protocol_tb/aid_class_reference_tb.v` is reused; this generator
ships per-test-case TB only for unit-level tests (single-module).

chip-AGNOSTIC. Replaces skills `testbench-gen` and `rtl-unit-testbench-gen`
(archived).

SUBSTANCE CONTRACT (the #209 fix)
---------------------------------
This generator emits a testbench that INSTANTIATES THE DUT and CAN FAIL, or it
emits NOTHING and says why. It never emits a file that prints a PASS it did not
verify.

Until this fix it emitted a vacuous skeleton: a portless module that printed
`PASS_PLACEHOLDER (replace with real stimulus)` with the DUT instantiation left
COMMENTED OUT. Every such file was a green light nobody earned — the sim log
said PASS, the design was never driven, and `l10_tb_conformance_check` credited
the case because the case id appeared in the TB text. `vacuous_testbench_check`
(#209) now FAILs a run containing one, and `l10_tb_conformance_check` (#206)
suppresses its evidence, so the skeleton had already lost all of its value as
coverage evidence while keeping all of its power to mislead. This generator no
longer produces it.

What it emits instead: the DUT port surface is parsed from the synthesizable
RTL (`reset_clock_variant_alias.parse_module_ports`, the same parser the
chip_top wrapper gen trusts), every port is declared at its real width, the DUT
is instantiated LIVE with named connections, clock and reset are driven, and
the TB asserts the one property that is true of every correct design regardless
of what it does — NO OUTPUT MAY REMAIN X/Z ONCE RESET HAS BEEN RELEASED. That
check is genuinely falsifiable: a DUT whose outputs are undriven or whose reset
does not take fails it, `$fatal(1)` fires, and `vvp` exits non-zero.

What it deliberately does NOT claim: this is a SUBSTANCE floor, not a
functional oracle for the L10 case. The case's own stimulus/expected text is
carried into a clearly-marked block for a real drive/compare to be written
against. A TB emitted here proves the design was built and driven; it does not
prove the case passed, and it does not print a message saying it did.

When the DUT cannot be resolved (no rtl/ yet, top module not found, port list
non-ANSI) or when the DUT exposes no outputs to check, NOTHING is written and
the reason is reported. A refusal is a real result; a placeholder is not.

Usage:
    python3 testbench_gen.py <project>
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl

# Generic, chip-AGNOSTIC signal-role vocabulary. These match on STRUCTURE of the
# identifier (a `clk`/`clock` token, a `rst`/`reset` token, an active-low `_n`
# suffix) — never on a chip, vendor, SKU or design name.
_CLOCK_RE = re.compile(r"(?:^|_)(?:clk|clock)(?:$|_)", re.IGNORECASE)
_RESET_RE = re.compile(r"(?:^|_)(?:rst|reset|resetn|rstn)(?:$|_)", re.IGNORECASE)
_ACTIVE_LOW_RE = re.compile(r"(?:_n$|n$|_b$|(?:^|_)(?:rstn|resetn)(?:$|_))",
                            re.IGNORECASE)
_LEGAL_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

# The emitted TB drives the DUT and can fail, but it does NOT verify the L10
# case's own oracle — it asserts the substance floor only. Without this marker
# the fix would trade one fabrication for a subtler one: `l10_tb_conformance_check`
# credits a case when its id appears in the testbench text, and a tree with a live
# instantiation does not trip the #206 evidence suppression. So a generated TB
# would silently CONVERT "no credit" into "covered" for a case nobody verified.
# The gate reads this marker and excludes the file from the evidence blob; the
# case stays uncovered until someone writes the oracle and deletes the line.
ORACLE_NONE_MARKER = "VIBEIC_TB_ORACLE: NONE (substance floor only)"
# Power / ground rails are TIED, never driven as stimulus, and never checked for
# X (they are legitimately undriven unless `USE_POWER_PINS is set).
_POWER_RE = re.compile(
    r"^(?:v(?:ccd|ssd|dda|ssa|pwr|gnd|dd|ss|bat|ccio|ssio|ddpst|ddio)|"
    r"vpb|vnb|gnd|dvdd|dvss|avdd|avss)\w*$", re.IGNORECASE)

# A module instantiation, for the instantiation-graph root search. Two
# identifiers before a '(' at a statement boundary, minus the keywords that
# share that shape.
_MODULE_DECL_RE = re.compile(r"^[ \t]*module\s+([A-Za-z_]\w*)", re.MULTILINE)
_INST_RE = re.compile(
    r"(?:^|[;\)]|\bend\b)\s*([A-Za-z_]\w*)\s*(?:#\s*\([^;]*?\)\s*)?"
    r"([A-Za-z_]\w*)\s*\(", re.MULTILINE | re.DOTALL)
_NON_INST_KEYWORDS = frozenset("""
module endmodule always always_ff always_comb always_latch initial final
begin end if else for while repeat forever case casex casez endcase default
task endtask function endfunction assign reg wire logic bit integer real time
input output inout parameter localparam generate endgenerate posedge negedge
wait disable package endpackage import typedef enum struct union
""".split())


# --------------------------------------------------------------------------
# DUT resolution — structural, from the RTL on disk
# --------------------------------------------------------------------------
def _rtl_sources(project: Path) -> List[Tuple[Path, str]]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return []
    out: List[Tuple[Path, str]] = []
    for ext in (".v", ".sv"):
        for f in sorted(rtl_dir.rglob(f"*{ext}")):
            try:
                out.append((f, f.read_text(errors="replace")))
            except OSError:
                continue
    return out


def _parse_ports(text: str, module: str) -> List[Tuple[str, str, str]]:
    """(direction, width_decl, name) for `module`, via the SHARED ANSI parser.

    Reusing `reset_clock_variant_alias.parse_module_ports` is what keeps this
    generator's view of the DUT surface identical to the chip_top wrapper gen's
    and the full-stack TB gen's — a TB bound to a different surface than the
    one the runner compiles against is uncompilable, which is the failure mode
    ORGANIC #629 / #643 / #671 were all opened for.
    """
    try:
        import reset_clock_variant_alias as _rcv
    except Exception:  # pragma: no cover — defensive import guard
        return []
    try:
        return _rcv.parse_module_ports(text, module) or []
    except Exception:
        return []


def resolve_dut(project: Path, top: str) -> Tuple[Optional[str],
                                                  List[Tuple[str, str, str]],
                                                  str]:
    """Resolve (module_name, ports, reason).

    Prefers `top` when it names a real module with a parseable ANSI port list.
    Falls back to the instantiation-graph ROOT when that is unambiguous — L9's
    top_module / --top is frequently a product or SKU name rather than an RTL
    module (ORGANIC #661), and binding a TB to a name with no definition emits
    a phantom instantiation that iverilog rejects.

    Returns `(None, [], reason)` when no DUT can be bound. The caller must then
    emit NOTHING: a testbench that cannot name its DUT cannot drive it, and a
    file that pretends otherwise is the defect this module exists to not
    reproduce.
    """
    sources = _rtl_sources(project)
    if not sources:
        return None, [], f"no RTL under {_pl.rtl_dir(project)} — nothing to instantiate"

    if top:
        for _f, txt in sources:
            ports = _parse_ports(txt, top)
            if ports:
                return top, ports, f"bound to --top module {top!r}"

    defined: Dict[str, str] = {}
    for _f, txt in sources:
        for m in _MODULE_DECL_RE.finditer(txt):
            defined.setdefault(m.group(1), txt)
    if not defined:
        return None, [], "no module declaration found in the RTL sources"

    instantiated = set()
    for _f, txt in sources:
        for m in _INST_RE.finditer(txt):
            mod, inst = m.group(1), m.group(2)
            if mod in _NON_INST_KEYWORDS or inst in _NON_INST_KEYWORDS:
                continue
            if mod in defined:
                instantiated.add(mod)
    roots = sorted(set(defined) - instantiated)
    if len(roots) == 1:
        ports = _parse_ports(defined[roots[0]], roots[0])
        if ports:
            return roots[0], ports, (
                f"--top {top!r} names no RTL module; bound to the unambiguous "
                f"instantiation-graph root {roots[0]!r}")
        return None, [], (
            f"instantiation-graph root {roots[0]!r} has no parseable ANSI port "
            f"list (non-ANSI header) — cannot bind a TB to it")
    return None, [], (
        f"--top {top!r} names no RTL module and the instantiation-graph root is "
        f"ambiguous ({len(roots)} candidates: {roots[:8]}) — refusing to guess")


# --------------------------------------------------------------------------
# TB emission
# --------------------------------------------------------------------------
def _classify(ports: List[Tuple[str, str, str]]):
    """Split the port surface into the roles the TB needs to drive/observe."""
    inputs, outputs, inouts = [], [], []
    for d, w, n in ports:
        if not n or not _LEGAL_ID_RE.match(n):
            continue          # a corrupted L9/RTL name would make the TB uncompilable
        d = (d or "input").strip().lower()
        w = (w or "").strip()
        if d.startswith("output"):
            outputs.append((n, w))
        elif d.startswith("inout"):
            inouts.append((n, w))
        else:
            inputs.append((n, w))
    return inputs, outputs, inouts


def _pick_clock(inputs) -> Optional[str]:
    for n, w in inputs:
        if not w and _CLOCK_RE.search(n):
            return n
    return None


def _pick_reset(inputs) -> Tuple[Optional[str], bool]:
    for n, w in inputs:
        if not w and _RESET_RE.search(n):
            return n, bool(_ACTIVE_LOW_RE.search(n))
    return None, False


def emit_unit_tb(case: dict, out_dir: Path, top: str,
                 ports: "List[Tuple[str, str, str]] | None" = None,
                 dut_module: "str | None" = None,
                 report: "dict | None" = None) -> Path | None:
    """Emit ONE unit TB for `case`, or return None and record why.

    `ports` is the DUT surface resolved once by `emit_unit_tbs` (parsing it per
    case would re-read the RTL for every test case). Passing `ports=None` is
    the refusal path: no DUT surface, no testbench.
    """
    name = case.get("name", "tb_unit")
    if not _LEGAL_ID_RE.match(name):
        if report is not None:
            report.setdefault("skipped", []).append(
                {"case": name, "reason": "case name is not a legal Verilog identifier"})
        return None
    opcode = case.get("opcode_hex", "0x00")
    expected = case.get("expected", "(see L3 response_payload_template)")
    kind = case.get("kind", "happy_path")
    polarity = case.get("polarity", "positive")
    stimulus = case.get("stimulus", "")
    dut = dut_module or top

    if not ports:
        if report is not None:
            report.setdefault("skipped", []).append(
                {"case": name, "reason": "DUT port surface unresolved"})
        return None

    inputs, outputs, inouts = _classify(ports)
    checkable = [(n, w) for n, w in outputs if not _POWER_RE.match(n)]
    if not checkable:
        # A TB with nothing to observe cannot fail, and a TB that cannot fail is
        # the placeholder defect wearing a live instantiation. Refuse.
        if report is not None:
            report.setdefault("skipped", []).append(
                {"case": name,
                 "reason": f"DUT {dut!r} exposes no non-power output — a TB over "
                           f"it could not fail, so none was emitted"})
        return None

    clk = _pick_clock(inputs)
    rst, rst_active_low = _pick_reset(inputs)

    def decl(kw: str, n: str, w: str) -> str:
        return f"  {kw} {w + ' ' if w else ''}{n};"

    lines: List[str] = []
    lines.append(f"// Auto-generated unit TB for case={name}")
    lines.append(f"// kind={kind} polarity={polarity}")
    lines.append(f"// stimulus: {stimulus}")
    lines.append(f"// expected: {expected}")
    lines.append("//")
    lines.append("// SUBSTANCE: this TB instantiates the DUT and CAN FAIL. It asserts the")
    lines.append("// universal post-reset property (no output may remain X/Z once reset is")
    lines.append("// released) and calls $fatal on violation, so vvp exits non-zero.")
    lines.append("// It is a substance FLOOR, not a functional oracle for the case above:")
    lines.append("// write the case's drive/compare into the marked block below. This TB")
    lines.append("// never prints a PASS for a check it did not run.")
    lines.append("//")
    lines.append(f"// {ORACLE_NONE_MARKER}")
    lines.append("// ^ machine-readable, read by l10_tb_conformance_check: this file is")
    lines.append("//   EXCLUDED from the Step-4 coverage-evidence blob while the marker is")
    lines.append("//   present, so merely existing never credits the case. Delete the marker")
    lines.append("//   line when a real oracle for this case has been written below.")
    lines.append("`timescale 1ns/1ps")
    lines.append(f"module {name};")
    for n, w in inputs:
        # Every input starts at 0 — including the clock, which the always-block
        # below toggles. An input left at X would make the DUT's outputs X and
        # turn the substance check into a false alarm about the TB, not the DUT.
        lines.append(f"  reg {w + ' ' if w else ''}{n} = 0;")
    for n, w in outputs:
        lines.append(decl("wire", n, w))
    for n, w in inouts:
        lines.append(decl("wire", n, w))
    lines.append("  integer errors = 0;")
    lines.append("")
    conns = ", ".join(f".{n}({n})" for n, _w in (inputs + outputs + inouts))
    lines.append(f"  {dut} u_dut ({conns});")
    lines.append("")
    if clk:
        lines.append(f"  always #5 {clk} = ~{clk};")
        lines.append("")
    lines.append("  initial begin")
    lines.append(f'    $display("[TB {name}] BEGIN — opcode={opcode} kind={kind}");')
    if rst:
        asserted, released = ("0", "1") if rst_active_low else ("1", "0")
        lines.append(f"    {rst} = 1'b{asserted};")
        lines.append(f"    #100 {rst} = 1'b{released};")
    else:
        lines.append("    #100;   // no reset port on this DUT surface")
    lines.append("")
    lines.append("    // ---- BEGIN case stimulus ----------------------------------------")
    lines.append(f"    //   {stimulus}")
    lines.append(f"    // expected: {expected}")
    lines.append("    // Drive the case's inputs and compare against `expected` here. Add a")
    lines.append("    // check that increments `errors` on mismatch; do NOT print a PASS")
    lines.append("    // without one.")
    lines.append("    #1000;")
    lines.append("    // ---- END case stimulus ------------------------------------------")
    lines.append("")
    lines.append("    // Universal post-reset substance check: a released design drives its")
    lines.append("    // outputs. Reduction-XOR is X when ANY bit of the bus is X or Z.")
    for n, _w in checkable:
        lines.append(f"    if ((^{n}) === 1'bx) begin")
        lines.append("      errors = errors + 1;")
        lines.append(f'      $display("[TB {name}] FAIL: output \'{n}\' is X/Z after reset release");')
        lines.append("    end")
    lines.append("")
    lines.append("    if (errors != 0) begin")
    lines.append(f'      $display("[TB {name}] FAIL — %0d check(s) failed", errors);')
    lines.append("      $fatal(1);")
    lines.append("    end")
    lines.append(f'    $display("[TB {name}] SUBSTANCE_OK — DUT {dut} driven, '
                 f'{len(checkable)} output(s) resolved (case oracle not yet written)");')
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")

    f = out_dir / f"{name}.v"
    f.write_text("\n".join(lines) + "\n")
    return f


def _detect_ic_class(project: Path) -> "str | None":
    """Best-effort ic_class detection so the per-case golden-oracle path can
    fire for the arithmetic-primitive family (chip-AGNOSTIC)."""
    try:
        import ic_class_profile as _icp  # type: ignore
        prof = _icp.detect_ic_class(project.resolve())
        if isinstance(prof, dict):
            return prof.get("ic_class")
    except Exception:
        pass
    return None


def _case_profile(case: dict) -> str:
    """Map an L10 case to a deterministic operand PROFILE for its golden oracle
    (chip-AGNOSTIC — keyed on the case's own semantic name tokens, not a SKU):
    a corner-operand case drives the enumerated corners; a random-equivalence /
    toggle-coverage case drives the pseudo-random tail; else a mix."""
    n = str(case.get("name", "")).lower()
    if "corner" in n or "edge" in n or "boundary" in n:
        return "corners"
    if ("random" in n or "toggle" in n or "branch" in n or "coverage" in n
            or "equivalence" in n):
        return "random"
    return "mixed"


def _emit_case_golden_oracle(project: Path, ic_class: "str | None",
                             case: dict, out_dir: Path,
                             report: "dict | None") -> "Path | None":
    """Emit a REAL per-case golden oracle TB (no ORACLE_NONE) for an L10
    `functional_vector` case, using the declared-function convention in
    arith_oracle_tb_gen. Returns the written path, or None when no closed-form
    oracle is derivable for this design (→ caller falls back to the substance
    floor; fail-closed)."""
    name = case.get("name", "")
    if not _LEGAL_ID_RE.match(str(name)):
        return None
    try:
        import arith_oracle_tb_gen as _aog  # type: ignore
    except Exception:
        return None
    try:
        text = _aog.emit_case_oracle(
            project, ic_class, str(name), _case_profile(case))
    except Exception as e:  # pragma: no cover — never let it break the loop
        if report is not None:
            report.setdefault("oracle_errors", []).append(
                {"case": name, "error": str(e)})
        return None
    if not text:
        return None
    f = out_dir / f"{name}.v"
    f.write_text(text)
    if report is not None:
        report.setdefault("golden_oracle_cases", []).append(str(name))
    return f


def emit_unit_tbs(project: Path, top: str = "chip_top",
                  kind: "str | None" = None,
                  report: "dict | None" = None) -> int:
    """ORGANIC #797 — importable producer entry point. Emit one unit TB per L10
    test case under `<project>/sim/tb/`, optionally KIND-SCOPED.

    Returns the number of TBs emitted, or a negative sentinel:
      -1  no L10_TEST_CASES.json — caller should SKIP
      -2  L10 present but the DUT could not be resolved from the RTL, so NOTHING
          was emitted. This is the #209 refusal: the previous behaviour was to
          emit a `PASS_PLACEHOLDER` skeleton with the DUT commented out, which
          is a fabricated green. `report["reason"]` carries the explanation.

    `kind` (e.g. `functional_vector`) restricts emission to cases of that kind —
    the §4.05 no-leak scoping: the runner wiring only auto-produces skeletons for
    `functional_vector` cases (whose oracle is an id-substring trace), so a
    `cmd_response` case whose oracle is the stricter opcode/summary path NEVER
    gets manufactured evidence and STILL fails the Step-4 gate when uncovered."""
    if report is None:
        report = {}
    l10_path = _pl.generated_docs_dir(project) / "L10_TEST_CASES.json"
    if not l10_path.is_file():
        report["reason"] = "no L10_TEST_CASES.json"
        return -1
    l10 = json.loads(l10_path.read_text())
    cases = [c for c in (l10.get("test_cases") or l10.get("cases") or [])
             if isinstance(c, dict)]
    if kind is not None:
        cases = [c for c in cases if c.get("kind") == kind]
    if not cases:
        report["reason"] = "no matching L10 test case"
        return 0

    dut_module, ports, reason = resolve_dut(project, top)
    report["dut_module"] = dut_module
    report["dut_resolution"] = reason
    if dut_module is None:
        report["reason"] = (
            f"refused to emit: {reason}. A testbench that cannot instantiate "
            f"the DUT would print a PASS it never verified (#209).")
        return -2

    out_dir = _pl.sim_dir(project) / "tb"
    out_dir.mkdir(parents=True, exist_ok=True)
    # For the arithmetic-primitive family the L10 functional_vector cases have a
    # closed-form golden (the declared function p = a OP b mod 2^N). Author a
    # REAL per-case golden oracle (drive the declared operands, compare the DUT
    # result === the independently-computed golden) so the case carries genuine
    # evidence l10_tb_conformance credits — the IC-expert convention, keyed on
    # interface shape, chip-AGNOSTIC. Fail-closed: any case whose golden is NOT
    # closed-form-derivable keeps the substance-floor scaffold (ORACLE_NONE), so
    # a case nobody can verify still fails the Step-4 gate honestly.
    ic_class = _detect_ic_class(project)
    emitted = 0
    for c in cases:
        wrote = None
        if str(c.get("kind", "")) == "functional_vector":
            wrote = _emit_case_golden_oracle(project, ic_class, c, out_dir,
                                             report)
        if wrote is None:
            wrote = emit_unit_tb(c, out_dir, top, ports=ports,
                                 dut_module=dut_module, report=report)
        if wrote is not None:
            emitted += 1
    if emitted == 0 and report.get("skipped"):
        report["reason"] = (
            "refused to emit any TB: "
            + "; ".join(s["reason"] for s in report["skipped"][:3]))
        return -2
    return emitted


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top", default="chip_top")
    p.add_argument("--kind", default=None,
                   help="emit ONLY cases of this L10 kind (e.g. "
                        "functional_vector); omit to emit every case")
    args = p.parse_args()
    report: dict = {}
    try:
        emitted = emit_unit_tbs(args.project, args.top, args.kind, report)
    except Exception as e:
        print(f"[FAIL] testbench_gen: L10 parse failed: {e}")
        return 1
    if emitted == -1:
        print("[SKIP] testbench_gen: no L10_TEST_CASES.json")
        return 0
    if emitted == -2:
        # Emitting nothing and saying so is the CORRECT outcome here, not an
        # error: the alternative the code used to take was a placeholder that
        # printed PASS without driving the design (#209). Exit 0 so a project
        # that has not reached RTL yet is not spuriously failed; the reason is
        # printed so it is never silent.
        print(f"[SKIP] testbench_gen: no TB emitted — {report.get('reason')}")
        return 0
    print(f"[PASS] testbench_gen: {emitted} unit TB files emitted "
          f"under sim/tb/"
          + (f" (kind={args.kind})" if args.kind else "")
          + (f" [DUT={report.get('dut_module')}]" if report.get("dut_module") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
