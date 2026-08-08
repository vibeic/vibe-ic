#!/usr/bin/env python3
"""
nvm_program_supply_intent.py — does a design that intends to PROGRAM an on-chip
non-volatile memory have a physical path to bring the programming supply IN?

The convention this encodes
---------------------------
Any field-programmable non-volatile memory (one-time-programmable, fuse-based,
multiple-time-programmable, antifuse — the whole family) separates two
operations with different electrical needs:

  * READ    — needs the core supply only. Ordinary digital access.
  * PROGRAM — needs a SEPARATE supply, EXTERNALLY sourced, at a voltage ABOVE
              the core supply, delivered through a DEDICATED terminal.

The programming supply cannot come from the core power grid: it is above the
core voltage, so nothing on-die produces it. It has to enter the die from
outside, through a package pin or a wafer-probe pad. This is not a vendor
option, it is what the storage mechanism physically requires — independently
observed on unrelated programmable-NVM IP families built on the same process,
one process-native and one third-party, both specifying the programming supply
as externally supplied and both above the core rail.

The defect
----------
A design instantiates a programmable NVM macro AND carries programming-control
logic in RTL (a program request, an address, data, a busy/done handshake). That
combination is a STATEMENT OF INTENT: this design means to burn the array at
some point. If the top level then exposes no terminal that can carry the
programming supply, the design cannot do the thing it says it does.

Nothing downstream notices. The digital logic is completely well-formed: it
simulates, it lints, it synthesises, it routes, it passes DRC and LVS. Every
gate in a digital flow is asking a question this defect does not answer to.
It surfaces at bring-up, on silicon, as an array that will not take a burn.

Relationship to #309 (hardmacro_supply_intent)
----------------------------------------------
#309 catches a LATER symptom: a macro PG pin that the power-intent layer does
not account for, gets tied in RTL, and aborts detailed routing. It asks
"is this macro pin claimed by a rail the design declares?".

This module asks the question BEFORE that one: "granted the design declares a
rail — is there a PIN that brings it in from outside?". A rail declared in the
power-intent layer with no terminal at the boundary is a supply that exists
only on paper. Same family of defect, one step earlier in the causal chain.

The two share the LEF grammar and the rail-name matcher rather than restating
them (see `_lef_pg_pins` / `_rail_token_match` below) — #309 landed with a bug
in exactly that matcher, and a second, drifting copy is how that bug would come
back.

chip-AGNOSTIC — what makes this decidable without any name literal
------------------------------------------------------------------
Pin names differ per vendor, so nothing here matches a supply pin by name.
The discriminator is STRUCTURAL and follows from the convention itself:

  A macro that must be programmed needs TWO distinct supply terminals — the
  read/core supply and the programming supply. So a macro whose own LEF
  declares >= 2 DISTINCT `USE POWER` pins is multi-supply by its own
  declaration.

A plain single-supply memory (an SRAM compiler instance, a regular hard macro)
declares exactly one `USE POWER`, and is therefore never considered here. The
LEF `USE POWER` record is the macro's own authoritative statement that a
terminal is a supply — the same record TritonRoute honours.

AND THE DISCRIMINATOR NEEDS THAT RECORD TO BE THERE (#785)
----------------------------------------------------------
Counting a record answers ZERO both when the macro has one supply and when the
abstract types no pin at all — and `magic`'s `lef write` emits the second. So
the count is taken over the macro's own Liberty `pg_pin` groups too, which
survive that write; a macro that resolves to two distinct supply terminals from
EITHER view runs the same pipeline. An abstract that types nothing and that no
Liberty view resolves is reported `inconclusive`, never as a single-supply
macro — see `untyped_abstracts` / `untyped_abstracts_unverifiable` in the
report.

Everything else is likewise the design's own input: which masters the input RTL
instantiates, which signals that RTL declares, and which names appear in the
design's own boundary inventory (RTL ports, pin table, pad list, top ports).

Classification, per (master, pin)
---------------------------------
  external_pin      a boundary terminal corresponds to this supply -> a path
                    exists
  declared_gap      an explicit L21 `hard_macro_supplies` entry marks it
                    `integration_gap: true` -> a known, OWNED gap is
                    disclosure, not silence (same escape hatch as #309, same
                    field, so the two cannot diverge)
  no_external_path  nothing at the boundary can carry it -> the gap

`no_external_path` is only ever reported for a macro that ALSO passed the
programming-intent test, because a multi-supply macro that the design never
intends to program is not a defect — it is a macro used read-only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── shared with #309: ONE LEF grammar, ONE rail-name matcher ────────────────
# Importing rather than restating is deliberate. #309 shipped with a matcher
# bug (it split rail names on the underscore, so `AVDD_REF` yielded the token
# `AVDD` and bound the wrong pin). A private copy here would have to be fixed
# twice, and a supply rule that mis-binds a terminal is worse than one that
# reports a gap.
from hardmacro_supply_intent import (  # noqa: E402
    lef_pg_pins as _lef_pg_pins,
    lef_untyped_masters as _lef_untyped_masters,
    project_liberty_pg_pins as _project_liberty_pg_pins,
    _rail_token_match,
    declared_rails,
    load_macro_lefs,
    load_l21,
)

# ── programming-intent vocabulary ───────────────────────────────────────────
# CLOSED and GENERIC. These are the words the discipline uses for the operation
# itself — they are not, and must never become, part numbers, process names or
# IP model names. The set is closed (not an open pattern) so that widening it
# is a reviewed edit rather than a silent behaviour change.
#
# The PROGRAM category is what makes the intent specific; the other three are
# the supporting signals any burn controller needs. A match in the PROGRAM
# category ALONE is not enough (a lone `otp_present` parameter states no
# intent) — see `program_control_evidence`.
_ROLE_TOKENS: Dict[str, frozenset] = {
    # the operation: burning charge / blowing a link / committing a fuse
    "program": frozenset({
        "prog", "program", "programming", "pgm", "burn", "blow", "fuse",
        "efuse", "otp", "mtp", "antifuse", "nvm",
    }),
    # where in the array
    "address": frozenset({"addr", "address", "adr"}),
    # what to put there
    "data": frozenset({"data", "din", "wdata", "dat", "payload"}),
    # the completion handshake a burn needs because it is not single-cycle
    "handshake": frozenset({
        "busy", "done", "ready", "rdy", "ack", "complete", "finished",
        "finish", "valid",
    }),
}

# A Verilog/SystemVerilog port declaration: direction, optional type/width,
# then the identifier. Structure only — captures the NAME, judges nothing.
_PORT_DECL_RE = re.compile(
    r"\b(?:input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned|tri))*"
    r"(?:\s*\[[^\]]*\])?"
    r"\s+([A-Za-z_]\w*)",
    re.IGNORECASE)

# Any declared identifier — ports, nets, registers. The programming-intent
# evidence may live on an internal net, not only on a port.
_DECL_RE = re.compile(
    r"\b(?:input|output|inout|wire|reg|logic)\b"
    r"(?:\s+(?:wire|reg|logic|bit|signed|unsigned|tri))*"
    r"(?:\s*\[[^\]]*\])?"
    r"\s+([A-Za-z_]\w*)",
    re.IGNORECASE)

_MODULE_DECL_RE = re.compile(r"^[ \t]*module\s+([A-Za-z_]\w*)", re.MULTILINE)

# §4.05 — never read an oracle / harness / golden segment. Reuse the existing
# definition rather than restating the directory list.
try:
    from reused_ip_rtl_consume import (  # noqa: E402
        _is_oracle_parts as _is_oracle_parts,
        _is_tb_file as _is_tb_file,
    )
except Exception:  # noqa: BLE001 — helper absent: fall back to a local copy
    _ORACLE_DIR_NAMES = frozenset({
        "tb", "test", "tests", "sim", "sims", "dv", "verif", "verification",
        "formal", "bench", "testbench", "testbenches", "gl", "gate", "gates",
        "netlist", "netlists", "golden", "ref", "reference", "sol", "solution",
        "solutions", "output", "outputs", "answer", "answers", "scoring",
    })

    def _is_oracle_parts(parts) -> bool:  # type: ignore[misc]
        return any(str(p).lower() in _ORACLE_DIR_NAMES for p in parts)

    def _is_tb_file(path: Path) -> bool:  # type: ignore[misc]
        return bool(re.search(r"(^tb[_.]|_tb$|_tb_|^test[_.]|_test$|_bench$)",
                              path.stem, re.IGNORECASE))

ACCOUNTED = frozenset({"external_pin", "declared_gap"})


# ── LEF side ────────────────────────────────────────────────────────────────

def multi_supply_macros(lef_texts: Iterable[str]) -> Dict[str, List[str]]:
    """`{master: [power_pin, ...]}` for every macro declaring >= 2 DISTINCT
    `USE POWER` pins in its own LEF.

    The threshold IS the convention: a memory that must be programmed needs a
    read supply and a programming supply, so it declares two supply terminals.
    A single-supply macro declares one and never reaches this module — which is
    what keeps an ordinary SRAM instance out of the finding set without any
    name-based exclusion list.

    GROUND pins are counted separately and never contribute: a second ground is
    a return path, not a second supply.
    """
    by_master: Dict[str, List[str]] = {}
    for txt in lef_texts or []:
        for p in _lef_pg_pins(txt):
            if p.get("use") != "POWER":
                continue
            pins = by_master.setdefault(p["master"], [])
            if p["pin"] not in pins:
                pins.append(p["pin"])
    return {m: pins for m, pins in by_master.items() if len(pins) >= 2}


def untyped_abstracts(lef_texts: Iterable[str]) -> Dict[str, List[str]]:
    """`{master: [pin, ...]}` for every hard macro whose abstract types NO pin.

    THE DISCRIMINATOR NEEDS A RECORD THAT MAY NOT BE THERE (vibe-ic#785)
    -------------------------------------------------------------------
    `multi_supply_macros` counts `USE POWER` records, so it answers ZERO for a
    macro whose abstract types nothing at all — and `assess` then reported
    `applicable: False` with the reason "no macro declares two or more distinct
    LEF `USE POWER` pins". That sentence is TRUE and its implication is FALSE:
    a macro whose abstract carries no `USE` record anywhere is not a macro that
    declared one supply, and `magic`'s `lef write` writes exactly that abstract.
    So a programmable NVM regenerated honestly became indistinguishable from an
    ordinary single-supply SRAM, and the check that exists to notice a missing
    programming supply went quiet on the file that lost the evidence.
    """
    out: Dict[str, List[str]] = {}
    for txt in lef_texts or []:
        for master, pins in _lef_untyped_masters(txt).items():
            bucket = out.setdefault(master, [])
            for p in pins:
                if p not in bucket:
                    bucket.append(p)
    return out


def recovered_supply_pins(untyped: Dict[str, List[str]],
                          project: Path) -> Dict[str, Dict[str, str]]:
    """`{master: {pin: USE}}` recovered from the macro's OWN Liberty view.

    `pg_pin` / `pg_type` survive a ``lef write`` that drops the LEF ``USE``
    records, so this is the design's own independent statement about the same
    macro. It is the ONLY recovery used here: the discriminator counts DISTINCT
    SUPPLY TERMINALS, so a source that cannot tell power from ground (rail
    name-equality) cannot answer this question, and guessing would put an
    ordinary memory into the finding set.
    """
    if not untyped:
        return {}
    try:
        lib = _project_liberty_pg_pins(project)
    except Exception:  # noqa: BLE001 - corroboration, never a verdict
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for master, pins in untyped.items():
        cell = lib.get(master) or {}
        got = {p: cell[p] for p in pins if cell.get(p) in ("POWER", "GROUND")}
        if got:
            out[master] = got
    return out


# ── RTL side (design INPUT only) ────────────────────────────────────────────

def input_rtl_files(project: Path) -> List[Path]:
    """Every Verilog/SystemVerilog source under `<project>/input/`, excluding
    testbenches, anything under an oracle/harness segment (§4.05), and a
    macro's OWN vendor-supplied view.

    Deliberately broader than the Phase-2 build-source resolver: this module
    only needs to know what the design DECLARES, and reading one extra
    non-oracle source can only make the boundary inventory larger — which makes
    a finding LESS likely, never more. Erring toward silence is the right
    direction for a gate that blocks.

    THE MACRO-STUB EXCLUSION IS NOT OPTIONAL (vibe-ic, this module's own
    circularity). `input/pdk_local/<vendor>/...` is the SAME handoff tree
    `load_macro_lefs` reads a macro's LEF from — it is the macro's own
    behavioural/stub Verilog view, shipped for simulation, not the chip's own
    top-level RTL. A vendor's behavioural model routinely types its own supply
    pins as ordinary `input`/`inout` ports (needed for testbench-style
    behavioural modelling of the supply-dependent logic, e.g. a pass-gate
    modelling the programming path) — the SAME pins this module exists to ask
    "does the TOP LEVEL expose a path for". Scanning that file for port names
    answers the question with the question: the macro's own declaration of
    its own pin was being read as proof the CHIP boundary carries it, which
    made `boundary_is_usable` self-corroborate on every macro whose vendor
    stub types its PG pins, and made `classify_pin` report `external_pin` for
    a supply the design's real top level never wires anywhere (MEASURED: a
    programmable-NVM macro whose digital top explicitly declines to connect
    its programming-supply pin, by design, still classified `external_pin`
    with zero gaps, because that pin's OWN name appeared in the macro's own
    ``module NAME(...)`` port list one directory below).
    """
    root = project / "input"
    if not root.is_dir():
        return []
    out: List[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".v", ".sv"):
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if _is_oracle_parts(rel.parts) or _is_tb_file(p):
            continue
        if rel.parts and rel.parts[0] == "pdk_local":
            continue
        out.append(p)
    return out


def _read(paths: Iterable[Path]) -> List[str]:
    out = []
    for p in paths:
        try:
            out.append(p.read_text(errors="replace"))
        except OSError:
            pass
    return out


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


def _name_tokens(name: str) -> Set[str]:
    """Split an identifier into lower-case word tokens.

    Splits on the underscore, on camelCase humps, and on digit boundaries, so
    `otp_prog_addr`, `otpProgAddr` and `prog0addr` all yield the same tokens.
    Matching is on WHOLE tokens: `progress` never matches `prog`, and a net
    called `data_valid` contributes `data` and `valid` but never `dat`.
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {t for t in re.split(r"[^A-Za-z]+", s.lower()) if t}


