#!/usr/bin/env python3
"""RESET-INVARIANT oracle TBs — the family beside the boot-latency one.

MEASURED on subservient x gf180mcuD as a DIE, FRONT DOOR, run r48 (lane
icsub2, host 8HD-4, tree 41d3b39b8, image 0.3.67 sha256:4e9f54ef): 1 of 10
declared L10 cases executed its own oracle. Four of the nine that did not
need a test program nobody delivers; three are conditional on ISA options the
design does not select. TWO need NOTHING DELIVERED AT ALL --

    reset_assert_sram
      stimulus "Reset assert 中 SRAM 內容保留"
    i_rst_glitch_instruction_fetch_race
      stimulus "i_rst glitch 不應導致 instruction fetch race"

-- because they are PROPERTIES over the design's own declared observables.
They fell to the substance-floor scaffold only because the flow owns an
emitter for one property family (`cpu_boot_latency_oracle_tb_gen`, the
"within N cycles of reset release" convention -- which is exactly why
`reset_n_cycle_instruction` is the single case that executed) and none for
this one. This module is that missing family.

WHAT IT GROUNDS. Full storage retention requires the selected external-memory
protocol, actual byte snapshots and both idle and pending-write reset windows.
The pending window includes reset's FIRST sampled edge; the external memory
always consumes the previous registered transaction, even on that edge.
Missing protocol, pending activity or current bytes is NOT_MEASURED.

  RESET_ASSERT_HOLD measures byte content through the explicitly declared
    registered dual-port byte protocol. Without that binding the historical
    write-strobe check remains a falsifiable necessary condition only. It can
    detect a violation, but its success cannot credit full memory retention.

  RESET_GLITCH_NO_RACE  "a reset glitch must not cause a fetch race" is
    observed as: during a SHORT reset pulse applied mid-operation, the bus
    activity output stays deasserted, and after release no observable output
    is left X/Z. A transaction that survives into -- or is launched inside --
    the reset window is the race the case names.

    It does NOT claim the converse (an unraced fetch is not proven correct by
    this TB), and it does not fabricate an instruction stream.

FAIL-CLOSED throughout: a case whose own text does not state the invariant,
or a DUT whose port surface offers nothing to observe it on, returns None and
falls through to the substance-floor scaffold, so a case nobody can verify
still fails the Step-4 gate honestly.

chip-AGNOSTIC: keyed on the case's own declared grammar and on structural
port-name vocabulary (`we`/`wen`/`write`/`wr`; `cyc`/`stb`/`req`/`valid`),
never on a case-name, chip, vendor or SKU literal.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import json
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── the case's own grammar ────────────────────────────────────────────────
#: reset is ASSERTED (held), as opposed to released — the boot-latency family
#: owns the release side and the two must not both claim a case.
_RE_RESET_ASSERT = re.compile(
    r"reset\s*(?:assert|中|期間|holds?)|(?:^|\s)rst\s*assert", re.IGNORECASE)
#: "content/state is preserved / retained / unchanged"
_RE_PRESERVED = re.compile(
    r"保留|保持|不變|preserv|retain|unchanged|intact", re.IGNORECASE)
#: a storage noun the invariant is about
_RE_STORAGE = re.compile(r"sram|ram|memory|記憶體|register\s*file|regfile",
                         re.IGNORECASE)
#: a short reset pulse / glitch
_RE_GLITCH = re.compile(r"glitch|毛刺|spike|短脈衝", re.IGNORECASE)
#: the hazard the case names
_RE_RACE = re.compile(r"race|競|hazard", re.IGNORECASE)
#: negation — the case says the hazard must NOT happen
_RE_MUST_NOT = re.compile(r"不應|不得|不能|must\s*not|should\s*not|no\s+",
                          re.IGNORECASE)

# ── structural port vocabulary (suffix match, never a chip literal) ───────
_WRITE_TOKENS = ("we", "wen", "write", "wr", "wstrb", "wr_en")
_WRITE_RES = [re.compile(rf"(?:^|_){t}(?:_o|_out)?$", re.IGNORECASE)
              for t in _WRITE_TOKENS]
_BUS_ACTIVITY_TOKENS = ("cyc", "stb", "strobe", "req", "valid")
_BUS_ACTIVITY_RES = [re.compile(rf"(?:^|_){t}(?:_o|_out)?$", re.IGNORECASE)
                     for t in _BUS_ACTIVITY_TOKENS]
#: Read-enables are bus activity, the mirror of `wen` above; see the same
#: vocabulary in `cpu_boot_latency_oracle_tb_gen` for the measurement. A
#: FALLBACK ONLY: a top with a handshake output keeps observing it.
_READ_ENABLE_TOKENS = ("ren", "rden", "rd_en", "read_en")
_READ_ENABLE_RES = [re.compile(rf"(?:^|_){t}(?:_o|_out)?$", re.IGNORECASE)
                    for t in _READ_ENABLE_TOKENS]
_CLOCK_RE = re.compile(r"(?:^|_)(?:clk|clock)(?:$|_)", re.IGNORECASE)
_RESET_RE = re.compile(r"(?:^|_)(?:rst|reset|resetn|rstn)(?:$|_)",
                       re.IGNORECASE)
_ACTIVE_LOW_RE = re.compile(r"(?:_n$|n$|_b$|(?:^|_)(?:rstn|resetn)(?:$|_))",
                            re.IGNORECASE)

FAMILY_HOLD = "RESET_ASSERT_HOLD"
FAMILY_GLITCH = "RESET_GLITCH_NO_RACE"

#: Cycles observed after the glitch is released. Every one is sampled, from
#: the FIRST edge after release (R-0929-X-QUALIFIED), not a single late look.
POST_RELEASE_CYCLES = 8

# ── R-0929-X-QUALIFIED: the qualifiers the DESIGN INPUT declares ──────────
#: A condition word: the sentence makes one signal's meaning conditional on
#: another's level ("wdata is sampled WHEN wen=1", "資料於 we 為 1 時有效").
_QUAL_COND_RE = re.compile(
    r"\bwhen(?:ever)?\b|\bwhile\b|\bif\b|\bqualified\s+by\b|\bsampled\b|"
    r"\bvalid\b|當|時|期間|有效|取樣", re.IGNORECASE)
#: VALIDITY semantics (R-0929-X-QUALIFIED): the clause says the output's value
#: is VALID / SAMPLED / QUALIFIED / CAPTURED at the qualifier's level. A bare
#: condition ("o_done is high when o_busy is low", "o_q cleared to 0 when
#: rst_n is low") is a behaviour or a reset value, not a validity qualifier.
#: `低有效` / `高電位有效` spell ACTIVE-LOW / -HIGH, not validity.
_QUAL_VALIDITY_RE = re.compile(
    r"\bvalid(?:ity)?\b|\bsampled\b|\bqualified\b|\bqualifies\b|"
    r"\bcaptured\b|\blatched\b|\bstrobed\b|(?<![低高位])有效|取樣|採樣|鎖存",
    re.IGNORECASE)
_ID_CH = r"A-Za-z0-9_$"
#: `<q> = 1`, `<q>==1'b1`, `<q> 為 0`, `<q> is 1`
_QUAL_BIT_TMPL = (r"(?<![{c}]){q}`?\s*(?:==?|為|是|is)\s*(?:1'b)?([01])(?![{c}'])")
#: `<q> high|asserted|拉高` / `<q> low|deasserted|拉低`
_QUAL_WORD_TMPL = (r"(?<![{c}]){q}`?\s*(?:is\s+|為)?\s*"
                   r"(asserted|deasserted|high|low|拉高|拉低|高|低)")
_QUAL_WORD_LEVEL = {"asserted": "1", "high": "1", "拉高": "1", "高": "1",
                    "deasserted": "0", "low": "0", "拉低": "0", "低": "0"}
#: What ends one statement in the L9 prose (sentences, table cells, lines).
_QUAL_SPLIT_RE = re.compile(r"[。;；|\n]|\.\s")


def _names(text: str, name: str) -> bool:
    return bool(re.search(rf"(?<![{_ID_CH}]){re.escape(name)}(?![{_ID_CH}])",
                          text))


def _qualifier_level(sentence: str, q: str) -> Optional[str]:
    """The ACTIVE level the sentence binds to `q`, or None."""
    qe = re.escape(q)
    m = re.search(_QUAL_BIT_TMPL.format(c=_ID_CH, q=qe), sentence)
    if m:
        return m.group(1)
    m = re.search(_QUAL_WORD_TMPL.format(c=_ID_CH, q=qe), sentence,
                  re.IGNORECASE)
    if m:
        return _QUAL_WORD_LEVEL[m.group(1).lower()]
    return None


def qualifiers_from_statements(
        statements: List[Tuple[Optional[str], str]],
        outputs: List[Tuple[str, str]],
        inputs: List[Tuple[str, str]],
        excluded: "Tuple[str, ...]" = (),
        data_outputs: "Optional[List[str]]" = None,
) -> Dict[str, List[Dict[str, str]]]:
    """{output: [{qualifier, active, evidence}]} from the design's own text.

    NOT CONSULTED BY THIS ORACLE (R-0929-X-QUALIFIED-4): `declared_output_
    qualifiers` reads only the D1-signed structured `qualified_by` field
    (`_qualified_by`). This text reader is kept as a pure function for
    callers that PROPOSE a field for review; its answer is never trusted
    as a declaration by itself.

    `statements` are (subject, text): a port-table row's description has its
    port as the implicit subject; a prose sentence has none and must name the
    qualified output itself. A qualifier is declared only when ONE statement
    names the output, names another 1-bit port, binds an active level to that
    port and carries a condition word -- and is not denied (`_prose_polarity`).
    Nothing is inferred from a port's NAME: an output the text never qualifies
    has no qualifier, and X on it after reset release is a FAIL.

    FULLSTACKTB final review (a false PASS): the clause must state VALIDITY
    (`_QUAL_VALIDITY_RE`), the qualified output must be a DATA output
    (`data_outputs`; by default, and always from `declared_output_qualifiers`,
    the multi-bit outputs), and the ports the testbench drives as CLOCK and RESET
    (`excluded`) are never a qualifier -- a reset-value sentence ("o_q cleared
    to 0 when rst_n is low") is the very invariant the X check tests, and read
    as a qualifier it exempted an UNRESET output after release.
    """
    import _prose_polarity as _pp
    one_bit = [n for n, w in (outputs + inputs)
               if not w and n not in excluded]
    out_names = [n for n, w in outputs if n not in excluded]
    if data_outputs is None:
        data_outputs = [n for n, w in outputs if w]
    found: Dict[str, List[Dict[str, str]]] = {}
    for subject, text in statements:
        for sent in _QUAL_SPLIT_RE.split(text or ""):
            sent = (sent or "").strip()
            if not sent or not _QUAL_COND_RE.search(sent) \
                    or not _QUAL_VALIDITY_RE.search(sent) \
                    or _pp.is_denied(sent):
                continue
            targets = [d for d in out_names if d in data_outputs
                       and (d == subject or _names(sent, d))]
            for d in targets:
                for q in one_bit:
                    if q == d or not _names(sent, q):
                        continue
                    level = _qualifier_level(sent, q)
                    if level is None:
                        continue
                    rows = found.setdefault(d, [])
                    if not any(r["qualifier"] == q for r in rows):
                        rows.append({"qualifier": q, "active": level,
                                     "evidence": sent[:200]})
    return found


def declared_output_qualifiers(
        project: Path, outputs: List[Tuple[str, str]],
        inputs: List[Tuple[str, str]],
) -> Dict[str, List[Dict[str, str]]]:
    """The qualifiers this oracle may honour: ONLY the D1-signed structured
    `qualified_by` field of the L9 port table (R-0929-X-QUALIFIED-4, via
    `_qualified_by.trusted_qualifiers`). This oracle never reads a port
    description: two versions that did produced false PASSes. The landed strict
    rules still bind: clock and reset never qualify, only a multi-bit output is
    qualified, and an unsigned or malformed field is ignored."""
    return declared_output_qualifiers_and_refusals(project, outputs,
                                                   inputs)[0]


def declared_output_qualifiers_and_refusals(
        project: Path, outputs: List[Tuple[str, str]],
        inputs: List[Tuple[str, str]],
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, str]]:
    """`declared_output_qualifiers`, plus {output: why its field was ignored}
    so the testbench's FAIL text can say it."""
    import _qualified_by as _qb
    excluded = tuple(n for n in (_pick_clock(inputs), _pick_reset(inputs)[0])
                     if n)
    return _qb.trusted_qualifiers(project, outputs, inputs, excluded=excluded)


def _text(case: dict) -> str:
    return f"{case.get('stimulus', '')} {case.get('expected', '')}"


def is_reset_hold_case(case: dict) -> bool:
    """True iff the case's OWN text says stored content survives reset assert."""
    t = _text(case)
    return bool(_RE_RESET_ASSERT.search(t) and _RE_PRESERVED.search(t)
                and _RE_STORAGE.search(t))


def is_reset_glitch_case(case: dict) -> bool:
    """True iff the case's OWN text says a reset glitch must not race."""
    t = _text(case)
    return bool(_RE_GLITCH.search(t) and _RE_RACE.search(t)
                and _RE_MUST_NOT.search(t))


def case_family(case: dict) -> Optional[str]:
    """Which invariant this case states, or None. A case that reads as BOTH is
    refused rather than guessed — an ambiguous grounding is not a grounding."""
    hold = is_reset_hold_case(case)
    glitch = is_reset_glitch_case(case)
    if hold and glitch:
        return None
    if hold:
        return FAMILY_HOLD
    if glitch:
        return FAMILY_GLITCH
    return None


def _pick(outputs: List[Tuple[str, str]], regexes) -> Optional[str]:
    for n, _w in outputs:
        if any(p.search(n) for p in regexes):
            return n
    return None


def _pick_clock(inputs: List[Tuple[str, str]]) -> Optional[str]:
    for n, w in inputs:
        if not w and _CLOCK_RE.search(n):
            return n
    return None


def _pick_reset(inputs: List[Tuple[str, str]]) -> Tuple[Optional[str], bool]:
    for n, w in inputs:
        if not w and _RESET_RE.search(n):
            return n, bool(_ACTIVE_LOW_RE.search(n))
    return None, False


def _vstr(text: str) -> str:
    """`text` safe inside a Verilog string literal passed to $display."""
    return (str(text).replace("\\", "/").replace('"', "'")
            .replace("%", " pct").replace("\n", " "))[:400]


RETENTION_PROTOCOL = "registered_dual_port_8bit_async_read_sync_write"
RETENTION_HEADER = "// VIBEIC_RESET_RETENTION: "
RETENTION_EDGES = 6
RETENTION_ACTIVE_CYCLES = 64


def _declared_retention_preload(decl: dict, depth: int) -> Tuple[Optional[list], Optional[str]]:
    """Optional verification free choice, separate from the hardware protocol.

    verification_stimuli.reset_retention.memory_preload is a non-empty list
    of {address, byte}: unique in-range addresses and integer bytes, no bools.
    Absent fields keep the stock seed. An explicit malformed choice must not
    silently fall back to that seed or credit an actual-byte retention case.
    """
    selected = decl
    for key in ("verification_stimuli", "reset_retention"):
        if key not in selected:
            return None, None
        selected = selected[key]
        if not isinstance(selected, dict):
            return None, f"NOT_MEASURED: retention stimulus {key} must be an object"
    if "memory_preload" not in selected:
        return None, None
    entries = selected["memory_preload"]
    if not isinstance(entries, list) or not entries:
        return None, "NOT_MEASURED: retention memory_preload must be a non-empty list"
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"address", "byte"}:
            return None, "NOT_MEASURED: retention memory_preload entries need exactly address and byte"
        address, byte = entry["address"], entry["byte"]
        if (type(address) is not int or not 0 <= address < depth
                or type(byte) is not int or not 0 <= byte <= 255):
            return None, "NOT_MEASURED: retention memory_preload needs in-range integer addresses and bytes"
        if address in seen:
            return None, "NOT_MEASURED: retention memory_preload addresses must be unique"
        seen.add(address)
    return sorted(entries, key=lambda entry: entry["address"]), None


