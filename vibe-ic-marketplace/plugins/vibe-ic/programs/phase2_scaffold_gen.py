"""phase2_scaffold_gen.py — ORACLE ONLY: the executable specification of what a conforming Phase 2 emits from the L docs. Nothing in the flow runs it.

ORACLE-ONLY — READ THIS BEFORE TREATING THIS MODULE AS LIVE CODE (#509)
=======================================================================
Nothing in the shipping flow calls this program to author RTL. Measured
across ALL refs at v1.7.73 and re-measured on this change:

    programs/*runner*.py naming it ........ none, at any version
    flow/phase1_phase2_phase3.yaml ........ does not name it
    subprocess / CLI invocation ........... none
    anything else writing <top>_fsm.v ..... none

`emit_fsm_v()` / `derive_fsm_states()` are reached from this module's own
`main()` and from the layer gates below — nowhere else. Phase 2 authors RTL
through a different and fully-developed path: `design_one_shot_runner.
step_rtl_gen` dispatches deterministically, WAIVEs to the `spec-to-rtl`
skill for a class carrying `rtl_gen: null`, and consults
`reused_ip_rtl_consume` for a design that stages its own implementation.

So what this module IS, is a REFERENCE IMPLEMENTATION: an executable
statement of what a conforming Phase 2 must be able to produce from the L
docs. The layer gates import it and drive it as a CONTRACT ORACLE, and that
is the whole of its production role. It is a good one — an executable spec
beats a prose one, and it is why #404 and #377 were catchable at all:

    l1_pin_bus_width_actionable_check        l16_compliance_properties_…
    l4_regmap_phase2_emitter_contract_check  l17_channel_catalog_consumer_…
    l6_fsm_scaffold_actionable_check         cross_layer_reference_check
    regmap_bit_layout_check                  (l10 / l22 cite it in prose)

WHAT THAT OBLIGES EVERY SENTENCE WRITTEN ABOUT THIS MODULE TO SAY. A
requirement derived from it is a claim about what a CONFORMING PHASE 2
WOULD receive — never about what phase 2 does receive. The two read alike
and are not alike: a gate that blocks on a consequence which does not occur
is a gate no reader can evaluate, which is what #509 measured on the L6
gate. The requirements themselves survive unchanged, because an L doc that
cannot yield a scaffoldable FSM, a unique register identifier or a
resolvable port width is underspecified whether or not any program consumes
it. Only the justification becomes counterfactual.

`tests/test_issue509_phase2_scaffold_gen_is_oracle_only.py` pins all four
measurements above over the real tree. Wiring this module into the flow is
a legitimate thing to decide; doing it silently is not, and that test is
what makes the decision loud.

v0.1.88 — bridges Phase 1 protocol coverage (39 families, ~51 KLoC of L docs)
into deterministic Phase 2 RTL scaffolding. Reads `phase1/generated_docs/L*.json`
and emits a synthesizable Verilog skeleton at `phase2/stage1/scaffold/`.

Doctrine: this generator is GENERAL across all 39 (and future) protocols.
It uses the L-doc schema as the contract — it does NOT key off protocol
names. Each output file is a SKELETON: ports declared and tied to TODO
stubs, FSM states enumerated, registers laid out. The user/LLM fills in
behavior; the harness enforces that ports/widths/states match the spec.

Outputs — WHEN THE CLI BELOW IS RUN BY HAND. No flow step produces these
files; the gates drive the derivation functions in memory and write nothing.

    phase2/stage1/scaffold/
      ├── <top>_top.v                — module + port list + sub-module instances
      ├── <top>_regs.v               — register file skeleton (L4 derived)
      ├── <top>_fsm.v                — FSM state enum + transition skeleton (L6)
      ├── <top>_tb.v                 — testbench scaffold (clk/reset/stimulus from L10)
      ├── <top>_soc_wrap.v           — APB-lite SoC integration wrapper (L4 + L17 + L9)
      ├── <top>_cocotb_test.py       — cocotb test skeleton (clk/reset + TODO stimulus)
      ├── Makefile                   — cocotb Makefile (Icarus default)
      └── compliance_vectors.txt     — checkable spec properties (L10/L16/L22)

The generator is fail-open per file: failure to derive one scaffold does
not block the others.

ONE EXCEPTION, and it is deliberate (ORGANIC #404). If the layers STATE a
port width this generator cannot resolve to an integer — a `width_symbolic`
such as `"size-1:0"`, or a `width` that is prose — it emits NOTHING and
exits 1. It used to coerce that case to 1 bit silently, which produced a
scaffold whose top-module interface was narrower than the design and was
byte-identical to a scaffold for a design that really has a 1-bit port.
Fail-open is the right policy for a derivation that produced nothing; it is
the wrong policy for one that produced a confident wrong answer. See
`derive_signals` for the three width states and `UnresolvedPortWidth` for
why resolving the symbol here is not the remedy.

Usage (CLI):

    python3 phase2_scaffold_gen.py <project>
        --skip-tb      # skip Verilog testbench scaffold
        --skip-regs    # skip register-file scaffold
        --skip-cocotb  # skip cocotb test + Makefile scaffold
        --skip-soc     # skip APB-lite SoC integration wrapper
        --force        # overwrite existing scaffold/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Verilog reserved-word set (H3 / M5)
# ---------------------------------------------------------------------------
# A protocol signal/module literally named "reg", "input", "wire", "begin",
# etc. would emit uncompilable Verilog. We escape any sanitized identifier
# that collides (case-insensitively) with a Verilog-2005 / SystemVerilog
# reserved word by suffixing "_sig". Source: IEEE 1364-2005 Annex B keyword
# list + IEEE 1800 SystemVerilog additions.
VERILOG_RESERVED: frozenset[str] = frozenset({
    # --- Verilog-2005 (IEEE 1364-2005) keywords ---
    "always", "and", "assign", "automatic", "begin", "buf", "bufif0",
    "bufif1", "case", "casex", "casez", "cell", "cmos", "config", "deassign",
    "default", "defparam", "design", "disable", "edge", "else", "end",
    "endcase", "endconfig", "endfunction", "endgenerate", "endmodule",
    "endprimitive", "endspecify", "endtable", "endtask", "event", "for",
    "force", "forever", "fork", "function", "generate", "genvar", "highz0",
    "highz1", "if", "ifnone", "incdir", "include", "initial", "inout",
    "input", "instance", "integer", "join", "large", "liblist", "library",
    "localparam", "macromodule", "medium", "module", "nand", "negedge",
    "nmos", "nor", "noshowcancelled", "not", "notif0", "notif1", "or",
    "output", "parameter", "pmos", "posedge", "primitive", "pull0", "pull1",
    "pulldown", "pullup", "pulsestyle_onevent", "pulsestyle_ondetect", "rcmos",
    "real", "realtime", "reg", "release", "repeat", "rnmos", "rpmos", "rtran",
    "rtranif0", "rtranif1", "scalared", "showcancelled", "signed", "small",
    "specify", "specparam", "strong0", "strong1", "supply0", "supply1",
    "table", "task", "time", "tran", "tranif0", "tranif1", "tri", "tri0",
    "tri1", "triand", "trior", "trireg", "unsigned", "use", "uwire", "vectored",
    "wait", "wand", "weak0", "weak1", "while", "wire", "wor", "xnor", "xor",
    # --- SystemVerilog (IEEE 1800) additions (common subset) ---
    "alias", "always_comb", "always_ff", "always_latch", "assert", "assume",
    "before", "bind", "bins", "binsof", "bit", "break", "byte", "chandle",
    "class", "clocking", "const", "constraint", "context", "continue",
    "cover", "covergroup", "coverpoint", "cross", "dist", "do", "endclass",
    "endclocking", "endgroup", "endinterface", "endpackage", "endprogram",
    "endproperty", "endsequence", "enum", "expect", "export", "extends",
    "extern", "final", "first_match", "foreach", "forkjoin", "iff", "ignore_bins",
    "illegal_bins", "import", "inside", "interface", "intersect", "join_any",
    "join_none", "local", "logic", "longint", "matches", "modport", "new",
    "null", "package", "packed", "priority", "program", "property", "protected",
    "pure", "rand", "randc", "randcase", "randsequence", "ref", "return",
    "sequence", "shortint", "shortreal", "solve", "static", "string", "struct",
    "super", "tagged", "this", "throughout", "timeprecision", "timeunit",
    "type", "typedef", "union", "unique", "var", "virtual", "void", "wait_order",
    "wildcard", "with", "within",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _unwrap_fields(d: dict) -> dict:
    """Some L docs (L14-L23) wrap content under d['fields']. Normalize."""
    if isinstance(d, dict) and "fields" in d and isinstance(d["fields"], dict):
        merged = dict(d)
        merged.update(d["fields"])
        return merged
    return d


def _sanitize_id(s: str) -> str:
    """Convert an arbitrary string to a valid Verilog identifier.

    Beyond character/leading-digit sanitization, this escapes Verilog-2005
    and SystemVerilog reserved words (case-insensitively) so a protocol
    signal/module literally named e.g. "reg", "input", "wire", "module"
    cannot emit uncompilable Verilog (H3 / M5). The collision is resolved
    by suffixing "_sig" (e.g. "reg" -> "reg_sig", "input" -> "input_sig").
    """
    s = re.sub(r"[^A-Za-z0-9_]", "_", s.strip())
    # collapse repeated underscores, strip trailing only (not leading; we
    # need leading _ to be preserved when first char is a digit)
    s = re.sub(r"_+", "_", s).rstrip("_")
    if not s:
        return "unnamed"
    if not (s[0].isalpha() or s[0] == "_"):
        s = "sig_" + s.lstrip("_")
    if s.lower() in VERILOG_RESERVED:
        s = s + "_sig"
    return s


def _list_or_empty(v: Any) -> list:
    if isinstance(v, list):
        return v
    return []


def _dict_or_empty(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    return {}


# ---------------------------------------------------------------------------
# Top-module derivation (L9 + L17)
# ---------------------------------------------------------------------------

def derive_top_module_name(l1: dict, l9: dict, ic_name: str | None) -> str:
    """Choose a Verilog-valid top-module name from L1/L9.

    Priority: L9.top_module → L1.ic_name → "dut".
    """
    cand = ""
    for src in (l9.get("top_module"), l1.get("ic_name"), ic_name):
        if isinstance(src, str) and src.strip():
            cand = src.strip()
            break
    if not cand:
        cand = "dut"
    # Strip parenthesized suffixes like "(ARM IHI 0033C ...)"
    cand = re.sub(r"\s*\(.*\)\s*$", "", cand)
    return _sanitize_id(cand)


class UnresolvedPortWidth(RuntimeError):
    """An emitter was asked to render a port whose width was never resolved.

    Raised rather than rendered. `derive_signals` marks such a port
    ``width: None`` (ORGANIC #404); every emitter below turns a width into
    either nothing (`width == 1`) or `[width-1:0]`, and there is no third
    rendering that is honest. Emitting the 1-bit form would restore exactly
    the silent coercion this class exists to stop, one layer further down.
    """

    def __init__(self, artefact: str, ports: list[dict]) -> None:
        self.artefact = artefact
        self.ports = ports
        detail = "; ".join(
            "%s (declared %r)" % (p.get("name"), p.get("width_declared"))
            for p in ports)
        super().__init__(
            "UNRESOLVED_PORT_WIDTH: %s cannot be emitted — %d port(s) carry a "
            "width the layers STATE and phase2_scaffold_gen.derive_signals "
            "could not resolve to an integer: %s. The scaffold will not "
            "declare a 1-bit scalar for a port the design declares as a bus: "
            "that emission is byte-identical to a real 1-bit port, so nothing "
            "downstream could tell the difference, and the interface error "
            "would surface several steps later with an opaque cause. Resolving "
            "the symbol here is NOT the remedy — #404 measured that a wrong "
            "resolution and a right one are indistinguishable from outside. "
            "The remedy is in the LAYER: state the width as an integer, or "
            "declare the parameter the range names in the same document."
            % (artefact, len(ports), detail))


# Distinguishes "the layer stated no width" from every value a layer CAN
# state — including the `1` that `dict.get`'s default used to supply, which
# was then indistinguishable from a layer that really said 1.
_WIDTH_NOT_STATED = object()


def _record_declared_width(entry: dict, name: str,
                           into: dict[str, str]) -> None:
    """Note a width this module cannot use but the layer nonetheless STATES.

    Two shapes, both taken from the layer's own keys rather than from any
    prose pattern: a non-empty ``width_symbolic`` (which
    `phase1_doc_one_shot_runner._parse_port_width` fills on purpose, "so
    downstream consumers can resolve at elaboration time"), and a ``width``
    that is a non-empty string carrying anything other than digits.
    """
    if not isinstance(entry, dict):
        return
    key = _sanitize_id(str(name or ""))
    if not key or key in into:
        return
    sym = entry.get("width_symbolic")
    if isinstance(sym, str) and sym.strip():
        into[key] = sym.strip()
        return
    w = entry.get("width")
    if isinstance(w, str) and w.strip() and not w.strip().isdigit():
        into[key] = w.strip()


def unresolved_width_ports(signals: list[dict]) -> list[dict]:
    """Signals `derive_signals` refused to assign a width to."""
    return [s for s in signals
            if isinstance(s, dict) and s.get("width") is None]


def require_resolved_widths(signals: list[dict], artefact: str) -> None:
    """Raise `UnresolvedPortWidth` if any signal has no resolved width.

    Called by EVERY emitter that renders a port width, not only by
    `emit_scaffold`, so importing one emitter directly cannot route around
    the refusal.
    """
    bad = unresolved_width_ports(signals)
    if bad:
        raise UnresolvedPortWidth(artefact, bad)


def derive_signals(l17: dict, l9: dict) -> list[dict]:
    """Return a deduplicated list of {name, direction, width, comment} dicts.

    Sources, in priority order:
      1. L17.channels (list of {name, direction_master, direction_slave, purpose})
      2. L9.top_ports (if structured as list of port dicts)
      3. L9.ports

    For each channel we default to master-side direction.

    WIDTH HAS THREE STATES, NOT TWO (ORGANIC #404)
    ----------------------------------------------
    Until this landing there were two: an integer, or the 1-bit default that
    every other case fell into. A port the design declares as `[size-1:0]`
    therefore came out as ``width: 1`` — byte-identical to a real 1-bit
    scalar. An absent answer indistinguishable from a real one is the
    false-certificate shape this repo has spent a campaign removing, and it
    is worse here than elsewhere because three gates IMPORT this function to
    decide what the consumer gets. They were reading a fabricated 1.

    The three states:

      RESOLVED   the layer states a width this function can use — an int, a
                 digit-string, or a numeric ``[N:0]`` hint in an L17 channel
                 name.  ->  ``width: <int>``

      UNRESOLVED the layer STATES a width and this function cannot turn it
                 into an integer — a non-empty ``width_symbolic``, or a
                 ``width`` that is a non-empty non-numeric string.
                 ->  ``width: None`` + ``width_declared: "<the text>"``
                 The emitters REFUSE to render this (see
                 `require_resolved_widths`): a scaffold that declares a
                 1-bit port for a bus is wrong at its interface and the
                 failure surfaces several steps downstream with an opaque
                 cause.

      ABSENT     the layer states NO width at all (key missing, or null,
                 with no ``width_symbolic``).  ->  ``width: 1``, the
                 scaffold's documented scalar default.

    BOTH ENCODINGS OF "NO WIDTH" MUST BEHAVE ALIKE (#404, round 6)
    ---------------------------------------------------------------
    The contract above names two encodings of ABSENT — "key missing, or
    null" — and until this landing only the NULL one honoured
    ``width_symbolic``. `port.get("width", 1)` turned a MISSING key into an
    int >= 1, which registered the port as `resolved_from_layer` and made
    the post-pass skip it, so key-absent + ``width_symbolic`` emitted a
    silent 1-bit scalar and no emitter ever raised. Which of two equivalent
    spellings of "I have no width" the producer happened to choose decided
    whether the refusal fired.

    That was not hypothetical. Measured on this repo's own producers:
    `phase1_doc_one_shot_runner._parse_port_width` returns
    ``(None, None, 0, 'size-1:0')`` for the only non-numeric width cell in
    the tracked corpus, and BOTH L1->L9 promotion sites copy the typed
    fields under ``if _v is not None``, so a None width is DROPPED while
    ``width_symbolic`` is kept — precisely the divergent shape. It does not
    appear in any tracked L9 today only because the L1 emitter separately
    keeps the raw prose in ``width``, a retention its own comment calls
    "backward compatibility". The enforcement axis therefore rested on a
    legacy field in a different program. It no longer does.

    WHY ABSENT IS NOT UNRESOLVED, stated as a measurement rather than a
    preference: over the 106 published cells carrying
    `phase1/generated_docs`, 80 derived ports come from an entry with no
    width at all, and `l1_pin_bus_width_actionable_check.derive_bus_evidence`
    — which reads the design's OWN input files, not any L-doc — proves a bit
    range for ZERO of them. There is no measured case where the scalar
    default contradicts the design. Folding ABSENT into UNRESOLVED would
    refuse 6 of 15 IC cells for a defect no evidence supports, which is how
    a check gets deleted rather than fixed.

    THIS RESOLVES NOTHING, and that is deliberate. #404 measured that joining
    ``width_symbolic`` against the corpus' ``parameters[]`` and writing the
    result back into L1 turns `l1_pin_bus_width_actionable_check` from a
    correct FAIL into a PASS, and that resolving it HERE instead is equally
    undetectable — a same-document parameter contradicting the port's own
    stated width resolved to 4 bits on a port the design ships as 32, with
    no diagnostic anywhere. Refusing is the only answer that a wrong number
    cannot imitate.
    """
    signals: list[dict] = []
    seen: set[str] = set()
    # name -> the width TEXT the layers state and this function cannot use.
    declared_unresolved: dict[str, str] = {}
    # names whose width came from a range this function actually parsed, as
    # opposed to the 1-bit default. A port that got a real number from L17
    # is RESOLVED even if an L9 twin also carries an unusable string.
    resolved_from_layer: set[str] = set()

    def _normalize_dir(d: str | None) -> str:
        if not d:
            return "inout"
        d = d.lower()
        if "out" in d and "in" not in d:
            return "output"
        if "in" in d and "out" not in d:
            return "input"
        if "bidirectional" in d or "i/o" in d:
            return "inout"
        return "input"

    def _add(name: str, direction: str, width: int = 1,
             comment: str = "") -> None:
        if not name:
            return
        clean = _sanitize_id(name)
        if clean in seen:
            return
        seen.add(clean)
        signals.append({
            "name": clean,
            "direction": direction,
            "width": width,
            "comment": comment.strip(),
        })

    # L17 channels
    for ch in _list_or_empty(l17.get("channels")):
        if not isinstance(ch, dict):
            continue
        name = ch.get("name") or ""
        direction = _normalize_dir(ch.get("direction_master")
                                   or ch.get("direction") or "")
        purpose = ch.get("purpose") or ch.get("description") or ""
        # Attempt to parse a width hint from name (e.g., "DQ[7:0]")
        width = 1
        m = re.search(r"\[(\d+):0\]", str(name))
        if m:
            width = int(m.group(1)) + 1
            name = re.sub(r"\[\d+:0\]", "", str(name))
            resolved_from_layer.add(_sanitize_id(name))
        _record_declared_width(ch, name, declared_unresolved)
        _add(name, direction, width, comment=purpose)

    # L17 global_signals (clock, reset, power, etc.)
    for sig in _list_or_empty(l17.get("global_signals")):
        if not isinstance(sig, dict):
            continue
        name = sig.get("name") or ""
        purpose = sig.get("purpose") or sig.get("description") or ""
        direction = _normalize_dir(sig.get("direction") or "input")
        _add(name, direction, 1, comment=purpose)

    # L9 top_ports / ports fallback
    for src_key in ("top_ports", "ports"):
        for port in _list_or_empty(l9.get(src_key)):
            if not isinstance(port, dict):
                continue
            name = port.get("name") or ""
            direction = _normalize_dir(port.get("direction") or "input")
            # What the LAYER states, or the sentinel when it states nothing.
            # This used to be `port.get("width", 1)`, which supplied the
            # 1-bit default HERE — and the default then satisfied the
            # `int >= 1` test below and registered the port in
            # `resolved_from_layer`, whose own comment above says it holds
            # names resolved "as opposed to the 1-bit default". The post-pass
            # skips anything in that set, so a port carrying `width_symbolic`
            # with NO `width` key came out a silent 1-bit scalar and
            # `require_resolved_widths` never saw it — the exact collapse the
            # rest of this function exists to refuse, reachable through the
            # one encoding of "no width" that bypassed the check.
            width = port.get("width", _WIDTH_NOT_STATED)
            if isinstance(width, str) and width.isdigit():
                width = int(width)
            if isinstance(width, int) and not isinstance(width, bool) \
                    and width >= 1:
                # `_WIDTH_NOT_STATED` is not an int, so this arm is now
                # reachable only from a width the layer actually stated.
                resolved_from_layer.add(_sanitize_id(name))
            else:
                width = 1
            _record_declared_width(port, name, declared_unresolved)
            comment = port.get("description") or port.get("purpose") or ""
            _add(name, direction, width, comment=comment)

    # Ensure we have at least a clock + reset stub. Use the SAME predicate as
    # _detect_clk_port / _detect_rst_port (single source of truth) so a real
    # clock named e.g. BusClock / PCLK / HCLK is recognised and we do NOT
    # append a spurious second "clk" port (M2).
    if not any(_is_clock_name(s["name"]) for s in signals):
        _add("clk", "input", 1, comment="System clock (auto-added by scaffold)")
    if not any(_is_reset_name(s["name"]) for s in signals):
        _add("rst_n", "input", 1, comment="Active-low reset (auto-added)")

    # A single post-pass, so the verdict does not depend on which source won
    # the dedup. `_add` returns early for a name it has already seen, so a
    # port contributed by L17 with no width hint and re-stated in L9 with an
    # unusable one would otherwise keep the 1-bit default and lose the fact
    # that a declaration exists which this function never managed to read.
    for s in signals:
        text = declared_unresolved.get(s["name"])
        if text is None or s["name"] in resolved_from_layer:
            continue
        s["width"] = None
        s["width_declared"] = text

    return signals


# ---------------------------------------------------------------------------
# Clock-period derivation (L8) — shared by cocotb + (potential) tb tuning
# ---------------------------------------------------------------------------

def _to_mhz(value: Any, unit: str | None) -> float | None:
    """Normalize a (value, unit) frequency literal to MHz. Returns None on
    anything unparseable."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    u = (unit or "MHz").strip().lower()
    if u in ("ghz", "g"):
        return v * 1000.0
    if u in ("mhz", "m"):
        return v
    if u in ("khz", "k"):
        return v / 1000.0
    if u in ("hz", ""):
        return v / 1_000_000.0
    return None


def derive_clock_period_ns(l8: dict, *, default_ns: float = 10.0) -> tuple[float, str]:
    """Derive a clock period (in ns) for the testbench clock.

    GENERAL (no protocol keys). Priority:
      1. L8.clock_mhz (explicit extracted system-clock frequency)
      2. The maximum frequency literal in L8.auto_discovered_literals
         (kind == 'frequency') — the system clock is typically the fastest.
      3. default_ns (10 ns / 100 MHz).

    The resulting period is clamped to >= 1 ns to keep simulation sane for
    very high frequencies, and we ignore derived periods above 1 us (such
    literals are almost always payload/baud rates, not the core clock).
    Returns (period_ns, source_note).
    """
    mhz: float | None = None
    note = "default 100 MHz"

    cm = l8.get("clock_mhz")
    cm_mhz = _to_mhz(cm, "MHz") if cm is not None else None
    if cm_mhz:
        mhz = cm_mhz
        note = f"L8.clock_mhz = {cm_mhz} MHz"
    else:
        best: float | None = None
        for lit in _list_or_empty(l8.get("auto_discovered_literals")):
            if not isinstance(lit, dict):
                continue
            if str(lit.get("kind", "")).lower() != "frequency":
                continue
            m = _to_mhz(lit.get("value"), lit.get("unit"))
            if m is None:
                continue
            # 1 ns clamp <=> 1000 MHz; ignore sub-1-MHz (period > 1 us)
            if m < 1.0:
                continue
            if best is None or m > best:
                best = m
        if best:
            mhz = best
            note = f"L8 frequency literal max = {best} MHz"

    if not mhz:
        return float(default_ns), note
    period = 1000.0 / mhz  # MHz -> ns
    if period < 1.0:
        period = 1.0
    # round to a tidy value
    period = round(period, 3)
    return period, note


# ---------------------------------------------------------------------------
# Output: <top>_top.v
# ---------------------------------------------------------------------------

def emit_top_v(top: str, signals: list[dict], l1_ic_name: str) -> str:
    require_resolved_widths(signals, f"{top}_top.v")
    lines: list[str] = [
        "// Auto-generated by phase2_scaffold_gen.py — DO NOT EDIT THE PORT",
        "// LIST manually; fill in the BODY (marked TODO) with module logic.",
        f"// Protocol: {l1_ic_name}",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top} (",
    ]
    # Port declarations
    n = len(signals)
    for i, s in enumerate(signals):
        width = "" if s["width"] == 1 else f"[{s['width']-1}:0] "
        comma = "," if i < n - 1 else ""
        comment = f"  // {s['comment']}" if s["comment"] else ""
        lines.append(f"    {s['direction']:<6} {width}{s['name']}{comma}{comment}")
    lines += [
        ");",
        "",
        "    // -----------------------------------------------------------",
        "    // TODO — protocol behavior (registers + FSM + datapath).",
        "    // The generated scaffold pins ports, widths, and",
        "    // sub-module hierarchy. Functional logic must be written by",
        "    // hand or by the spec-to-rtl skill.",
        "    // -----------------------------------------------------------",
        "",
    ]
    # If we have a clk port, emit a register skeleton; if outputs are present,
    # tie them low to avoid synthesis errors at this stage.
    for s in signals:
        if s["direction"] == "output":
            zero = "1'b0" if s["width"] == 1 else f"{s['width']}'b0"
            lines.append(f"    assign {s['name']} = {zero}; // TODO drive")
    lines += [
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_regs.v
# ---------------------------------------------------------------------------

# A bit designation and NOTHING else. The strictness is measured, not
# defensive: 50 `bits` values in the published corpus are pin designations like
# `A[15:13]` / `A8, A10, A[15:13]` harvested from an address-pin table. A
# substring search reads `A[15:13]` as bits 15:13 of a register and would size
# a register off a package pin.
_REG_FIELD_BITS_RE = re.compile(r"^\s*\[?\s*(\d+)\s*(?::\s*(\d+)\s*)?\]?\s*$")

_REG_WIDTH_DEFAULT = 8


def _reg_width_from_own_fields(reg: dict) -> int:
    """Widest bit index declared by this register's OWN fields, +1.

    Returns the default when nothing in the record says anything numeric —
    which is the honest answer, not a fallback to be minimised. 202 fields in
    the published corpus are explicit `WHOLE_REG` placeholders meaning "this
    document carries no field breakdown" (vibe-ic#377), and they contribute
    NOTHING here on purpose: #377 measured that feeding those placeholders to
    a standard register generator produced 3235 lines of SystemVerilog
    implementing a layout nobody ever specified, indistinguishable from the
    fields that were. A placeholder must not acquire a width by being read
    twice."""
    widest = 0
    for f in _list_or_empty(reg.get("fields")):
        if not isinstance(f, dict):
            continue
        m = _REG_FIELD_BITS_RE.match(str(f.get("bits") or ""))
        if not m:
            continue
        hi = int(m.group(1))
        lo = int(m.group(2)) if m.group(2) else hi
        widest = max(widest, hi, lo)
    return (widest + 1) if widest else _REG_WIDTH_DEFAULT


def derive_registers(l4: dict, l8: dict) -> list[dict]:
    """Return a normalized [{name, offset, width, access, fields}, ...]."""
    out: list[dict] = []
    raw = _list_or_empty(l4.get("registers"))
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = _sanitize_id(str(r.get("name") or r.get("abbrev") or "REG"))
        # layergate-2 — DISTILLED FIX, not a per-design workaround.
        # `regmap_table_extractor.py` (this plugin's own L4 register-table
        # walker) emits a register's address as `addr_hex`; the rst/CSR
        # walkers in phase1_doc_one_shot_runner do the same. This function
        # read only `offset`/`address`, so for every register extracted by
        # those paths the address was silently dropped and emit_regs_v()
        # wrote nothing but `// TODO — address decode (per L4 offsets)`.
        # Two programs in the same plugin disagreeing on one key.
        # Measured across the fleet before this fix: 49 of 139 real
        # Phase-1 outputs affected (30 of 42 registers on one design,
        # 32 of 80 on another, 1 of 1 on a third) — the address was
        # always present in L4, just under a key its consumer never read.
        # Reading the sibling key here fixes the whole class at once
        # rather than leaving 49 runs to be patched individually.
        off = (r.get("offset") or r.get("address")
               or r.get("addr_hex") or r.get("addr") or "")
        width = r.get("width") or r.get("width_bits")
        if isinstance(width, str):
            m = re.search(r"\d+", width)
            width = int(m.group(0)) if m else None
        if width is None:
            # SAME DEFECT SHAPE AS layergate-2 ABOVE: the value is present in
            # the record the consumer is already holding, under a key it never
            # reads. The register's own fields state their bits; this read only
            # `width`/`width_bits` and otherwise emitted `reg [7:0]`.
            #
            # MEASURED over the published corpus (strict bit-designation match):
            #     81 registers wide enough already
            #      8 emitted NARROWER than their own fields declare
            # and the widest of those declares a field spanning 32 bits and was
            # emitted `reg [7:0]` — 24 bits of a DECLARED field simply absent
            # from the RTL, with no diagnostic. The output is byte-identical to
            # a register the design really did specify as 8 bits.
            #
            # Scoped to ONE record on purpose. #404 measured that joining a
            # width against a corpus-global `parameters[]` by bare name lets an
            # unrelated layer size a bus; nothing here leaves the register.
            width = _reg_width_from_own_fields(r)
        access = r.get("access") or r.get("attribute") or "rw"
        out.append({
            "name": name,
            "offset": str(off),
            "width": int(width),
            "access": str(access).lower(),
            "fields": _list_or_empty(r.get("fields")),
        })
    return out


def emit_regs_v(top: str, regs: list[dict]) -> str:
    if not regs:
        # Protocols without a register file get a stub
        return (
            "// Auto-generated — protocol has no addressable register file.\n"
            "// This file is intentionally empty.\n"
            f"// Top module: {top}\n"
        )
    lines = [
        "// Auto-generated register-file skeleton.",
        "// Address decode + read/write hooks are stubbed; behavior is TODO.",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_regs (",
        "    input         clk,",
        "    input         rst_n,",
        "    input  [31:0] reg_addr,",
        "    input         reg_we,",
        "    input  [31:0] reg_wdata,",
        "    output reg [31:0] reg_rdata",
        ");",
        "",
        "    // Register declarations",
    ]
    for r in regs:
        w = r["width"]
        wdecl = "" if w == 1 else f"[{w-1}:0] "
        lines.append(f"    reg {wdecl}{r['name']}; // offset {r['offset']} ({r['access']})")
    lines += [
        "",
        "    // Reset",
        "    always @(posedge clk or negedge rst_n) begin",
        "        if (!rst_n) begin",
    ]
    for r in regs:
        w = r["width"]
        zero = "1'b0" if w == 1 else f"{w}'b0"
        lines.append(f"            {r['name']} <= {zero};")
    lines += [
        "        end else if (reg_we) begin",
        "            // TODO — address decode (per L4 offsets)",
        "        end",
        "    end",
        "",
        "    // Read mux (TODO — match the offsets above)",
        "    always @(*) begin",
        "        reg_rdata = 32'b0;",
        "    end",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_fsm.v
# ---------------------------------------------------------------------------

def derive_fsm_states(l6: dict) -> list[str]:
    out: list[str] = []
    for src_key in ("fsm_states", "fsm_hints",
                    "fsm_hints_transmitter",
                    "fsm_hints_receiver",
                    "fsm_hints_master",
                    "fsm_hints_slave"):
        raw = l6.get(src_key)
        for st in _list_or_empty(raw):
            if isinstance(st, dict):
                nm = st.get("name") or st.get("state") or ""
                if nm:
                    out.append(_sanitize_id(str(nm)))
            elif isinstance(st, str):
                out.append(_sanitize_id(st))
    # Dedup preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq[:32]  # cap at 32 to keep enum widths sane


def emit_fsm_v(top: str, states: list[str]) -> str:
    if not states:
        return (
            "// Auto-generated — protocol has no enumerable FSM in L6.\n"
            "// This file is intentionally empty.\n"
            f"// Top module: {top}\n"
        )
    n = len(states)
    w = max(1, (n - 1).bit_length())
    lines = [
        "// Auto-generated FSM skeleton.",
        f"// {n} states — transitions are TODO; only state enum + reset path are generated.",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_fsm (",
        "    input  clk,",
        "    input  rst_n,",
        f"    output reg [{w-1}:0] state",
        ");",
        "",
        "    // State encoding",
    ]
    for i, s in enumerate(states):
        lines.append(f"    localparam [{w-1}:0] S_{s.upper()} = {w}'d{i};")
    lines += [
        "",
        "    always @(posedge clk or negedge rst_n) begin",
        "        if (!rst_n) begin",
        f"            state <= S_{states[0].upper()};",
        "        end else begin",
        "            // TODO — transition logic per L6.fsm_transitions",
        "        end",
        "    end",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_tb.v
# ---------------------------------------------------------------------------

def emit_tb_v(top: str, signals: list[dict]) -> str:
    require_resolved_widths(signals, f"{top}_tb.v")
    inputs = [s for s in signals if s["direction"] == "input"]
    outputs = [s for s in signals if s["direction"] == "output"]
    inouts = [s for s in signals if s["direction"] == "inout"]
    lines = [
        "// Auto-generated testbench scaffold.",
        "// Stimulus + checks are TODO; the scaffold provides clock, reset,",
        "// DUT instantiation, and waveform dump.",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_tb;",
        "",
    ]
    # Declare DUT signals
    for s in signals:
        w = "" if s["width"] == 1 else f"[{s['width']-1}:0] "
        if s["direction"] == "input":
            lines.append(f"    reg  {w}{s['name']};")
        elif s["direction"] == "output":
            lines.append(f"    wire {w}{s['name']};")
        else:
            lines.append(f"    wire {w}{s['name']}; // inout")
    lines += [
        "",
        "    // DUT instance",
        f"    {top} u_dut (",
    ]
    n = len(signals)
    for i, s in enumerate(signals):
        comma = "," if i < n - 1 else ""
        lines.append(f"        .{s['name']}({s['name']}){comma}")
    lines += [
        "    );",
        "",
        "    // Clock generation — defaults to 100 MHz; override per protocol.",
    ]
    clk_name = next((s["name"] for s in inputs
                     if "clk" in s["name"].lower() or "clock" in s["name"].lower()),
                    None)
    if clk_name:
        lines += [
            f"    initial {clk_name} = 1'b0;",
            f"    always #5 {clk_name} = ~{clk_name};",
        ]
    lines += [
        "",
        "    // Reset + waveform + minimal scenario",
        "    initial begin",
        "        $dumpfile(\"" + top + "_tb.vcd\");",
        f"        $dumpvars(0, {top}_tb);",
    ]
    # Default all inputs to 0
    for s in inputs:
        if s["name"] == clk_name:
            continue
        zero = "1'b0" if s["width"] == 1 else f"{s['width']}'b0"
        lines.append(f"        {s['name']} = {zero};")
    # Release reset after 30 ns if a reset-like input is present
    rst_name = next((s["name"] for s in inputs
                     if "rst" in s["name"].lower() or "reset" in s["name"].lower()),
                    None)
    if rst_name:
        active_low = "n" in rst_name.lower()
        if active_low:
            lines.append(f"        {rst_name} = 1'b0;")
            lines.append("        #30;")
            lines.append(f"        {rst_name} = 1'b1;")
        else:
            lines.append(f"        {rst_name} = 1'b1;")
            lines.append("        #30;")
            lines.append(f"        {rst_name} = 1'b0;")
    lines += [
        "        // TODO — protocol stimulus + assertions per L10 test cases.",
        "        #1000;",
        "        $finish;",
        "    end",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: compliance_vectors.txt
# ---------------------------------------------------------------------------

def emit_compliance_vectors(l10: dict, l16: dict, l22: dict) -> str:
    lines = [
        "# Auto-generated compliance vector catalog.",
        "# One requirement per line; format: <source-L-doc>: <description>",
        "",
    ]
    # L10 test_cases
    for src in (l10.get("test_cases"),
                l10.get("derived_compliance_test_categories"),
                l10.get("annex_c_normative_fsms"),
                l10.get("annex_d_typical_examples")):
        for item in _list_or_empty(src):
            txt = str(item.get("name") if isinstance(item, dict) else item)
            if txt:
                lines.append(f"L10: {txt[:120]}")
    # L16 must-have compliance.
    #
    # SILENT DEAD READ (fixed): this used to read only `must_have_properties` /
    # `must_have_compliance` / `compliance_properties` — the shapes the
    # hand-written protocol synthesisers emit. The Phase-1 EXTRACTOR
    # (phase1_protocol_spec_extract.extract_l16_compliance) emits
    # `properties[]` with the requirement text under `english_form`, so on
    # every extractor-driven run BOTH the container key AND the text key
    # missed and L16 contributed ZERO lines to compliance_vectors.txt while
    # the layer reported EXTRACTED. Reading `properties` and `english_form`
    # closes that. Guarded by l16_compliance_properties_actionable_check.py.
    for src in (l16.get("properties"),
                l16.get("must_have_properties"),
                l16.get("must_have_compliance"),
                l16.get("compliance_properties")):
        for item in _list_or_empty(src):
            if isinstance(item, str):
                txt = item
            elif isinstance(item, dict):
                txt = str(item.get("english_form") or item.get("text")
                          or item.get("description") or item.get("statement")
                          or item)
            else:
                txt = str(item)
            if txt and len(txt) > 1:
                lines.append(f"L16: {txt[:120]}")
    # L22 verification plan
    for src in (l22.get("verification_categories"),
                l22.get("verification_plan")):
        for item in _list_or_empty(src):
            txt = str(item if isinstance(item, str) else item.get("text") or
                      item.get("description") or item)
            if txt and len(txt) > 1:
                lines.append(f"L22: {txt[:120]}")
    if len(lines) == 3:
        lines.append("# (no extractable compliance properties found in L10/L16/L22)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Clock / reset port detection (shared by tb + cocotb + soc_wrap + derive_signals)
# ---------------------------------------------------------------------------

def _is_clock_name(n: str) -> bool:
    """True when a (case-insensitive) signal name looks like a clock.

    Single source of truth — substring match on 'clk' / 'clock' so names like
    BusClock / PCLK / HCLK / SCK_clk are all recognised. Used by BOTH the
    derive_signals auto-add guard AND _detect_clk_port."""
    n = n.lower()
    return "clk" in n or "clock" in n


def _is_reset_name(n: str) -> bool:
    """True when a (case-insensitive) signal name looks like a reset.

    Single source of truth — substring match on 'rst' / 'reset'. Used by BOTH
    the derive_signals auto-add guard AND _detect_rst_port."""
    n = n.lower()
    return "rst" in n or "reset" in n


def _is_active_low_reset_name(n: str) -> bool:
    """True only for canonical ACTIVE-LOW reset name forms.

    Recognises rst_n / resetn / rstn / n_rst / nreset / arstn (and the
    aresetn / presetn family) plus an explicit _n / _b / _l suffix. Common
    ACTIVE-HIGH names that merely happen to start/end with 'n' (e.g.
    'reset_in', 'n_clk_en') are NOT matched — that was the M3 false-positive."""
    n = n.lower()
    canonical = ("rst_n", "resetn", "rstn", "n_rst", "nreset", "arstn")
    if any(tok in n for tok in canonical):
        return True
    return n.endswith("_n") or n.endswith("_b") or n.endswith("_l")


def _detect_clk_port(signals: list[dict]) -> str | None:
    """Return the name of the most clock-like INPUT port, else None."""
    for s in signals:
        if s["direction"] != "input":
            continue
        if _is_clock_name(s["name"]):
            return s["name"]
    return None


def _detect_rst_port(signals: list[dict]) -> tuple[str | None, bool]:
    """Return (reset_input_name, active_low). active_low True only for
    canonical active-low forms (rst_n / resetn / aresetn / _n / _b / _l …)."""
    for s in signals:
        if s["direction"] != "input":
            continue
        if _is_reset_name(s["name"]):
            return s["name"], _is_active_low_reset_name(s["name"])
    return None, False


# ---------------------------------------------------------------------------
# Output: <top>_cocotb_test.py + Makefile
# ---------------------------------------------------------------------------

def emit_cocotb_test(top: str, signals: list[dict], l8: dict,
                     compliance_categories: list[str]) -> str:
    """Emit a cocotb test skeleton.

    GENERAL (no protocol keys): starts a clock on the detected clk port,
    asserts/releases the detected reset, and leaves a TODO block for
    protocol stimulus. Clock period comes from L8 (see
    derive_clock_period_ns); falls back to 10 ns.
    """
    require_resolved_widths(signals, f"{top}_cocotb_test.py")
    period_ns, period_note = derive_clock_period_ns(l8)
    clk = _detect_clk_port(signals)
    rst, active_low = _detect_rst_port(signals)

    lines: list[str] = [
        '"""Auto-generated cocotb test skeleton for ' + top + '.',
        "",
        "Generated by phase2_scaffold_gen.py — GENERAL across all protocols.",
        "Fill in the protocol stimulus marked TODO; the scaffold wires the",
        "clock and reset only.",
        "",
        "Run with:  make   (uses the generated Makefile / Icarus by default)",
        '"""',
        "import cocotb",
        "from cocotb.clock import Clock",
        "from cocotb.triggers import RisingEdge, Timer",
        "",
        "",
    ]
    # Compliance categories as comments
    if compliance_categories:
        lines.append("# Compliance-vector categories (see compliance_vectors.txt):")
        for c in compliance_categories[:20]:
            lines.append(f"#   - {c}")
        lines.append("")

    lines += [
        "@cocotb.test()",
        f"async def test_{top}_smoke(dut):",
        '    """Smoke test: clock the DUT, pulse reset, idle.',
        "",
        f"    Clock period derived from {period_note}.",
        '    """',
    ]
    if clk:
        lines += [
            f"    # Start a {period_ns} ns clock on the detected clock port.",
            f"    cocotb.start_soon(Clock(dut.{clk}, {period_ns}, units=\"ns\").start())",
        ]
    else:
        lines += [
            "    # No clock port detected in L17/L9; combinational or",
            "    # externally-clocked DUT. Add a clock here if needed.",
        ]
    lines.append("")

    if rst:
        if active_low:
            lines += [
                "    # Assert active-low reset, hold, then release.",
                f"    dut.{rst}.value = 0",
                "    await Timer(100, units=\"ns\")",
                f"    dut.{rst}.value = 1",
            ]
        else:
            lines += [
                "    # Assert active-high reset, hold, then release.",
                f"    dut.{rst}.value = 1",
                "    await Timer(100, units=\"ns\")",
                f"    dut.{rst}.value = 0",
            ]
    else:
        lines += [
            "    # No reset port detected; nothing to de-assert.",
        ]
    lines.append("")

    if clk:
        lines += [
            f"    await RisingEdge(dut.{clk})",
        ]
    lines += [
        "",
        "    # TODO: drive protocol stimulus per L10 compliance_vectors.",
        "    #   1. Apply the input transactions for each compliance category",
        "    #      listed above.",
        "    #   2. Sample DUT outputs and assert against expected behavior.",
        "    #   3. Cover reset, idle, and error/edge cases.",
        "",
        "    await Timer(1000, units=\"ns\")",
        f"    dut._log.info(\"{top} cocotb smoke test completed (stimulus is TODO)\")",
        "",
    ]
    return "\n".join(lines)


def emit_cocotb_makefile(top: str) -> str:
    """Standard cocotb Makefile targeting Icarus by default."""
    lines = [
        "# Auto-generated cocotb Makefile for " + top + ".",
        "# Override SIM=verilator (etc.) on the command line if desired.",
        "",
        "TOPLEVEL_LANG ?= verilog",
        "SIM ?= icarus",
        "",
        f"VERILOG_SOURCES = $(PWD)/{top}_top.v",
        "# Add register-file / FSM / soc-wrap sources here as the design grows:",
        f"# VERILOG_SOURCES += $(PWD)/{top}_regs.v",
        f"# VERILOG_SOURCES += $(PWD)/{top}_fsm.v",
        f"# VERILOG_SOURCES += $(PWD)/{top}_soc_wrap.v",
        "",
        f"TOPLEVEL = {top}",
        f"MODULE   = {top}_cocotb_test",
        "",
        "include $(shell cocotb-config --makefiles)/Makefile.sim",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_soc_wrap.v — APB-lite SoC integration wrapper
# ---------------------------------------------------------------------------

def emit_soc_wrap_v(top: str, signals: list[dict], regs: list[dict]) -> str:
    """Emit an APB-lite SoC integration wrapper around <top>.

    GENERAL (no protocol keys): reads L4 registers + L17/L9 signals + L9
    top_module. Exposes a standard APB-lite register-access bus so the
    protocol block can drop into an SoC.

      - If the protocol HAS a register file (L4 non-empty): wire an
        APB -> register-file decode stub (TODO body) that the integrator
        connects to the block's internal registers.
      - If the protocol has NO register file: expose the block's native
        ports at the wrapper boundary and tie the APB bus to a read-only
        ID register (so the SoC can still probe the wrapper).
    """
    require_resolved_widths(signals, f"{top}_soc_wrap.v")
    has_regs = bool(regs)
    # Native (non-clock/reset) ports we re-expose at the wrapper boundary.
    clk = _detect_clk_port(signals)
    rst, _active_low = _detect_rst_port(signals)
    native = [s for s in signals
              if s["name"] != clk and s["name"] != rst]

    lines: list[str] = [
        "// Auto-generated SoC integration wrapper (APB-lite).",
        "// Wraps " + top + " and exposes a standard register-access bus so the",
        "// protocol block can drop into an SoC. Decode body is TODO.",
        f"// Top module: {top}",
        f"// Register file present (L4): {'yes' if has_regs else 'no'}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_soc_wrap (",
        "    // ---- APB-lite register-access bus ----",
        "    input         PCLK,",
        "    input         PRESETn,",
        "    input  [11:0] PADDR,",
        "    input         PSEL,",
        "    input         PENABLE,",
        "    input         PWRITE,",
        "    input  [31:0] PWDATA,",
        "    output reg [31:0] PRDATA,",
        "    output        PREADY",
    ]
    # Re-expose native protocol ports (so the block still connects to pads).
    if native:
        lines.append("    ,")
        lines.append("    // ---- native protocol ports (passthrough to pads) ----")
        for i, s in enumerate(native):
            w = "" if s["width"] == 1 else f"[{s['width']-1}:0] "
            comma = "," if i < len(native) - 1 else ""
            comment = f"  // {s['comment']}" if s["comment"] else ""
            lines.append(f"    {s['direction']:<6} {w}{s['name']}{comma}{comment}")
    lines += [
        ");",
        "",
        "    // APB-lite is always single-cycle ready in this wrapper.",
        "    assign PREADY = 1'b1;",
        "",
        "    wire apb_write = PSEL & PENABLE &  PWRITE;",
        "    wire apb_read  = PSEL & PENABLE & ~PWRITE;",
        "",
    ]

    if has_regs:
        lines += [
            "    // -----------------------------------------------------------",
            "    // APB -> register-file decode stub.",
            f"    // The protocol exposes {len(regs)} register(s) (from L4).",
            "    // TODO: connect PWDATA/PRDATA to the block's register file",
            "    //       using the offsets below, then instantiate the block.",
            "    // -----------------------------------------------------------",
        ]
        for r in regs:
            lines.append(
                f"    // offset {r['offset']:<8} {r['name']} "
                f"[{r['width']}b, {r['access']}]")
        lines += [
            "",
            "    always @(*) begin",
            "        PRDATA = 32'h0;",
            "        if (apb_read) begin",
            "            case (PADDR)",
            "                // TODO: 12'hXXX: PRDATA = <reg>;  per offsets above",
            "                default: PRDATA = 32'h0;",
            "            endcase",
            "        end",
            "    end",
            "",
            "    // TODO: on apb_write, decode PADDR and update the block's",
            "    //       register file (writes are stubbed out for now).",
            "",
        ]
    else:
        lines += [
            "    // -----------------------------------------------------------",
            "    // No register file (L4 empty). Expose a read-only ID register",
            "    // so the SoC can still probe the wrapper, and pass the block's",
            "    // native ports through to the wrapper boundary.",
            "    // -----------------------------------------------------------",
            "    localparam [31:0] WRAP_ID = 32'h5343_5750; // \"SCWP\"",
            "",
            "    always @(*) begin",
            "        PRDATA = 32'h0;",
            "        if (apb_read) begin",
            "            case (PADDR)",
            "                12'h000: PRDATA = WRAP_ID; // read-only ID register",
            "                default: PRDATA = 32'h0;",
            "            endcase",
            "        end",
            "    end",
            "",
        ]

    # Instantiate the wrapped block, connecting native ports straight through.
    lines += [
        "    // Wrapped protocol-block instance.",
        f"    {top} u_{top} (",
    ]
    inst_ports: list[str] = []
    for s in signals:
        if s["name"] == clk:
            inst_ports.append(f"        .{s['name']}(PCLK)")
        elif s["name"] == rst:
            # Connect block reset to PRESETn (best-effort; integrator confirms
            # polarity). PRESETn is active-low, matching the common rst_n case.
            inst_ports.append(f"        .{s['name']}(PRESETn)")
        else:
            inst_ports.append(f"        .{s['name']}({s['name']})")
    for i, p in enumerate(inst_ports):
        comma = "," if i < len(inst_ports) - 1 else ""
        lines.append(p + comma)
    lines += [
        "    );",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compliance-category extraction (for cocotb comments)
# ---------------------------------------------------------------------------

def _compliance_categories(text: str) -> list[str]:
    """Pull short category labels from a compliance_vectors.txt blob."""
    cats: list[str] = []
    seen: set[str] = set()
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        # Format is "<Lxx>: <description>"
        _, _, rest = ln.partition(":")
        rest = rest.strip()
        if rest and rest not in seen:
            seen.add(rest)
            cats.append(rest[:80])
    return cats


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def emit_scaffold(project: Path,
                  *,
                  skip_tb: bool = False,
                  skip_regs: bool = False,
                  skip_cocotb: bool = False,
                  skip_soc: bool = False,
                  force: bool = False) -> dict:
    """Emit scaffold for one benchmark project. Returns a report dict."""
    gd = project / "phase1" / "generated_docs"
    if not gd.is_dir():
        return {"project": str(project), "status": "skipped",
                "reason": "phase1/generated_docs missing"}
    out_dir = project / "phase2" / "stage1" / "scaffold"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load the relevant L docs (unwrap fields where applicable)
    l1 = _unwrap_fields(_load(gd / "L1_DATASHEET.json"))
    l4 = _unwrap_fields(_load(gd / "L4_REGMAP.json"))
    l6 = _unwrap_fields(_load(gd / "L6_CONTROL_LOGIC.json"))
    l8 = _unwrap_fields(_load(gd / "L8_RTL_CONSTANTS.json"))
    l9 = _unwrap_fields(_load(gd / "L9_INTEGRATION_SPEC.json"))
    l10 = _unwrap_fields(_load(gd / "L10_TEST_CASES.json"))
    l16 = _unwrap_fields(_load(gd / "L16_COMPLIANCE_PROPERTIES.json"))
    l17 = _unwrap_fields(_load(gd / "L17_CHANNEL_SIGNAL_CATALOG.json"))
    l22 = _unwrap_fields(_load(gd / "L22_VERIFICATION_PLAN.json"))

    ic_name = l1.get("ic_name") or "unknown"
    top = derive_top_module_name(l1, l9, ic_name)
    signals = derive_signals(l17, l9)

    # BLOCKING, and BEFORE the first write (ORGANIC #404). The individual
    # emitters refuse too, but a refusal discovered on the fourth `_write`
    # leaves three scaffold files on disk built around an interface the
    # fourth just declared unemittable — a partial scaffold is a worse
    # artefact than none, and the next reader has no way to tell it is
    # partial. `_top.v` is the first thing written, so the check has to be
    # here to be ahead of it.
    #
    # Blast radius, measured over the 106 published cells that carry
    # `phase1/generated_docs` (the 15 under `benchmark-data/ic` plus the
    # 81-IC phase-1 parity corpus, which is where the published scaffold
    # artefacts actually live): 3 cells declare a width this consumer
    # cannot resolve, all three the SAME port of the same design, and NONE
    # of the three has a published scaffold — their RTL was authored, and
    # it declares the parameter and the symbolic range correctly. So this
    # refusal changes ZERO published artefacts while changing what the
    # generator would emit on the one input shape where it was wrong.
    require_resolved_widths(signals, f"{top}_top.v")

    written: list[str] = []

    def _write(name: str, content: str) -> None:
        path = out_dir / name
        if path.is_file() and not force and path.read_text() == content:
            return
        path.write_text(content)
        written.append(name)

    # Always emit top + fsm + compliance
    _write(f"{top}_top.v", emit_top_v(top, signals, ic_name))
    fsm_states = derive_fsm_states(l6)
    _write(f"{top}_fsm.v", emit_fsm_v(top, fsm_states))
    compliance_text = emit_compliance_vectors(l10, l16, l22)
    _write("compliance_vectors.txt", compliance_text)

    # Registers are derived once and shared by regs + soc_wrap emitters.
    regs = derive_registers(l4, l8)

    if not skip_regs:
        _write(f"{top}_regs.v", emit_regs_v(top, regs))

    if not skip_tb:
        _write(f"{top}_tb.v", emit_tb_v(top, signals))

    if not skip_cocotb:
        cats = _compliance_categories(compliance_text)
        _write(f"{top}_cocotb_test.py",
               emit_cocotb_test(top, signals, l8, cats))
        _write("Makefile", emit_cocotb_makefile(top))

    if not skip_soc:
        _write(f"{top}_soc_wrap.v", emit_soc_wrap_v(top, signals, regs))

    clk_period_ns, clk_period_note = derive_clock_period_ns(l8)
    return {
        "project": str(project),
        "status": "ok",
        "ic_name": ic_name,
        "top_module": top,
        "signals_count": len(signals),
        "registers_count": len(regs),
        "fsm_states_count": len(fsm_states),
        "clock_period_ns": clk_period_ns,
        "clock_period_source": clk_period_note,
        "has_register_file": bool(regs),
        "files_emitted": written,
        "out_dir": str(out_dir),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
    )
    ap.add_argument("project", type=Path,
                    help="Benchmark project root (contains phase1/, phase2/)")
    ap.add_argument("--skip-tb", action="store_true",
                    help="Skip testbench scaffold")
    ap.add_argument("--skip-regs", action="store_true",
                    help="Skip register-file scaffold")
    ap.add_argument("--skip-cocotb", action="store_true",
                    help="Skip cocotb testbench + Makefile scaffold")
    ap.add_argument("--skip-soc", action="store_true",
                    help="Skip APB-lite SoC integration wrapper")
    ap.add_argument("--force", action="store_true",
                    help="Re-emit even if content matches")
    args = ap.parse_args()

    proj = args.project.resolve()
    if not proj.is_dir():
        print(f"ERROR: project not a directory: {proj}", file=sys.stderr)
        return 2

    try:
        report = emit_scaffold(proj,
                               skip_tb=args.skip_tb,
                               skip_regs=args.skip_regs,
                               skip_cocotb=args.skip_cocotb,
                               skip_soc=args.skip_soc,
                               force=args.force)
    except UnresolvedPortWidth as exc:
        # NOT swallowed into a "skipped" report. The module docstring says
        # this generator is fail-open PER FILE — one scaffold failing does
        # not block the others — and that policy is right for a derivation
        # that produced nothing. It is wrong here: the port list is the one
        # artefact every other file is built from, and the failure mode this
        # replaces was a scaffold that emitted happily and was wrong.
        print(json.dumps({
            "project": str(proj),
            "status": "blocked",
            "reason": "UNRESOLVED_PORT_WIDTH",
            "artefact": exc.artefact,
            "ports": [{"name": p.get("name"),
                       "width_declared": p.get("width_declared")}
                      for p in exc.ports],
            "detail": str(exc),
        }, indent=2))
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