def instantiated_masters(rtl_texts: Iterable[str],
                         masters: Iterable[str]) -> Set[str]:
    """Which of `masters` the input RTL INSTANTIATES.

    A macro that ships in the PDK directory but is never instantiated is not
    part of this design. The macro's own Verilog stub (`module <master> (...)`)
    is a declaration, not an instantiation, and is excluded — otherwise every
    macro whose stub ships alongside its LEF would look instantiated.
    """
    hits: Set[str] = set()
    blobs = [_strip_comments(t) for t in rtl_texts or []]
    for m in masters:
        if not m:
            continue
        # `<master> [#(params)] <instance_name> (`  — the instantiation shape.
        inst = re.compile(
            r"(?<![\w.])" + re.escape(m) + r"\s*"
            r"(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?"
            r"[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?\(")
        decl = re.compile(r"\bmodule\s+" + re.escape(m) + r"\b")
        for blob in blobs:
            for match in inst.finditer(blob):
                head = blob[max(0, match.start() - 40):match.start()]
                if re.search(r"\bmodule\s*$", head):
                    continue
                if decl.search(blob[max(0, match.start() - 8):match.start()
                                    + len(m) + 8]):
                    continue
                hits.add(m)
                break
            if m in hits:
                break
    return hits


def program_control_evidence(rtl_texts: Iterable[str]) -> Dict[str, Any]:
    """Does the input RTL carry PROGRAMMING-control logic?

    Returns `{"intends_to_program": bool, "roles": {role: [signal, ...]}}`.

    True requires BOTH:
      * at least one declared signal in the PROGRAM category — the operation
        is named somewhere in the design's own RTL, and
      * at least one OTHER role category (address / data / handshake).

    The second condition is what separates INTENT from MENTION. A design that
    merely instantiates a macro whose name contains `otp` has one PROGRAM-token
    signal and nothing else; a design that means to burn the array has to move
    an address and data and wait for a busy/done, because a burn is not a
    single-cycle write. Requiring the supporting signals is what keeps a
    read-only user of a programmable macro out of the finding set.
    """
    roles: Dict[str, List[str]] = {k: [] for k in _ROLE_TOKENS}
    seen: Set[str] = set()
    for txt in rtl_texts or []:
        body = _strip_comments(txt)
        for m in _DECL_RE.finditer(body):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            toks = _name_tokens(name)
            for role, vocab in _ROLE_TOKENS.items():
                if toks & vocab:
                    roles[role].append(name)
    present = {r for r, v in roles.items() if v}
    intends = "program" in present and len(present) >= 2
    return {
        "intends_to_program": intends,
        "roles": {r: sorted(v)[:12] for r, v in roles.items() if v},
        "role_categories": sorted(present),
    }


