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
import argparse, json, re, shutil, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl
import _l10_execution as _l10x
from _atomic_artefact import write_text as _atomic_write_text
import _port_width  # resolve a `[aw-1:0]` cell over the DUT's own params, or refuse

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


def _resolve_widths(project: Path,
                    sources: List[Tuple[Path, str]],
                    module: str,
                    ports: List[Tuple[str, str, str]]
                    ) -> Tuple[Optional[List[Tuple[str, str, str]]], str]:
    """`(ports_with_literal_widths, why)` or `(None, refusal)`.

    The ANSI parser hands back the width cell VERBATIM, so a port declared
    `input [aw-1:0] adr` arrives as the cell `[aw-1:0]`. `aw` is a parameter of
    the DUT's own header and does not exist in the TB module's scope, so
    emitting the cell as written produced

        error: Unable to bind parameter `aw' in `tb_<case>'
        error: Dimensions must be a constant with no unknown or high-Z bits.

    and killed EVERY unit TB for that DUT (iverilog rc=2). The cell is now
    EVALUATED over the DUT's own parameter defaults by the shared `_port_width`
    resolver -- the same resolver the full-stack TB generator uses, so the two
    TBs cannot disagree about how wide a port is.

    The defaults, and not any instantiation override, are what elaborate here:
    the TB emits a bare `<dut> u_dut ( ... )` with no `#(...)`.

    A width that does not evaluate REFUSES, naming the symbol. It is not
    narrowed to one bit: a TB whose ports are the wrong width is a TB whose
    result means nothing, and one that says so is worth more than one that
    runs."""
    params = _port_width.defaults_from_sources(sources, module)
    # The same L9 numbers the full-stack TB generator uses. Without them the two
    # generators would disagree about a port whose cell needs a `define -- one
    # resolving it, the other refusing -- which is exactly the kind of split
    # view a single shared resolver exists to prevent.
    l9 = _port_width.l9_bounds(_pl.generated_docs_dir(project))
    resolved, refusals = _port_width.resolve_ports_with_l9(ports, params, l9)
    if refusals:
        return None, (
            f"DUT {module!r} declares {len(refusals)} port(s) whose width is "
            f"not derivable from its own parameter defaults "
            f"({params or 'none declared'}): " + "; ".join(refusals)
            + " -- refusing to emit a TB rather than declaring them 1 bit")
    return resolved, f"widths resolved over {params or 'no parameters'}"


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
                resolved, why = _resolve_widths(project, sources, top, ports)
                if resolved is None:
                    return None, [], why
                return top, resolved, f"bound to --top module {top!r}; {why}"

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
            resolved, why = _resolve_widths(project, sources, roots[0], ports)
            if resolved is None:
                return None, [], why
            return roots[0], resolved, (
                f"--top {top!r} names no RTL module; bound to the unambiguous "
                f"instantiation-graph root {roots[0]!r}; {why}")
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
    # v1.15.45 (sha256 capture) — NEVER regenerate over an authored oracle.
    # The scaffold's own instruction is "write the case's drive/compare into
    # the marked block and delete the marker line". An author who follows it
    # produces a file WITHOUT `ORACLE_NONE_MARKER`; re-emitting the scaffold
    # here on the next runner invocation erased that work and its evidence —
    # the same clobber `professional_tb_gen` closed for tb_<top>.py. A file
    # that still carries the marker is the scaffold itself and is refreshed.
    authored = out_dir / f"{name}.v"
    if authored.is_file():
        try:
            prior_text = authored.read_text(errors="replace")
        except OSError:
            prior_text = ""
        if prior_text and ORACLE_NONE_MARKER not in prior_text:
            if report is not None:
                report.setdefault("preserved_authored", []).append(
                    {"case": name, "path": str(authored)})
            return authored
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


# --------------------------------------------------------------------------
# The PRODUCER's declared SCOPE over the L10 layer  (#761)
# --------------------------------------------------------------------------
# ORGANIC #761 — one layer, two readers, two private scopes. The producer
# filtered L10 on the single literal `functional_vector`; `l10_tb_conformance_
# check` graded EVERY case in the layer. A measured run whose 95 L10 cases were
# typed {happy_path, addr_max, len_max, pre_wake_false} therefore produced
# `SKIP  no functional_vector L10 cases — nothing to produce` followed by
# `{"total": 95, "ok": 0, "fail": 95}` — a statement about the FILTER reported
# as a statement about the LAYER, and a 95-case markdown nothing in the run
# connected to it.
#
# The scope is now DECLARED here, once, and both readers use this one
# definition: the producer emits by it, and the consumer imports it to name the
# gap in its own FAIL. It is not a relaxation — the consumer still grades all
# 95 and still FAILs — it is the end of the two-private-filters shape.

