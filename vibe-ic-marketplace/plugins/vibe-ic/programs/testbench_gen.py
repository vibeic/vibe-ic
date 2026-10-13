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

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

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

#: Stamped into every oracle THIS PRODUCER generates, so a later invocation can
#: tell its own output (refreshable) from an oracle somebody else authored
#: (never overwritable).  `ORACLE_NONE_MARKER` already carried that distinction
#: for the substance-floor scaffold; the three REAL-oracle emitters emitted a
#: file carrying neither marker, so their output was indistinguishable from
#: authored work and the preservation rule could not be applied to them.
ORACLE_GENERATED_MARKER = _l10x.ORACLE_GENERATED_MARKER
# Power / ground rails are TIED, never driven as stimulus, and never checked for
# X (they are legitimately undriven unless `USE_POWER_PINS is set).
_POWER_RE = re.compile(
    r"^(?:v(?:ccd|ssd|dda|ssa|pwr|gnd|dd|ss|bat|ccio|ssio|ddpst|ddio)|"
    r"vpb|vnb|gnd|dvdd|dvss|avdd|avss)\w*$", re.IGNORECASE)

# A module instantiation, for the instantiation-graph root search. Two
# identifiers before a '(' at a statement boundary, minus the keywords that
# share that shape.
#
# The instance name may carry an ARRAY range (IEEE 1364 §12.1.2,
# `adder u[N-1:0] (...)`), and the statement may open a generate item on the
# same line as its `begin [: label]` / `else`. MEASURED on a supplied design
# whose top instantiates its only child as an array: without the range the
# child read as a second root, the root search refused as "ambiguous", and no
# unit TB was emitted for any L10 case.
_MODULE_DECL_RE = re.compile(r"^[ \t]*module\s+([A-Za-z_]\w*)", re.MULTILINE)
_INST_RE = re.compile(
    r"(?:^|[;\)]|\bend\b|\belse\b|\bbegin\b(?:\s*:\s*[A-Za-z_]\w*)?)"
    r"\s*([A-Za-z_]\w*)\s*(?:#\s*\([^;]*?\)\s*)?"
    r"([A-Za-z_]\w*)\s*(?:\[[^\]\[;]*\]\s*)?\(", re.MULTILINE | re.DOTALL)
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
    runs.

    WHEN THE SOURCE SET DECLARES ONE PACKAGE TWICE, the resolver picks the copy
    the elaboration of this DUT reaches and SHADOWS the other. That is a choice
    the run made about which numbers the widths came from, so it is reported in
    the reason rather than left in the resolver: a reader who sees `[31:0]` is
    entitled to know that a second copy of the package said something else and
    was not used. Nothing is added when a package is declared once, or when the
    copies say the same thing -- there is nothing to record."""
    notes: List[str] = []
    params = _port_width.defaults_from_sources(sources, module, notes=notes)
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
            f"({_port_width.scope_summary(params)}): " + "; ".join(refusals)
            + " -- refusing to emit a TB rather than declaring them 1 bit")
    return resolved, (f"widths resolved over {_port_width.scope_summary(params)}"
                      + ("; " + "; ".join(notes) if notes else ""))


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


# ORGANIC #2064 — THE SCOPE TABLE IS NOT THE FLOW'S SCOPE.
#
# `SCAFFOLD_KINDS` above is THIS producer's scope. A Step-4 consumer that
# reports it as "how many declared rows any producer in the flow can author"
# is right only while this file is the only producer — and it stopped being
# that when `analog_acceptance_tb_gen` (#2064) started authoring an executable
# acceptance for `verification_intent` rows out of L22's plan and the A4
# corner-sweep record. The two answers must come from ONE accessor, or the
# gap that #761 closed inside this file reopens one level up.
#
# The analog half is NOT a kind set. Whether a `verification_intent` row is
# authorable depends on whether the design's own input states a bound or a PVT
# matrix for it, so it is a per-PROJECT, per-ROW question and is answered by
# asking that producer, never by widening `SCAFFOLD_KINDS`. Widening it would
# also make Step 4 pass on an EMPTY denominator, which is the outcome the
# #2064 ruling refused.
def acceptance_authorable_rows(project: Path) -> "set | None":
    """The L10 row names the ANALOG-ACCEPTANCE producer can author, or None.

    `None` means "could not be measured" (producer absent or unreadable) — it
    is never handed back as an empty set, so a caller cannot report "0
    authorable" for a question nobody asked."""
    try:
        import analog_acceptance_tb_gen as _acc  # noqa: WPS433 — lazy on purpose
    except Exception:
        return None
    return _acc.authorable_row_names(project)


def flow_authorable(project: Path, rows: List[dict]) -> Dict[str, object]:
    """How many of `rows` ANY producer in the flow is scoped to author.

    Keys: `scaffold` (this file's), `analog_acceptance` (#2064's),
    `authorable` (the union) and `unauthorable_kinds` (a histogram of what is
    left over). `analog_acceptance` is absent — not zero — when that producer
    could not be asked; the union then degrades to the scaffold count and says
    so through the missing key."""
    scaffold = [r for r in rows
                if isinstance(r, dict) and case_kind(r) in SCAFFOLD_KINDS]
    out: Dict[str, object] = {"scaffold": len(scaffold),
                              "scaffold_kinds": sorted(SCAFFOLD_KINDS)}
    authorable = {id(r) for r in scaffold}
    names = acceptance_authorable_rows(project)
    if names is not None:
        acc = [r for r in rows
               if isinstance(r, dict) and str(r.get("name") or "") in names]
        out["analog_acceptance"] = len(acc)
        authorable |= {id(r) for r in acc}
    out["authorable"] = len(authorable)
    out["total"] = len(rows)
    out["unauthorable_kinds"] = kind_histogram(
        [r for r in rows if isinstance(r, dict) and id(r) not in authorable])
    return out


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


def authored_oracle_preserved(out_dir: Path, name: str,
                              report: "dict | None") -> "Path | None":
    """The existing TB when it is an AUTHORED oracle that must NOT be regenerated.

    v1.15.45 gave `emit_unit_tb` the rule "NEVER regenerate over an authored
    oracle": the scaffold's own instruction is to write the case's drive/compare
    into it and delete the marker line, and re-emitting the scaffold on the next
    runner invocation erased that work and its evidence.

    MEASURED: the rule lived on the ONE emitter that cannot produce a real
    oracle.  `emit_unit_tbs` tries `_emit_case_known_answer_vector`,
    `_emit_case_golden_oracle` and `_emit_case_boot_latency_oracle` FIRST, and
    all three called `f.write_text(text)` unconditionally.  ORGANIC #761 widened
    those three to run for EVERY case, so any case an emitter learns to ground
    later silently overwrites an oracle already authored for it — the same
    clobber, on the paths that reach a case first.

    A file is AUTHORED when it carries NEITHER marker: not the substance-floor
    `ORACLE_NONE_MARKER` (that file is the scaffold and is refreshed), and not
    `ORACLE_GENERATED_MARKER` (that file is this producer's own previous output
    and stays refreshable, so a plugin upgrade still reaches it).
    """
    authored = Path(out_dir) / f"{name}.v"
    if not authored.is_file():
        return None
    try:
        prior = authored.read_text(errors="replace")
    except OSError:
        return None
    if not prior:
        return None
    if ORACLE_NONE_MARKER in prior or ORACLE_GENERATED_MARKER in prior:
        return None
    if report is not None:
        report.setdefault("preserved_authored", []).append(
            {"case": str(name), "path": str(authored)})
    return authored


def stamp_generated(text: str, emitter: str) -> str:
    """Mark `text` as this producer's own output, so the next invocation may
    refresh it.  A leading HDL comment is inert to every consumer of the file."""
    if ORACLE_GENERATED_MARKER in text:
        return text
    return f"// {ORACLE_GENERATED_MARKER}{emitter}\n" + text