# ── boundary side: what terminals does the design say it has? ───────────────

def _l_doc(project: Path, stem: str) -> Dict[str, Any]:
    for rel in (Path("phase1") / "generated_docs", Path("generated_docs"),
                Path("input") / "generated_docs"):
        p = project / rel / f"{stem}.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(errors="replace"))
            except (OSError, ValueError):
                return {}
    return {}


def _harvest_names(node: Any, keys: Iterable[str], out: List[str]) -> None:
    """Collect string values stored under any of `keys`, at any depth.

    Pin/pad tables are shaped differently per layer and per extractor (a list of
    dicts, a dict keyed by pin name, a nested `dtop_top_level.ports`). Walking
    for the KEY rather than assuming one shape is what keeps this from silently
    reading an empty inventory — and an empty inventory is precisely what would
    manufacture a false finding.
    """
    kset = {k.lower() for k in keys}
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.lower() in kset and isinstance(v, str):
                out.append(v)
            else:
                _harvest_names(v, kset, out)
    elif isinstance(node, list):
        for it in node:
            _harvest_names(it, kset, out)


def _pin_container_names(node: Any, out: List[str]) -> None:
    """Names of a pin/pad container that is keyed BY the pin name.

    `L1.pinout` is commonly `{"VDD": {...}, "SCL": {...}}` — the terminal name
    is the KEY, not a value under a `name` field. Reading only `name`-style
    values would miss the entire package pinout of any design that uses this
    (very common) shape and report a gap the design does not have.

    Only the container's OWN keys count. Recursing would harvest the per-pin
    ATTRIBUTE names (`type`, `direction`, `description`) as if they were
    terminals — junk that can only ever mask a real gap by accidentally
    matching a supply pin name.
    """
    if isinstance(node, dict):
        out.extend(k for k in node if isinstance(k, str) and k)