def declared_retention_memory(project: Path, dut: str,
                              inputs: List[Tuple[str, str]],
                              outputs: List[Tuple[str, str]]) -> Tuple[Optional[dict], str]:
    """Bind the selected SRAM protocol and explicit role map; never infer timing."""
    path = Path(project) / "plugin_output/declaration.json"
    try:
        raw = path.read_bytes()
        decl = json.loads(raw)
    except (OSError, ValueError):
        return None, "NOT_MEASURED: no readable selected memory declaration"
    if isinstance(decl, dict) and isinstance(decl.get("fields"), dict):
        decl = decl["fields"]
    from isa_suite_producer import parse_sram_protocol
    protocol, _ = parse_sram_protocol(decl.get("sram_interface_protocol")) if isinstance(decl, dict) else (None, "")
    if (protocol is None or protocol["width"] != 8 or protocol["read_latency"] != 0
            or {"we" if role == "wen" else role for role in protocol["stated_roles"]}
            != {"raddr", "rdata", "waddr", "wdata", "we"}):
        return None, "NOT_MEASURED: unsupported or unstated external memory commit protocol"
    roles = decl.get("sram_interface")
    if (not isinstance(roles, dict) or type(roles.get("read_latency_cycles", 0)) is not int
            or roles.get("read_latency_cycles", 0) != 0 or "read_enable" in roles):
        return None, "NOT_MEASURED: selected protocol needs explicit SRAM roles and asynchronous read"
    memory = {role: roles.get(key) for role, key in (
        ("raddr", "read_address"), ("waddr", "write_address"),
        ("wdata", "write_data"), ("rdata", "read_data"), ("we", "write_enable"))}
    ins, outs = dict(inputs), dict(outputs)
    if (any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", n)
            for n in memory.values()) or len(set(memory.values())) != 5
            or memory["rdata"] not in ins
            or any(memory[k] not in outs for k in ("raddr", "waddr", "wdata", "we"))):
        return None, "NOT_MEASURED: selected memory roles do not bind to the actual DUT ports"
    def bits(width):
        if not width:
            return 1
        m = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", str(width))
        return abs(int(m[1]) - int(m[2])) + 1 if m else None
    abits = bits(outs[memory["waddr"]])
    if (abits is None or not 1 <= abits <= 16
            or bits(outs[memory["raddr"]]) != abits
            or bits(outs[memory["wdata"]]) != 8 or bits(ins[memory["rdata"]]) != 8
            or bits(outs[memory["we"]]) != 1):
        return None, "NOT_MEASURED: unsupported or unknown byte-memory port widths"
    memory.update(protocol=decl["sram_interface_protocol"], depth=1 << abits, dut=dut,
                  declaration_sha256=hashlib.sha256(raw).hexdigest())
    preload, refusal = _declared_retention_preload(decl, memory["depth"])
    if refusal:
        return None, refusal
    if preload is not None:
        memory["memory_preload"] = preload
    return memory, "selected declaration; previous registered transaction commits on every rising edge"