def _emit_case_golden_oracle(project: Path, ic_class: "str | None",
                             case: dict, out_dir: Path,
                             report: "dict | None",
                             case_stated: bool = False) -> "Path | None":
    """Emit a REAL per-case golden oracle TB (no ORACLE_NONE) for an L10
    `functional_vector` case, using the declared-function convention in
    arith_oracle_tb_gen. Returns the written path, or None when no closed-form
    oracle is derivable for this design (→ caller falls back to the substance
    floor; fail-closed).

    `case_stated` hands the case itself to the emitter so the population, the
    corners and the reset-mid-computation scenario the case's OWN text states
    are what the module drives (`arith_oracle_tb_gen.case_oracle_options`).
    The full-stack functional producer asks for it; the Step-4 unit-TB loop
    keeps the historical sample."""
    name = case.get("name", "")
    if not _LEGAL_ID_RE.match(str(name)):
        return None
    kept = authored_oracle_preserved(out_dir, name, report)
    if kept is not None:
        return kept
    try:
        import arith_oracle_tb_gen as _aog  # type: ignore
    except Exception:
        return None
    try:
        # `case=` only when asked: the Step-4 call keeps its historical
        # four-argument shape exactly.
        _stated = {"case": case} if case_stated else {}
        text = _aog.emit_case_oracle(
            project, ic_class, str(name), _case_profile(case), **_stated)
    except Exception as e:  # pragma: no cover — never let it break the loop
        if report is not None:
            report.setdefault("oracle_errors", []).append(
                {"case": name, "error": str(e)})
        return None
    if not text:
        return None
    f = out_dir / f"{name}.v"
    f.write_text(stamp_generated(text, "_emit_case_golden_oracle"))
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
    kept = authored_oracle_preserved(out_dir, name, report)
    if kept is not None:
        return kept
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
    f.write_text(stamp_generated(text, "_emit_case_boot_latency_oracle"))
    if report is not None:
        report.setdefault("boot_latency_oracle_cases", []).append(str(name))
    return f



def _emit_case_reset_invariant_oracle(project: Path, case: dict,
                                      dut_module: str,
                                      ports: "List[Tuple[str, str, str]]",
                                      out_dir: Path,
                                      report: "dict | None") -> "Path | None":
    """R-0915-102(2) companion — emit a REAL RESET-INVARIANT oracle TB.

    The boot-latency family owns "within N cycles of reset RELEASE"; this one
    owns the two invariants stated about reset ASSERT: stored content held
    across an assert, and a reset GLITCH not racing a bus access. MEASURED on
    subservient x gf180mcuD, front door, r48: those two cases needed no
    delivered program at all and fell to the substance floor purely because no
    emitter owned their family -- which is also why the single case that DID
    execute was the one the boot-latency emitter grounds.

    Returns None (defer to the substance-floor scaffold) whenever the case's
    own text does not state one of the two invariants, or the DUT surface
    offers no port to observe it on -- fail-closed, never fabricates.
    """
    name = case.get("name", "")
    if not _LEGAL_ID_RE.match(str(name)):
        return None
    kept = authored_oracle_preserved(out_dir, name, report)
    if kept is not None:
        return kept
    try:
        import reset_invariant_oracle_tb_gen as _riv  # type: ignore
    except Exception:
        return None
    inputs, outputs, inouts = _classify(ports)
    try:
        # R-0929-X-QUALIFIED — which outputs the DESIGN INPUT qualifies, and
        # by what; every other output must be known after reset release.
        quals, refused = _riv.declared_output_qualifiers_and_refusals(
            project, outputs, inputs)
        memory, memory_basis = _riv.declared_retention_memory(
            project, dut_module, inputs, outputs)
        text = _riv.emit_case_oracle_from_ports(
            case, dut_module, inputs, outputs, inouts, qualifiers=quals,
            refusals=refused, memory=memory)
    except Exception as e:  # pragma: no cover — never break the loop
        if report is not None:
            report.setdefault("oracle_errors", []).append(
                {"case": name, "error": str(e)})
        return None
    if not text:
        return None
    f = Path(out_dir) / f"{name}.v"
    f.write_text(stamp_generated(text, "_emit_case_reset_invariant_oracle"))
    if report is not None:
        report.setdefault("reset_invariant_cases", []).append(
            {"case": name, "family": _riv.case_family(case),
             "retention_memory": memory, "retention_basis": memory_basis})
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
    kept = authored_oracle_preserved(out_dir, case.get("name", ""), report)
    if kept is not None:
        return kept
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
    f.write_text(stamp_generated(text, "_emit_case_known_answer_vector"))
    if report is not None:
        report.setdefault("known_answer_vector_cases", []).append(
            {"case": case.get("name"), "citation": case.get("citation")})
    return f



# ── R-0915-113(2): a (message -> digest) vector over the DECLARED bus ─────
#: L4 is read ONCE per project — the emitter ladder runs per case, and a
#: register map re-read 11 times is 11 reads of the same file.
_L4_CACHE: "dict" = {}


def _project_regmap(project) -> "dict":
    """The design's OWN register map, out of its Phase-1 documents.

    Never an oracle tree, never a golden: `phase1/generated_docs/` is the
    machine reading of the design's own input documents. A project that has no
    L4 yields `{}` and every stated-vector emission then refuses by name."""
    key = str(project)
    if key in _L4_CACHE:
        return _L4_CACHE[key]
    import json as _json
    doc = {}
    for rel in ("phase1/generated_docs/L4_REGMAP.json",
                "plugin_output/phase1/generated_docs/L4_REGMAP.json"):
        f = Path(project) / rel
        if not f.is_file():
            continue
        try:
            loaded = _json.loads(f.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict) and loaded.get("registers"):
            doc = loaded
            break
    _L4_CACHE[key] = doc
    return doc


def _emit_case_stated_vector_bus(project: Path, case: dict, dut_module: str,
                                 ports: "List[Tuple[str, str, str]]",
                                 out_dir: Path,
                                 report: "dict | None") -> "Path | None":
    """R-0915-113(2) — emit a REAL self-checking TB that drives the case's own
    STATED payload over the design's own memory-mapped register bus and
    compares the design's own answer window against the case's own STATED
    literal.

    The family the two known-answer routes fall between. MEASURED, sha256 x
    sky130A, front door, run20: 11 of 11 L10 cases fell to the substance floor
    (`VIBEIC_TB_ORACLE: NONE`) and Step 4 read a ZERO functional denominator,
    while the design's input stated the whole transport — cs/we/address/
    write_data/read_data in its port table, BLOCK<i>/DIGEST<i> windows and
    CTRL/STATUS bit roles in its register map — and stated BOTH halves of six
    of those cases. The port route refuses (no `message` port exists) and the
    struct-bus route refuses by name (`this driver drives a (plaintext ->
    ciphertext) block vector; got inputs=['message'] outputs=['digest']`).

    Fail-closed like every sibling: a case that does not state its answer as a
    literal — an acceptance PERCENTAGE over a coverage scope, or a message
    LENGTH with no message — returns None with the reason recorded, and the
    case falls to the substance floor so Step 4 still fails it honestly. No
    digest, checksum or reference value is ever COMPUTED here."""
    name = case.get("name", "")
    if not _LEGAL_ID_RE.match(str(name)):
        return None
    kept = authored_oracle_preserved(out_dir, name, report)
    if kept is not None:
        return kept
    try:
        import stated_vector_bus_oracle_gen as _svb  # type: ignore
    except Exception:
        return None
    l4 = _project_regmap(project)
    if not l4:
        if report is not None:
            report.setdefault("stated_vector_unbound", []).append(
                {"case": str(name),
                 "reason": "the project stages no L4 register map"})
        return None
    try:
        text, why = _svb.emit_case_stated_vector_bus(case, l4, dut_module,
                                                     ports)
    except Exception as e:  # pragma: no cover — never break the loop
        if report is not None:
            report.setdefault("oracle_errors", []).append(
                {"case": str(name), "error": str(e)})
        return None
    if not text:
        if report is not None:
            report.setdefault("stated_vector_unbound", []).append(
                {"case": str(name), "reason": why})
        return None
    f = Path(out_dir) / f"{name}.v"
    f.write_text(stamp_generated(text, "_emit_case_stated_vector_bus"))
    if report is not None:
        report.setdefault("stated_vector_cases", []).append(
            {"case": str(name),
             "evidence": case.get("evidence") or case.get("citation"),
             "provenance": "GENERATED_FROM_STATED_VECTOR"})
        _known_answer_vector_driven_later(report, str(name), case,
                                          "_emit_case_stated_vector_bus")
    return f