_PIN_NAME_KEYS = ("name", "pin", "pin_name", "port", "port_name", "signal",
                  "pad", "pad_name", "net", "terminal")

# Where a design states the terminals it physically has. Every one of these is
# a place the fleet's own designs already populate; the union is taken so a
# design that records its boundary in ANY of them is credited.
_BOUNDARY_SOURCES = (
    ("L1_DATASHEET", ("pinout", "pin_table", "pins", "pads", "package_pins")),
    ("L5_ADI_SPEC", ("pads", "pad_ring", "pin_table")),
    ("L9_INTEGRATION_SPEC", ("top_level_ports", "top_ports", "ports",
                             "top_module_pins")),
    ("L21_POWER_INTENT", ("supply_pins", "external_supplies", "pads")),
    ("L7_TEST_DEBUG", ("probe_pads", "test_pads", "pads")),
)


def boundary_entry_points(project: Path,
                          rtl_texts: Optional[Iterable[str]] = None
                          ) -> Dict[str, Any]:
    """Every terminal name the design claims at its own boundary.

    Union of (a) every port declared in the design's input RTL and (b) the
    pin / pad / port inventories in the design's own L-docs. The union is
    deliberate: a supply that appears in ANY of these has SOME stated path in,
    and this module only reports the case where it appears in NONE of them.
    """
    names: List[str] = []
    sources: Dict[str, int] = {}

    rtl_texts = list(rtl_texts) if rtl_texts is not None else \
        _read(input_rtl_files(project))
    n0 = 0
    for txt in rtl_texts:
        for m in _PORT_DECL_RE.finditer(_strip_comments(txt)):
            names.append(m.group(1))
            n0 += 1
    if n0:
        sources["input_rtl_ports"] = n0

    for stem, keys in _BOUNDARY_SOURCES:
        doc = _l_doc(project, stem)
        if not doc:
            continue
        fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
        got: List[str] = []
        for key in keys:
            node = None
            if isinstance(fields, dict) and key in fields:
                node = fields[key]
            elif isinstance(doc, dict) and key in doc:
                node = doc[key]
            if node is None:
                continue
            _harvest_names(node, _PIN_NAME_KEYS, got)
            _pin_container_names(node, got)
        # `dtop_top_level.ports` — the schema-v1 shape of the top port list.
        dtop = (fields or {}).get("dtop_top_level") if isinstance(fields, dict) else None
        if isinstance(dtop, dict) and dtop.get("ports") is not None:
            _harvest_names(dtop["ports"], _PIN_NAME_KEYS, got)
            _pin_container_names(dtop["ports"], got)
        if got:
            sources[stem] = len(got)
            names.extend(got)

    uniq = sorted({n.strip() for n in names if isinstance(n, str) and n.strip()})
    return {"names": uniq, "sources": sources}


