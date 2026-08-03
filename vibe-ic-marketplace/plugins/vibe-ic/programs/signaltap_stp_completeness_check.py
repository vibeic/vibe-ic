#!/usr/bin/env python3
"""
signaltap_stp_completeness_check.py — Validate that a generated Quartus
SignalTap II `.stp` configuration actually captures everything the
skills/fpga-signaltap/SKILL.md "Generated .stp Captures" policy requires.

The `.stp` GENERATION itself is performed by the MCP tool
`eda_rtl_signaltap_autogen` (it scans RTL and emits the SignalTap XML). This
program is the deterministic VALIDATION of that output — it catches the real
silicon-debug defect where the .stp is re-compiled into a SOF but is *missing
a signal you needed*, so the post-failure capture is useless and you have to
re-fit (a ~30-minute Quartus round-trip) all over again.

It encodes the two deterministic rules the SKILL.md states as policy (not
judgment):

  RULE-2  capture-signal policy: the .stp MUST contain
            - EVERY DUT input port      (stimulus being applied)
            - EVERY DUT output port     (actual responses)
            - the four BIST-engine signals: bist_state, test_index,
              pass_count, fail_count
          The DUT port list comes from the RTL (--sv parses the module's
          port list) or from an explicit --ports "name:dir:width,..." string.
          A port present in the RTL but absent from the .stp signal_set is a
          MISSING_PORT finding. A required BIST signal absent is a
          MISSING_BIST_SIGNAL finding.

  RULE-3  trigger / depth / clock policy: the .stp MUST define
            - a trigger (a <trigger>/<trigger_set>/<basic_trigger> element, or
              a trigger_input naming a signal)
            - a sample_depth / buffer depth that is a positive integer
            - a capture clock (a <clock name=...> or clock= attribute)
          A missing trigger / non-positive depth / missing clock are
          NO_TRIGGER / BAD_DEPTH / NO_CLOCK findings respectively.

chip-AGNOSTIC: no chip / register / protocol names are baked in. The only
fixed tokens are the four BIST-engine signal *roles* that SKILL.md names
verbatim (bist_state / test_index / pass_count / fail_count); these are the
standard fpga-test-harness BIST engine outputs, not a per-chip name.

HONESTY:
  - No .stp input -> SKIP (exit 2) — the disclosed-skip tier, never a pass.
    A .stp that WAS given but contains NO signal_set at all is FAIL (exit 1):
    that is a real, broken artifact, not an absent one.
  - No port source (neither --sv nor --ports) -> the port-coverage half is
    SKIPPED honestly (RULE-3 trigger/depth/clock is still enforced). We never
    vacuously PASS the port policy without knowing the ports.

CORRECTIONS (2026-08-03, vibe-ic#693 fpga-signaltap family)
===========================================================
  (1) NO_TRIGGER was a FALSE NEGATIVE on the one artefact this gate was aimed
      at. `_STP_TRIGGER_RE` was a TAG-PRESENCE match, so an EMPTY self-closing
      `<trigger_set is_expanded="true" name="trigger: trigger_set_1"/>` —
      exactly what `eda_rtl_signaltap_autogen` emits — satisfied "the .stp
      defines a trigger". A trigger element that triggers on nothing is the
      free-running capture this rule exists to reject. `_has_trigger` now
      requires a trigger element with actual content: a `<basic_trigger>` /
      `<trigger_input>` / `<trigger_node>`, or a `<trigger_set>` that is not
      empty.

  (2) The no-input SKIP exited 0, which `flow_compliance_check` credits as a
      plain PASS. It now exits 2 (VACUOUS_PASS tier) and prints a `[SKIP]`-
      prefixed line so `gate_skip_routing_check._skip_token`, which matches its
      vocabulary at LINE START, can see the declaration at all.

WHERE THIS GATE IS DRIVEN
=========================
NOWHERE automatically, and that is deliberate: no flow step produces a `.stp`.
It is registered in `flow/phase1_phase2_phase3.yaml` step 39 (`programs:`) with
the reason written down; see that entry.

MEASURED STATE OF THE TWO IN-REPO PRODUCERS (2026-08-03)
========================================================
  tools/signaltap_gen.py            -> PASSes this gate (ports + BIST group +
                                       populated trigger + depth + clock).
  eda_rtl_signaltap_autogen (MCP)   -> FAILs it on its DEFAULT invocation, and
                                       that tool is the producer this module's
                                       header and skills/fpga-signaltap/SKILL.md
                                       both name. Driven at the published
                                       sha256 RTL dir it emitted ONE signal
                                       ("state"), no DUT ports, no BIST group
                                       and an empty trigger: 4 x
                                       MISSING_BIST_SIGNAL + 8 x MISSING_PORT
                                       + (after correction 1) NO_TRIGGER.
                                       Tracked separately — the producer's
                                       contract is a design question, and this
                                       gate must not be made a blocking
                                       post-condition of it until that is
                                       settled.

Usage:
    python3 signaltap_stp_completeness_check.py <file.stp> --sv <top.sv>
    python3 signaltap_stp_completeness_check.py <file.stp> \
        --ports "clk:I:1,rst_n:I:1,d:I:1,q:O:1"
    python3 signaltap_stp_completeness_check.py <file.stp> --sv top.sv \
        --json out.json

Exit codes:
    0 = PASS (all required signals present + trigger/depth/clock OK)
    1 = FAIL (one or more completeness findings)
    2 = SKIP — NOTHING EXAMINED (no .stp given). The disclosed-skip tier,
        never a pass. Also usage / io errors.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional


# ---------------------------------------------------------------------------
# The four BIST-engine signals SKILL.md names verbatim as a fixed include-set.
# ---------------------------------------------------------------------------
REQUIRED_BIST_SIGNALS = ("bist_state", "test_index", "pass_count", "fail_count")


# ---------------------------------------------------------------------------
# Comment handling for the RTL parse
# ---------------------------------------------------------------------------
_LINE_CMT = re.compile(r"//[^\n]*")
_BLOCK_CMT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(src: str) -> str:
    src = _BLOCK_CMT.sub("", src)
    src = _LINE_CMT.sub("", src)
    return src


# ---------------------------------------------------------------------------
# RTL port-list parse  (ANSI-style `module foo ( input ... , output ... );`)
# ---------------------------------------------------------------------------
_MODULE_HDR_RE = re.compile(
    r"\bmodule\b\s+(\w+)\s*(?:#\s*\([^)]*\))?\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire|reg|logic|signed|unsigned|\s)*"
    r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?"
    r"([A-Za-z_]\w*)",
    re.IGNORECASE,
)


@dataclass
class Port:
    name: str
    direction: str   # input | output | inout
    width: int


def parse_ports_from_sv(src: str, module_hint: Optional[str] = None
                        ) -> List[Port]:
    """Parse the (first matching) module's ANSI port list into Port records.

    Returns [] if no module/port list is found (honest: caller treats an empty
    list as 'ports unknown' rather than a vacuous PASS).
    """
    text = _strip_comments(src)
    chosen = None
    for m in _MODULE_HDR_RE.finditer(text):
        if module_hint and m.group(1).lower() != module_hint.lower():
            continue
        chosen = m
        break
    if chosen is None:
        return []
    body = chosen.group(2)
    ports: List[Port] = []
    seen: Set[str] = set()
    for pm in _PORT_DECL_RE.finditer(body):
        direction = pm.group(1).lower()
        if pm.group(2) is not None and pm.group(3) is not None:
            hi, lo = int(pm.group(2)), int(pm.group(3))
            width = abs(hi - lo) + 1
        else:
            width = 1
        name = pm.group(4)
        if name.lower() in ("input", "output", "inout", "wire", "reg",
                             "logic", "signed", "unsigned"):
            continue
        if name in seen:
            continue
        seen.add(name)
        ports.append(Port(name=name, direction=direction, width=width))
    return ports


def parse_ports_from_str(spec: str) -> List[Port]:
    """Parse a manual port spec "name:dir:width,name:dir:width,...".

    dir token: I/IN/INPUT -> input ; O/OUT/OUTPUT -> output ; B/IO/INOUT ->
    inout. width defaults to 1 when absent.
    """
    out: List[Port] = []
    seen: Set[str] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        name = parts[0].strip()
        if not name or name in seen:
            continue
        d = (parts[1].strip().lower() if len(parts) > 1 else "input")
        if d in ("i", "in", "input"):
            direction = "input"
        elif d in ("o", "out", "output"):
            direction = "output"
        elif d in ("b", "io", "inout"):
            direction = "inout"
        else:
            direction = "input"
        try:
            width = int(parts[2]) if len(parts) > 2 and parts[2].strip() else 1
        except ValueError:
            width = 1
        seen.add(name)
        out.append(Port(name=name, direction=direction, width=width))
    return out


# ---------------------------------------------------------------------------
# .stp parse  (vendor XML — we only need the captured signal names + trigger /
# depth / clock evidence; tolerant of either the SKILL.md hand-form or the MCP
# tool's `eda_rtl_signaltap_autogen` output form)
# ---------------------------------------------------------------------------
# A signal entry: <signal name="cd4013b_inst|clk" .../>  or
#                 <signal name="bist_state[2:0]" .../>
_STP_SIGNAL_RE = re.compile(r"<signal\b[^>]*\bname\s*=\s*\"([^\"]+)\"",
                            re.IGNORECASE)
_STP_SIGNAL_SET_RE = re.compile(r"<signal_set\b", re.IGNORECASE)
# trigger evidence.
#
# A trigger element that CONTAINS a trigger condition. `<basic_trigger>`,
# `<trigger_input>` and `<trigger_node>` name a signal by construction, so their
# presence is enough. `<trigger_set>` is a CONTAINER: an empty one triggers on
# nothing and the analyzer free-runs, which is precisely what NO_TRIGGER exists
# to reject — see correction (1) in the module header.
_STP_TRIGGER_ELEM_RE = re.compile(
    r"<\s*(?:basic_trigger|trigger_input|trigger_node)\b", re.IGNORECASE)
#: `<trigger_set ...>` / `<trigger ...>` with the tail needed to tell a
#: self-closing empty container from one with content.
_STP_TRIGGER_SET_RE = re.compile(
    r"<\s*(trigger_set|trigger)\b([^>]*)>", re.IGNORECASE)


def _has_trigger(stp_text: str) -> bool:
    """True only when the .stp defines a trigger that can actually fire."""
    if _STP_TRIGGER_ELEM_RE.search(stp_text):
        return True
    for m in _STP_TRIGGER_SET_RE.finditer(stp_text):
        attrs = m.group(2) or ""
        if attrs.rstrip().endswith("/"):
            continue                       # `<trigger_set .../>` — empty
        tag = m.group(1)
        close = re.compile(r"<\s*/\s*" + re.escape(tag) + r"\s*>",
                           re.IGNORECASE).search(stp_text, m.end())
        body = stp_text[m.end():close.start()] if close else \
            stp_text[m.end():]
        if body.strip():
            return True
    return False
# sample depth: sample_depth="1024" OR <buffer depth="1024" />
_STP_DEPTH_RE = re.compile(
    r"(?:sample_depth|depth)\s*=\s*\"?(\d+)\"?", re.IGNORECASE)
# clock: <clock name="CLOCK_50" .../> OR clock="CLOCK_50"
_STP_CLOCK_RE = re.compile(
    r"(?:<clock\b[^>]*\bname\s*=\s*\"([^\"]+)\"|(?<![\w_])clock\s*=\s*\"([^\"]+)\")",
    re.IGNORECASE,
)


def _stp_signal_basenames(stp_text: str) -> Set[str]:
    """Every captured signal, normalised to a comparable base name.

    Strips a hierarchical instance prefix `inst|sig` -> `sig` and a bit-range
    suffix `sig[2:0]` -> `sig`, lower-cased, so the port/BIST membership test
    is robust to how the generator qualified the name.
    """
    out: Set[str] = set()
    for m in _STP_SIGNAL_RE.finditer(stp_text):
        raw = m.group(1)
        base = raw.split("|")[-1]            # drop hierarchy prefix
        base = re.sub(r"\[.*?\]\s*$", "", base)  # drop [hi:lo] / [n]
        base = base.strip()
        if base:
            out.add(base.lower())
    return out


@dataclass
class StpFacts:
    has_signal_set: bool
    signal_names: List[str]
    has_trigger: bool
    sample_depth: Optional[int]
    clock: Optional[str]


def parse_stp(stp_text: str) -> StpFacts:
    has_set = bool(_STP_SIGNAL_SET_RE.search(stp_text))
    names = sorted(_stp_signal_basenames(stp_text))
    has_trig = _has_trigger(stp_text)
    depth = None
    dm = _STP_DEPTH_RE.search(stp_text)
    if dm:
        try:
            depth = int(dm.group(1))
        except ValueError:
            depth = None
    clock = None
    cm = _STP_CLOCK_RE.search(stp_text)
    if cm:
        clock = cm.group(1) or cm.group(2)
    return StpFacts(has_signal_set=has_set, signal_names=names,
                    has_trigger=has_trig, sample_depth=depth, clock=clock)


# ---------------------------------------------------------------------------
# Findings / result
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    detail: str
    fix_hint: str


@dataclass
class Result:
    status: str                                   # PASS | FAIL | SKIP
    stp_file: str = ""
    findings: List[Finding] = field(default_factory=list)
    ports_checked: bool = False
    dut_ports: List[str] = field(default_factory=list)
    captured_signals: List[str] = field(default_factory=list)
    trigger_present: bool = False
    sample_depth: Optional[int] = None
    clock: Optional[str] = None


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------
def validate(stp_text: str, stp_label: str, ports: Optional[List[Port]]
             ) -> Result:
    facts = parse_stp(stp_text)
    findings: List[Finding] = []

    # A .stp with no signal_set at all is a broken artifact -> real FAIL.
    if not facts.has_signal_set:
        findings.append(Finding(
            rule="NO_SIGNAL_SET",
            severity="ERROR",
            detail=(f"'{stp_label}' contains no <signal_set> — it captures "
                    f"nothing and cannot help debug a failure."),
            fix_hint=("Re-run eda_rtl_signaltap_autogen (or signaltap_gen) to "
                      "produce a .stp whose signal_set lists the DUT I/O."),
        ))

    captured = set(facts.signal_names)

    # ---- RULE-2: every BIST-engine signal present ------------------------
    for bist in REQUIRED_BIST_SIGNALS:
        if bist.lower() not in captured:
            findings.append(Finding(
                rule="MISSING_BIST_SIGNAL",
                severity="ERROR",
                detail=(f"Required BIST-engine signal '{bist}' is not in the "
                        f".stp signal_set — the capture cannot show which test "
                        f"index / pass-fail count was live at the failure."),
                fix_hint=(f"Add '{bist}' to the captured signal set "
                          f"(it is one of the four mandatory BIST signals "
                          f"{list(REQUIRED_BIST_SIGNALS)})."),
            ))

    # ---- RULE-2: every DUT input/output port present ---------------------
    ports_checked = ports is not None and len(ports) > 0
    if ports_checked:
        for p in ports:  # type: ignore[union-attr]
            # SignalTap captures observable I/O; inout counted as both, also
            # observable. The clock/reset are still I/O and must be captured.
            if p.name.lower() not in captured:
                findings.append(Finding(
                    rule="MISSING_PORT",
                    severity="ERROR",
                    detail=(f"DUT {p.direction} port '{p.name}' "
                            f"(width {p.width}) is driven on the board but is "
                            f"NOT in the .stp signal_set — its transitions "
                            f"around the failure are invisible."),
                    fix_hint=(f"Add DUT port '{p.name}' to the captured "
                              f"signal set; the policy is ALL inputs + ALL "
                              f"outputs."),
                ))

    # ---- RULE-3: trigger / depth / clock ---------------------------------
    if not facts.has_trigger:
        findings.append(Finding(
            rule="NO_TRIGGER",
            severity="ERROR",
            detail=("The .stp defines no trigger — the analyzer free-runs and "
                    "will not align the capture window on the failure event."),
            fix_hint=("Define a trigger (default per SKILL.md: rising edge of "
                      "bist_fail)."),
        ))
    if facts.sample_depth is None or facts.sample_depth <= 0:
        findings.append(Finding(
            rule="BAD_DEPTH",
            severity="ERROR",
            detail=(f"The .stp sample/buffer depth is "
                    f"{facts.sample_depth!r} — it must be a positive integer "
                    f"(default 1024) or the capture buffer holds nothing."),
            fix_hint=("Set sample_depth / buffer depth to a positive value "
                      "(SKILL.md default = 1024)."),
        ))
    if not facts.clock:
        findings.append(Finding(
            rule="NO_CLOCK",
            severity="ERROR",
            detail=("The .stp names no capture clock — SignalTap needs a "
                    "sampling clock (default CLOCK_50)."),
            fix_hint=("Add a <clock name=\"CLOCK_50\" .../> capture clock."),
        ))

    status = "FAIL" if findings else "PASS"
    return Result(
        status=status,
        stp_file=stp_label,
        findings=findings,
        ports_checked=ports_checked,
        dut_ports=[p.name for p in (ports or [])],
        captured_signals=facts.signal_names,
        trigger_present=facts.has_trigger,
        sample_depth=facts.sample_depth,
        clock=facts.clock,
    )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.strip().split("\n")[0])
    ap.add_argument("stp", nargs="?", default=None,
                    help="Path to the SignalTap .stp file to validate")
    ap.add_argument("--sv", type=Path, default=None,
                    help="SystemVerilog/Verilog source to parse DUT ports from")
    ap.add_argument("--module", default=None,
                    help="Module name hint when --sv has multiple modules")
    ap.add_argument("--ports", default=None,
                    help='Manual DUT port list "name:dir:width,..." '
                         '(used instead of --sv)')
    ap.add_argument("--json", type=Path, default=None,
                    help="Also write the result JSON to this path")
    args = ap.parse_args(argv)

    # No .stp at all -> genuinely nothing to validate -> honest SKIP.
    if not args.stp:
        res = Result(status="SKIP")
        out = json.dumps(asdict(res), indent=2)
        if args.json:
            args.json.write_text(out)
        print(out)
        print("[SKIP] signaltap_stp_completeness_check: no .stp given — "
              "NOTHING EXAMINED, this is not a pass", file=sys.stderr)
        return 2

    stp_path = Path(args.stp)
    if not stp_path.is_file():
        print(f"ERROR: .stp not found: {stp_path}", file=sys.stderr)
        return 2
    stp_text = stp_path.read_text(errors="replace")

    # Resolve the DUT port list (optional — honest SKIP of the port half if
    # neither source is supplied, never a vacuous PASS of the port policy).
    ports: Optional[List[Port]] = None
    if args.ports:
        ports = parse_ports_from_str(args.ports)
    elif args.sv is not None:
        if not args.sv.is_file():
            print(f"ERROR: --sv not found: {args.sv}", file=sys.stderr)
            return 2
        ports = parse_ports_from_sv(args.sv.read_text(errors="replace"),
                                    args.module)
        if not ports:
            print(f"WARNING: no ports parsed from {args.sv} — port-coverage "
                  f"half SKIPPED (trigger/depth/clock still checked)",
                  file=sys.stderr)
            ports = None

    res = validate(stp_text, str(stp_path), ports)
    out = json.dumps(asdict(res), indent=2)
    if args.json:
        args.json.write_text(out)
    print(out)

    if res.findings:
        print(f"signaltap_stp_completeness_check: FAIL — "
              f"{len(res.findings)} finding(s)", file=sys.stderr)
        for f in res.findings:
            print(f"  [{f.rule}] {f.detail}", file=sys.stderr)
        return 1

    if not res.ports_checked:
        print("signaltap_stp_completeness_check: PASS — trigger/depth/clock "
              "OK and all BIST signals present (DUT-port coverage SKIPPED: no "
              "--sv/--ports supplied)", file=sys.stderr)
    else:
        print(f"signaltap_stp_completeness_check: PASS — all "
              f"{len(res.dut_ports)} DUT port(s) + 4 BIST signals captured, "
              f"trigger/depth/clock OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