def _known_answer_vector_driven_later(report: dict, name: str, case: dict,
                                      rung: str) -> None:
    """A known-answer vector the known-answer rung refused and a LATER rung of
    the same ladder drove: it is driven, not unbound.

    MEASURED (sha256 x sky130A, front door): the census read "0 bound,
    3 unbound -- the vectors exist and could NOT be driven" while this rung had
    written all three TBs and they passed. The known-answer rung records its
    refusal before the ladder moves on; the record must end in the state the
    case ends in. The first refusal is kept on the row, not discarded."""
    unbound = report.get("known_answer_vector_unbound") or []
    hit = [u for u in unbound
           if isinstance(u, dict) and str(u.get("case")) == name]
    if not hit:
        return
    report["known_answer_vector_unbound"] = [u for u in unbound
                                             if u not in hit]
    report.setdefault("known_answer_vector_cases", []).append(
        {"case": name, "citation": case.get("citation"),
         "driven_by": rung, "first_refusal": hit[0].get("reason")})


# ── R-0915-89(ii): the run must SAY which oracles it did not write ──────────
#: The three ways a file under `sim/tb/` can have got there.
ORACLE_SOURCE_AUTHORED = "PRESERVED_AUTHORED"
ORACLE_SOURCE_GENERATED = "GENERATED"
ORACLE_SOURCE_FLOOR = "SUBSTANCE_FLOOR"
#: A fourth way, and the one a pristine front-door run has to have: the
#: design DELIVERED the case's own test program with its input.
ORACLE_SOURCE_DELIVERED = "DELIVERED_INPUT"

#: An authored oracle states, in its own header, which input line it derives
#: from. Read back rather than re-asserted, so the published provenance cannot
#: drift from the file it describes.
_CITATION_RE = re.compile(r"^//\s*CITATION\s*:\s*(.+?)\s*$", re.M)
#: The emitter term of `ORACLE_GENERATED_MARKER`: exactly what `stamp_generated`
#: writes after the marker, which is a Python function name and nothing else.
_EMITTER_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ORACLE_LINE_RE = re.compile(r"^//\s*ORACLE\s*:\s*(.+?)\s*$", re.M)
#: A DELIVERED oracle states, in its own header, which INPUT path it was
#: installed from. Same read-it-back rule as CITATION.
_DELIVERED_TERM = "DELIVERED"
_DELIVERED_RE = re.compile(r"^//\s*DELIVERED\s*:\s*(.+?)\s*$", re.M)


#: Where a delivered test program is looked for, in order. These are INPUT
#: paths: the design's own test programs, delivered with the design (§4.05 —
#: the input only; an oracle/golden/harness tree is never read, and the
#: exclusion below enforces that on every candidate).
_DELIVERED_TB_DIRS = ("input/sim/tb", "input/tb", "input/sim")
#: Program/stimulus images a delivered TB may need beside it ($readmemh, ...).
_DELIVERED_PROGRAM_DIRS = ("input/sim/programs", "input/programs", "input/sim")
#: §4.05 — never read from these, wherever they sit under input/.
_INPUT_FORBIDDEN_PARTS = frozenset(
    {"golden", "oracle", "reference_flow", "harness", "submission_template"})


def _input_safe(rel_parts) -> bool:
    return not any(part.lower() in _INPUT_FORBIDDEN_PARTS for part in rel_parts)


def delivered_case_oracle(project: Path, name: str) -> "Path | None":
    """The delivered testbench for this case, or None.

    WHY THIS EXISTS. MEASURED on subservient x gf180mcuD, front door, run r48
    (lane icsub2, host 8HD-4, tree 41d3b39b8, image 0.3.67): 1 of 10 declared
    L10 cases executed its own oracle. The one that did was GENERATED in-flow
    by `_emit_case_boot_latency_oracle`; the other nine got the substance-floor
    scaffold. Earlier runs of the same IC scored 10/10 only because nine
    authored testbenches had been placed into `phase2/stage1/sim/tb/` BY HAND,
    where `authored_oracle_preserved` then found them.

    The reason a front-door run could never reproduce that: NOTHING in this
    producer ever looked at the design INPUT for a delivered test program. The
    only input-reading helper here, `_resolve_from_design_input`, resolves a
    MODULE DEFINITION a testbench instantiates -- not a testbench, and not a
    program. So a dataset could deliver the case's own test program and no step
    in the flow would consult it. This is the path that makes delivery
    meaningful; without it, "deliver the programs" has nowhere to land.

    These are the design's OWN test programs, delivered as input -- not the
    benchmark's hidden oracle. §4.05 is enforced structurally: any candidate
    whose path carries a `golden`/`oracle`/`reference_flow`/`harness`/
    `submission_template` segment is refused, wherever it sits.

    Fail-closed: no delivered file, no behaviour change -- the caller falls
    through to exactly the emitters and scaffold it used before.
    """
    if not _LEGAL_ID_RE.match(str(name)):
        return None
    for rel in _DELIVERED_TB_DIRS:
        d = Path(project) / rel
        if not d.is_dir():
            continue
        for ext in (".v", ".sv"):
            cand = d / f"{name}{ext}"
            if not cand.is_file():
                continue
            try:
                parts = cand.relative_to(Path(project)).parts
            except ValueError:
                continue
            if not _input_safe(parts):
                continue
            return cand
    return None


def delivered_case_program(project: Path, stimulus: str) -> "Path | None":
    """The delivered stimulus image a case's own declared text names, or None.

    A case whose stimulus is a firmware image (`blinky.hex`) needs the image
    itself, not only a testbench. The name comes from the case's OWN declared
    stimulus text, so this cannot reach a file the design did not name.
    """
    stim = (stimulus or "").strip()
    m = re.search(r"([A-Za-z0-9_.-]+\.(?:hex|bin|mem|elf|vmem))", stim)
    if not m:
        return None
    leaf = m.group(1)
    for rel in _DELIVERED_PROGRAM_DIRS:
        d = Path(project) / rel
        if not d.is_dir():
            continue
        cand = d / leaf
        if not cand.is_file():
            continue
        try:
            parts = cand.relative_to(Path(project)).parts
        except ValueError:
            continue
        if not _input_safe(parts):
            continue
        return cand
    return None