#: The L10 `kind` vocabulary the substance-floor SCAFFOLD is auto-emitted for.
#: These are the same five tokens `l10_tb_conformance_check` recognises for its
#: CPU functional-oracle waiver (`_FUNCTIONAL_VECTOR_KINDS`); a producer that
#: recognised only ONE of them was the same scope defect one level down — a
#: `kind=functional` case was waivable by the consumer and unproducible by the
#: producer. chip-AGNOSTIC: a kind vocabulary, never a chip/vendor/SKU literal.
SCAFFOLD_KINDS = frozenset({
    # G19 — a declared known-answer vector is a functional case. It is named
    # here so `producer_scope` counts it IN scope; its own emitter runs before
    # the scaffold and, when it binds, the scaffold never sees the case.
    "known_answer_vector",
    "functional_vector",
    "functional",
    "functional_test",
    "instruction_test",
    "cpu_functional",
})

#: The kind the one-shot runner asks for. Named so the runner and the consumer
#: gate resolve the SAME scope from the SAME constant instead of each spelling
#: the literal out again.
DEFAULT_SCAFFOLD_KIND = "functional_vector"

#: The keys an L10 document may carry its case list under, in priority order.
#: This producer read only the first two while `l10_tb_conformance_check.load_l10`
#: read all five — a SECOND instance of the #761 shape hiding in the same pair of
#: files: an L10 keyed `vectors` was 0 cases to the producer and N cases to the
#: gate. One tuple, imported by both.
L10_CASE_LIST_KEYS = ("test_cases", "cases", "vectors", "cmd_response", "tests")


def case_kind(case: dict) -> str:
    """Normalised kind/category/type token for an L10 case (lowercased).

    Mirrors `l10_tb_conformance_check.case_kind` exactly — the two readers must
    not disagree about what a case's kind IS while arguing about which kinds are
    in scope."""
    raw = case.get("kind", case.get("category", case.get("type", "")))
    return str(raw or "").strip().lower()