# ── the decision ────────────────────────────────────────────────────────────

def _declared_gap(l21: Dict[str, Any], master: str, pin: str) -> bool:
    """#309's escape hatch, read from #309's field. A known, OWNED gap is
    disclosure. Sharing the field means a design that discloses once is
    disclosed to both gates, and neither can drift from the other."""
    f = (l21 or {}).get("fields") or {}
    for m in (f.get("hard_macro_supplies") or []):
        if not isinstance(m, dict):
            continue
        if (str(m.get("master", "")).strip() == master.strip()
                and str(m.get("pin", "")).strip() == pin.strip()
                and m.get("integration_gap") is True):
            return True
    return False


def classify_pin(master: str, pin: str, boundary: List[str],
                 l21: Dict[str, Any]) -> Dict[str, Any]:
    """Classify ONE supply pin of a programmable macro against the boundary."""
    if _declared_gap(l21, master, pin):
        return {"master": master, "pin": pin, "status": "declared_gap",
                "detail": "declared as a known integration gap in "
                          "L21.fields.hard_macro_supplies"}
    hit = _rail_token_match(pin, boundary)
    if hit:
        return {"master": master, "pin": pin, "status": "external_pin",
                "terminal": hit,
                "detail": f"boundary terminal {hit!r} corresponds to this pin"}
    return {"master": master, "pin": pin, "status": "no_external_path",
            "detail": ("no port, pin-table entry, pad or probe pad at the "
                       "design's own boundary corresponds to this supply")}