def _emit_retention_oracle(case: dict, dut: str, inputs, outputs, inouts,
                           memory: dict) -> str:
    """Actual byte model, idle reset and active/pending reset, including edge zero."""
    name = case["name"]
    clk = _pick_clock(inputs)
    rst, low = _pick_reset(inputs)
    asserted, released = ("0", "1") if low else ("1", "0")
    depth = memory["depth"]
    raddr, waddr, data, rdata, we = (memory[k] for k in
                                   ("raddr", "waddr", "wdata", "rdata", "we"))
    lines = [f"// Auto-generated RESET-INVARIANT oracle TB for case={name}",
             f"// family={FAMILY_HOLD} — actual byte retention, no first-edge exception",
             RETENTION_HEADER + json.dumps(memory, sort_keys=True),
             "`timescale 1ns/1ps", f"module {name};"]
    for n, w in inputs:
        lines.append(f"  reg {w + ' ' if w else ''}{n} = 0;")
    for n, w in outputs + inouts:
        lines.append(f"  wire {w + ' ' if w else ''}{n};")
    conns = ", ".join(f".{n}({n})" for n, _ in inputs + outputs + inouts)
    lines += [f"  {dut} u_dut ({conns});", f"  always #5 {clk} = ~{clk};",
              f"  reg [7:0] retention_mem [0:{depth - 1}];",
              f"  reg [7:0] retention_before [0:{depth - 1}];",
              "  integer errors = 0; integer _i; integer edge_number; integer active_cycles;",
              "  reg pending_found;",
              f"  always @(*) {rdata} = retention_mem[{raddr}];",
              "  // Consume the previous registered transaction on EVERY rising edge.",
              "  // Never gate the external memory commit on reset or discard a launched write.",
              f"  always @(posedge {clk}) if ({we} === 1'b1)",
              f"    retention_mem[{waddr}] <= {data};",
              "  task observe_reset(input integer arm);",
              "    begin",
              f"      for (_i = 0; _i < {depth}; _i = _i + 1)",
              "        retention_before[_i] = retention_mem[_i];",
              '      $write("RESET_RETENTION BASELINE arm=%0d bytes=", arm);',
              f'      for (_i = 0; _i < {depth}; _i = _i + 1) $write("%02x", retention_mem[_i]);',
              '      $display("");',
              f"      {rst} = 1'b{asserted};",
              f"      for (edge_number = 0; edge_number < {RETENTION_EDGES}; edge_number = edge_number + 1) begin",
              f"        @(posedge {clk}); @(negedge {clk});",
              '        $write("RESET_RETENTION SAMPLE arm=%0d edge=%0d bytes=", arm, edge_number);',
              f'        for (_i = 0; _i < {depth}; _i = _i + 1) $write("%02x", retention_mem[_i]);',
              f'        $display(" post_edge_we=%b", {we});',
              f"        for (_i = 0; _i < {depth}; _i = _i + 1) begin",
              "          if (retention_mem[_i] !== retention_before[_i]) begin",
              "            errors = errors + 1;",
              f'            $display("[TB {name}] FAIL: retention arm=%0d edge=%0d byte=%0d before=%02x after=%02x", arm, edge_number, _i, retention_before[_i], retention_mem[_i]);',
              "          end",
              "        end",
              "      end",
              "    end",
              "  endtask",
              "  initial begin",
              f"    for (_i = 0; _i < {depth}; _i = _i + 1) retention_mem[_i] = 8'ha5 + _i * 17;"]
    for entry in memory.get("memory_preload", []):
        lines.append(f"    retention_mem[{entry['address']}] = 8'h{entry['byte']:02x};")
    lines += [f"    {rst} = 1'b{asserted};",
              f"    repeat (4) @(negedge {clk});",
              "    observe_reset(0);",
              f"    {rst} = 1'b{released}; pending_found = 0;",
              f"    for (active_cycles = 0; active_cycles < {RETENTION_ACTIVE_CYCLES} && !pending_found; active_cycles = active_cycles + 1) begin",
              f"      @(negedge {clk});",
              f"      if ({we} === 1'b1 && ^({waddr}) !== 1'bx && ^({data}) !== 1'bx",
              f"          && retention_mem[{waddr}] !== {data}) pending_found = 1;",
              "    end",
              "    if (!pending_found) begin",
              f'      $display("[TB {name}] NOT_MEASURED: no actual non-idempotent pending write within {RETENTION_ACTIVE_CYCLES} cycles");',
              "      $finish;",
              "    end else begin",
              f'      $display("RESET_RETENTION PENDING address=%0d before=%02x data=%02x", {waddr}, retention_mem[{waddr}], {data});',
              "      observe_reset(1);",
              f'      if (errors != 0) begin $display("[TB {name}] FAIL — %0d byte checks failed", errors); $fatal(1); end',
              f'      $display("[TB {name}] PASS — actual byte retention including first sampled edge");',
              "      $finish;", "    end", "  end", "endmodule"]
    return "\n".join(lines) + "\n"