def kind_histogram(cases: List[dict]) -> Dict[str, int]:
    """{kind: count} over an L10 case list, in descending count order."""
    hist: Dict[str, int] = {}
    for c in cases:
        k = case_kind(c) or "(none)"
        hist[k] = hist.get(k, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def scaffold_kind_scope(kind: "str | None") -> "frozenset | None":
    """The set of L10 kinds the SCAFFOLD is emitted for, given a `kind` request.

    `None` -> every kind. A kind inside the functional-vector family -> the
    WHOLE family (see `SCAFFOLD_KINDS`). Any other kind -> exactly that kind."""
    if kind is None:
        return None
    k = str(kind).strip().lower()
    return SCAFFOLD_KINDS if k in SCAFFOLD_KINDS else frozenset({k})


def load_l10_cases(project: Path) -> "List[dict] | None":
    """The L10 case list for `project`, or None when the layer is absent.

    Shared by the producer and (via import) by the consumer gate's scope
    report, so "how many cases does this layer carry" has ONE answer."""
    l10_path = _pl.generated_docs_dir(project) / "L10_TEST_CASES.json"
    if not l10_path.is_file():
        return None
    # A malformed L10 RAISES — it must not be reported as an ABSENT L10. "the
    # layer is not there" and "the layer is unreadable" are different facts, and
    # collapsing them is the same defect one file over (#761).
    l10 = json.loads(l10_path.read_text())
    if isinstance(l10, list):
        raw = l10
    else:
        raw = []
        for key in L10_CASE_LIST_KEYS:
            v = l10.get(key)
            if isinstance(v, list):
                raw = v
                break
    return [c for c in raw if isinstance(c, dict)]


def producer_scope(cases: List[dict],
                   kind: "str | None" = DEFAULT_SCAFFOLD_KIND) -> Dict[str, object]:
    """The PRODUCER's scope over `cases`, as a machine-readable record.

    This is the fact the #761 SKIP message stated backwards: it reports what
    the LAYER carries AND what the producer is scoped for, so neither number
    can be read as the other."""
    scope = scaffold_kind_scope(kind)
    in_scope = [c for c in cases if scope is None or case_kind(c) in scope]
    out_of_scope = [c for c in cases
                    if scope is not None and case_kind(c) not in scope]
    return {
        "total": len(cases),
        "kind_histogram": kind_histogram(cases),
        "requested_kind": kind,
        "scaffold_kinds": sorted(scope) if scope is not None else None,
        "in_scaffold_scope": len(in_scope),
        "out_of_scaffold_scope": len(out_of_scope),
        "out_of_scope_kinds": kind_histogram(out_of_scope),
    }


def describe_scope(scope: Dict[str, object]) -> str:
    """One-line human rendering of `producer_scope` — the LAYER fact first, the
    FILTER fact second, so a reader cannot mistake the second for the first."""
    hist = scope.get("kind_histogram") or {}
    kinds = ", ".join(f"{k} {v}" for k, v in hist.items()) or "(none)"
    scaffold = scope.get("scaffold_kinds")
    scaffold_txt = "{" + ", ".join(scaffold) + "}" if scaffold else "every kind"
    return (f"L10 carries {scope.get('total', 0)} case(s) [{kinds}]; the TB "
            f"producer's scaffold scope is {scaffold_txt} — "
            f"{scope.get('in_scaffold_scope', 0)} in scope, "
            f"{scope.get('out_of_scaffold_scope', 0)} out of scope")


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


def _emit_case_boot_latency_oracle(project: Path, case: dict,
                                   dut_module: str,
                                   ports: "List[Tuple[str, str, str]]",
                                   out_dir: Path,
                                   report: "dict | None") -> "Path | None":
    """ORGANIC #778 companion — emit a REAL reset-to-first-bus-activity
    LATENCY oracle TB (no ORACLE_NONE) for an L10 `functional_vector` case
    whose own stimulus+expected text describes a "within N cycles of reset
    release" boot-latency bound (chip-AGNOSTIC shape, any clocked core —
    see `cpu_boot_latency_oracle_tb_gen`). Returns None (defer to the
    substance-floor scaffold) when this case/DUT-surface pair is not a
    groundable boot-latency oracle — fail-closed, never fabricates."""
    name = case.get("name", "")
    if not _LEGAL_ID_RE.match(str(name)):
        return None
    try:
        import cpu_boot_latency_oracle_tb_gen as _clg  # type: ignore
    except Exception:
        return None
    inputs, outputs, inouts = _classify(ports)
    try:
        text = _clg.emit_case_oracle_from_ports(
            case, dut_module, inputs, outputs, inouts)
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
        report.setdefault("boot_latency_oracle_cases", []).append(str(name))
    return f



def _emit_case_known_answer_vector(project: Path, case: dict, dut_module: str,
                                   ports: "List[Tuple[str, str, str]]",
                                   out_dir: Path,
                                   report: "dict | None") -> "Path | None":
    """G19 — emit a REAL self-checking TB for an L10 `known_answer_vector`.

    This is the emitter the capture exists for: the case carries a TYPED
    expected value, so the TB drives the vector's inputs onto the DUT's own
    ports, compares the sampled outputs against the literal, increments
    `errors` and ends `$fatal(1)`. Nothing is written into a comment.

    Fail-closed like its two siblings: a vector whose every field does not bind
    to a port of this DUT at the value's own width returns None, the reason is
    recorded, and the case falls through to the substance floor — so a vector
    nobody can actually drive still fails the Step-4 gate honestly."""
    try:
        import known_answer_vector as _kav
        import known_answer_vector_tb_gen as _ktb
    except Exception:
        return None
    if not _kav.is_known_answer_vector(case):
        return None
    text, why = _ktb.emit_case_oracle_from_ports(case, dut_module, ports)
    if not text:
        # The design may state its transport — opentitan_aes does: "經自建 TB
        # 由 TL-UL register interface 驅動". A peripheral whose interface is a
        # BUS exposes no key/plaintext ports, so the port emitter refusing is
        # the normal case, not the end of it. Second route, same fail-closed
        # contract, and it drives what the design says it is driven over.
        text, why2 = _ktb.emit_case_register_bus(project, case, dut_module,
                                                 ports)
        if not text:
            why = f"{why}; register-bus route: {why2}"
    if not text:
        if report is not None:
            report.setdefault("known_answer_vector_unbound", []).append(
                {"case": case.get("name"), "reason": why})
        return None
    f = out_dir / f"{case.get('name')}.v"
    f.write_text(text)
    if report is not None:
        report.setdefault("known_answer_vector_cases", []).append(
            {"case": case.get("name"), "citation": case.get("citation")})
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

    `kind` (e.g. `functional_vector`) scopes the SUBSTANCE-FLOOR SCAFFOLD to the
    kind family it names (`scaffold_kind_scope`) — the §4.05 no-leak scoping: a
    `cmd_response` case whose oracle is the stricter opcode/summary path never
    gets an auto-emitted scaffold, so it STILL fails the Step-4 gate when
    uncovered.

    ORGANIC #761 — the kind filter used to drop out-of-scope cases before the
    REAL per-case oracle emitters ever saw them. Those emitters
    (`arith_oracle_tb_gen`, `cpu_boot_latency_oracle_tb_gen`) are keyed on the
    case's OWN declared text and interface shape and are fail-closed: they
    return None for anything they cannot ground. Gating them on a kind TOKEN
    denied a genuine golden to a case whose only defect was that Phase 1 typed
    it `happy_path` instead of `functional_vector`. They now run for EVERY case;
    the token-scoped part is the scaffold alone. This cannot fabricate evidence
    — a real oracle drives the declared stimulus and compares against an
    independently computed golden, or it emits nothing.

    `report["scope"]` always carries the `producer_scope` record, on every
    return path INCLUDING the refusals, so the caller can state the LAYER fact
    (how many cases exist, of which kinds) rather than only the FILTER fact."""
    if report is None:
        report = {}
    cases = load_l10_cases(project)
    if cases is None:
        report["reason"] = "no L10_TEST_CASES.json"
        return -1
    report["scope"] = producer_scope(cases, kind)
    if not cases:
        report["reason"] = "L10 carries no test case"
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
    scope = scaffold_kind_scope(kind)
    emitted = 0
    for c in cases:
        # ORGANIC #761 — the REAL oracle emitters run for EVERY case. Both are
        # content-keyed and fail-closed (a closed-form declared function for the
        # arithmetic family; the case's own "within N cycles of reset release"
        # text for the boot-latency family), so widening them to the whole layer
        # cannot manufacture evidence: a case they cannot ground still gets
        # None. What it CAN do is give a genuine golden to a case Phase 1 typed
        # with some other kind token.
        # G19 — a case carrying a TYPED declared reference output is tried
        # FIRST: its oracle is stated by the design, so it outranks a
        # closed-form re-derivation. Fail-closed, so a vector that does not
        # bind falls straight through to the emitters below.
        wrote = _emit_case_known_answer_vector(project, c, dut_module, ports,
                                               out_dir, report)
        if wrote is None:
            wrote = _emit_case_golden_oracle(project, ic_class, c, out_dir,
                                             report)
        if wrote is None:
            # ORGANIC #778 companion — the datapath (arith) convention
            # didn't ground this case; try the CPU-core / clocked-core
            # BOOT-LATENCY convention before falling back to the
            # substance floor. chip-AGNOSTIC, fail-closed (see
            # cpu_boot_latency_oracle_tb_gen.emit_case_oracle_from_ports).
            wrote = _emit_case_boot_latency_oracle(
                project, c, dut_module, ports, out_dir, report)
        if wrote is None:
            # The substance-floor SCAFFOLD stays kind-scoped. It is the part
            # with a §4.05 side effect: a scaffold is a LIVE driver, and
            # `l10_tb_conformance_check` suppresses its whole evidence blob only
            # while NOTHING under the sim tree drives the DUT (#206). Emitting
            # scaffolds for every case would flip that suppression off and let
            # any vacuous testbench sitting beside them credit its case by
            # id-substring — trading a visible FAIL for an invisible one.
            if scope is None or case_kind(c) in scope:
                wrote = emit_unit_tb(c, out_dir, top, ports=ports,
                                     dut_module=dut_module, report=report)
            else:
                report.setdefault("out_of_scaffold_scope", []).append(
                    {"case": c.get("name", c.get("id", "")),
                     "kind": case_kind(c)})
        if wrote is not None:
            emitted += 1
    if emitted == 0 and report.get("skipped"):
        report["reason"] = (
            "refused to emit any TB: "
            + "; ".join(s["reason"] for s in report["skipped"][:3]))
        return -2
    if emitted == 0:
        # #761 — say what the LAYER holds, not only what the filter matched.
        report["reason"] = describe_scope(report["scope"])
    return emitted



# ---------------------------------------------------------------------------
# THE EXECUTOR — a producer without a consumer runs zero tests
# ---------------------------------------------------------------------------
# MEASURED, opentitan_aes at v1.16.66: `emit_unit_tbs` wrote 8 known-answer
# vector TBs that PASS against the design's own 131-file RTL, and Step 4 still
# read "0 functional tests ran for 8 declared L10/L12 row(s)". Nothing was
# wrong with the testbenches: no runner path EXECUTED them. `sim/tb/` appeared
# in the runner exactly once, at the producer. The only functional-test
# denominator Step 4 reads is `_sim_results_bridge.find_professional_tb_pass`,
# i.e. a JUnit document under `phase2/stage1/sim_professional/*/results.xml`.
# This is that missing consumer: it builds and runs each emitted unit TB and
# writes the JUnit result the Step-4 bridge already knows how to read.
#
# FAIL-CLOSED, three states kept apart (they are NOT two):
#   NOT_EXECUTED — no simulator at any dispatch site, or no TB to run. NOTHING
#              is known (`sim_executed=False`, the runner's own v1.16.91
#              vocabulary). No results.xml is written at all: an empty JUnit
#              would let the bridge speak about an empty population, which is
#              the v1.16.21 defect shape.
#   ERRORED  — the simulator RAN and could not BUILD the closure. An <error>
#              testcase, so `errors > 0` and the bridge keeps refusing.
#   FAILED / PASSED — the simulation executed and judged the design.
UNIT_TB_RESULT_DIR = "l10_unit_tb"
#: The simulator this executor drives. The DISPATCH SITE that finds it is the
#: runner's (v1.16.91), not a second one owned here.
SIMULATOR = "verilator"
_MISSING_MODULE_RE = re.compile(
    r"[Cc]annot find (?:file containing )?module:?\s*'?([A-Za-z_][\w$]*)'?")
_MODULE_DEF_RE = r"(?m)^\s*module\s+{}\b"


def sim_professional_dir(project: Path) -> Path:
    """The directory `_sim_results_bridge._PROFESSIONAL_GLOB` globs."""
    return project / "phase2/stage1/sim_professional"


def is_unit_tb(path: Path) -> bool:
    """A TB is a PORTLESS top module named after its own file — the shape this
    generator emits. A support module copied in beside it (a vendor primitive
    the TB instantiates) has ports and is a SOURCE, not a top. Pure grammar."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    return re.search(r"(?m)^\s*module\s+" + re.escape(path.stem) + r"\s*;",
                     text) is not None