def _all_pg_pins(lef_texts: Iterable[str], masters: Set[str],
                 recovered: Optional[Dict[str, Dict[str, str]]] = None
                 ) -> List[Dict[str, str]]:
    """Every PG pin (POWER *and* GROUND) of the given masters.

    `recovered` carries the pins whose supply role came from the macro's own
    Liberty view because its abstract types nothing. They belong here for the
    same reason they belong in the finding set: `boundary_is_usable` asks
    whether ANY of the macro's supply terminals is recorded at the boundary, and
    a terminal is no less real for having been read out of the Liberty instead
    of the LEF. Omitting them would make every recovered macro report
    `inconclusive` on an inventory that in fact answers.
    """
    out: List[Dict[str, str]] = []
    for txt in lef_texts or []:
        for p in _lef_pg_pins(txt):
            if p["master"] in masters:
                out.append(p)
    for master, pins in (recovered or {}).items():
        if master not in masters:
            continue
        for pin, use in sorted(pins.items()):
            out.append({"master": master, "pin": pin, "use": use})
    return out


def boundary_is_usable(pg_pins: List[Dict[str, str]],
                       boundary: List[str]) -> Dict[str, Any]:
    """Can the design's boundary inventory be trusted to answer the question?

    Yes iff at least ONE of the instantiated macro's own supply/ground pins
    already corresponds to a boundary terminal. That single corroborating hit
    proves the design DOES record supply terminals at its boundary — so a
    supply that is absent from it is genuinely absent, not merely unrecorded.

    Without this guard the check would accuse every design whose pinout has not
    been extracted yet, which is a different defect with a different owner. The
    distinction is reported, never swallowed: an unusable inventory produces
    its own named, printed finding rather than a quiet pass.
    """
    corroborating = []
    for p in pg_pins:
        hit = _rail_token_match(p["pin"], boundary)
        if hit:
            corroborating.append({"pin": p["pin"], "use": p["use"],
                                  "terminal": hit})
    return {"usable": bool(corroborating), "corroborating": corroborating}


