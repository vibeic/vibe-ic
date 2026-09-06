#!/usr/bin/env python3
"""phase1_sufficiency_check.py — the SUFFICIENCY GATE of the Phase-1 dialogue
dual-track convergence (owner directive 2026-06-20).

After the program track + IC-Expert AI track converge on an L1-L24 JSON (see
programs/phase1_json_converge.py), the IC Expert Agent must confirm the JSON is
actually SUFFICIENT TO DESIGN THE IC before handing off to Phase 2. If a
required design fact is missing, the agent does NOT guess — it asks the user a
PLAIN-LANGUAGE question (its external user-facing register) and re-ingests.

This program is the DETERMINISTIC half of that gate: it inspects the converged
layer JSON and reports, structurally, which minimum design facts are present
and which are missing — and for each missing REQUIRED fact it emits a ready-to-
ask plain-language question (no silicon jargon), so the user is never shown
`CRC`/`opcode`/`reset`/`V_DD`.

Severity model (conservative — avoid false "insufficient" loop-backs):
  REQUIRED   : block (a design genuinely cannot be authored without it)
                 - a module / chip name
                 - at least one REAL external port (a signal carrying a
                   direction/width, or sitting in a pinout/ports/io container —
                   a chip name / parameter / placeholder is NOT a port)
  ADVISORY   : warn only — surfaced for the IC-Expert AI track to judge, NEVER
               blocking (clock/reset is advisory even on a sequential design):
                 - a clock / reset signal, when the design is detected
                   SEQUENTIAL. NOTE: 'sequential' here is inferred ONLY from an
                   actual clock/reset PORT name, deliberately NOT from the mere
                   presence of an L6/L8/L12 layer body — every project emits a
                   24-layer skeleton whose hint strings would otherwise fire a
                   clock/reset over-demand on purely combinational parts (a known
                   false-'insufficient' class). The prose-level "this runs on
                   each clock" judgment is the IC-Expert AI track's job; the
                   deterministic gate never blocks on clock/reset.
                 - parameters, a register map / protocol when indicated

chip-AGNOSTIC: structural inspection of the layer JSON only; no chip-specific
strings; the plain-language questions are generic product language.

Usage:
    phase1_sufficiency_check.py <L*.json dir | merged.json> [--json OUT] [--strict]
    # exit 0 unless --strict and a REQUIRED fact is missing (then exit 1)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CLOCK_RE = re.compile(r"\b(clk|clock|sclk|hclk|pclk|aclk)\b", re.I)
_RESET_RE = re.compile(r"\b(rst|reset|resetn|rst_n|nreset|areset|sreset)\b",
                       re.I)
_PORTISH_KEYS = ("name", "signal", "port", "pin")
# A dict is a REAL port only when it carries a direction/width indicator OR sits
# inside an explicit port CONTAINER — a bare `name`/`signal` key alone also
# describes a chip name, a parameter, or a document author, so counting those as
# ports lets a design with ZERO real I/O pass the REQUIRED "≥1 port" fact
# (Step-2.7 §4.05 false-skip).
_PORT_EVIDENCE_KEYS = ("dir", "direction", "mode", "io", "inout", "in_out",
                       "input", "output", "width", "bits", "bit_width", "msb",
                       "lsb", "active", "polarity", "sense")
_PORT_CONTAINER_KEYS = ("pinout", "pin_table", "pins", "ports", "port_list",
                        "port_table", "io", "ios", "io_list", "signals",
                        "signal_list", "interface", "interfaces")
# Sentinel / unfilled-template port values that are NOT a real signal.
_PLACEHOLDER_RE = re.compile(r"[<>]|fill[\s_-]*in|todo|tbd|xxx|placeholder|"
                             r"^_+$|example", re.I)


def _is_placeholder_port(name: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(name)) or not name.strip()


def _load_layers(path: Path) -> Dict[str, Any]:
    """Return {layer_code: parsed_json}. Accepts a dir of L*.json or a single
    merged/structured JSON file (then keyed by its top-level L<N> keys)."""
    out: Dict[str, Any] = {}
    if path.is_dir():
        for f in sorted(path.glob("L*.json")):
            stem = f.stem
            code = stem
            for i in range(len(stem), 0, -1):
                head = stem[:i]
                if head and head[0] == "L" and head[1:].rstrip("R").isdigit():
                    code = head
                    break
            try:
                out[code] = json.loads(f.read_text())
            except Exception:  # noqa: BLE001
                continue
    elif path.is_file():
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            return out
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and k and k[0] == "L" \
                        and k[1:].rstrip("R").isdigit():
                    out[k] = v
            if not out:                 # a single L*.json's bare body
                out["L1"] = data
    return out


def _iter_strings(node: Any) -> List[str]:
    acc: List[str] = []
    if isinstance(node, dict):
        for v in node.values():
            acc.extend(_iter_strings(v))
    elif isinstance(node, list):
        for v in node:
            acc.extend(_iter_strings(v))
    elif isinstance(node, str):
        acc.append(node)
    return acc


def _collect_port_names(layers: Dict[str, Any]) -> List[str]:
    """Pull REAL port/signal names from the port-bearing layers (L1 pinout, L8R).

    A dict with a `name`/`signal`/`port`/`pin` key counts as a port ONLY when it
    ALSO carries a direction/width indicator OR it sits inside an explicit port
    CONTAINER (pinout / ports / io / signals …). A lone name key alone is NOT a
    port — chip names, parameter names, and document-author names all bear one,
    and an unfilled `<fill-in-port-name>` template placeholder is rejected. Without
    these guards a design with zero real I/O satisfied the REQUIRED "≥1 port"
    fact (Step-2.7 §4.05 false-skip)."""
    names: List[str] = []

    def _port_name(node: dict) -> Optional[str]:
        for k in _PORTISH_KEYS:
            for kk, vv in node.items():
                if str(kk).lower() == k and isinstance(vv, (str, int)):
                    return str(vv)
        return None

    def _has_evidence(node: dict) -> bool:
        return any(str(kk).lower() in _PORT_EVIDENCE_KEYS for kk in node)

    def _scan(node: Any, in_container: bool) -> None:
        if isinstance(node, dict):
            nm = _port_name(node)
            if nm and (in_container or _has_evidence(node)) \
                    and not _is_placeholder_port(nm):
                names.append(nm)
            for kk, vv in node.items():
                child_in = in_container or str(kk).lower() in _PORT_CONTAINER_KEYS
                _scan(vv, child_in)
        elif isinstance(node, list):
            for v in node:
                _scan(v, in_container)

    for code in ("L1", "L8R", "L5", "L17"):
        if code in layers:
            _scan(layers[code], False)
    return names


def _name_present(layers: Dict[str, Any]) -> bool:
    for code in ("L1", "L9"):
        blob = layers.get(code)
        if not isinstance(blob, dict):
            continue
        for key in ("chip_name", "ic_name", "module_name", "top_module",
                    "name", "top"):
            v = blob.get(key)
            if isinstance(v, str) and v.strip() and \
                    v.strip().upper() not in ("UNNAMED_CHIP", "__UNKNOWN__"):
                return True
    return False


def _is_sequential(layers: Dict[str, Any], port_names: List[str]) -> bool:
    """Sequential iff a clock OR reset port is actually present.

    NOTE: we deliberately do NOT infer 'sequential' from the mere existence
    of an L6/L8/L12 layer body — every project emits a 24-layer SKELETON whose
    extraction-hint strings ("Look for scan / DFT …") are present even when the
    layer extracted nothing, so a string-presence test fired on EVERY design
    and over-demanded a clock/reset on purely combinational parts (a known
    false-'insufficient' class). The clock/reset gap is ADVISORY anyway (see
    check()); the prose-level "this runs on each clock" judgment is the
    IC-Expert AI track's job, not this structural gate's."""
    return (any(_CLOCK_RE.search(n) for n in port_names)
            or any(_RESET_RE.search(n) for n in port_names))


# plain-language (no-jargon) question per missing fact — the IC Expert Agent's
# external user-facing register reads these out verbatim.
_QUESTIONS = {
    "name": "What should we call this chip / part?",
    "ports": "What signals does this part use to connect to the outside "
             "world — what information goes in, and what comes out?",
    # NO silicon jargon in the user-facing strings (the agent reads these
    # verbatim) — the gate's own contract forbids showing the user tokens like
    # `reset`/`clock`; describe the concept in plain product language instead.
    "clock": "Does this part work in steps driven by a regular timing beat? "
             "If so, what should that timing signal be called?",
    "reset": "Is there a way to put this part back to a known starting state? "
             "Should it return to that state when the signal is on, or off?",
}


def _width_completeness_advisories(doc_text: str, port_names: List[str]
                                   ) -> List[Dict[str, str]]:
    """Run the GENERAL completeness engine (spec_complete_extract.assess_spec) over
    the original design doc + the collected ports, and turn any width gap into a
    plain-language ADVISORY the IC Expert Agent can ask the user. This is how the
    benchmark-convergence width-extraction work (CVDP/RTLLM/VE) reaches the general
    Phase-1 flow: a port whose width the doc never states becomes a user question,
    instead of an AI silently guessing a bus width. §4.05: a width gap is reported,
    never auto-filled; the agent elicits the real value."""
    if not doc_text or not port_names:
        return []
    try:
        import spec_complete_extract as _eng
        # the doc is the spec; we cannot know each port's direction here, so pass
        # all collected names as inputs (direction does not affect width gaps).
        spec = _eng.assess_spec(doc_text, list(port_names), [])
    except Exception:
        return []
    advs: List[Dict[str, str]] = []
    for g in spec.get("gaps", []):
        if g.get("type") in ("width_not_stated", "param_expression_width"):
            m = re.search(r"port `?(\w+)`?", g.get("detail", ""))
            sig = m.group(1) if m else "a signal"
            advs.append({
                "fact": f"width:{sig}",
                "question": (f"How many bits wide is the `{sig}` connection — "
                             f"is it a single on/off line, or does it carry a "
                             f"number / several bits at once?"),
            })
    return advs



# ── #czl9docs — "no ports" has TWO causes, and only one is legitimate ──
#
# Measured: a docs-mode Phase-1 over an input whose FIRST lines are
# `- input clk` / `- output cmd_out (4 bits)` emitted an L9 with 0 ports, and
# every downstream gate that reads L9 ports then reported PASS over an empty
# population. The sufficiency gate said `insufficient / MISSING ['ports']` and
# the run continued, because the gate is ADVISORY and cannot tell the two
# causes apart:
#
#   (a) the INPUT declares no ports  — a pure behavioural spec. Legitimate.
#       The design is allowed through; the gap is a question for the user.
#   (b) the INPUT declares ports and the extractor found none — an EXTRACTION
#       GAP. Nothing downstream can be measured, and a PASS from a port-reading
#       gate is a verdict over zero inputs.
#
# This function separates them by reading the design INPUT only (§4.05 — never
# the L-docs' own claim about the input, never a golden/reference tree). The
# evidence it accepts is Verilog/SV direction grammar and the port-table /
# port-heading shapes that every extractor in this repo already keys on; it is
# deliberately NARROW, because a false (b) blocks a run.
_INPUT_PORT_EVIDENCE = (
    # `- input clk`, `* output data_o`, `input [7:0] x`, `inout wire sda`
    re.compile(r"(?im)^\s*(?:[-*+]\s+)?`?(?:input|output|inout)\b`?"
               r"(?:\s+(?:wire|reg|logic))?"
               r"(?:\s*\[[^\]\n]{1,40}\])?"
               r"\s+`?[A-Za-z_][A-Za-z0-9_]{1,40}`?\b"),
    # a `Ports:` / `Top-level signals:` / `Pin table` heading
    re.compile(r"(?im)^\s*(?:[-*+]\s+|#{1,6}\s+)?\*{0,2}"
               r"(?:top[-_ ]?level\s+|external\s+|chip[-_ ]?level\s+)?"
               r"(?:ports?|pinouts?|pin\s+table|signals?|pins?|i/?o\s+ports?)"
               r"\*{0,2}\s*[:.]?\s*$"),
    # a markdown/RST table row carrying a direction cell
    re.compile(r"(?im)^\s*\|[^|\n]{1,60}\|\s*(?:input|output|inout|i/o)\s*\|"),
)
_INPUT_TEXT_SUFFIXES = {".md", ".txt", ".rst", ".markdown", ".yaml", ".yml",
                        ".json", ".v", ".sv", ".csv"}


def input_declares_ports(project: Path) -> Optional[bool]:
    """Does the design INPUT itself declare at least one port?

    Returns True / False, or **None** when nothing readable was found — which
    is NOT_MEASURED and must never be collapsed to False. §4.05: reads
    ``input/`` and the extracted ``input_doc/`` mirror only.
    """
    if project is None:
        return None
    roots = [project / "input", project / "input_doc",
             project / "phase1" / "input_doc",
             project / "phase1" / "input_prompt"]
    read_any = False
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in _INPUT_TEXT_SUFFIXES:
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue          # unreadable — not evidence of absence
            read_any = True
            for rx in _INPUT_PORT_EVIDENCE:
                if rx.search(text):
                    return True
    return False if read_any else None


def check(path: Path, doc_text: str = "",
          project: Optional[Path] = None) -> Dict[str, Any]:
    layers = _load_layers(path)
    port_names = _collect_port_names(layers)
    has_name = _name_present(layers)
    has_ports = len(port_names) >= 1
    sequential = _is_sequential(layers, port_names)
    has_clock = any(_CLOCK_RE.search(n) for n in port_names)
    has_reset = any(_RESET_RE.search(n) for n in port_names)
    width_advisories = _width_completeness_advisories(doc_text, port_names)

    required: List[Dict[str, Any]] = []
    conditional: List[Dict[str, Any]] = []

    def _item(key: str, present: bool) -> Dict[str, Any]:
        return {"fact": key, "present": present,
                "question": None if present else _QUESTIONS.get(key)}

    required.append(_item("name", has_name))
    required.append(_item("ports", has_ports))
    # clock/reset are ADVISORY, never blocking. A sequential design that omits
    # a reset is legal, and 'sequential' itself is only inferred from a real
    # clock/reset port — so this can surface a genuine gap (a reset port but no
    # clock) without the over-demand that flips a combinational part to
    # 'insufficient'. The IC-Expert Agent decides whether an advisory is worth
    # a user question; the gate never forces it.
    if sequential:
        conditional.append(_item("clock", has_clock))
        conditional.append(_item("reset", has_reset))

    missing_required = [i for i in required if not i["present"]]
    missing_conditional = [i for i in conditional if not i["present"]]
    # VERDICT blocks on REQUIRED facts only (name + at least one port). The
    # advisory gaps are reported for the agent's judgment, not auto-blocked.
    sufficient = not missing_required
    # #czl9docs — separate the two causes of "no ports" (see
    # `input_declares_ports`). `None` is NOT_MEASURED and stays None.
    ports_in_input = input_declares_ports(project) if project else None
    extraction_gap = (not has_ports) and ports_in_input is True
    if has_ports:
        ports_reason = "ports_extracted"
    elif ports_in_input is True:
        ports_reason = "extraction_gap"
    elif ports_in_input is False:
        ports_reason = "input_declares_no_ports"
    else:
        ports_reason = "NOT_MEASURED"
    questions = [i["question"] for i in missing_required if i["question"]]
    advisories = [i["question"] for i in missing_conditional if i["question"]]
    # width-completeness advisories from the general engine — surfaced for the
    # IC-Expert Agent to elicit, NEVER blocking (an unstated bus width is a
    # question to ask, not a reason to fail the gate).
    advisories += [a["question"] for a in width_advisories]
    return {
        "verdict": "sufficient" if sufficient else "insufficient",
        # #czl9docs
        "ports_declared_in_input": ports_in_input,
        "ports_reason": ports_reason,
        "extraction_gap": extraction_gap,
        "sequential": sequential,
        "layers_seen": sorted(layers.keys()),
        "port_count": len(port_names),
        "required": required,
        "conditional": conditional,
        "missing_required": [i["fact"] for i in missing_required],
        "missing_conditional": [i["fact"] for i in missing_conditional],
        "width_gaps": [a["fact"] for a in width_advisories],
        "questions_for_user": questions,
        "advisories_for_agent": advisories,
    }


def _fmt(rep: Dict[str, Any]) -> str:
    lines = [f"sufficiency verdict: {rep['verdict']}",
             f"  layers={','.join(rep['layers_seen']) or '(none)'} "
             f"ports={rep['port_count']} sequential={rep['sequential']}"]
    if rep["missing_required"]:
        lines.append(f"  MISSING required: {rep['missing_required']}")
    # #czl9docs — say WHICH cause, so a reader never has to guess whether a
    # port-less L9 came from a behavioural spec or from a broken extractor.
    if rep.get("ports_reason") == "extraction_gap":
        lines.append("  EXTRACTION GAP: the design INPUT declares ports and "
                     "the L documents carry none — every downstream gate that "
                     "reads a port list would report a verdict over ZERO "
                     "ports. This is NOT a port-less design.")
    elif rep.get("ports_reason") == "input_declares_no_ports":
        lines.append("  the design INPUT declares no ports either — a purely "
                     "behavioural specification; allowed through, ask the user.")
    elif rep.get("ports_reason") == "NOT_MEASURED":
        lines.append("  NOT_MEASURED: no readable design input was found, so "
                     "whether the input declares ports is unknown.")
    if rep["missing_conditional"]:
        lines.append(f"  MISSING conditional: {rep['missing_conditional']}")
    for q in rep["questions_for_user"]:
        lines.append(f"  ask user > {q}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layers", type=Path,
                    help="converged L*.json dir or merged.json")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full sufficiency report here")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a REQUIRED fact is missing (block)")
    ap.add_argument("--project", type=Path, default=None,
                    help="the project root — reads input/ + input_doc/ to tell "
                         "an EXTRACTION GAP (input declares ports, L docs carry "
                         "none) from a genuinely port-less behavioural spec")
    ap.add_argument("--strict-extraction-gap", action="store_true",
                    help="exit 1 ONLY on the extraction gap (input declares "
                         "ports, L docs carry none). A port-less input still "
                         "exits 0.")
    ap.add_argument("--doc", type=Path, default=None,
                    help="the original design-doc / prompt text — runs the general "
                         "completeness engine to surface unstated-width advisories")
    args = ap.parse_args(argv)
    if not (args.layers.is_dir() or args.layers.is_file()):
        print(f"ERROR: not found: {args.layers}", file=sys.stderr)
        return 2
    doc_text = ""
    if args.doc and args.doc.is_file():
        doc_text = args.doc.read_text(errors="ignore")
    rep = check(args.layers, doc_text=doc_text, project=args.project)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(_fmt(rep))
    if args.strict and rep["missing_required"]:
        return 1
    if args.strict_extraction_gap and rep.get("extraction_gap"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