def _hdl_code_only(src: str) -> str:
    """`src` with `//` and `/* */` comments blanked, STRING LITERALS INTACT.

    MEASURED, vibe-ic#712 item: a single comment inverted the compile order.
    `x.sv` really declares `pkg_x`; `y.sv` really declares `pkg_y` and really
    reads `pkg_x::w`. Adding to x.sv the line

        // historical note: this used to read pkg_y::WIDTH

    made the scanner believe x.sv depends on y.sv, closed a cycle, and dropped
    both files into the `cycle: keep them` fallback in GIVEN order — emitting
    `y.sv, x.sv`, which `verilator --binary` cannot compile in one pass. The
    comment declared nothing and denied nothing, and it decided the order.

    STRINGS ARE PRESERVED DELIBERATELY. The three strippers already in this
    tree (`arith_ss_corner_risk_check`, `cdc_async_input_check`,
    `clock_domain_reg_crossing_check`) all treat `//` inside a string literal
    as the start of a comment, so a line like

        $display("a//b", pkg_x::VAL);

    would be blanked from the `//` onward and a REAL dependency would be lost.
    Trading a wrong order for a missing edge is not a fix, so this one tracks
    the string state. It is local rather than shared for the same reason: the
    shared copies carry the gap this exists to avoid.
    """
    out: List[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':                       # string literal — copied verbatim
            j = i + 1
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    j += 1                 # \" does not end the literal
                elif src[j] == "\n":
                    break                  # unterminated: SV strings are 1-line
                j += 1
            out.append(src[i:min(j + 1, n)])
            i = min(j + 1, n)
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:end]))
            i = end
        elif src.startswith("//", i):
            end = src.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i))
            i = end
        else:
            out.append(c)
            i += 1
    return "".join(out)