# ── WHY A CASE DID NOT RUN: the design input, or this flow? ──────────────────
#
# Owner rule (2026-09-28): only a plain FAIL is red. A declared case that
# CANNOT run because the design input does not supply its stimulus is
# NOT_MEASURED, with the case and the missing input named; a case that ran and
# failed stays FAIL; a case this flow COULD have run and did not stays a
# blocking NOT_EXECUTED.
#
# MEASURED on subservient (reused serv 1.4.0, 8HD-4, 2026-09-28): 5 of 6
# executable L10 cases fell to the substance floor and Step 4 FAILed. Two
# (`reset_n_cycle_instruction`, `i_rst_glitch_instruction_fetch_race`) were
# THIS FLOW's gap -- their oracle families could not see the top's SRAM
# read-enable -- and run and pass once they can. Three were the INPUT's:
# `blinky_hex` / `hello_hex` name `blinky.hex` / `hello.hex`, and no such file
# is anywhere in the design input; `zifencei` states its stimulus as
# "Zifencei 指令" and its expected half as "PASS", with no program delivered.
# No step of this flow may author that program (§4.05), so nothing can run it.
#
# The distinction is decided by DELIVERY and by the plugin's own oracle
# families, never by guessing at prose: a case is the input's gap only when no
# program or testbench is delivered for it AND no oracle family this producer
# owns claims its declared text. A family that claims a case and cannot ground
# it is this flow's work, and stays blocking.

#: Program / data images a stimulus can name. File FORMATS, never a design.
#: A path prefix (`sw/`, `input/sim/programs/`) is allowed and is not part of
#: the name: group 1 is the LEAF, which is what `input/**` is searched for
#: (FX_P2 review wave 6 -- a lookbehind that refused `/` made every
#: path-qualified image invisible).
_STIMULUS_IMAGE_RE = re.compile(
    r"(?<![\w.-])(?:[\w.-]+/)*([A-Za-z0-9_][\w.-]*\."
    r"(?:hex|ihex|mem|memh|vmem|bin|elf|srec|s19|coe|mif|dat|vec))\b",
    re.IGNORECASE)

#: The ONLY expected halves that are no statement of a result: a bare verdict
#: word, the verdict of a program the input would have to deliver. A CLOSED
#: list, compared whole after dropping case, spaces and punctuation -- never a
#: search. Anything else the input writes as the expected half (a behaviour in
#: words, a quoted string, a signal name, an equation, a number) is a result a
#: testbench can check, so the case is this flow's to run (FX_P2 review wave 6:
#: "no number" was read as "no result", and worded behaviours such as "full
#: flag asserted and further writes are ignored" were booked input_absent).
_BARE_VERDICT_WORDS = frozenset({
    "pass", "passed", "passes", "ok", "success", "succeeds", "allpass",
    "allpassed", "passfail", "通過", "成功", "全部通過", "全數通過"})
_VERDICT_NOISE_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def expected_is_a_bare_verdict(case: dict) -> bool:
    """True only when the case's expected half is nothing but a verdict word
    (`_BARE_VERDICT_WORDS`) and it carries no `expected_outputs`."""
    outs = case.get("expected_outputs")
    if outs:
        return False
    text = _VERDICT_NOISE_RE.sub("", str(case.get("expected") or "")).lower()
    return bool(text) and text in _BARE_VERDICT_WORDS


#: `oracle_family_claiming`'s answer when a family's detector (or its module)
#: RAISED. Not a family and not "no family": the question is unanswered, and
#: an unanswered question keeps the case where it was -- blocking.
FAMILY_UNKNOWN = "UNKNOWN_DETECTOR_RAISED"

#: A value the expected half STATES: a C / Verilog hex or binary literal, or
#: any number. Presence only -- never the value -- so a case that states one
#: is claimed by the stated-vector family even when its driver cannot read the
#: shape (two outputs, an odd-length hex, a decimal). That is this flow's
#: driver gap, and it stays blocking.
_STATED_LITERAL_RE = re.compile(
    r"0[xX][0-9a-fA-F_]+|\d*'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ]+|\d")


def states_a_checkable_answer(case: dict) -> bool:
    """Does the case's OWN expected half state a value a testbench could check?

    `expected_outputs` with any entry does; so does an `expected` text carrying
    any literal or number. "PASS" or a prose outcome with no value does not --
    that expected half is the verdict of a program the input must deliver."""
    outs = case.get("expected_outputs")
    if isinstance(outs, (dict, list, tuple)) and len(outs) > 0:
        return True
    if isinstance(outs, str) and outs.strip():
        return True
    return bool(_STATED_LITERAL_RE.search(str(case.get("expected") or "")))


def _family_by_detector(case: dict,
                        ic_class: "str | None" = None) -> "str | None":
    """The family whose OWN detector claims `case` -- the predicate its emitter
    refuses on first -- or None; `FAMILY_UNKNOWN` when a detector (or a family
    module's import) raised."""
    try:
        import known_answer_vector_tb_gen as _ktb  # type: ignore
        if _ktb._kav is not None and _ktb._kav.is_known_answer_vector(case):
            return "known_answer_vector"
        import stated_vector_bus_oracle_gen as _svb  # type: ignore
        if _svb.stated_answer(case)[0] is not None:
            return "stated_vector"
        import cpu_boot_latency_oracle_tb_gen as _clg  # type: ignore
        if _clg.is_boot_latency_case(case):
            return "boot_latency"
        import reset_invariant_oracle_tb_gen as _riv  # type: ignore
        if _riv.is_reset_hold_case(case) or _riv.is_reset_glitch_case(case):
            return "reset_invariant"
        import arith_oracle_tb_gen as _aog  # type: ignore
        if ic_class and ic_class in _aog._ARITH_CLASSES:
            return "arith_closed_form"
    except Exception:                                        # noqa: BLE001
        return FAMILY_UNKNOWN
    return None


def oracle_family_claiming(case: dict,
                           ic_class: "str | None" = None) -> "str | None":
    """The oracle family of THIS producer that claims `case`, or None.

    Each family is asked through its OWN detector (`_family_by_detector`), so
    this cannot disagree with the emitters about which cases they own. A
    claimed case that did not run is this flow's gap.

    FAIL-CLOSED. A detector (or a family module's import) that raises answers
    `FAMILY_UNKNOWN`, never None: "no family claims it" is what moves a case
    OUT of blocking, so it may only be said when every detector answered. The
    stated-vector family claims every case that STATES a checkable value
    (`states_a_checkable_answer`), not only the ones its driver can extract --
    an extraction refusal is the driver's limit, not the input's gap. The
    reset-invariant family claims a case either of its detectors fires on,
    including the ambiguous both-fire case its emitter refuses to guess."""
    if states_a_checkable_answer(case):
        return "stated_vector"
    return _family_by_detector(case, ic_class)


def _in_flow_testbench(project: Path, name: str) -> "Path | None":
    """This run's own testbench for the case, when it is more than the
    substance floor (authored, generated or delivered into `sim/tb/`). A case
    the flow HAD a testbench for, and did not execute, is the flow's failure."""
    tb_dir = _pl.sim_dir(Path(project)) / "tb"
    for ext in (".v", ".sv"):
        f = tb_dir / f"{name}{ext}"
        try:
            if f.is_file() and ORACLE_NONE_MARKER not in f.read_text(
                    errors="replace"):
                return f
        except OSError:
            return f        # unreadable: not evidence of absence
    return None


def _input_file_leaves(project: Path) -> "set":
    """Lower-cased basenames of every file in the design input (§4.05-safe)."""
    root = Path(project) / "input"
    leaves: set = set()
    if not root.is_dir():
        return leaves
    for f in root.rglob("*"):
        try:
            if f.is_file() and _input_safe(f.relative_to(Path(project)).parts):
                leaves.add(f.name.lower())
        except (OSError, ValueError):
            continue
    return leaves