def assess(project: Path) -> Dict[str, Any]:
    """Full assessment for one project. Reads design INPUT plus the design's
    own L-doc boundary inventory; never an oracle or a golden artefact."""
    lefs = load_macro_lefs(project)
    macros = multi_supply_macros(lefs)

    # ---- an abstract that types nothing counts NOTHING (#785) ------------- #
    # `multi_supply_macros` can only count `USE POWER` records, so a macro whose
    # abstract types no pin at all answers ZERO — the same answer a genuinely
    # single-supply memory gives. Recover the typing from the macro's OWN
    # Liberty view, which survives a `lef write`; a macro that then shows two or
    # more distinct supply terminals is multi-supply on the design's own
    # evidence and runs the SAME pipeline as a LEF-typed one.
    untyped = {m: p for m, p in untyped_abstracts(lefs).items()
               if m not in macros}
    recovered = recovered_supply_pins(untyped, project)
    recovered_multi: Dict[str, List[str]] = {}
    for master, pins in recovered.items():
        pwr = sorted(p for p, u in pins.items() if u == "POWER")
        if len(pwr) >= 2:
            recovered_multi[master] = pwr
    macros = {**macros, **recovered_multi}
    # An abstract that types nothing AND that no Liberty view resolves cannot be
    # placed on either side of the discriminator.
    unverifiable = sorted(m for m in untyped if m not in recovered)

    rep: Dict[str, Any] = {
        "multi_supply_macros": {m: pins for m, pins in macros.items()},
        "instantiated": [],
        "program_intent": {"intends_to_program": False, "roles": {},
                           "role_categories": []},
        "boundary": {"names": [], "sources": {}},
        "boundary_usable": {"usable": False, "corroborating": []},
        "pins": [],
        "gaps": [],
        "applicable": False,
        "inconclusive": False,
        "reason": "",
        "untyped_abstracts": {m: untyped[m] for m in sorted(untyped)},
        "recovered_supply_pins": {m: recovered[m] for m in sorted(recovered)},
        "untyped_abstracts_unverifiable": unverifiable,
    }
    if not macros:
        if unverifiable:
            # NOT `applicable: False` with a single-supply reason. The
            # discriminator did not answer "one supply" — it could not read the
            # record it counts, in a file that exists.
            rep["inconclusive"] = True
            rep["reason"] = (
                f"{len(unverifiable)} staged hard macro(s) "
                f"({', '.join(unverifiable[:6])}) type NO pin with a `USE` "
                "record at all, and no Liberty `pg_pin` is staged beside the "
                "abstract to recover it from — so the multi-supply "
                "discriminator this check rests on cannot be evaluated. "
                "`magic`'s `lef write` emits neither `DIRECTION` nor `USE` on "
                "any PIN, so this is what an HONESTLY regenerated abstract "
                "looks like, and it is a different fact from a macro that "
                "declares a single supply. Reported, not decided: re-attach "
                "the typing to the abstract or stage the macro's Liberty view "
                "beside it")
            return rep
        rep["reason"] = (
            "no macro under input/pdk_local/ declares two or more distinct "
            "LEF `USE POWER` pins — no programmable-NVM supply question to ask"
            if lefs else
            "no macro LEF under input/pdk_local/ — nothing to assess")
        return rep

    rtl_texts = _read(input_rtl_files(project))
    inst = instantiated_masters(rtl_texts, macros.keys())
    rep["instantiated"] = sorted(inst)
    if not inst:
        rep["reason"] = (
            "a multi-supply macro is present but the design's input RTL "
            "instantiates none of them — not part of this design")
        return rep

    intent = program_control_evidence(rtl_texts)
    rep["program_intent"] = intent
    if not intent["intends_to_program"]:
        rep["reason"] = (
            "a multi-supply macro is instantiated but the input RTL carries "
            "no programming-control logic (needs a PROGRAM-category signal "
            "plus at least one of address / data / handshake) — the macro is "
            "used read-only, which needs no programming supply")
        return rep

    boundary = boundary_entry_points(project, rtl_texts)
    rep["boundary"] = boundary
    l21 = load_l21(project)
    rep["declared_rails"] = declared_rails(l21)

    usable = boundary_is_usable(_all_pg_pins(lefs, inst, recovered),
                                boundary["names"])
    rep["boundary_usable"] = usable
    if not usable["usable"]:
        rep["inconclusive"] = True
        rep["reason"] = (
            "a programmable-NVM macro is instantiated with programming-control "
            "logic, but NOT ONE of its supply or ground pins corresponds to "
            "anything in the design's boundary inventory — so the inventory "
            "records no supply terminals at all and cannot answer whether the "
            "programming supply is among them. Reported, not decided: this is "
            "a missing pinout, which is a different defect with a different "
            "owner")
        return rep

    rep["applicable"] = True
    rep["reason"] = (
        "a programmable-NVM macro is instantiated and the RTL carries "
        "programming-control logic — every supply the macro declares needs a "
        "path in from outside")

    pins: List[Dict[str, Any]] = []
    for master in sorted(inst):
        for pin in macros[master]:
            pins.append(classify_pin(master, pin, boundary["names"], l21))
    rep["pins"] = pins
    rep["gaps"] = [p for p in pins if p["status"] not in ACCOUNTED]
    return rep