def package_first_order(files: List[Path]) -> List[Path]:
    """Order sources so a package is compiled before the package that imports
    it — `verilator --binary` is single-pass. Pure `package X;` / `X::` grammar,
    chip-AGNOSTIC; non-package files keep their given order, after the rest.

    Comments are blanked first (`_hdl_code_only`): a commented-out declaration
    is not a declaration and a commented-out `X::` is not a dependency."""
    defines: Dict[str, Path] = {}
    text_of: Dict[Path, str] = {}
    for f in files:
        try:
            text_of[f] = _hdl_code_only(f.read_text(errors="replace"))
        except OSError:
            text_of[f] = ""
        for m in re.finditer(r"(?m)^\s*package\s+([A-Za-z_]\w*)\s*;",
                             text_of[f]):
            defines.setdefault(m.group(1), f)
    pkg_files = [f for f in files if f in set(defines.values())]
    others = [f for f in files if f not in set(defines.values())]
    deps: Dict[Path, set] = {}
    for f in pkg_files:
        refs = set(re.findall(r"([A-Za-z_]\w*)::", text_of[f]))
        deps[f] = {defines[r] for r in refs
                   if r in defines and defines[r] is not f}
    ordered: List[Path] = []
    placed: set = set()
    for _ in range(len(pkg_files) + 1):
        for f in pkg_files:
            if f not in placed and deps[f] <= placed:
                ordered.append(f)
                placed.add(f)
        if len(placed) == len(pkg_files):
            break
    ordered += [f for f in pkg_files if f not in placed]   # cycle: keep them
    return ordered + others