def named_stimulus_images(stimulus: str) -> "List[str]":
    """The program / data images the stimulus NAMES as its input.

    A name inside a sentence that denies it ("no blinky.hex is needed") is not
    a stimulus the case asks for, so it is not returned (#712 polarity)."""
    import _prose_polarity as _pp
    text = str(stimulus or "")
    out: List[str] = []
    for m in _STIMULUS_IMAGE_RE.finditer(text):
        lo, hi = _pp.sentence_scope(text, m.start(1), m.end(1))
        if _pp.is_denied(text[lo:hi]):
            continue
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def case_input_gap(project: Path, case: dict,
                   ic_class: "str | None" = None) -> "dict | None":
    """Why the design input cannot run `case`, or None when it is not the input.

    POSITIVE EVIDENCE ONLY -- the record names what is missing from the input.
    None (the case's non-execution stays this flow's, blocking) when:
      * a program or testbench is DELIVERED for it in the input;
      * this run's own `sim/tb/` holds a testbench for it that is more than the
        substance floor (the flow had one and did not execute it);
      * an oracle family's own detector claims it, or a detector could not
        answer (`FAMILY_UNKNOWN`);
      * it states no stimulus at all (no evidence either way);
      * every image its stimulus names IS in the design input;
      * it is conditional on a design option (`applies_when`);
      * `delivered_case_program` finds the program its stimulus names;
      * it names no image and its expected half is anything but a bare
        verdict word (`expected_is_a_bare_verdict`) -- a behaviour in words is
        a result a testbench can check, so the missing piece is this flow's.
    The input's gap is exactly: a named image absent from `input/**`, or no
    named image, no delivered program and an expected half that is only a
    verdict word (e.g. "PASS" -- the verdict of a program the input never
    delivers).
    """
    name = str(case.get("name") or case.get("id") or "")
    if not name:
        return None
    if delivered_case_oracle(project, name) is not None:
        return None
    if _in_flow_testbench(project, name) is not None:
        return None
    if _family_by_detector(case, ic_class) is not None:
        return None
    # A CONDITIONAL case (R-0915-102 `applies_when`) is never the input's gap.
    # The input stated it "applies only if <option> is selected": when the
    # design's declaration excludes the option the gate books it
    # NOT_APPLICABLE citing that declaration; while no selection is declared
    # it stays where R-0915-102's fail-closed rule puts it. Booking it
    # input_absent would drop the condition from the reason (lane fxrtl,
    # subservient M / Zicsr / C).
    _aw = case.get("applies_when")
    if isinstance(_aw, dict) and _aw.get("option"):
        return None
    stimulus = str(case.get("stimulus") or "").strip()
    if not stimulus:
        # POSITIVE EVIDENCE ONLY. A row that states no stimulus at all says
        # nothing about what the input supplies; its non-execution stays
        # blocking rather than being read as the input's gap.
        return None
    if delivered_case_program(project, stimulus) is not None:
        return None           # the flow's own delivery reader finds it
    named = named_stimulus_images(stimulus)
    present = _input_file_leaves(project)
    missing = [n for n in named if n.lower() not in present]
    if named and not missing:
        return None
    # A NAMED image the input does not contain is positive proof on its own,
    # whatever the expected half states (MEASURED on subservient: hello_hex
    # names hello.hex and expects a UART string "by 115200 baud" -- a number,
    # but nothing can run without the image). Without a named image, a case
    # whose expected half states a value is the stated-vector family's.
    if not missing and not expected_is_a_bare_verdict(case):
        return None
    looked = list(_DELIVERED_TB_DIRS) + ["input/** (every file, by name)"]
    expected = str(case.get("expected") or "").strip()
    if missing:
        what = (f"its stimulus names {', '.join(missing)}, which the design "
                f"input does not contain")
    else:
        what = (f"the design input states its stimulus only as "
                f"{stimulus[:120]!r}, delivers no program or testbench for "
                f"it, and states its expected result only as "
                f"{expected[:60]!r} -- a bare verdict, not a result a "
                f"testbench could check: the verdict of a program the input "
                f"does not deliver")
    return {
        "case": name,
        "missing_from_input": missing or [
            f"a program or testbench for {name!r}"],
        # The NAMED program images the input lacks, and nothing else: empty
        # for a bare-verdict case. `input_absent_exclusion` reads this field,
        # never the prose.
        "missing_images": list(missing),
        "stimulus": stimulus,
        "looked_in": looked,
        "reason": (f"case {name!r} cannot run: {what} (looked in "
                   f"{', '.join(looked)}). Supplying it is the design "
                   f"input's; this flow may not author it (§4.05)."),
    }


# ── A FIRMWARE ROW WHOSE IMAGE IS ABSENT LEAVES THE VERDICT, BY NAME ─────────
#
# Owner ruling R-0929-OWNER-SUB-ACCEPT (2), 2026-09-29: firmware rows whose
# input is absent (the owner's 2026-09-28 ruling kept subservient's
# `blinky.hex` / `hello.hex` input_absent -- they are the deliberately removed
# reference software) are EXCLUDED from "real PASS" exactly like the FPGA
# board steps 6/39: listed separately as NOT_MEASURED [input_absent], never
# PASS, not blocking.
#
# THE SAME MECHANISM AS STEPS 6/39. `flow_compliance_check` (F10) marks a board
# step that could not run NOT_MEASURED, gives it an `excluded_from_verdict`
# sentence ("NOT_MEASURED, excluded from the run verdict: <basis>"), removes it
# from every verdict bucket, and publishes it as `not_measured_excluded` beside
# the verdict. A firmware row is the same fact one level down -- a declared
# case, not a step -- so it gets the same three things from the gate that
# judges it: the NOT_MEASURED status with `reason_class` input_absent, the
# `excluded_from_verdict` sentence, and a place in that gate's own
# `not_measured_excluded` list. Nothing about it is ever counted as a pass.
#
# WHICH ROWS. Exactly those `case_input_gap` already books the INPUT's gap
# because the case's own stimulus NAMES a program image (`blinky.hex`) that is
# nowhere in `input/**` -- its `missing_images` field, read as data. A row
# that names no image (a bare "PASS" expected half with no program delivered)
# is not a firmware row, stays in `input_not_supplied`, and keeps blocking.
# Every refusal `case_input_gap` makes (a delivered program or testbench, a
# claiming oracle family, an `applies_when` option, an image the input DOES
# carry, an executed case) is inherited unchanged, because this asks it.
EXCLUDED_FROM_VERDICT_PREFIX = "NOT_MEASURED, excluded from the verdict: "


def input_absent_exclusion(project: Path, case: dict,
                           ic_class: "str | None" = None) -> "dict | None":
    """The exclusion record for a firmware row whose image the input lacks,
    or None (the row is judged as before)."""
    gap = case_input_gap(project, case, ic_class)
    images = list((gap or {}).get("missing_images") or [])
    if not gap or not images:
        return None
    import verdict as _vd                            # noqa: E402 (taxonomy)
    return {
        "case": gap["case"],
        "status": _vd.Verdict.NOT_MEASURED.value,
        "reason_class": _vd.ReasonClass.INPUT_ABSENT.value,
        "missing_from_input": images,
        "excluded_from_verdict": EXCLUDED_FROM_VERDICT_PREFIX + gap["reason"],
    }