def retention_measurement(transcript: str, memory: dict) -> dict:
    """Decode actual bytes; missing pending transition/edge zero is not retention."""
    depth = memory["depth"]
    baselines, samples = {}, {}
    for arm, data in re.findall(r"(?m)^RESET_RETENTION BASELINE arm=([01]) bytes=([0-9a-fA-F]+)$", transcript):
        baselines[arm] = data.lower()
    for arm, edge, data in re.findall(r"(?m)^RESET_RETENTION SAMPLE arm=([01]) edge=(\d+) bytes=([0-9a-fA-F]+) post_edge_we=[01]$", transcript):
        samples.setdefault(arm, {})[int(edge)] = data.lower()
    p = re.search(r"(?m)^RESET_RETENTION PENDING address=(\d+) before=([0-9a-fA-F]{2}) data=([0-9a-fA-F]{2})$", transcript)
    pending = {"address": int(p[1]), "before": p[2].lower(), "data": p[3].lower()} if p else None
    complete = (set(baselines) == {"0", "1"} and pending is not None
                and 0 <= pending["address"] < depth and pending["before"] != pending["data"]
                and baselines["1"][2 * pending["address"]:2 * pending["address"] + 2] == pending["before"]
                and all(len(baselines[a]) == 2 * depth and set(samples.get(a, {})) == set(range(RETENTION_EDGES))
                        and all(len(s) == 2 * depth for s in samples[a].values()) for a in ("0", "1")))
    changed = complete and any(s != baselines[a] for a in ("0", "1") for s in samples[a].values())
    return {"complete": bool(complete), "changed": bool(changed), "baselines": baselines,
            "samples": {a: {str(k): v for k, v in rows.items()} for a, rows in samples.items()},
            "pending": pending}


