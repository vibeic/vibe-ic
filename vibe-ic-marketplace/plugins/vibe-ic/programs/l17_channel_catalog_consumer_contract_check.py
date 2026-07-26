#!/usr/bin/env python3
"""l17_channel_catalog_consumer_contract_check.py — SEMANTIC gate for L17.

VERDICT MODE: **ADVISES**. The process exit code is unchanged — exit 1 on an
ERROR finding, `--advisory` downgrades it — but the mode this program DECLARES
about itself, which `flow_gate_enforcement_audit.py` reads and which decides
where the flow may wire it, is ADVISES.

ENFORCEMENT — WHY THE DECLARATION CHANGED (vibe-ic#316)
--------------------------------------------------------
It said BLOCKS, and nothing wired it anywhere. `flow_gate_enforcement_audit`
recorded it as an ORPHAN: a gate declaring an intent it could not act on
because it never ran at all. It was held out of the flow's advisory slot
PRECISELY because it said BLOCKS — so the over-claim was what kept it from
executing. #316 also warned that registering it blocking would fail 100% of
runs.

Measured before changing this, over the twelve cells published under
`benchmark-data/ic/`: rc=1 on eleven, SKIP on the twelfth. The findings are
TRUE — a catalog reporting `extraction_status=EXTRACTION_FOUND_NOTHING` with
zero channels while carrying a populated narrative field whose identifier
tokens resolve nowhere in that design is exactly the template leak described
below. But it is ONE producer-side defect reproduced across the corpus, not
eleven independent design errors, and a gate that fails every run gets turned
off within a week. ADVISES is what it does; wired into the flow's advisory
slot it now judges every real project instead of nothing.

Promotion to BLOCKS is a one-line change once the producer stops stamping
unextracted narrative into this layer — argue it from a re-measurement of the
same corpus, not from this docstring.

WHY IT MATTERS
--------------
L17 is not a documentation layer — it is the FIRST source of the emitted top
module's PORT LIST. `phase2_scaffold_gen.derive_signals(l17, l9)` reads
`L17.channels[]` and `L17.global_signals[]` ahead of L9, and the cocotb scaffold
decides "clocked vs combinational" from whatever that derivation returns
("No clock port detected in L17/L9; combinational or ..."). A wrong or empty
L17 therefore silently produces a wrong module interface — the failure surfaces
five steps downstream as a port mismatch or an unclocked testbench, with an
opaque error. That is precisely the L21_POWER_INTENT failure mode this gate
family exists to prevent, so it must be able to stop the flow.

THE PRINCIPLE THIS GATE ENCODES
-------------------------------
  A layer is complete when the requirement is present IN THE LAYER THAT
  CONSUMES IT, in an actionable form — not when a token appears somewhere.

So this gate does not count tokens and does not test "is the file non-empty".
It **runs the consumer's own derivation** (it imports
`phase2_scaffold_gen.derive_signals` / `_is_clock_name` / `_sanitize_id`) and
asserts the derived artefact is usable. What the consumer silently drops, this
gate reports.

WHAT IT CATCHES
---------------
E1 TEMPLATE_WITHOUT_EXTRACTION
    The layer's own `extraction_status` says the extractor found NOTHING in the
    design's source, the catalog declares zero channels and zero global signals
    — yet narrative fields (`dependency_graph`, `handshake_pairs`,
    `typical_topologies`, `channel_counts`) are populated. Content that the
    producer says it did not extract cannot have come from this design; it is a
    template leaking in from an unrelated protocol. This is the exact
    "file reports non-empty fields so every presence heuristic reads it as
    populated" shape — a false CAPTURED.
    Verdict is derived from the producer's OWN machine-emitted status field,
    never from prose matching, so no protocol/vendor/design literal is involved.

E2 NARRATIVE_NAMES_UNDECLARED_SIGNAL
    `handshake_pairs` (a STRUCTURED field: {ch: {valid: <sig>, ready: <sig>}})
    names a signal that appears nowhere in this design's own declared entity
    universe (L17 channels/signals/globals + L9 ports/wires + L1 pins + L4
    registers + L8 parameters, all read from the run's own L-docs). A handshake
    over a signal the design does not have is a non-fact.

E3 CHANNEL_NOT_PORT_DERIVABLE
    A declared channel either carries no name with identifier content (so
    `_sanitize_id` substitutes a placeholder and the top module gains a port
    the design never declared) or contributes ZERO ports when the real
    consumer derivation runs over it. Detected by diffing the consumer's own
    output, not by re-implementing its rules.

E3b CHANNEL_GROUP_COLLAPSED_TO_ONE_PORT
    A channel declares N member signals but contributes ONE port under the
    consumer's own derivation, because `derive_signals` reads
    `channels[].name` and never expands `channels[].signals[]`. A catalog whose
    channels are GROUPS (the shape the Phase-1 extractor emits: one entry per
    channel group carrying its member rows) therefore emits the GROUP name as a
    single port and drops every member. The declared interface silently
    shrinks from N signals to 1.

E3c PORT_WIDTH_COLLAPSED_TO_ONE_BIT
    A port is emitted as a 1-bit scalar while the L9 entry it comes from
    carries a SYMBOLIC width (`width_symbolic: "ACC_W-1:0"`) or a non-numeric
    `width` string. `derive_signals` coerces any width that is neither an int
    nor a digit-string to 1 with NO diagnostic, so the emitted interface is
    narrower than the design declares. The value is not missing: L1 keeps the
    textual form on purpose "so downstream consumers can resolve at
    elaboration time", phase1 forwards it into L9, and the consumer discards
    it. REPORTS ONLY — #404 measured that resolving the symbol and writing it
    back into an L-doc turns a correct FAIL into a PASS, because
    `parameters[]` carries no module/layer qualifier and a bare-name join let
    an L12 scan-chain count size a data bus.

E3d PORT_WIDTH_SYMBOL_UNCORROBORATED
    The same layer condition as E3c — the L9 entry declares a SYMBOLIC or
    non-numeric width — but the consumer emitted a CONCRETE bit count instead
    of collapsing to 1. Something resolved the symbol, and the only evidence
    for the number is the step that produced it.
    THIS RAIL IS WHY E3c KEYS ON THE LAYER AND NOT ON THE NUMBER. #404's own
    proposed next increment (resolve in the consumer, scoped to one document)
    was measured to make E3c go silent — and to go equally silent when the
    parameter it joined against contradicted the port's own stated width, so
    a wrong resolution was indistinguishable from a right one. Keying the
    rail on `width == 1` would have handed a future resolver a green gate.
    Keying it on the layer's declaration and branching on the outcome means a
    repair can change WHICH finding is reported and can never remove it.

E4 CHANNEL_DIRECTION_SILENTLY_INOUT
    A declared channel yields a port whose direction the consumer had to guess
    because the channel carries no key the consumer reads. `derive_signals`
    reads `direction_master` / `direction`; `_normalize_dir(None)` returns
    "inout". A top-level port silently typed `inout` is a real interface defect
    (it is also how a SIGNAL net ends up on a wrongly-typed terminal).

E5 CLOCK_PORT_SYNTHESISED_BY_CONSUMER
    The design's own L-docs declare it sequential (`clock_domains`, `clocks`, a
    clock period, or an FSM / pipeline), but NEITHER L17 nor L9 declares a
    clock PORT, so `derive_signals` invents a "clk" stub to fill the hole and
    the emitted top-module interface no longer matches the design.
    NOTE ON WHY IT IS PHRASED THIS WAY: `derive_signals` ALWAYS auto-adds a
    clk/rst stub, so the obvious test — "did a clock port come out?" — can
    never fail. This rail instead asks whether the clock the consumer emitted
    was DECLARED by the layers it reads. Requirement present in some layer,
    absent from the layer that consumes it.

W1 CHANNEL_PURPOSE_MISSING / W2 NO_EXTRACTION_EVIDENCE — advisory only.

GENERALITY / NO-CHEATING STATEMENT
----------------------------------
No design name, PDK name, vendor part number, protocol name, or pin/signal
literal appears in this file. Every expectation is derived from:
  * the run's own L-doc JSON (entity universe, sequential-vs-combinational),
  * the producer's own machine-emitted `extraction_status`,
  * the CONSUMER's own imported functions (`derive_signals`, `_is_clock_name`,
    `_sanitize_id`).
Grep this file for any protocol/bus/signal name: there is none.

SINGLE TRACK, HONESTLY DECLARED
-------------------------------
This gate has ONE deterministic track. It claims no AI second track, so there
is no dual-track that can silently degenerate into one track contributing zero
(the `ai_captured_tokens_count: 0` failure).

USAGE
    python3 l17_channel_catalog_consumer_contract_check.py <project> [--json OUT]
                                                           [--advisory]

EXIT CODES
    0 = pass (or --advisory)
    1 = at least one ERROR finding — BLOCKING
    2 = not applicable / unreadable (no phase1/generated_docs, no L17 doc,
        unparseable JSON)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# Consumer import — the gate asserts against the CONSUMER'S OWN derivation.
# ---------------------------------------------------------------------------
_CONSUMER_IMPORT_ERROR: Optional[str] = None
try:  # pragma: no cover - exercised implicitly by every run
    import phase2_scaffold_gen as _consumer  # noqa: E402
except Exception as exc:  # pragma: no cover
    _consumer = None
    _CONSUMER_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def _c_derive_signals(l17: dict, l9: dict) -> List[dict]:
    if _consumer is not None:
        return list(_consumer.derive_signals(l17, l9))
    return []


def _c_is_clock_name(n: str) -> bool:
    if _consumer is not None:
        return bool(_consumer._is_clock_name(n))
    n = (n or "").lower()
    return "clk" in n or "clock" in n


def _c_sanitize_id(s: str) -> str:
    if _consumer is not None:
        return str(_consumer._sanitize_id(s))
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", (s or "").strip())).rstrip("_")


# ---------------------------------------------------------------------------
# Status vocabulary. These are PRODUCER status tokens, not design literals.
# ---------------------------------------------------------------------------
_STATUS_FOUND_NOTHING = {
    "EXTRACTION_FOUND_NOTHING", "FOUND_NOTHING", "NOT_FOUND", "NOTHING_FOUND",
    "EMPTY", "NONE", "NOT_APPLICABLE", "N/A", "NA", "SKIPPED", "ABSENT",
    "NO_CONTENT", "NOT_PRESENT",
}
_STATUS_SUCCESS = {
    "EXTRACTED", "CAPTURED", "OK", "COMPLETE", "PRESENT", "SUCCESS", "DONE",
}

# Narrative fields of L17 — content that ASSERTS facts but carries no ports.
_NARRATIVE_KEYS = ("dependency_graph", "handshake_pairs", "typical_topologies",
                   "channel_counts", "ordering_rules", "protocol_notes")

# Keys anywhere in an L-doc whose STRING value names a design entity.
_ENTITY_NAME_KEYS = {
    "name", "signal", "signal_name", "pin", "pin_name", "port", "port_name",
    "net", "net_name", "wire", "wire_name", "mnemonic", "register",
    "reg_name", "field_name", "identifier", "source_pin", "top_module",
    "instance", "instance_name", "module",
}
# Keys whose value may be a bare list of entity-name strings.
_ENTITY_LIST_KEYS = {
    "ports", "pins", "signals", "top_ports", "top_level_ports", "dtop_ports",
    "top_module_pins", "internal_wires", "nets", "clocks", "resets",
    "clock_domains", "reset_domains", "parameters",
}

_TOKEN_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{1,63}$")


@dataclass
class Finding:
    severity: str          # ERROR | WARNING | INFO
    category: str
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generic L-doc helpers
# ---------------------------------------------------------------------------
def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(errors="ignore"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _unwrap(d: Optional[dict]) -> dict:
    if not isinstance(d, dict):
        return {}
    if isinstance(d.get("fields"), dict):
        merged = dict(d)
        merged.update(d["fields"])
        return merged
    return d


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _norm(tok: str) -> str:
    """Normalize an entity name for comparison: strip bus range, lowercase."""
    tok = re.sub(r"\[[^\]]*\]", "", str(tok or "")).strip()
    tok = tok.strip("`'\"*_ \t")
    return tok.lower()


def _collect_entity_names(node: Any, out: Set[str], depth: int = 0) -> None:
    """Recursively harvest entity-name-shaped strings from an L-doc."""
    if depth > 12:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            lk = str(k).lower()
            if isinstance(v, str):
                if lk in _ENTITY_NAME_KEYS and _TOKEN_SHAPE.match(v.strip()):
                    n = _norm(v)
                    if len(n) >= 2:
                        out.add(n)
            elif isinstance(v, list) and lk in _ENTITY_LIST_KEYS:
                for it in v:
                    if isinstance(it, str) and _TOKEN_SHAPE.match(it.strip()):
                        n = _norm(it)
                        if len(n) >= 2:
                            out.add(n)
            _collect_entity_names(v, out, depth + 1)
    elif isinstance(node, list):
        for it in node:
            _collect_entity_names(it, out, depth + 1)


def build_entity_universe(gd: Path, exclude: Set[str]) -> Set[str]:
    """Union of every entity name this design declares in its OWN L-docs.

    `exclude` holds file names to leave out (always the doc under test, so a
    layer can never self-corroborate its own claims)."""
    universe: Set[str] = set()
    for p in sorted(gd.glob("L*.json")):
        if p.name in exclude:
            continue
        d = _read_json(p)
        if d is None:
            continue
        _collect_entity_names(d, universe)
    return universe


def _resolves(tok: str, universe: Set[str]) -> bool:
    n = _norm(tok)
    if len(n) < 2:
        return False
    return n in universe


# ---------------------------------------------------------------------------
# Sequential-vs-combinational, derived from the design's OWN L-docs
# ---------------------------------------------------------------------------
def design_is_clocked(gd: Path) -> Tuple[bool, List[str]]:
    """True when the run's own L-docs declare a clock domain / clocked element.

    Sources (all the design's own declarations, no name heuristics on the
    design itself):
      * any L-doc's non-empty `clock_domains` / `clocks`
      * any L-doc's non-empty `fsm_states` / `pipeline_stages`
      * an L-doc clock frequency/period field with a real value
    """
    reasons: List[str] = []
    for p in sorted(gd.glob("L*.json")):
        d = _unwrap(_read_json(p))
        if not d:
            continue
        for key in ("clock_domains", "clocks", "fsm_states", "pipeline_stages"):
            if _as_list(d.get(key)):
                reasons.append(f"{p.name}.{key}[{len(_as_list(d.get(key)))}]")
        for key in ("clock_mhz", "clock_frequency_hz", "clock_period_ns",
                    "frequency_mhz"):
            v = d.get(key)
            if isinstance(v, (int, float)) and v > 0:
                reasons.append(f"{p.name}.{key}={v}")
    return (bool(reasons), reasons)


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------
L17_GLOB = "L17_*.json"


def audit(project: Path) -> Tuple[List[Finding], Dict[str, Any]]:
    findings: List[Finding] = []
    info: Dict[str, Any] = {}

    gd = project / "phase1" / "generated_docs"
    if not gd.is_dir():
        findings.append(Finding("SKIP", "NO_GENERATED_DOCS",
                                f"{gd} does not exist"))
        return findings, info

    l17_files = sorted(gd.glob(L17_GLOB))
    if not l17_files:
        findings.append(Finding("SKIP", "NO_L17_DOC",
                                "no L17_*.json in generated_docs"))
        return findings, info
    l17_path = l17_files[0]
    raw17 = _read_json(l17_path)
    if raw17 is None:
        findings.append(Finding("SKIP", "INVALID_JSON",
                                f"{l17_path.name} is not readable JSON"))
        return findings, info

    l17 = _unwrap(raw17)
    l9 = _unwrap(_read_json(gd / "L9_INTEGRATION_SPEC.json"))
    status = str(raw17.get("extraction_status")
                 or l17.get("extraction_status")
                 or raw17.get("status") or "").strip().upper()

    channels = _as_list(l17.get("channels"))
    globals_ = _as_list(l17.get("global_signals"))
    info.update({
        "l17_file": l17_path.name,
        "extraction_status": status or None,
        "channels_declared": len(channels),
        "global_signals_declared": len(globals_),
        "consumer_import": ("phase2_scaffold_gen"
                            if _consumer is not None
                            else f"UNAVAILABLE ({_CONSUMER_IMPORT_ERROR})"),
    })

    universe = build_entity_universe(gd, exclude={l17_path.name})
    info["entity_universe_size"] = len(universe)

    # -- E1 TEMPLATE_WITHOUT_EXTRACTION ------------------------------------
    narrative_populated: Dict[str, Any] = {}
    for key in _NARRATIVE_KEYS:
        v = l17.get(key)
        if isinstance(v, dict) and v:
            # channel_counts is pure arithmetic over channels[]; it is only a
            # claim when it asserts a NON-ZERO count with no channels.
            if key == "channel_counts":
                nz = {k: x for k, x in v.items()
                      if isinstance(x, (int, float)) and x}
                if nz:
                    narrative_populated[key] = nz
                continue
            narrative_populated[key] = v
        elif isinstance(v, list) and v:
            narrative_populated[key] = v
    info["narrative_fields_populated"] = sorted(narrative_populated)

    if (status in _STATUS_FOUND_NOTHING and not channels and not globals_
            and narrative_populated):
        # Evidence: which named tokens does the narrative assert, and do any
        # of them resolve in the design's own entity universe?
        toks = _identifier_tokens(narrative_populated)
        resolved = sorted(t for t in toks if _resolves(t, universe))
        findings.append(Finding(
            "ERROR", "TEMPLATE_WITHOUT_EXTRACTION",
            f"L17 extraction_status={status!r} (the producer says it extracted "
            f"nothing from this design's source) and the catalog declares 0 "
            f"channels / 0 global signals, yet "
            f"{sorted(narrative_populated)} carry assertions about this "
            f"design. Content the producer did not extract cannot describe "
            f"this design — it is template content leaking in from an "
            f"unrelated protocol, and any presence/non-empty heuristic will "
            f"read this layer as POPULATED.",
            {"populated_fields": sorted(narrative_populated),
             "identifier_tokens_asserted": sorted(toks)[:40],
             "tokens_that_resolve_in_design": resolved,
             "sample": {k: narrative_populated[k]
                        for k in sorted(narrative_populated)[:2]}}))

    # -- E2 NARRATIVE_NAMES_UNDECLARED_SIGNAL ------------------------------
    # handshake_pairs is STRUCTURED: {ch: {valid: <sig>, ready: <sig>}}. Every
    # signal it names must exist in the design's own entity universe.
    hp = _as_dict(l17.get("handshake_pairs"))
    undeclared: List[str] = []
    for ch, pair in hp.items():
        for role, sig in _as_dict(pair).items():
            if isinstance(sig, str) and sig.strip():
                if not _resolves(sig, universe) and not _l17_declares(l17, sig):
                    undeclared.append(f"{ch}.{role}={sig}")
    if undeclared:
        findings.append(Finding(
            "ERROR", "NARRATIVE_NAMES_UNDECLARED_SIGNAL",
            f"handshake_pairs names {len(undeclared)} signal(s) that this "
            f"design declares nowhere (not in L17 channels/globals, not in "
            f"L9 ports/wires, not in any other L-doc entity). A handshake "
            f"over a signal the design does not have is a non-fact.",
            {"undeclared": undeclared[:20]}))

    # -- Consumer derivation ------------------------------------------------
    derived = _c_derive_signals(l17, l9)
    derived_names = {d.get("name") for d in derived}
    info["consumer_derived_port_count"] = len(derived)

    # What does L17 ALONE contribute? (L9-only fallback must not mask an L17
    # defect, and an L17 defect must not be excused by L9.)
    derived_l17_only = _c_derive_signals(l17, {})
    info["ports_derived_from_l17_alone"] = len(derived_l17_only)

    # -- E3 CHANNEL_NOT_PORT_DERIVABLE / E4 DIRECTION_SILENTLY_INOUT --------
    dropped: List[Any] = []
    inout_guessed: List[str] = []
    collapsed: List[Dict[str, Any]] = []
    for ch in channels:
        if not isinstance(ch, dict):
            dropped.append({"channel": repr(ch)[:80],
                            "why": "not an object"})
            continue
        # A channel is port-derivable only if SOME declared name of its own
        # carries identifier content. When none does, the consumer's
        # _sanitize_id() substitutes a placeholder and the emitted top module
        # gains a port the design never declared.
        if not _any_identifier_content(ch):
            dropped.append({"channel": ch.get("name"),
                            "keys": sorted(ch.keys()),
                            "why": "no declared name carries identifier "
                                   "content; the consumer substitutes a "
                                   "placeholder port name"})
            continue
        contributed = _channel_contribution(ch, derived_l17_only)
        if not contributed:
            dropped.append({"channel": ch.get("name"),
                            "keys": sorted(ch.keys()),
                            "why": "contributes no port to the consumer's "
                                   "own derivation"})
            continue
        # A channel that declares N member signals but contributes ONE port is
        # collapsed to its GROUP name: N-1 declared signals never reach the
        # emitted interface. derive_signals reads only `channels[].name`, so a
        # catalog whose channels are groups-with-members loses every member.
        sub_named = [s for s in _as_list(ch.get("signals"))
                     if (isinstance(s, dict) and s.get("name"))
                     or (isinstance(s, str) and s.strip())]
        if len(sub_named) > 1 and len(contributed) <= 1:
            collapsed.append({
                "channel": ch.get("name"),
                "declared_member_signals": len(sub_named),
                "ports_contributed": len(contributed),
                "lost": [(s.get("name") if isinstance(s, dict) else s)
                         for s in sub_named][:12]})

        # Direction the consumer can actually read.
        sub_signals = [s for s in _as_list(ch.get("signals"))
                       if isinstance(s, dict)]
        if sub_signals:
            missing_dir = [s.get("name") for s in sub_signals
                           if not (s.get("direction") or s.get("dir"))]
            if missing_dir:
                inout_guessed.extend(str(m) for m in missing_dir if m)
        elif not (ch.get("direction_master") or ch.get("direction")):
            inout_guessed.append(str(ch.get("name")))

    if collapsed:
        lost = sum(c["declared_member_signals"] - c["ports_contributed"]
                   for c in collapsed)
        findings.append(Finding(
            "ERROR", "CHANNEL_GROUP_COLLAPSED_TO_ONE_PORT",
            f"{len(collapsed)} channel(s) declare member signals but collapse "
            f"to a single port under the consumer's own derivation — {lost} "
            f"declared signal(s) never reach the emitted top module. "
            f"phase2_scaffold_gen.derive_signals reads `channels[].name` only "
            f"and does not expand `channels[].signals[]`, so a catalog whose "
            f"channels are GROUPS emits the group name as one port instead of "
            f"its members. Either the catalog must list member signals as "
            f"channels, or derive_signals must expand them.",
            {"collapsed": collapsed[:10]}))

    if dropped:
        findings.append(Finding(
            "ERROR", "CHANNEL_NOT_PORT_DERIVABLE",
            f"{len(dropped)} declared channel(s) contribute ZERO ports when "
            f"the real consumer derivation (phase2_scaffold_gen."
            f"derive_signals) is run over this L17. The consumer drops them "
            f"silently; the emitted top module will be missing that "
            f"interface.",
            {"dropped": dropped[:20]}))

    if inout_guessed:
        findings.append(Finding(
            "ERROR", "CHANNEL_DIRECTION_SILENTLY_INOUT",
            f"{len(inout_guessed)} declared channel signal(s) carry no "
            f"direction key that the consumer reads "
            f"(`direction_master` / `direction`). "
            f"phase2_scaffold_gen._normalize_dir(None) returns 'inout', so "
            f"these become silently bidirectional top-level ports.",
            {"signals": sorted(set(inout_guessed))[:20]}))

    # -- E3c PORT_WIDTH_COLLAPSED_TO_ONE_BIT (ORGANIC #404, increment 1) ---
    # `derive_signals` coerces any width that is neither an int nor a
    # digit-string to 1, with NO diagnostic. So a port the design declares as
    # `[ACC_W-1:0]` is emitted as a 1-bit scalar and the RTL is silently
    # wrong at its interface.
    #
    # The value is NOT missing. L1's `_parse_port_width` deliberately keeps
    # the textual form in `width_symbolic` "so downstream consumers can
    # resolve at elaboration time", phase1 forwards it into the L9 entry, and
    # the consumer then throws it away. Measured with the real function:
    #     {'name':'acc_o','width':'ACC_W-1:0','width_symbolic':'ACC_W-1:0'}
    #       -> {'name': 'acc_o', 'width': 1}
    #
    # THIS REPORTS; IT WRITES NOTHING. #404 measured that the obvious repair
    # — resolving the symbol against the corpus' `parameters[]` and writing
    # the result back into L1 — is WORSE than the defect: the L-doc corpus
    # puts no module or layer qualifier on `parameters[]`, so a corpus-global
    # join by bare name let an L12 scan-chain count `N=4` size a data bus the
    # datasheet stated as 48, and turned `l1_pin_bus_width_actionable_check`
    # from a correct FAIL into a PASS. A finding cannot do that: if that gate
    # is also failing, both keep failing and each names its own layer.
    #
    # WHY THE `width == 1` TEST IS A BRANCH AND NOT A GUARD (#404 round 2)
    # -------------------------------------------------------------------
    # #404 proposed, as its next increment, resolving the symbol in the
    # CONSUMER scoped to the SAME document, on the stated ground that then
    # "no gate's input is rewritten by its own repair". MEASURED, that ground
    # is false: this gate's input IS the consumer's output. With an
    # Increment-2 resolver monkeypatched over `derive_signals` and the real
    # published cell that fires this rail as input, the rail went silent —
    #     stock consumer      -> PORT_WIDTH_COLLAPSED_TO_ONE_BIT, rc 1
    #     increment-2 consumer-> finding absent
    # — and it went equally silent when the same-document parameter default
    # was mutated to CONTRADICT the number the port's own width prose states
    # (resolved 4 bits against a documented and shipped 32). A wrong
    # resolution and a right one are indistinguishable from outside: exactly
    # the failure that withdrew the L1 resolver, one layer down.
    #
    # So the rail keys on the LAYER's declaration — a symbolic or non-numeric
    # width in the L9 entry, which no width repair in the consumer rewrites —
    # and merely CLASSIFIES by what the consumer emitted. A repair can change
    # which finding is reported. It cannot make this gate green.
    collapsed_widths = []
    uncorroborated_widths = []
    _l9_by_name = {}
    # The SAME two keys, in the SAME order, that derive_signals itself reads
    # (phase2_scaffold_gen:238) — so this cannot describe a port list the
    # consumer never looked at.
    for _key in ("top_ports", "ports"):
        for _p in _as_list(l9.get(_key)):
            if isinstance(_p, dict) and _p.get("name"):
                _l9_by_name.setdefault(
                    _c_sanitize_id(str(_p["name"])), _p)
    for _s in derived:
        if not isinstance(_s, dict):
            continue
        _src = _l9_by_name.get(_c_sanitize_id(str(_s.get("name") or "")))
        if not isinstance(_src, dict):
            continue
        _sym = _src.get("width_symbolic")
        _w = _src.get("width")
        _string_width = (isinstance(_w, str)
                         and not str(_w).strip().isdigit())
        if not ((_sym and str(_sym).strip()) or _string_width):
            continue
        _row = {
            "port": _s.get("name"),
            "l9_width": _w,
            "width_symbolic": _sym,
        }
        if _s.get("width") == 1:
            collapsed_widths.append(_row)
        else:
            _row["consumer_width"] = _s.get("width")
            uncorroborated_widths.append(_row)
    if collapsed_widths:
        findings.append(Finding(
            "ERROR", "PORT_WIDTH_COLLAPSED_TO_ONE_BIT",
            f"{len(collapsed_widths)} port(s) are emitted as 1-bit scalars by "
            f"the consumer's own derivation while the L9 entry they come from "
            f"carries a SYMBOLIC or non-numeric width. "
            f"phase2_scaffold_gen.derive_signals coerces any width that is "
            f"neither an int nor a digit-string to 1 with no diagnostic, so "
            f"the emitted top module's interface is narrower than the design "
            f"declares and the error surfaces several steps downstream. "
            f"This gate REPORTS only — resolving the symbol and writing it "
            f"back into an L-doc was measured (#404) to turn a correct FAIL "
            f"into a PASS, because `parameters[]` carries no module or layer "
            f"qualifier and a bare-name join is unsound by construction.",
            {"ports": collapsed_widths[:20]}))

    if uncorroborated_widths:
        findings.append(Finding(
            "ERROR", "PORT_WIDTH_SYMBOL_UNCORROBORATED",
            f"{len(uncorroborated_widths)} port(s) whose L9 entry declares a "
            f"SYMBOLIC or non-numeric width come out of the consumer's own "
            f"derivation as a CONCRETE bit count this gate cannot corroborate "
            f"against the layer. The layer states a symbol; something in the "
            f"consumer turned it into a number, and the only evidence for "
            f"that number is the step that produced it. #404 measured that a "
            f"wrong resolution and a right one are indistinguishable from "
            f"outside — a same-document parameter default contradicting the "
            f"port's own stated width resolved to 4 bits on a port the design "
            f"documents and ships as 32, with no diagnostic anywhere. A "
            f"resolver may only land here once this gate can CHECK the "
            f"resolved value against a statement the resolver did not write; "
            f"until then the resolution is reported, not trusted.",
            {"ports": uncorroborated_widths[:20]}))

    # -- E5 CLOCK_PORT_SYNTHESISED_BY_CONSUMER -----------------------------
    # derive_signals AUTO-ADDS a "clk"/"rst_n" stub when neither L17 nor L9
    # declares one, so "did a clock come out?" is a test that can never fail.
    # The real question is whether the clock the consumer emits was DECLARED
    # by the layers it reads, or INVENTED to fill the hole. A synthesised
    # clock port means the emitted top-module interface does not match the
    # design — the same class of defect as a signal net landing on a
    # power-typed terminal.
    clocked, clock_reasons = design_is_clocked(gd)
    declared = _declared_port_names(l17, l9)
    synthetic = sorted(str(n) for n in derived_names
                       if isinstance(n, str) and _norm(n) not in declared)
    clock_ports = sorted(n for n in derived_names
                         if isinstance(n, str) and _c_is_clock_name(n))
    synth_clocks = [n for n in synthetic if _c_is_clock_name(n)]
    info["design_is_clocked"] = clocked
    info["clocked_evidence"] = clock_reasons[:8]
    info["clock_ports_derived"] = clock_ports
    info["ports_synthesised_by_consumer"] = synthetic
    if clocked and synth_clocks:
        findings.append(Finding(
            "ERROR", "CLOCK_PORT_SYNTHESISED_BY_CONSUMER",
            f"This design's own L-docs declare it sequential "
            f"({', '.join(clock_reasons[:3])}), but NEITHER L17 nor L9 "
            f"declares a clock port, so phase2_scaffold_gen.derive_signals "
            f"invented {synth_clocks} to fill the hole. The clock requirement "
            f"exists in another layer and is ABSENT from the layer that "
            f"derives the top-module interface; the emitted port list "
            f"therefore does not match the design.",
            {"declared_clock_evidence": clock_reasons[:8],
             "synthesised_ports": synthetic,
             "declared_port_count": len(declared)}))

    # -- W1 / W2 ------------------------------------------------------------
    no_purpose = [str(ch.get("name")) for ch in channels
                  if isinstance(ch, dict)
                  and not (ch.get("purpose") or ch.get("description")
                           or ch.get("semantics"))]
    if no_purpose:
        findings.append(Finding(
            "WARNING", "CHANNEL_PURPOSE_MISSING",
            f"{len(no_purpose)} channel(s) carry no purpose/description/"
            f"semantics; the consumer emits an empty port comment.",
            {"channels": no_purpose[:20]}))

    ev = raw17.get("extraction_evidence") or raw17.get("evidence")
    if status in _STATUS_SUCCESS and not ev:
        findings.append(Finding(
            "WARNING", "NO_EXTRACTION_EVIDENCE",
            f"extraction_status={status!r} but extraction_evidence is empty, "
            f"so no claim in this layer is traceable to a source line."))

    return findings, info


def _l17_declares(l17: dict, sig: str) -> bool:
    """True when L17 itself declares `sig` among its channels/globals."""
    n = _norm(sig)
    for ch in _as_list(l17.get("channels")):
        if not isinstance(ch, dict):
            continue
        if _norm(ch.get("name") or "") == n:
            return True
        for s in _as_list(ch.get("signals")):
            if isinstance(s, dict) and _norm(s.get("name") or "") == n:
                return True
            if isinstance(s, str) and _norm(s) == n:
                return True
    for g in _as_list(l17.get("global_signals")):
        if isinstance(g, dict) and _norm(g.get("name") or "") == n:
            return True
        if isinstance(g, str) and _norm(g) == n:
            return True
    return False


def _declared_port_names(l17: dict, l9: dict) -> Set[str]:
    """Normalized names the two layers derive_signals reads actually DECLARE."""
    out: Set[str] = set()

    def _put(v: Any) -> None:
        if isinstance(v, str) and v.strip():
            out.add(_norm(_c_sanitize_id(re.sub(r"\[\d+:0\]", "", v))))

    for ch in _as_list(l17.get("channels")):
        if isinstance(ch, dict):
            _put(ch.get("name"))
            for s in _as_list(ch.get("signals")):
                _put(s.get("name") if isinstance(s, dict) else s)
        else:
            _put(ch)
    for g in _as_list(l17.get("global_signals")):
        _put(g.get("name") if isinstance(g, dict) else g)
    for key in ("top_ports", "ports", "top_level_ports", "dtop_ports",
                "top_module_pins"):
        for p in _as_list(l9.get(key)):
            _put(p.get("name") if isinstance(p, dict) else p)
    out.discard("")
    return out


_IDENT_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _identifier_tokens(node: Any, out: Optional[Set[str]] = None) -> Set[str]:
    """Identifier-shaped tokens appearing in narrative values (evidence only —
    never the basis of a verdict, so no stop-word list is needed)."""
    if out is None:
        out = set()
    if isinstance(node, str):
        for m in _IDENT_TOKEN.finditer(node):
            t = m.group(0)
            if re.search(r"[A-Z]{2}", t) or "_" in t:
                out.add(t)
    elif isinstance(node, dict):
        for k, v in node.items():
            _identifier_tokens(str(k), out)
            _identifier_tokens(v, out)
    elif isinstance(node, list):
        for it in node:
            _identifier_tokens(it, out)
    return out


# ---------------------------------------------------------------------------
def _has_identifier_content(name: Any) -> bool:
    """True when `name` survives identifier sanitization as a real name.

    Deliberately independent of the consumer's placeholder string: it tests
    the DECLARED name, so a future change to that placeholder cannot turn this
    rail into a check that can never fail."""
    if not isinstance(name, str):
        return False
    cleaned = re.sub(r"_+", "_",
                     re.sub(r"[^A-Za-z0-9_]", "_", name.strip())).strip("_")
    return bool(cleaned)


def _any_identifier_content(ch: dict) -> bool:
    if _has_identifier_content(ch.get("name")):
        return True
    for s in _as_list(ch.get("signals")):
        cand = s.get("name") if isinstance(s, dict) else s
        if _has_identifier_content(cand):
            return True
    return False


def _channel_contribution(ch: dict, derived: List[dict]) -> List[str]:
    """Ports in `derived` attributable to channel `ch`."""
    names = {d.get("name") for d in derived}
    hits: List[str] = []
    cand = [ch.get("name")]
    for s in _as_list(ch.get("signals")):
        if isinstance(s, dict):
            cand.append(s.get("name"))
        elif isinstance(s, str):
            cand.append(s)
    for c in cand:
        if not c:
            continue
        clean = _c_sanitize_id(re.sub(r"\[\d+:0\]", "", str(c)))
        if clean and clean in names:
            hits.append(clean)
    return hits


def build_report(project: Path, findings: List[Finding],
                 info: Dict[str, Any]) -> dict:
    errs = [f for f in findings if f.severity == "ERROR"]
    return {
        "program": "l17_channel_catalog_consumer_contract_check",
        "version": "1.0.0",
        "layer": "L17",
        # vibe-ic#316 — was "BLOCKS"; see "ENFORCEMENT" in the module
        # docstring for the measurement that changed it.
        "verdict_mode": "ADVISES",
        "project": str(project),
        "summary": {
            "pass": not errs,
            "error_count": len(errs),
            "warning_count": sum(1 for f in findings
                                 if f.severity == "WARNING"),
            "finding_count": len(findings),
        },
        "info": info,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L17 channel/signal catalog consumer-contract gate")
    ap.add_argument("project", type=Path,
                    help="run root containing phase1/generated_docs")
    ap.add_argument("--json", default=None, help="write JSON report here")
    ap.add_argument("--advisory", action="store_true",
                    help="report only; always exit 0 unless unreadable")
    args = ap.parse_args(argv)

    findings, info = audit(args.project)
    report = build_report(args.project, findings, info)
    out = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)

    if any(f.severity == "SKIP" for f in findings):
        return 2
    if args.advisory:
        return 0
    return 1 if any(f.severity == "ERROR" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
