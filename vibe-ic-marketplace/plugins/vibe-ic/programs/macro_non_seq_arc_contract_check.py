#!/usr/bin/env python3
"""macro_non_seq_arc_contract_check.py — a staged macro's NON-SEQUENTIAL timing
requirement must reach the integration BEFORE post-CTS.

ENFORCEMENT: advisory

WHY THIS GATE EXISTS (the measured defect it is distilled from)
---------------------------------------------------------------
A vendor hard macro staged under the design's OWN pdk-local tree declared, in
its OWN Liberty, an address-stable-around-strobe requirement:

    timing_type : non_seq_setup_rising;    (8.00 ns)
    timing_type : non_seq_hold_falling;    (9.00 ns)

The generated integration drove that address pin straight from a rising-edge
flop on the same clock as the strobe, so it is held for clk-to-Q and nothing
more. The FIRST time anything in the flow said so was Step 20 (post-CTS hold
fixing):

    HOLD_SLACK_NEGATIVE: hold report shows NEGATIVE worst hold slack
                         -8.680074682484532

...whose own verdict named the wrong repair ("re-CTS / insert delay cells"):
closing -8.68 ns on a DATA path with hold buffers needs on the order of
87 stages. The correct repair is at the integration level — hold the address
across the strobe (register-enable de-asserted), or launch the strobe from a
later edge — and it must land before synthesis, not after CTS.

The requirement was IN the run the whole time, in a file the flow itself
staged and read: `read_liberty` loads that macro Liberty at synthesis and at
every STA corner. Measured on the tree before this file existed, the number of
places in `programs/`, `flow/`, `skills/` and `mcp-eda/` that read a
`non_seq_*` arc was ZERO. So the flow staged a machine-readable integration
contract, generated an integration that violated it, and then reported the
violation 13 steps later in a vocabulary that points at the router.

THE PRINCIPLE (inherited from `l21_macro_supply_rail_declared_check`)
--------------------------------------------------------------------
    A requirement is surfaced when it is present IN THE LAYER THAT CONSUMES
    IT, in an actionable form — not when it merely exists in an input file
    some tool happens to read.

The consumer of a macro's non-sequential arc is the INTEGRATION: the RTL that
drives the constrained pin and the constraint set built around it. So the
load-bearing clause is:

    every `non_seq_*` timing arc that an INSTANTIATED, design-staged hard
    macro declares in its OWN Liberty must be recorded as a structured macro
    timing requirement in the design's OWN L-doc layer (L8/L9), naming the
    macro, the constrained pin, the related pin and the window in ns.

WHAT IT CHECKS
--------------
  NSQ-1 (rc=1)  An arc with NO matching structured record anywhere in the
                design's L-doc layer. This is the measured defect: the
                requirement reaches nothing until post-CTS.
  NSQ-2 (rc=1)  An arc recorded with a window SMALLER than the macro's own
                Liberty declares. A record that understates the requirement is
                worse than none — the integration is built to a number the
                macro will not honour.
  NSQ-3 (note)  The declared window is >= the design's own clock period, so no
                single-cycle same-clock integration can satisfy it at all: the
                repair is multi-cycle (hold the pin) and cannot be a delay-cell
                one. Escalates the message; never changes the exit code on its
                own.

Everything is DERIVED from the design's own machine-readable inputs — the
macro's own Liberty, the design's own RTL/netlist instantiations, the design's
own L-docs and SDC. There is no PDK name, design name, vendor part number or
pin/cell literal anywhere in this file. A design that stages no macro Liberty
carrying `non_seq_*` arcs SKIPs (rc=2) and is byte-identically unaffected.

SCOPE — WHY THE PDK STD-CELL LIBRARY IS NOT IN IT
-------------------------------------------------
`non_seq_*` arcs are NOT exotic: measured on this repo's own corpus, an
open-source std-cell Liberty carries 24 of them (SET/RESET recovery windows on
set-reset flops, 0.1-0.4 ns). Those are satisfied by construction and gating on
them would fire on every design that ever synthesised. Two independent
restrictions keep this gate on the real population:

  * ROOT — only Liberty under the DESIGN-STAGED macro roots is read
    (`input/pdk_local/**`, `input/macros/**`, `input/hardmacro/**`,
    `phase3|phase2/analog/hardmacro/**`) — the same roots the backend's own
    macro collection uses. The PDK library root (`input/pdk/**`) is not one of
    them.
  * CLASS — a cell an accompanying staged LEF explicitly types `CLASS CORE` is
    a std cell and is dropped, by LEF grammar and not by filename.

WHY ADVISORY AND NOT BLOCKING
-----------------------------
The finding is a DISCLOSURE that a requirement is unrecorded — not a proof
that it is violated. Proving violation early needs a structural trace from the
constrained pin back to its driving flop's enable, pre-synthesis; this gate
does not do that and must not pretend to. A macro may also carry a small
non-sequential window its integration meets by construction.

So it is wired to `advisory_program_exit_zero`: it RUNS on every real project
and every finding is reported, and rc=1 does not stop the step. That is the
same call, on the same evidence shape, as
`l21_macro_supply_rail_declared_check` — and it is what the measurement
supports. Swept over the published corpus in `benchmark-data/`, exactly three
design-staged macro Liberties exist and NONE declares a `non_seq_*` arc, so
this gate SKIPs on all of them: wiring it blocking today would be a decision
taken with zero evidence behind it.

The honest escape hatch is a NAMED waiver, not silence: set
`macro_non_seq_arc_requirement_disclosed` in `<project>/waivers.json` to a
>=40-char justification and the gate reports PASS_WITH_WAIVERS (rc=0) while
still printing every finding.

WHAT THIS GATE DOES NOT DO
--------------------------
It does not suppress, soften or pre-empt the post-CTS hold FAIL. Step 20's
`hold_closure_check` still FAILs on a negative hold slack exactly as before;
that gate separately learned to NAME the arc kind when the violating path
cites a library non-sequential hold time, so the late failure points at the
integration-level repair instead of at the router. Both exist: the early
warning and the late hard failure.

USAGE
-----
    python3 macro_non_seq_arc_contract_check.py <project_dir> [--json OUT]

EXIT CODES
----------
    0 = PASS (or PASS_WITH_WAIVERS)
    1 = FAIL (findings; advisory at its wired slot)
    2 = not applicable / input missing (SKIP)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # checker doctrine: reuse the SIBLING gate's instantiation walk so the
      # two macro gates can never disagree about what "instantiated" means.
    from l21_macro_supply_rail_declared_check import (  # type: ignore
        _instantiated_masters as _sibling_instantiated_masters,
        _macro_classes as _sibling_macro_classes,
    )
except Exception:  # pragma: no cover - keeps the gate usable stand-alone
    _sibling_instantiated_masters = None  # type: ignore
    _sibling_macro_classes = None  # type: ignore

# The ONE negation vocabulary (#712), for the stand-alone fallback below. It
# must answer what the sibling answers, denials included, or the fallback is a
# second opinion rather than a fallback.
from _prose_polarity import (  # type: ignore  # noqa: E402
    blank_bracketed as _blank_bracketed,
    is_denied as _is_denied,
)

GATE_NAME = "macro_non_seq_arc_contract_check"
WAIVER_KEY = "macro_non_seq_arc_requirement_disclosed"
WAIVER_MIN = 40

#: Design-OWNED macro roots. Mirrors `l21_macro_supply_rail_declared_check`'s
#: LEF roots; deliberately excludes `input/pdk/**` (the std-cell library).
_MACRO_LIB_GLOBS: Tuple[str, ...] = (
    "input/pdk_local/**/*.lib",
    "input/macros/**/*.lib",
    "input/hardmacro/**/*.lib",
    "phase3/analog/hardmacro/**/*.lib",
    "phase2/analog/hardmacro/**/*.lib",
)
_MACRO_LEF_GLOBS: Tuple[str, ...] = tuple(
    g[:-4] + ".lef" for g in _MACRO_LIB_GLOBS)

_INSTANCE_TEXT_GLOBS: Tuple[str, ...] = (
    "phase2/stage1/rtl/**/*.v",
    "phase2/stage1/rtl/**/*.sv",
    "phase2/stage2/synth/**/*.v",
    "phase3/stage3/pnr/**/*.v",
)

#: Liberty `timing_type` values that state a NON-SEQUENTIAL constraint, i.e. a
#: stability window referenced to another SIGNAL pin rather than to a clock.
#: Liberty grammar, not a vendor list.
_NON_SEQ_TYPES = (
    "non_seq_setup_rising", "non_seq_setup_falling",
    "non_seq_hold_rising", "non_seq_hold_falling",
)

#: Where the design records a macro timing requirement. Accepted under the doc
#: root or under `fields`, so the gate does not depend on one L-doc shape.
_CONTRACT_LIST_KEYS = (
    "macro_timing_requirements", "macro_timing_arcs",
    "hard_macro_timing_requirements", "non_sequential_timing_requirements",
    "macro_non_seq_requirements",
)
_ENTRY_MACRO_KEYS = ("macro", "cell", "master", "macro_cell", "macro_name",
                     "name")
_ENTRY_PIN_KEYS = ("constrained_pin", "pin", "data_pin", "port",
                   "constrained_port")
_ENTRY_RELATED_KEYS = ("related_pin", "reference_pin", "strobe_pin", "related",
                       "related_port")
_ENTRY_VALUE_KEYS = ("requirement_ns", "value_ns", "window_ns", "hold_ns",
                     "setup_ns", "ns", "value")
_ENTRY_KIND_KEYS = ("timing_type", "arc", "kind", "arc_kind", "type")

_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_SDC_PERIOD_RE = re.compile(r"create_clock\b[^\n]*?-period\s+([-+.\deE]+)")


# --------------------------------------------------------------------------- #
# Liberty parsing — a brace-scoped group walk, not a keyword grep
# --------------------------------------------------------------------------- #
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_GROUP_HDR_RE = re.compile(r"([A-Za-z_]\w*)\s*\(([^()]*)\)\s*$")
_SIMPLE_ATTR_RE = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(.*)$", re.S)
_COMPLEX_ATTR_RE = re.compile(r"^([A-Za-z_]\w*)\s*\((.*)\)\s*$", re.S)


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_non_seq_arcs(lib_text: str) -> List[Dict[str, object]]:
    """Every `non_seq_*` timing arc in a Liberty, as
    ``{cell, constrained_pin, related_pin, timing_type, window_ns}``.

    A brace-scoped walk, so a `timing()` group is attributed to the `pin`/`bus`
    group that actually encloses it. `window_ns` is the MAXIMUM value found in
    the arc's own `*_constraint` tables — the worst case the integration has to
    honour. Arcs whose tables carry no number at all are still returned, with
    ``window_ns = None``, so an un-characterised requirement is reported rather
    than dropped."""
    text = _COMMENT_RE.sub(" ", lib_text or "")
    text = text.replace("\\\n", " ")

    arcs: List[Dict[str, object]] = []
    stack: List[Tuple[str, str]] = []
    buf: List[str] = []
    cur_arc: Optional[Dict[str, object]] = None
    i, n = 0, len(text)

    def _enclosing(kind: str) -> str:
        for gtype, gname in reversed(stack):
            if gtype == kind:
                return gname
        return ""

    def _constrained_pin() -> str:
        for gtype, gname in reversed(stack):
            if gtype in ("pin", "bus", "bundle"):
                return gname
        return ""

    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            buf.append(text[i:min(j + 1, n)])
            i = j + 1
            continue
        if c == "{":
            header = "".join(buf).strip()
            buf = []
            m = _GROUP_HDR_RE.search(header)
            gtype = m.group(1) if m else ""
            gname = _unquote(m.group(2)) if m else ""
            stack.append((gtype, gname))
            if gtype == "timing":
                cur_arc = {"cell": _enclosing("cell"),
                           "constrained_pin": _constrained_pin(),
                           "related_pin": "", "timing_type": "",
                           "values": []}
            i += 1
            continue
        if c == "}":
            buf = []
            if stack:
                gtype, _ = stack.pop()
                if gtype == "timing" and cur_arc is not None:
                    tt = str(cur_arc.get("timing_type", ""))
                    if tt in _NON_SEQ_TYPES:
                        vals = [v for v in cur_arc["values"]  # type: ignore
                                if isinstance(v, float) and math.isfinite(v)]
                        arcs.append({
                            "cell": cur_arc["cell"],
                            "constrained_pin": cur_arc["constrained_pin"],
                            "related_pin": cur_arc["related_pin"],
                            "timing_type": tt,
                            "window_ns": max(vals) if vals else None,
                        })
                    cur_arc = None
                    # a `timing` group may not nest, so nothing to restore
            i += 1
            continue
        if c == ";":
            stmt = "".join(buf).strip()
            buf = []
            if cur_arc is not None and stmt:
                sm = _SIMPLE_ATTR_RE.match(stmt)
                if sm:
                    key, val = sm.group(1), _unquote(sm.group(2))
                    if key in ("related_pin", "timing_type"):
                        cur_arc[key] = val
                else:
                    cm = _COMPLEX_ATTR_RE.match(stmt)
                    # Only the arc's own CONSTRAINT tables carry the window. A
                    # bare `values` collector would also swallow a delay table
                    # if one ever shared the group, and report a propagation
                    # number as if it were a stability requirement.
                    in_constraint = bool(stack) and stack[-1][0].endswith(
                        "_constraint")
                    if cm and cm.group(1) == "values" and in_constraint:
                        for tok in _FLOAT_RE.findall(cm.group(2)):
                            try:
                                cur_arc["values"].append(  # type: ignore
                                    float(tok))
                            except ValueError:
                                pass
            i += 1
            continue
        buf.append(c)
        i += 1
    return arcs


def _cell_names(lib_text: str) -> Set[str]:
    """Cell names a Liberty declares (`cell (NAME) {`). Liberty grammar."""
    return set(re.findall(r"\bcell\s*\(\s*([^()\s]+)\s*\)\s*\{",
                          lib_text or ""))


# --------------------------------------------------------------------------- #
# Design-side collection
# --------------------------------------------------------------------------- #
def _std_cell_masters(project: Path) -> Set[str]:
    """Cells an accompanying STAGED LEF explicitly types `CLASS CORE`.

    A std-cell library staged under a macro root would otherwise contribute its
    (satisfied-by-construction) recovery windows. LEF grammar, not filename."""
    out: Set[str] = set()
    for pat in _MACRO_LEF_GLOBS:
        for lef in sorted(project.glob(pat)):
            if not lef.is_file():
                continue
            try:
                text = lef.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            classes = (_sibling_macro_classes(text)
                       if _sibling_macro_classes is not None
                       else _local_macro_classes(text))
            for master, cls in classes.items():
                if cls.startswith("CORE"):
                    out.add(master)
    return out


def _local_macro_classes(lef_text: str) -> Dict[str, str]:
    """Stand-alone fallback for the sibling gate's `_macro_classes`.

    Mirrors it EXACTLY, denial rule included — see that function for the
    measurement and for why the polarity of a `CLASS` statement is not a
    formality. A fallback that answered differently from the walk it stands in
    for would make `_std_cell_masters` depend on whether an import succeeded.

    The value is subtractive HERE too: a master read as `CLASS CORE` is dropped
    from this gate's scope by `_std_cell_masters`, so honouring a denied one
    would let the LEF being audited switch the audit off. A denied CLASS is not
    published, and the master stays in scope.
    """
    out: Dict[str, str] = {}
    cur: Optional[str] = None
    lead: List[str] = []
    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        body, _, trail = s.partition("#")
        body, trail = body.strip(), trail.strip()
        if not body:
            lead = lead + [trail] if s.startswith("#") else []
            continue
        m = re.match(r"MACRO\s+(\S+)", body)
        if m:
            cur = m.group(1)
            lead = []
            continue
        if cur and body.startswith("END ") and body.split()[1:2] == [cur]:
            cur = None
            lead = []
            continue
        if cur is None:
            lead = []
            continue
        m = re.match(r"CLASS\s+(\S+)", body)
        if m:
            span = _blank_bracketed(
                " ".join(lead + ([trail] if trail else [])))
            if not _is_denied(span):
                out[cur] = m.group(1).rstrip(";").upper()
        lead = []
    return out


def _local_instantiated_masters(project: Path,
                                masters: Sequence[str]) -> Optional[Set[str]]:
    texts: List[str] = []
    for pat in _INSTANCE_TEXT_GLOBS:
        for f in sorted(project.glob(pat))[:400]:
            if not f.is_file():
                continue
            try:
                texts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    if not texts:
        return None
    blob = "\n".join(texts)
    return {m for m in masters if re.search(r"\b" + re.escape(m) + r"\b", blob)}


def collect_staged_non_seq_arcs(
        project: Path) -> Tuple[List[Dict[str, object]], List[str]]:
    """`([arc, ...], [liberty_rel_path, ...])` for every design-staged macro
    Liberty. Each arc carries its source path so a finding can cite the file."""
    arcs: List[Dict[str, object]] = []
    libs: List[str] = []
    seen: Set[Path] = set()
    std_cells = _std_cell_masters(project)
    for pat in _MACRO_LIB_GLOBS:
        for lib in sorted(project.glob(pat)):
            if not lib.is_file() or lib in seen:
                continue
            seen.add(lib)
            try:
                text = lib.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = str(lib.relative_to(project))
            found = [a for a in parse_non_seq_arcs(text)
                     if a.get("cell") and a["cell"] not in std_cells]
            if found:
                libs.append(rel)
            for a in found:
                a["liberty"] = rel
                arcs.append(a)
    return arcs, libs


# --------------------------------------------------------------------------- #
# The design's own recorded contract
# --------------------------------------------------------------------------- #
def _bus_base(pin: str) -> str:
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", str(pin or "")).strip()


def _first_str(entry: dict, keys: Sequence[str]) -> str:
    for k in keys:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _first_float(entry: dict, keys: Sequence[str]) -> Optional[float]:
    for k in keys:
        v = entry.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            m = _FLOAT_RE.search(v)
            if m:
                try:
                    return float(m.group(0))
                except ValueError:
                    continue
    return None


def _contract_entries(project: Path) -> Tuple[List[dict], List[str]]:
    """Structured macro-timing records the design's own L-doc layer carries."""
    entries: List[dict] = []
    docs: List[str] = []
    root = project / "phase1" / "generated_docs"
    if not root.is_dir():
        return entries, docs
    for doc in sorted(root.glob("*.json")):
        try:
            data = json.loads(doc.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        scopes = [data]
        fields = data.get("fields")
        if isinstance(fields, dict):
            scopes.append(fields)
        hit = False
        for scope in scopes:
            for key in _CONTRACT_LIST_KEYS:
                lst = scope.get(key)
                if isinstance(lst, list):
                    for e in lst:
                        if isinstance(e, dict):
                            entries.append(e)
                            hit = True
        if hit:
            docs.append(str(doc.relative_to(project)))
    return entries, docs


def _arc_family(timing_type: str) -> str:
    return "hold" if "hold" in str(timing_type or "").lower() else "setup"


def _entry_kind_matches(arc: Dict[str, object], entry: dict) -> bool:
    """A record that names a SETUP window must not be read as satisfying the
    HOLD arc of the same pin pair — a setup number and a hold number are
    different requirements and only one of them was the -8.68 ns.

    A record that states no kind at all is accepted for either: a design may
    legitimately record one combined stability window for the pin pair."""
    stated = " ".join(_first_str(entry, (k,)) for k in _ENTRY_KIND_KEYS).lower()
    has_hold, has_setup = "hold" in stated, "setup" in stated
    if not has_hold and not has_setup:
        return True
    return has_hold if _arc_family(arc.get("timing_type", "")) == "hold" \
        else has_setup


def _entry_value_keys(arc: Dict[str, object]) -> Tuple[str, ...]:
    """Value keys ordered so the arc's OWN family wins. An entry carrying both
    `setup_ns` and `hold_ns` must not have its setup number read as the hold
    requirement."""
    own, other = ("hold_ns", "setup_ns") if \
        _arc_family(arc.get("timing_type", "")) == "hold" else \
        ("setup_ns", "hold_ns")
    return ("requirement_ns", "value_ns", "window_ns", own, other, "ns",
            "value")


def _match_entry(arc: Dict[str, object],
                 entries: Sequence[dict]) -> Optional[dict]:
    """The recorded entry that names THIS arc: same cell, same constrained pin
    (bus base accepted), same related pin, compatible arc family. Name equality
    on the design's own identifiers — no fuzzy matching."""
    cell = str(arc.get("cell") or "")
    pin = str(arc.get("constrained_pin") or "")
    rel = str(arc.get("related_pin") or "")
    for e in entries:
        if _first_str(e, _ENTRY_MACRO_KEYS) != cell:
            continue
        e_pin = _first_str(e, _ENTRY_PIN_KEYS)
        if e_pin != pin and _bus_base(e_pin) != _bus_base(pin):
            continue
        e_rel = _first_str(e, _ENTRY_RELATED_KEYS)
        if e_rel != rel and _bus_base(e_rel) != _bus_base(rel):
            continue
        if not _entry_kind_matches(arc, e):
            continue
        return e
    return None


# --------------------------------------------------------------------------- #
# The design's own clock period (for the NSQ-3 escalation)
# --------------------------------------------------------------------------- #
def design_clock_period_ns(project: Path) -> Optional[float]:
    """Shortest `create_clock -period` in the design's own SDC, else the
    shortest clock period the design's own L8 declares. None when the design
    states neither — the escalation is then simply not made."""
    periods: List[float] = []
    cdir = project / "phase2" / "stage2" / "constraints"
    if cdir.is_dir():
        for sdc in sorted(cdir.rglob("*.sdc")):
            try:
                for m in _SDC_PERIOD_RE.finditer(
                        sdc.read_text(encoding="utf-8", errors="ignore")):
                    try:
                        periods.append(float(m.group(1)))
                    except ValueError:
                        continue
            except OSError:
                continue
    positive = [p for p in periods if p > 0]
    if positive:
        return min(positive)
    periods = []
    l8 = project / "phase1" / "generated_docs" / "L8_TIMING_WAVEFORM.json"
    try:
        data = json.loads(l8.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None
    fields = data.get("fields") if isinstance(data, dict) else None
    scope = fields if isinstance(fields, dict) else data
    if not isinstance(scope, dict):
        return None
    for clk in (scope.get("clocks") or []):
        if not isinstance(clk, dict):
            continue
        v = _first_float(clk, ("period_ns", "period", "clock_period_ns",
                               "period_nsec"))
        if v is not None and v > 0:
            periods.append(v)
    return min(periods) if periods else None


# --------------------------------------------------------------------------- #
def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return False, ""
    if not isinstance(doc, dict):
        return False, ""
    v = doc.get(WAIVER_KEY)
    if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
        return True, v.strip()
    return False, ""


def _repair_sentence(arc: Dict[str, object],
                     period: Optional[float]) -> str:
    kind = "hold" if "hold" in str(arc.get("timing_type", "")) else "setup"
    win = arc.get("window_ns")
    win_txt = f"{win} ns" if isinstance(win, float) else "an uncharacterised window"
    base = (
        f"the integration must keep `{arc.get('constrained_pin')}` stable for "
        f"{win_txt} {'after' if kind == 'hold' else 'before'} the "
        f"`{arc.get('related_pin')}` reference edge — i.e. hold the driving "
        f"register (de-assert its enable) across the strobe, or launch the "
        f"strobe from a later edge. A same-clock rising-edge driver supplies "
        f"only its clk-to-Q, so this lands as a post-CTS "
        f"{kind}-slack violation of roughly the full window")
    if kind == "hold":
        base += (", and hold-buffer insertion cannot close it: the whole "
                 "window would have to be built out of delay cells")
    if isinstance(win, float) and isinstance(period, float) and period > 0 \
            and win >= period:
        base += (f". NSQ-3: the window ({win} ns) is >= this design's own "
                 f"clock period ({period} ns), so NO single-cycle same-clock "
                 f"integration can satisfy it — the repair is necessarily "
                 f"multi-cycle")
    return base + "."


def evaluate(project: Path) -> Tuple[str, int, Dict[str, object]]:
    report: Dict[str, object] = {
        "gate": GATE_NAME,
        "project": str(project),
        "macro_liberties": [],
        "arcs": [],
        "findings": [],
        "notes": [],
    }

    arcs, libs = collect_staged_non_seq_arcs(project)
    report["macro_liberties"] = libs
    if not arcs:
        report["verdict"] = "SKIP"
        report["reason"] = (
            "no design-staged macro Liberty declares a non_seq_* timing arc "
            "(the PDK std-cell library is deliberately out of scope)")
        return "SKIP", 2, report

    cells = sorted({str(a["cell"]) for a in arcs})
    walk = (_sibling_instantiated_masters if _sibling_instantiated_masters
            is not None else _local_instantiated_masters)
    inst = walk(project, cells)
    if inst is None:
        in_scope = set(cells)
        scope_note = ("no RTL/netlist text available yet — every design-staged "
                      "macro treated as in scope")
    else:
        in_scope = {c for c in cells if c in inst}
        scope_note = (f"{len(in_scope)}/{len(cells)} staged macro(s) with "
                      "non_seq_* arcs are instantiated in the design's own "
                      "RTL/netlist")
    report["scope_note"] = scope_note
    report["in_scope_cells"] = sorted(in_scope)

    arcs = [a for a in arcs if str(a["cell"]) in in_scope]
    if not arcs:
        report["verdict"] = "SKIP"
        report["reason"] = (f"{scope_note}; no instantiated staged macro "
                            "declares a non_seq_* arc")
        return "SKIP", 2, report

    period = design_clock_period_ns(project)
    report["design_clock_period_ns"] = period
    entries, docs = _contract_entries(project)
    report["contract_docs"] = docs
    report["contract_entry_count"] = len(entries)

    findings: List[Dict[str, object]] = []
    for arc in arcs:
        rec = {k: arc[k] for k in
               ("cell", "constrained_pin", "related_pin", "timing_type",
                "window_ns", "liberty") if k in arc}
        match = _match_entry(arc, entries)
        rec["recorded"] = match is not None
        report["arcs"].append(rec)   # type: ignore[union-attr]
        ident = (f"`{arc['cell']}` arc {arc['timing_type']} "
                 f"{arc['constrained_pin']} <- {arc['related_pin']} "
                 f"({arc['window_ns']} ns)")
        if match is None:
            findings.append({
                "rule": "NSQ-1",
                "cell": arc["cell"],
                "constrained_pin": arc["constrained_pin"],
                "related_pin": arc["related_pin"],
                "timing_type": arc["timing_type"],
                "window_ns": arc["window_ns"],
                "liberty": arc.get("liberty"),
                "message": (
                    f"staged hard macro {ident} is declared in the macro's OWN "
                    f"Liberty ({arc.get('liberty')}) and is recorded in NO "
                    f"L-doc of this design, so it reaches nothing until "
                    f"post-CTS hold analysis. "
                    + _repair_sentence(arc, period)),
            })
            continue
        declared = _first_float(match, _ENTRY_VALUE_KEYS)
        win = arc.get("window_ns")
        if isinstance(win, float) and declared is not None and declared < win:
            findings.append({
                "rule": "NSQ-2",
                "cell": arc["cell"],
                "constrained_pin": arc["constrained_pin"],
                "related_pin": arc["related_pin"],
                "timing_type": arc["timing_type"],
                "window_ns": win,
                "recorded_ns": declared,
                "liberty": arc.get("liberty"),
                "message": (
                    f"staged hard macro {ident} is recorded with a window of "
                    f"{declared} ns — SMALLER than the {win} ns the macro's "
                    f"own Liberty declares. An integration built to the "
                    f"recorded number will still violate the macro's arc. "
                    + _repair_sentence(arc, period)),
            })
        elif declared is None:
            findings.append({
                "rule": "NSQ-2",
                "cell": arc["cell"],
                "constrained_pin": arc["constrained_pin"],
                "related_pin": arc["related_pin"],
                "timing_type": arc["timing_type"],
                "window_ns": win,
                "recorded_ns": None,
                "liberty": arc.get("liberty"),
                "message": (
                    f"staged hard macro {ident} is named in an L-doc record "
                    f"that carries NO numeric window, so the integration has "
                    f"nothing to build to. " + _repair_sentence(arc, period)),
            })

    report["findings"] = findings
    if not findings:
        report["verdict"] = "PASS"
        return "PASS", 0, report

    waived, why = _waived(project)
    if waived:
        report["verdict"] = "PASS_WITH_WAIVERS"
        report["waiver"] = why
        return "PASS_WITH_WAIVERS", 0, report
    report["verdict"] = "FAIL"
    return "FAIL", 1, report


def _emit(path: Optional[Path], report: Dict[str, object]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    except OSError:
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="staged-macro non-sequential timing-arc contract gate")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE_NAME}: not a directory: {project}")
        return 2

    verdict, rc, report = evaluate(project)
    _emit(args.json, report)

    if verdict == "SKIP":
        print(f"[SKIP] {GATE_NAME}: {report.get('reason')}")
        return rc
    findings = report.get("findings") or []
    if verdict == "PASS":
        print(f"[PASS] {GATE_NAME}: all "
              f"{len(report.get('arcs') or [])} non_seq_* arc(s) of "
              f"{report.get('in_scope_cells')} are recorded as structured "
              f"macro timing requirements in {report.get('contract_docs')}.")
        return rc
    head = "PASS_WITH_WAIVERS" if verdict == "PASS_WITH_WAIVERS" else "[FAIL]"
    print(f"{head} {GATE_NAME}: {len(findings)} staged-macro non-sequential "
          f"timing requirement(s) reach nothing before post-CTS "
          f"({report.get('scope_note')}; macro Liberties: "
          f"{report.get('macro_liberties')}).")
    for f in findings:                       # type: ignore[union-attr]
        print(f"  - {f['rule']}: {f['message']}")
    if verdict == "PASS_WITH_WAIVERS":
        print(f"  waiver `{WAIVER_KEY}` set: {str(report.get('waiver'))[:120]}")
        return rc
    print("  Fix: record each arc in the design's own L-doc layer (e.g. "
          "L9_INTEGRATION_SPEC.fields.macro_timing_requirements[] with "
          "macro / constrained_pin / related_pin / requirement_ns) so the "
          "integration has it as an INPUT, and build the integration to it — "
          f"or set waiver `{WAIVER_KEY}` (>={WAIVER_MIN} chars) to DISCLOSE "
          "that this design accepts the requirement unrecorded.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