def _retention_memory_identity(project: Path, tb: Path) -> Tuple[Optional[dict], str]:
    import testbench_gen as _tbg
    try:
        line = next(s for s in tb.read_text().splitlines() if s.startswith(RETENTION_HEADER))
        bound = json.loads(line[len(RETENTION_HEADER):])
        dut, ports, _ = _tbg.resolve_dut(project, bound["dut"])
        ins, outs, _ = _tbg._classify(ports)
        current, why = declared_retention_memory(project, dut, ins, outs)
        if current is None or current != bound:
            return None, "NOT_MEASURED: executed memory binding is absent, unsupported or changed"
        return current, why
    except (OSError, ValueError, StopIteration, KeyError, TypeError):
        return None, "NOT_MEASURED: testbench has no declared actual-byte memory binding"


def capture_retention_execution(project: Path, tb: Path, transcript: Path,
                                sources: dict) -> Tuple[Optional[dict], str]:
    """Attach native values to the existing execution row, not a second receipt."""
    memory, why = _retention_memory_identity(project, tb)
    if memory is None:
        return None, why
    try:
        raw = transcript.read_bytes()
    except OSError:
        return None, "NOT_MEASURED: native retention transcript is missing"
    measured = retention_measurement(raw.decode(errors="replace"), memory)
    evidence = {"memory": memory, "sources": sources, "transcript": str(transcript),
                "transcript_sha256": hashlib.sha256(raw).hexdigest(), "measurement": measured}
    return evidence, ("actual byte retention including idle and pending first sampled edges"
                      if measured["complete"] else
                      "NOT_MEASURED: current native bytes, pending transition or reset edge zero are incomplete")