# ── J-1: a delivered testbench binds the DESIGN'S OWN port names ───────────
#
# L3:33 says the SRAM signal NAMES and L3:73 says the SRAM bus PROTOCOL are
# declared by the implementation in its own `declaration.json`; L3:37-41 then
# writes down a "typical" set. A delivered testbench can only bind the typical
# set -- it is the only set stated anywhere in the design input -- and the
# delivered subservient testbenches say so in their own headers: "an
# implementation that declares a different SRAM signal set or a different read
# latency will not bind to this file".
#
# That is true of the file and must not be true of the FLOW. So the installed
# copy is bound to what the implementation DECLARED, and the typical set is the
# fallback used ONLY where the declaration is silent. Nothing here is a hand
# map from one design's names to another's: the roles come from the
# declaration, and the typical names are read from the same input table the
# delivered testbench read.
#
# MEASURED on subservient x gf180mcuD, r48: that design's declaration names no
# SRAM ports at all (it declares `sram_interface_protocol` and
# `sram_interface_timing` only), so every role falls back and the installed
# bytes are identical to the delivered ones -- which is the case this must not
# disturb.
#: Declaration fields that may carry the SRAM role -> port-name map.
_SRAM_PORT_FIELDS = ("sram_port_names", "sram_ports", "sram_signal_names")
#: Declaration fields that may carry the read latency, in clocks.
_SRAM_READ_LATENCY_KEYS = ("read_data_valid_after_request_cycles",
                           "read_data_latency_cycles", "read_latency_cycles")