def default_dispatch(argv: List[str], run_dir: Path,
                     container: "str | None", tool: str,
                     timeout: int) -> Tuple[int, str]:
    """The ONE dispatch site, borrowed from the runner (v1.16.91): container
    exec → a throwaway container of that container's OWN image → the host.

    This module does NOT resolve an image, choose a site or write provenance of
    its own: `design_one_shot_runner._run_sim_stage` already does all three for
    the reference-TB chain, and a second executor with its own copy of that
    logic is the failure this indirection exists to avoid. Imported lazily so
    `testbench_gen` stays importable on its own; with no container (or no
    runner importable) the argv runs on the host, which is the same last
    fallback that site takes."""
    import subprocess
    if container:
        try:
            import sys as _sys
            _here = str(Path(__file__).resolve().parent)
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            import design_one_shot_runner as _dsor
            rc, out, err = _dsor._run_sim_stage(
                [str(a) for a in argv], Path(run_dir), container,
                probe_tool=tool, timeout=timeout)
            return rc, (err or "") + (out or "")
        except Exception as e:                               # noqa: BLE001
            return 127, f"dispatch unavailable: {e}"
    try:
        pr = subprocess.run([str(a) for a in argv], cwd=str(run_dir),
                            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    except OSError as e:
        return 127, f"could not dispatch: {e}"
    # stderr FIRST: the container prints an environment banner, and a
    # transcript tail that ends in the banner hides the verdict line.
    return pr.returncode, (pr.stderr or "") + (pr.stdout or "")


def _resolve_from_design_input(project: Path, module: str) -> Optional[Path]:
    """Find the file that defines `module` in the design INPUT (§4.05: the
    input only — never an oracle, a golden or the harness). A TB may
    instantiate a vendor primitive the staged synthesis set did not need."""
    root = project / "input"
    if not root.is_dir():
        return None
    pat = re.compile(_MODULE_DEF_RE.format(re.escape(module)))
    for f in sorted(root.rglob("*.sv")) + sorted(root.rglob("*.v")):
        if any(part in {"golden", "oracle", "reference_flow", "submission_template"}
               for part in f.relative_to(root).parts):
            continue
        try:
            if pat.search(f.read_text(errors="replace")):
                return f
        except OSError:
            continue
    return None


def _junit(cases: List[Dict[str, Any]]) -> str:
    from xml.sax.saxutils import escape, quoteattr
    fails = sum(1 for c in cases if c["state"] == "failed")
    errs = sum(1 for c in cases if c["state"] == "errored")
    body = []
    for c in cases:
        body.append(f'  <testcase classname="{UNIT_TB_RESULT_DIR}" '
                    f'name={quoteattr(c["name"])} time="{c["time"]:.3f}">')
        if c["state"] == "failed":
            body.append(f'    <failure message={quoteattr(c["message"][:400])}>'
                        f'{escape(c["log_tail"][:2000])}</failure>')
        elif c["state"] == "errored":
            body.append(f'    <error message={quoteattr(c["message"][:400])}>'
                        f'{escape(c["log_tail"][:2000])}</error>')
        body.append("  </testcase>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<testsuites>\n<testsuite name="{UNIT_TB_RESULT_DIR}" '
            f'tests="{len(cases)}" failures="{fails}" errors="{errs}" '
            f'skipped="0">\n' + "\n".join(body) +
            "\n</testsuite>\n</testsuites>\n")


def run_unit_tbs(project: Path, container: "str | None" = None,
                 report: "dict | None" = None,
                 build_timeout: int = 1800,
                 run_timeout: int = 600,
                 dispatch=None) -> int:
    """Build and RUN every emitted unit TB; write the Step-4 JUnit.

    Returns the number of testbenches that EXECUTED (built and ran), or a
    negative sentinel — nothing is written on either:
      -1  no unit TB to run (the producer is the one that says why)
      -2  NOT_EXECUTED: no simulator at any dispatch site. Nothing ran, so
          nothing is known — and NO results.xml is written, because an empty
          JUnit would let the Step-4 bridge speak about an empty population.

    States use the runner's own v1.16.91 vocabulary: `sim_executed` False is
    NOT_EXECUTED; a build that the simulator RAN and rejected is an `<error>`
    testcase and a simulation the design failed is a `<failure>` — both are
    executed, both keep the Step-4 bridge refusing.

    `dispatch(argv, run_dir, container, tool, timeout) -> (rc, transcript)`
    defaults to `default_dispatch`, i.e. the runner's single dispatch site.
    chip-AGNOSTIC: file grammar, the standard verilator argv, the standard
    JUnit path — no chip/vendor literal.
    """
    if report is None:
        report = {}
    # Clear every prior execution record BEFORE any refusal path.  Otherwise
    # a rerun with no simulator (or no TB) can leave yesterday's PASS in place.
    _l10x.clear_record(project)
    disp = dispatch or default_dispatch
    tb_dir = _pl.sim_dir(project) / "tb"
    tbs = [p for p in sorted(tb_dir.glob("*.v")) + sorted(tb_dir.glob("*.sv"))
           if is_unit_tb(p)] if tb_dir.is_dir() else []
    report["tb_total"] = len(tbs)
    report["sim_executed"] = False
    if not tbs:
        report["reason"] = f"no unit TB under {tb_dir} — nothing to execute"
        return -1
    out_root = sim_professional_dir(project) / UNIT_TB_RESULT_DIR
    out_root.mkdir(parents=True, exist_ok=True)
    rc, _out = disp([SIMULATOR, "--version"], out_root, container,
                    SIMULATOR, 60)
    if rc != 0:
        report["reason"] = (
            f"NOT_EXECUTED: no {SIMULATOR} at any dispatch site "
            + (f"(container '{container}', its own image, or the host)"
               if container else "(the host)")
            + " — the testbenches were NOT executed, so nothing is known "
              "about them. No results.xml is written.")
        return -2
    rtl = _pl.rtl_dir(project)
    sources = package_first_order(
        sorted(rtl.glob("*.sv")) + sorted(rtl.glob("*.v")) if rtl.is_dir()
        else [])
    support = [p for p in sorted(tb_dir.glob("*.sv")) + sorted(tb_dir.glob("*.v"))
               if not is_unit_tb(p)]
    cases: List[Dict[str, Any]] = []
    extra: List[Path] = []
    for tb in tbs:
        t0 = time.time()
        wd = out_root / tb.stem
        shutil.rmtree(wd, ignore_errors=True)
        wd.mkdir(parents=True, exist_ok=True)
        state = "errored"
        message = ""
        log = ""
        try:
            has_case_oracle = ORACLE_NONE_MARKER not in tb.read_text(
                errors="replace")
        except OSError:
            has_case_oracle = False
        for _attempt in range(4):
            argv = ([SIMULATOR, "--binary", "--timing", "-j", "4",
                     "--top-module", tb.stem, "-Wno-fatal",
                     f"-I{rtl}", f"-I{tb_dir}"]
                    + [str(s) for s in sources + support + extra]
                    + [str(tb), "-o", f"sim_{tb.stem}"])
            brc, blog = disp(argv, wd, container, SIMULATOR, build_timeout)
            # The COMMAND belongs in the transcript: a build that silently
            # picked up (or did not pick up) a source is unreadable without it.
            (wd / "build.log").write_text(" ".join(argv) + "\n\n" + blog)
            if brc == 0:
                break
            # Simulator diagnostics can echo the source line that triggered
            # an error.  A comment such as ``// cannot find module old_ip``
            # is not an elaboration finding, even when it appears in the log.
            # Blank HDL comments/strings before extracting module names; the
            # returned spans stay aligned and real diagnostic prose remains.
            import _hdl_code_text as _hdl_text
            missing = [m for m in _MISSING_MODULE_RE.findall(
                _hdl_text.strip_hdl_comments_and_strings(blog))]
            found = False
            for mod in missing:
                src = _resolve_from_design_input(project, mod)
                if src is not None and src not in extra:
                    extra.append(src)
                    found = True
            if not found:
                message = (f"BUILD ERROR (rc={brc}): the simulator RAN and "
                           f"could not elaborate the closure — this TB did "
                           f"not execute")
                log = blog[-2000:]
                break
        else:
            brc = 1
        if brc == 0:
            rrc, rlog = disp([str(wd / "obj_dir" / f"sim_{tb.stem}")], wd,
                             container, SIMULATOR, run_timeout)
            (wd / "run.log").write_text(rlog)
            verdict_fail = re.search(r"(?m)^\s*(\[[^\]]*\]\s*)?FAIL\b", rlog)
            if rrc == 0 and not verdict_fail:
                state = "passed"
            else:
                state = "failed"
                message = (f"simulation FAILED (rc={rrc})"
                           + (f": {verdict_fail.group(0).strip()}"
                              if verdict_fail else ""))
                log = rlog[-2000:]
        cases.append({"name": tb.stem, "state": state, "message": message,
                      "log_tail": log, "time": time.time() - t0,
                      "work_dir": str(wd),
                      "tb_file": str(tb),
                      "has_case_oracle": has_case_oracle})
    executed = sum(1 for c in cases if c["state"] in ("passed", "failed"))
    report["cases"] = cases
    report["passed"] = sum(1 for c in cases if c["state"] == "passed")
    report["failed"] = sum(1 for c in cases if c["state"] == "failed")
    report["errored"] = sum(1 for c in cases if c["state"] == "errored")
    report["executed"] = executed
    report["sim_executed"] = executed > 0
    report["extra_sources_from_design_input"] = [str(x) for x in extra]
    if not cases:
        report["reason"] = "no testbench produced a result — nothing written"
        return -1
    results = out_root / "results.xml"
    # ATOMIC. `results.xml` is the FUNCTIONAL-TEST DENOMINATOR: the step-4
    # bridge reads it to substantiate `functional_verified`, and a writer that
    # dies mid-XML leaves a truncated file under the final name that the bridge
    # opens and counts. The final name must mean "this run finished".
    _atomic_write_text(results, _junit(cases))
    report["results_xml"] = str(results)
    l10_path = _pl.generated_docs_dir(project) / "L10_TEST_CASES.json"
    if not l10_path.is_file():
        # The simulator result remains a valid JUnit statement about what it
        # ran, but it cannot be bound to a declaration and therefore cannot
        # become per-case L10 evidence.
        report["execution_record_reason"] = (
            f"no L10 declaration at {l10_path}; no execution record written")
        return executed
    rows = []
    for case in cases:
        case_executed = (case["has_case_oracle"]
                         and case["state"] in ("passed", "failed"))
        if case_executed:
            verdict = (_l10x.PASS if case["state"] == "passed"
                       else _l10x.FAIL)
            detail = "self-checking case oracle executed by verilator"
        elif not case["has_case_oracle"]:
            verdict = _l10x.NOT_EXECUTED
            detail = ("simulator ran the substance-floor scaffold, but the "
                      "declared L10 case oracle was not executed")
        else:
            verdict = _l10x.NOT_EXECUTED
            detail = ("testbench did not execute because elaboration/build "
                      "did not complete")
        rows.append({
            "id": case["name"],
            "verdict": verdict,
            _l10x.SIM_EXECUTED_KEY: case_executed,
            "tb_file": case["tb_file"],
            "detail": detail,
        })
    execution_record = _l10x.write_record(
        project, l10_path, rows,
        producer="testbench_gen.run_unit_tbs",
        tb_dir=tb_dir, source_junit=results)
    report["execution_record"] = str(execution_record)
    return executed


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top", default="chip_top")
    p.add_argument("--kind", default=None,
                   help="emit ONLY cases of this L10 kind (e.g. "
                        "functional_vector); omit to emit every case")
    p.add_argument("--run", action="store_true",
                   help="EXECUTE the emitted unit TBs and write the Step-4 "
                        "JUnit under sim_professional/l10_unit_tb/ instead of "
                        "emitting; fail-closed (no simulator / no TB writes "
                        "NOTHING and exits non-zero)")
    p.add_argument("--container", default=None,
                   help="pinned EDA container to run the simulator in; "
                        "omit to use the simulator on PATH")
    args = p.parse_args()
    report: dict = {}
    if args.run:
        rep: dict = {}
        executed = run_unit_tbs(args.project, args.container, rep)
        if executed < 0:
            print(f"[NOT_EXECUTED] testbench_gen --run: "
                  f"{rep.get('reason')}")
            return 2
        print(f"[{'PASS' if rep['failed'] == 0 and rep['errored'] == 0 else 'FAIL'}] "
              f"testbench_gen --run: {rep['tb_total']} unit TB(s) — "
              f"{rep['passed']} passed, {rep['failed']} failed, "
              f"{rep['errored']} errored (elaboration); JUnit: "
              f"{rep.get('results_xml')}")
        for x in rep.get("extra_sources_from_design_input") or []:
            print(f"    resolved from design INPUT: {x}")
        for c in rep["cases"]:
            print(f"    {c['state']:8s} {c['name']} {c['message']}")
        return 0 if (rep["failed"] == 0 and rep["errored"] == 0) else 1
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
        if report.get("scope"):
            print(f"       {describe_scope(report['scope'])}")
        return 0
    if emitted == 0:
        # #761 — an empty FILTER is not an empty LAYER. Print both numbers.
        print(f"[SKIP] testbench_gen: no TB emitted — {report.get('reason')}")
        return 0
    print(f"[PASS] testbench_gen: {emitted} unit TB files emitted "
          f"under sim/tb/"
          + (f" (kind={args.kind})" if args.kind else "")
          + (f" [DUT={report.get('dut_module')}]" if report.get("dut_module") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