def retention_case_state(project: Optional[Path], case_id: str, record: dict) -> Tuple[str, str]:
    """L10 may credit full retention only from current executed actual bytes."""
    import _l10_execution as _l10x
    state, why = _l10x.case_state(case_id, record)
    if state != _l10x.PASS:
        return state, why  # Preserve a measured failure; never downgrade it.
    identity, why = _l10x.scenario_tb_identity(case_id, record)
    if not identity or project is None:
        return _l10x.NOT_EXECUTED, "NOT_MEASURED: current retention testbench identity is missing: " + why
    row = record["rows"][case_id]
    evidence = row.get("reset_retention")
    if not isinstance(evidence, dict):
        return _l10x.NOT_EXECUTED, "NOT_MEASURED: no current actual-byte retention execution evidence"
    try:
        memory, why = _retention_memory_identity(Path(project), Path(row["tb_file"]))
        sources = evidence.get("sources")
        if (memory is None or memory != evidence.get("memory") or not isinstance(sources, dict)
                or not sources or any(_l10x.file_sha256(Path(p)) != digest for p, digest in sources.items())):
            return _l10x.NOT_EXECUTED, "NOT_MEASURED: retention protocol, source bytes or selected declaration changed"
        raw = Path(evidence["transcript"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != evidence.get("transcript_sha256"):
            return _l10x.NOT_EXECUTED, "NOT_MEASURED: current native retention transcript changed"
        measured = retention_measurement(raw.decode(errors="replace"), memory)
        if not measured["complete"] or measured != evidence.get("measurement"):
            return _l10x.NOT_EXECUTED, "NOT_MEASURED: complete current byte snapshots and first sampled edge are missing"
        if measured["changed"]:
            return _l10x.FAIL, "actual memory bytes changed during reset, including its first sampled edge"
        return _l10x.PASS, "current native actual bytes retained across idle and pending reset, including edge zero"
    except (OSError, KeyError, TypeError, ValueError):
        return _l10x.NOT_EXECUTED, "NOT_MEASURED: native retention values or current source binding are unreadable"


def emit_case_oracle_from_ports(
    case: dict,
    dut: str,
    inputs: List[Tuple[str, str]],
    outputs: List[Tuple[str, str]],
    inouts: List[Tuple[str, str]],
    qualifiers: Optional[Dict[str, List[Dict[str, str]]]] = None,
    refusals: Optional[Dict[str, str]] = None,
    memory: Optional[dict] = None,
) -> Optional[str]:
    """Core, project-I/O-free emitter. Returns TB text, or None (fail-closed).

    `qualifiers` is `declared_output_qualifiers`' answer. After the glitch is
    released every output is sampled on every one of `POST_RELEASE_CYCLES`
    cycles from the first edge (R-0929-X-QUALIFIED): an output with no declared
    qualifier must be a known 0/1 on each; one with declared qualifiers may be
    X/Z only on a cycle where EVERY qualifier is known and at its inactive
    level, and each such cycle is printed as an `X_EXEMPT` line."""
    qualifiers = qualifiers or {}
    refusals = refusals or {}
    name = case.get("name", "")
    family = case_family(case)
    if family is None:
        return None
    clk = _pick_clock(inputs)
    rst, rst_low = _pick_reset(inputs)
    if clk is None or rst is None:
        # No clock to sample on, or no reset to assert: this DUT surface does
        # not let the invariant be observed at all.
        return None
    if family == FAMILY_HOLD and memory is not None:
        return _emit_retention_oracle(case, dut, inputs, outputs, inouts, memory)
    observed = (_pick(outputs, _WRITE_RES) if family == FAMILY_HOLD
                else (_pick(outputs, _BUS_ACTIVITY_RES)
                      or _pick(outputs, _READ_ENABLE_RES)))
    if observed is None:
        return None

    asserted, released = ("0", "1") if rst_low else ("1", "0")
    L: List[str] = []
    L.append(f"// Auto-generated RESET-INVARIANT oracle TB for case={name}")
    L.append(f"// family={family} (reset_invariant_oracle_tb_gen)")
    L.append(f"// stimulus: {case.get('stimulus', '')}")
    L.append(f"// expected: {case.get('expected', '')}")
    L.append("//")
    if family == FAMILY_HOLD:
        L.append("// REAL ORACLE: the design's own declared text says stored")
        L.append("// content survives reset assert. The only pin-visible way")
        L.append(f"// content can change is a WRITE, so this TB holds '{rst}'")
        L.append(f"// asserted and FAILs if '{observed}' ever asserts inside")
        L.append("// that window. Necessary condition, stated at the pins; no")
        L.append("// memory model and no instruction semantics are invented.")
    else:
        L.append("// REAL ORACLE: the design's own declared text says a reset")
        L.append("// GLITCH must not cause a bus/fetch race. This TB runs the")
        L.append(f"// design, applies a ONE-CYCLE pulse on '{rst}', and FAILs if")
        L.append(f"// '{observed}' is asserted anywhere inside the pulse, or if")
        L.append("// any observable output is X/Z on any cycle after release")
        L.append("// (R-0929-X-QUALIFIED: X is allowed only on an output whose")
        L.append("// declared qualifier is known and inactive). It does NOT")
        L.append("// claim the converse: a race-free pulse is not a proof that")
        L.append("// the fetch which follows is correct.")
        for d, rows in sorted(qualifiers.items()):
            for r in rows:
                L.append(f"// qualifier (design input): '{d}' qualified by "
                         f"'{r['qualifier']}' active={r['active']} -- "
                         + r["evidence"].replace("\n", " ")[:120])
    L.append("`timescale 1ns/1ps")
    L.append(f"module {name};")
    for n, w in inputs:
        L.append(f"  reg {w + ' ' if w else ''}{n} = 0;")
    for n, w in outputs:
        L.append(f"  wire {w + ' ' if w else ''}{n};")
    for n, w in inouts:
        L.append(f"  wire {w + ' ' if w else ''}{n};")
    L.append("  integer errors = 0;")
    L.append("  integer _i;")
    L.append("")
    conns = ", ".join(f".{n}({n})" for n, _w in (inputs + outputs + inouts))
    L.append(f"  {dut} u_dut ({conns});")
    L.append("")
    L.append(f"  always #5 {clk} = ~{clk};")
    L.append("")
    L.append("  initial begin")
    if family == FAMILY_HOLD:
        L.append(f'    $display("[TB {name}] BEGIN — no write on \'{observed}\' '
                 f'while \'{rst}\' is asserted");')
        L.append(f"    {rst} = 1'b{asserted};")
        L.append("    for (_i = 0; _i < 32; _i = _i + 1) begin")
        # SAMPLE MID-CYCLE, NEVER ON THE EDGE. A registered output is
        # updated by a non-blocking assignment at the posedge, so a
        # check written at that same edge reads the PREVIOUS value and
        # a violation one cycle wide is invisible. MEASURED: the first
        # draft of the glitch oracle sampled on the edge and PASSED a
        # mutant that asserts the observed output throughout reset.
        L.append(f"      @(posedge {clk}); @(negedge {clk});")
        L.append(f"      if (({observed}) === 1'b1) begin")
        L.append("        errors = errors + 1;")
        L.append(f'        $display("[TB {name}] FAIL: \'{observed}\' asserted '
                 f'at reset-assert cycle %0d — stored content is not held", _i);')
        L.append("      end")
        L.append("    end")
        L.append(f"    {rst} = 1'b{released};")
    else:
        L.append(f'    $display("[TB {name}] BEGIN — no activity on '
                 f'\'{observed}\' inside a one-cycle \'{rst}\' glitch");')
        L.append(f"    {rst} = 1'b{asserted};")
        L.append("    repeat (4) @(posedge " + clk + ");")
        L.append(f"    {rst} = 1'b{released};")
        L.append("    repeat (8) @(posedge " + clk + ");")
        L.append("    // THE GLITCH. The pulse is held across ONE clock edge")
        L.append("    // and sampled mid-cycle while still asserted. That window")
        L.append("    // is not an arbitrary choice: on a synchronous design the")
        L.append("    // earliest the DUT can answer the pulse is the edge that")
        L.append("    // ends it, so a window that closes ON that edge can see")
        L.append("    // nothing, and one that stays open past the release flags")
        L.append("    // ordinary resumption as a race. MEASURED, both drafts:")
        L.append("    // the edge-sampled window PASSED a mutant that drives the")
        L.append("    // observed output throughout reset, and the widened one")
        L.append("    // FAILED the shipped design for restarting after release.")
        L.append(f"    {rst} = 1'b{asserted};")
        L.append(f"    @(posedge {clk});")
        L.append(f"    @(negedge {clk});")
        L.append(f"    if (({observed}) === 1'b1) begin")
        L.append("      errors = errors + 1;")
        L.append(f'      $display("[TB {name}] FAIL: \'{observed}\' asserted '
                 f'inside the reset glitch — a transaction races the reset");')
        L.append("    end")
        L.append(f"    {rst} = 1'b{released};")
        # R-0929-X-QUALIFIED — from the FIRST edge after release, every cycle.
        L.append(f"    for (_i = 0; _i < {POST_RELEASE_CYCLES}; _i = _i + 1) "
                 "begin")
        L.append(f"      @(posedge {clk}); @(negedge {clk});")
        for n, _w in outputs:
            rows = [r for r in qualifiers.get(n) or []
                    if r.get("active") in ("0", "1")]
            L.append(f"      if (^({n}) === 1'bx) begin")
            if rows:
                inactive = " && ".join(
                    f"({r['qualifier']} === 1'b{1 - int(r['active'])})"
                    for r in rows)
                shown = ", ".join(f"{r['qualifier']}=%b" for r in rows)
                args = ", ".join(r["qualifier"] for r in rows)
                L.append(f"        if ({inactive}) begin")
                field = _vstr("; ".join(r.get("field") or r.get("evidence", "")
                                        for r in rows))
                L.append(f'          $display("[TB {name}] X_EXEMPT: cycle %0d '
                         f'after release: output \'{n}\' is X/Z while its '
                         f'declared qualifier(s) are inactive and known: '
                         f'{shown} -- basis: {field}", _i, {args});')
                # EVERY basis entry, one line each: a fixed-length cut once
                # dropped the third and fourth quotations (review wave58).
                for r in rows:
                    for cite in r.get("cites") or []:
                        L.append(f'          $display("[TB {name}]   basis '
                                 f'{_vstr(cite)}");')
                L.append("        end")
                L.append("        else begin")
                L.append("          errors = errors + 1;")
                L.append(f'          $display("[TB {name}] FAIL: output '
                         f'\'{n}\' is X/Z at cycle %0d after the glitch was '
                         f'released while a declared qualifier is asserted or '
                         f'unknown: {shown}", _i, {args});')
                L.append("        end")
            else:
                L.append("        errors = errors + 1;")
                why = (f"qualified_by ignored: {_vstr(refusals[n])}"
                       if n in refusals else
                       "no qualifier declared for it in the design input")
                L.append(f'        $display("[TB {name}] FAIL: output \'{n}\' '
                         f'is X/Z at cycle %0d after the glitch was released '
                         f'({why})", _i);')
            L.append("      end")
        L.append("    end")
    L.append("    if (errors != 0) begin")
    L.append(f'      $display("[TB {name}] FAIL — %0d check(s) failed", errors);')
    L.append("      $fatal(1);")
    L.append("    end")
    if family == FAMILY_HOLD:
        L.append(f'    $display("[TB {name}] NOT_MEASURED — write strobe necessary condition only; no actual byte retention measurement");')
    else:
        L.append(f'    $display("[TB {name}] PASS — {family} holds");')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def _load_case(project: Path, case_name: str) -> Optional[dict]:
    f = Path(project) / "phase1" / "generated_docs" / "L10_TEST_CASES.json"
    try:
        doc = json.loads(f.read_text(errors="replace"))
    except Exception:
        return None
    for row in (doc.get("test_cases") or doc.get("cases") or []):
        if row.get("name") == case_name:
            return row
    return None


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--case", required=True)
    ap.add_argument("--top", default="chip_top")
    a = ap.parse_args(argv)
    case = _load_case(Path(a.project), a.case)
    if case is None:
        print(f"no declared L10 case named {a.case!r}", file=sys.stderr)
        return 2
    fam = case_family(case)
    print(f"case={a.case} family={fam or 'NOT_A_RESET_INVARIANT_CASE'}")
    return 0 if fam else 1


if __name__ == "__main__":
    raise SystemExit(main())