#: role -> the names L3:37-41 itself writes down (the fallback, in order).
_SRAM_TYPICAL = {
    "addr":  ("o_sram_addr",),
    "wdata": ("o_sram_data", "o_sram_wdata"),
    "rdata": ("i_sram_data", "i_sram_rdata"),
    "we":    ("o_sram_we",),
    "cyc":   ("o_sram_cyc",),
}
#: role -> the keys a declaration may use for it.
_SRAM_ROLE_KEYS = {
    "addr":  ("addr", "address"),
    "wdata": ("wdata", "write_data", "data_out", "wr_data"),
    "rdata": ("rdata", "read_data", "data_in", "rd_data"),
    "we":    ("we", "write_enable", "wen", "wr_en"),
    "cyc":   ("cyc", "cycle", "stb", "strobe", "valid"),
}
#: A delivered TB that can express a read latency other than one clock says so
#: in its own header and names the localparam that carries it.
_TB_LATENCY_PARAM_RE = re.compile(
    r"^//\s*VIBEIC_TB_READ_LATENCY_PARAM\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.M)


def _declaration(project: Path) -> dict:
    try:
        obj = json.loads((Path(project) / "plugin_output"
                          / "declaration.json").read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    if not isinstance(obj, dict):
        return {}
    return obj.get("fields") if isinstance(obj.get("fields"), dict) else obj


def declared_sram_ports(project: Path) -> dict:
    """role -> declared port name, for the roles the design actually named."""
    decl = _declaration(project)
    raw = None
    for key in _SRAM_PORT_FIELDS:
        if isinstance(decl.get(key), dict):
            raw = decl[key]
            break
    if not raw:
        return {}
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}
    out = {}
    for role, keys in _SRAM_ROLE_KEYS.items():
        for k in keys:
            v = lowered.get(k)
            if isinstance(v, str) and _LEGAL_ID_RE.match(v.strip()):
                out[role] = v.strip()
                break
    return out


def declared_read_latency(project: Path) -> "int | None":
    """The read latency in clocks the design declared, or None if it did not."""
    timing = _declaration(project).get("sram_interface_timing")
    if not isinstance(timing, dict):
        return None
    for k in _SRAM_READ_LATENCY_KEYS:
        v = timing.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and v >= 0:
            return v
    return None


def _instance_span(text: str, top: str) -> "tuple[int, int] | None":
    """The byte span of the `<top> <inst> ( ... );` instantiation, or None.

    Only the DUT instance is rewritten. A named port connection `.x(` is
    instance syntax, but a testbench may instantiate something else too (a
    memory model, a monitor), and rewriting those would bind the wrong thing.
    """
    m = re.search(rf"\b{re.escape(top)}\s+[A-Za-z_][A-Za-z0-9_]*\s*(?:#\s*\([^;]*?\)\s*)?\(",
                  text)
    if not m:
        return None
    depth = 0
    for i in range(m.end() - 1, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return (m.start(), i + 1)
    return None


def bind_delivered_tb(text: str, top: str, declared: dict) -> "tuple[str, list]":
    """Rebind the DUT instance's port names to what the design declared.

    Returns (text, rebindings). Only the PORT side of a named connection is
    touched -- the testbench's own net names are its own. A role the design did
    not declare keeps the typical name the testbench already bound, which is
    the L3:37-41 fallback and is why a silent declaration changes nothing.
    """
    if not declared:
        return text, []
    span = _instance_span(text, top)
    if span is None:
        return text, []
    head, inst, tail = text[:span[0]], text[span[0]:span[1]], text[span[1]:]
    rebound = []
    for role, name in sorted(declared.items()):
        for typical in _SRAM_TYPICAL.get(role, ()):
            if typical == name:
                break
            pat = re.compile(rf"\.\s*{re.escape(typical)}\s*\(")
            if pat.search(inst):
                inst = pat.sub(f".{name}(", inst, count=1)
                rebound.append({"role": role, "was": typical, "now": name})
                break
    return head + inst + tail, rebound


def retime_delivered_tb(text: str, declared_latency: "int | None"
                        ) -> "tuple[str, dict | None]":
    """Set the testbench's read latency, or say it cannot express it.

    Returns (text, refusal). A declaration that states nothing, or states the
    one clock L3:37-41 describes, leaves the file untouched -- the delivered
    testbenches model exactly that. Any other latency needs the testbench to
    carry a knob and SAY it carries one; a testbench that does not is REFUSED
    BY NAME rather than installed to sample at a latency the design does not
    have. A wrong sampling point is a testbench that passes for the wrong
    reason, which is worse than no testbench at all.
    """
    if declared_latency is None or declared_latency == 1:
        return text, None
    m = _TB_LATENCY_PARAM_RE.search(text)
    if not m:
        return text, {
            "reason": "tb_cannot_express_declared_read_latency",
            "declared_read_latency_cycles": declared_latency,
            "detail": ("the design declares a read latency of "
                       f"{declared_latency} clock(s); this testbench models "
                       "the one clock L3:37-41 describes and declares no "
                       "`// VIBEIC_TB_READ_LATENCY_PARAM :` knob, so it cannot "
                       "be retimed. Installing it would sample at a latency "
                       "the design does not have."),
        }
    param = m.group(1)
    pat = re.compile(rf"(localparam\s+(?:integer\s+)?{re.escape(param)}\s*=\s*)"
                     r"(\d+)(\s*;)")
    if not pat.search(text):
        return text, {
            "reason": "declared_latency_knob_not_found",
            "declared_read_latency_cycles": declared_latency,
            "detail": (f"the testbench names `{param}` as its read-latency "
                       "knob but declares no `localparam` of that name"),
        }
    return pat.sub(rf"\g<1>{declared_latency}\g<3>", text, count=1), None


def _emit_case_delivered_oracle(project: Path, case: dict, out_dir: Path,
                                report: "dict | None") -> "Path | None":
    """Install the DELIVERED testbench for this case into the L10 run.

    Runs BEFORE every generator: a program the design delivered outranks
    anything this producer could derive. An oracle already AUTHORED in the run
    directory outranks both -- `authored_oracle_preserved` is asked first, so
    re-running the flow never clobbers work in progress.
    """
    name = case.get("name", "")
    kept = authored_oracle_preserved(out_dir, name, report)
    if kept is not None:
        return kept
    src = delivered_case_oracle(project, name)
    if src is None:
        return None
    try:
        text = src.read_text(errors="replace")
    except OSError:
        return None
    if not text.strip():
        return None
    # J-1 — BIND IT TO THIS IMPLEMENTATION, NOT TO THE TYPICAL SET.
    # The delivered file can only bind the names L3:37-41 writes down; the
    # design's own declaration is what the DUT actually has. Rebind the
    # instance's port side, fall back per role where the declaration is
    # silent, and refuse by name rather than install a testbench that would
    # sample at a read latency this design does not have.
    _top = str(_declaration(project).get("top_module") or "").strip()
    _rebound: list = []
    if _top and _LEGAL_ID_RE.match(_top):
        text, _rebound = bind_delivered_tb(
            text, _top, declared_sram_ports(project))
    text, _refusal = retime_delivered_tb(text, declared_read_latency(project))
    if _refusal is not None:
        if report is not None:
            _refusal["case"] = name
            _refusal["from"] = str(src.relative_to(Path(project)))
            report.setdefault("delivered_oracle_refusals", []).append(_refusal)
        return None
    dst = Path(out_dir) / f"{name}.v"
    prog = delivered_case_program(project, str(case.get("stimulus", "")))
    # The installed copy STATES where it came from, so `oracle_provenance`
    # reads the file's own claim rather than a second-hand ledger -- the
    # same discipline as `// CITATION :`. Without it a delivered oracle is
    # indistinguishable from one a lane hand-placed, which is exactly the
    # confusion r46-vs-r48 turned on.
    stamp = (f"// {_DELIVERED_TERM} : "
             f"{src.relative_to(Path(project))}\n")
    if prog is not None:
        stamp += (f"// {_DELIVERED_TERM}_PROGRAM : "
                  f"{prog.relative_to(Path(project))}\n")
    try:
        dst.write_text(stamp + text)
        if prog is not None:
            (Path(out_dir) / prog.name).write_bytes(prog.read_bytes())
    except OSError:
        return None
    if report is not None:
        report.setdefault("delivered_oracles", []).append(
            {"case": name,
             "from": str(src.relative_to(Path(project))),
             "program": (str(prog.relative_to(Path(project)))
                         if prog is not None else None),
             "port_rebindings": _rebound,
             "bound_by": ("declaration.json" if _rebound
                          else "L3 typical set (declaration silent)")})
    return dst


def oracle_provenance(project: Path) -> dict:
    """Per-case: was this testbench AUTHORED, GENERATED, or a SUBSTANCE FLOOR?

    R-0915-89(ii). `authored_oracle_preserved` already recognises a delivered
    oracle and refuses to regenerate over it — correctly, and since v1.15.45.
    What no artefact said is WHICH files that happened to. MEASURED: r18
    preserved all TEN of the testbench-author role's delivered oracles and
    executed them (10/10 `sim_executed`), and `preserved_authored` went into an
    in-memory dict that reached no published file; r27 generated one real
    oracle and nine substance floors, and said no more than that either. A
    reader of either run cannot tell a delivered oracle from a generated one
    from a scaffold that checks almost nothing — which is exactly the
    distinction r27's 1-of-10 turned on.

    DERIVED FROM THE FILES, NOT FROM A LEDGER. Each testbench already declares
    what it is: the substance floor carries `ORACLE_NONE_MARKER`, this
    producer's own output carries `ORACLE_GENERATED_MARKER` plus the emitter
    name, and a file carrying NEITHER is authored — the same three-way test
    `authored_oracle_preserved` makes, so the disclosure and the
    never-regenerate rule cannot disagree. An authored oracle's own
    `// CITATION :` line is read back verbatim, so the published provenance is
    the file's own claim about which input line it derives from, not a
    second-hand copy that could drift.
    """
    out_dir = _pl.sim_dir(project) / "tb"
    cases: list = []
    if out_dir.is_dir():
        for tb in sorted(out_dir.glob("*.v")):
            try:
                text = tb.read_text(errors="replace")
            except OSError as exc:
                cases.append({"case": tb.stem, "source": "UNREADABLE",
                              "why": f"{type(exc).__name__}"})
                continue
            row = {"case": tb.stem,
                   "path": str(tb.relative_to(project))
                           if tb.is_relative_to(project) else str(tb)}
            _dlv = _DELIVERED_RE.search(text)
            if _dlv is not None:
                row["source"] = ORACLE_SOURCE_DELIVERED
                row["delivered_from"] = _dlv.group(1)
                cases.append(row)
                continue
            if ORACLE_NONE_MARKER in text:
                row["source"] = ORACLE_SOURCE_FLOOR
                row["checks"] = ("no output remains X/Z after reset release; "
                                 "no case semantics")
            elif ORACLE_GENERATED_MARKER in text:
                row["source"] = ORACLE_SOURCE_GENERATED
                # THE LINE MUST BE EXACTLY THE GRAMMAR, OR THE EMITTER IS
                # REFUSED. `stamp_generated` writes the marker, ONE identifier
                # and a newline — nothing else, ever. MEASURED, TWICE:
                #   * this first read `tail.splitlines()[0].strip()`, and every
                #     word appended to the marker line was absorbed into the
                #     published name (21 of 21 denial tokens moved it);
                #   * the first repair took the LEADING identifier, and every
                #     word spliced IN FRONT of the name was then published AS
                #     the name — `emitter: "not"` (21 of 21 again).
                # Neither is a polarity reading; both are a reader taking more
                # or other than the grammar's one term. So the whole line tail
                # must BE one identifier. Anything else publishes "" — an
                # emitter this reader cannot name — and never a guess.
                tail = text.split(ORACLE_GENERATED_MARKER, 1)[1]
                line = tail.split("\n", 1)[0].strip()
                row["emitter"] = (line if _EMITTER_TERM_RE.fullmatch(line)
                                  else "")
            else:
                row["source"] = ORACLE_SOURCE_AUTHORED
                cite = _CITATION_RE.search(text)
                what = _ORACLE_LINE_RE.search(text)
                row["citation"] = cite.group(1) if cite else None
                row["oracle"] = what.group(1) if what else None
                if not row["citation"]:
                    # An authored oracle that cites no input line is DISCLOSED
                    # as uncited rather than quietly counted as provenanced.
                    row["uncited"] = True
            cases.append(row)
    counts: dict = {}
    for row in cases:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
    return {
        "schema": "vibeic.l10_oracle_provenance.v1",
        "tb_dir": str(out_dir),
        "cases": cases,
        "counts": counts,
        "authored_uncited": [r["case"] for r in cases if r.get("uncited")],
        "decided_by": "testbench_gen.oracle_provenance",
    }


#: Which oracle family wrote a case's TB, by the emitter's stamp. The full-stack
#: functional producer records it per case.
ORACLE_FAMILY_BY_EMITTER = {
    "_emit_case_delivered_oracle": "delivered_oracle",
    "_emit_case_known_answer_vector": "known_answer_vector",
    "_emit_case_stated_vector_bus": "stated_vector_bus",
    "_emit_case_golden_oracle": "declared_function_golden",
    "_emit_case_boot_latency_oracle": "boot_latency",
    "_emit_case_reset_invariant_oracle": "reset_invariant",
}


def emit_unit_tbs(project: Path, top: str = "chip_top",
                  kind: "str | None" = None,
                  report: "dict | None" = None,
                  out_dir: "Path | None" = None,
                  scaffold: bool = True,
                  case_stated: bool = False) -> int:
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
    (how many cases exist, of which kinds) rather than only the FILTER fact.

    FULLSTACKTB — the Step-5 full-stack functional producer asks the SAME
    ladder the same question, so it calls this function rather than a second
    copy of it: `out_dir` puts the testbenches in its own directory,
    `scaffold=False` withholds the substance-floor scaffold (a case no REAL
    oracle grounds gets no file at all — a scaffold is exactly the
    connectivity-only evidence that producer exists to refuse), and
    `case_stated` hands each case to the declared-function emitter so its own
    stated population, corners and reset-mid-computation scenario are driven
    (`_emit_case_golden_oracle`). The defaults are the Step-4 behaviour,
    unchanged."""
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

    out_dir = Path(out_dir) if out_dir is not None else _pl.sim_dir(project) / "tb"
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
        # A program the DESIGN DELIVERED outranks anything derived here.
        wrote = _emit_case_delivered_oracle(project, c, out_dir, report)
        if wrote is None:
            wrote = _emit_case_known_answer_vector(project, c, dut_module,
                                                   ports, out_dir, report)
        if wrote is None:
            # R-0915-113(2) — the design may state its transport as a plain
            # memory-mapped register bus and state BOTH halves of the vector
            # in its own documents. Tried before the closed-form families:
            # a value the design STATES outranks one this flow re-derives.
            wrote = _emit_case_stated_vector_bus(project, c, dut_module,
                                                 ports, out_dir, report)
        if wrote is None:
            wrote = _emit_case_golden_oracle(project, ic_class, c, out_dir,
                                             report, case_stated=case_stated)
        if wrote is None:
            # ORGANIC #778 companion — the datapath (arith) convention
            # didn't ground this case; try the CPU-core / clocked-core
            # BOOT-LATENCY convention before falling back to the
            # substance floor. chip-AGNOSTIC, fail-closed (see
            # cpu_boot_latency_oracle_tb_gen.emit_case_oracle_from_ports).
            wrote = _emit_case_boot_latency_oracle(
                project, c, dut_module, ports, out_dir, report)
        if wrote is None:
            # R-0915-102(2) — the reset-ASSERT invariants (content held
            # across an assert; a reset glitch not racing a bus access).
            # Beside the release-side family above, same fail-closed rule.
            wrote = _emit_case_reset_invariant_oracle(
                project, c, dut_module, ports, out_dir, report)
        if wrote is None and not scaffold:
            report.setdefault("no_real_oracle", []).append(
                str(c.get("name", c.get("id", ""))))
        elif wrote is None:
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
    skipped = sum(1 for c in cases if c["state"] == "not_measured")
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
        elif c["state"] == "not_measured":
            body.append(f'    <skipped message={quoteattr(c["message"][:400])}/>')
        body.append("  </testcase>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<testsuites>\n<testsuite name="{UNIT_TB_RESULT_DIR}" '
            f'tests="{len(cases)}" failures="{fails}" errors="{errs}" '
            f'skipped="{skipped}">\n' + "\n".join(body) +
            "\n</testsuite>\n</testsuites>\n")


def run_unit_tbs(project: Path, container: "str | None" = None,
                 report: "dict | None" = None,
                 build_timeout: int = 1800,
                 run_timeout: int = 600,
                 dispatch=None,
                 isa_producer=None) -> int:
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
    # ... and the SECOND per-case execution record, the ISA-suite receipt with
    # its transcripts: a rerun whose producer crashes, binds nothing or is
    # never reached must not leave yesterday's credit behind (review wave 58).
    _clear_isa_suite_evidence(project)
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
    import reset_invariant_oracle_tb_gen as _riv
    retention_cases = {str(c.get("name", c.get("id", ""))) for c in
                       (load_l10_cases(project) or []) if _riv.is_reset_hold_case(c)}
    support = [p for p in sorted(tb_dir.glob("*.sv")) + sorted(tb_dir.glob("*.v"))
               if not is_unit_tb(p)]
    cases: List[Dict[str, Any]] = []
    extra: List[Path] = []
    for tb in tbs:
        t0 = time.time()
        tb_identity = _l10x.capture_tb_identity(tb)
        wd = out_root / tb.stem
        shutil.rmtree(wd, ignore_errors=True)
        wd.mkdir(parents=True, exist_ok=True)
        state = "errored"
        message = ""
        log = ""
        retention = None
        source_identity = {}
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
            if tb.stem in retention_cases:
                source_identity = {str(s): _l10x.file_sha256(s) for s in sources + support + extra}
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
            if tb.stem in retention_cases:
                retention, retention_detail = _riv.capture_retention_execution(
                    project, tb, wd / "run.log", source_identity)
                if state == "passed" and (retention is None or
                                          not retention["measurement"]["complete"]):
                    state = "not_measured"
                    message = retention_detail
        cases.append({"name": tb.stem, "state": state, "message": message,
                      "log_tail": log, "time": time.time() - t0,
                      "work_dir": str(wd),
                      "tb_file": str(tb),
                      **tb_identity,
                      "has_case_oracle": has_case_oracle,
                      **({"reset_retention": retention} if tb.stem in retention_cases else {})})
    isa_rows = _isa_suite_rows(project, report, isa_producer)
    for row in isa_rows:
        # A case the ISA suite producer EXECUTED is judged by the suite, not by
        # the substance-floor scaffold that stood in for it.
        if not row.get(_l10x.SIM_EXECUTED_KEY):
            continue
        cases[:] = [c for c in cases if c["name"] != row["id"]]
        cases.append({"name": row["id"],
                      "state": ("passed" if row["verdict"] == _l10x.PASS
                                else "failed"),
                      "message": row["detail"][:400], "log_tail": "",
                      "time": 0.0, "work_dir": "", "tb_file": row["tb_file"],
                      # The same execution-time identity every scaffold case
                      # carries: the bytes of the evidence file that judged it.
                      **_l10x.capture_tb_identity(Path(row["tb_file"])),
                      "has_case_oracle": True})
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
            detail = (case["message"] if case["state"] == "not_measured" else
                      "testbench did not execute because elaboration/build did not complete")
        rows.append({
            "id": case["name"],
            "verdict": verdict,
            _l10x.SIM_EXECUTED_KEY: case_executed,
            "tb_file": case["tb_file"],
            "tb_sha256": case["tb_sha256"],
            "tb_provenance": case["tb_provenance"],
            "detail": detail,
            **({"reset_retention": case["reset_retention"]} if "reset_retention" in case else {}),
        })
    if isa_rows:
        import isa_suite_producer as _isa
        rows = _isa.merge_rows(rows, isa_rows)
    execution_record = _l10x.write_record(
        project, l10_path, rows,
        producer="testbench_gen.run_unit_tbs",
        tb_dir=tb_dir, source_junit=results,
        # Binds the receipt THIS run's producer wrote (it was cleared above).
        isa_receipt=Path(project) / _l10x.ISA_RECEIPT_REL)
    report["execution_record"] = str(execution_record)
    return executed


def _clear_isa_suite_evidence(project: Path) -> None:
    """Remove the ISA-suite receipt and the producer's per-case transcripts."""
    (Path(project) / _l10x.ISA_RECEIPT_REL).unlink(missing_ok=True)
    try:
        import isa_suite_producer as _isa
    except Exception:  # noqa: BLE001 — no producer, no transcripts of its own
        return
    for log in Path(project).glob(_isa.TRANSCRIPT_REL.format(case="*")):
        log.unlink(missing_ok=True)


def _isa_suite_rows(project: Path, report: dict, producer=None) -> list:
    """Execution rows for the declared L10 cases that ask for a public ISA
    instruction-set suite (`isa_suite_producer`). Empty when no case binds.

    Each row replaces the scaffold's row for the same case. A refusal (no
    network, a lock mismatch, a design fact the producer cannot derive) is a
    NOT_EXECUTED row that NAMES the refusal, never a PASS."""
    try:
        import isa_suite_producer as _isa
        rec = (producer or _isa.produce)(project)
    except Exception as exc:  # noqa: BLE001 — the executor never crashes
        report["isa_suite"] = {"error": f"ISA suite producer failed: {exc!r}"}
        # Whatever the failed call left is not this run's evidence.
        _clear_isa_suite_evidence(project)
        return []
    report["isa_suite"] = {"refusal": rec.get("refusal"),
                           "cases": rec.get("cases"),
                           "label": rec.get("label"),
                           "receipt": _isa.RECEIPT_REL}
    return list(rec.get("rows") or [])


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
