#!/usr/bin/env python3
"""
phase1_k5_quality_check.py — catch the K5 issues found by real Phase-2 synth.

Detects Phase-1 document patterns that produce weak / inconsistent RTL:

  K5-A  Templated L6 FSMs:   >=3 submodules share identical states list
  K5-B  Register overlap:    L4 register_map entries with overlapping ranges
  K5-D  Duplicate port keys: L9 ports have both "dir" and "direction"
  K5-E  Reset polarity split: L8 rst_i vs L9 rst_n
  K5-F  Missing crypto params: crypto-engine IC lacks key schedule
  ... (see the per-check docstrings below for the full current set)

Severity is WARN, not ERROR: a K5 finding never fails the umbrella.


ORGANIC #491 — "checked, nothing wrong" vs "nothing to check"
=============================================================
Every check used to return a bare `list`, so a check that examined 196
documents and found nothing was INDISTINGUISHABLE from a check whose
input field has never existed. Both returned `[]`. `main()` then returned
rc 0 unconditionally, and `flow_compliance_check`'s umbrella maps
"not rc 1, not rc 2" to ("pass", None) — so this gate was a permanent,
silent PASS inside a P0 umbrella that advertises it as one of its
checkers. That is a false certificate: the umbrella certified a checker
that examined nothing.

MEASURED on the tracked corpus at v1.7.68 (196 L9_INTEGRATION_SPEC.json,
201 L1_DATASHEET.json / L6_CONTROL_LOGIC.json), driving the functions:

    L9.submodules non-empty LIST          36 / 196
    L9.submodules non-empty DICT           0 / 196   <- only shape read
    check_generic_port_map returns >0      0 / 36
    ... and reshaping the list into dict{name: entry} left it at 0/36,
        because its ONLY field, `ports_mapped`, occurs 0 times across the
        114 shipped submodule entries.

Three fixes, applied per check on measured evidence (see `_RETIRED_CHECKS`
for the per-check deletion reasons):

  REPAIR   — the assertion survives in the schema the corpus ships, so the
             check now reads that. `_l9_ports` unions the v1 nested
             `dtop_top_level.ports` with the v2 flat keys exactly as
             ORGANIC #490 already did in `l9_rtl_pin_consistency_check`.
  RETIRE   — the check's sole input key has never been emitted by any
             producer, in any commit, anywhere in the repo. A check that
             cannot examine anything is worse than no check, because it
             reads as coverage. Recorded in `_RETIRED_CHECKS`, not merely
             deleted (vibe-ic#439 precedent).
  DISCLOSE — the check is sound and its input is real but CONDITIONAL
             (class-gated, or waiting on a producer that the plugin's own
             schema declares but no shipping generator emits). It now SAYS
             it examined nothing instead of returning `[]`.

Mechanically: every check returns a `CheckResult` (a `list` subclass, so
every existing caller keeps working) carrying `.examined` / `.applicable`
/ `.note`. `run_on_with_census` aggregates them; `main()` prints the
denominator and returns rc 2 (NOT CHECKED) when the whole gate examined
nothing, so the umbrella records a NAMED SKIP instead of a silent PASS.

Usage:
  python3 phase1_k5_quality_check.py <generated_docs/>
  python3 phase1_k5_quality_check.py --all
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# Override via VIBE_IC_BENCHMARK_ROOT to point at the local benchmark tree.
# Default to cwd so the --all sweep simply finds nothing if the env var is
# unset, instead of pointing at a developer-specific worktree path.
WORKTREE = Path(os.environ.get("VIBE_IC_BENCHMARK_ROOT", "."))


def lenient_load(p):
    t = p.read_text()
    try: return json.loads(t)
    except json.JSONDecodeError:
        return json.loads(re.sub(
            r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)',
            lambda m: m.group("pfx") + str(int(m.group(2), 16)), t))


# ---------------------------------------------------------------------------
# ORGANIC #491 — the vacuity-disclosing result type.
#
# A `list` subclass so every existing consumer (`out += check(...)`,
# `if fs:`, `len(fs)`, `assert check(x) == []`) keeps working byte-for-byte,
# while the census rides along on attributes. Equality is plain list
# equality, so `== []` in existing tests is unaffected.
# ---------------------------------------------------------------------------
class CheckResult(list):
    """Findings PLUS the denominator that produced them.

    applicable : did this check's precondition hold at all?
                 False => "nothing to check" (NOT the same as "clean").
    examined   : how many units (ports / registers / submodules / docs)
                 were actually inspected. 0 with applicable=True still
                 means nothing was looked at.
    note       : human-readable reason, REQUIRED when applicable is False.
    """
    __slots__ = ("check_id", "applicable", "examined", "note")

    def __init__(self, findings=(), *, check_id="", applicable=True,
                 examined=0, note=""):
        super().__init__(findings)
        self.check_id = check_id
        self.applicable = bool(applicable)
        self.examined = int(examined)
        self.note = note

    @property
    def vacuous(self) -> bool:
        """True when this check contributed no evidence either way."""
        return (not self.applicable) or self.examined == 0

    def census(self) -> dict:
        return {"check_id": self.check_id, "applicable": self.applicable,
                "examined": self.examined, "findings": len(self),
                "note": self.note}


def _na(check_id, note):
    """Not applicable — the precondition for this check does not hold."""
    return CheckResult(check_id=check_id, applicable=False, examined=0,
                       note=note)


def _seen(check_id, findings, examined, note=""):
    """Applicable and actually examined `examined` units."""
    return CheckResult(findings, check_id=check_id, applicable=True,
                       examined=examined, note=note)


# ---------------------------------------------------------------------------
# ORGANIC #491 — RETIRED checks.
#
# Each entry's sole input key is read by a check but has NO PRODUCER IN THIS
# REPOSITORY: `git grep -l -F <key>` over the tracked tree returns exactly
# ONE file — this one, the consumer — `git log --all -S <key>` over all refs
# returns only release-squash commits in which the sole hit is again this
# file, no deleted L6/L9 producer ever carried it, and driving the shipping
# generators (`gen_l9_integration_spec` / `gen_l6_control_logic` in
# phase1_doc_one_shot_runner.py, and phase1_engine's auto_fill + render
# path across 5 classes) emits none of them. Across the 196 tracked
# L9_INTEGRATION_SPEC.json the keys occur 0 times at any nesting depth.
#
# HONEST CAVEAT: `ports_mapped` was real ONCE, somewhere else. The v0.1.2
# release note (vibe-ic-marketplace/README.md at commit aa1ab02f) reports
# "K5-C generic L9 ports_mapped (116)", so the key existed in a private
# pre-v0.1.2 corpus that was never checked into this repository. The
# retirement claim is therefore scoped: no producer HERE, not "this key
# never existed anywhere". The consequence is the same — nothing this
# plugin can be run against will ever populate it — but the narrower claim
# is the one the evidence supports.
#
# These are DELETED, not disabled. The table is kept (and asserted by
# tests) so the deletion carries its reason forward and a future producer
# cannot silently resurrect a check nobody re-validated. vibe-ic#439 is
# the precedent: a check that has never examined anything and cannot be
# made to is worse than no check, because it reads as coverage.
# ---------------------------------------------------------------------------
_RETIRED_CHECKS = {
    "K5-C": {
        "was": "check_generic_port_map",
        "read": "L9.submodules[*].ports_mapped",
        "reason": (
            "`ports_mapped` has no producer in this repository. Measured at "
            "v1.7.68: 0 occurrences across the 114 submodule entries shipped "
            "by the 36 L9 docs that carry a non-empty `submodules` (of 196 "
            "tracked L9). The key appears in exactly 1 tracked file — this "
            "checker — and in no template, qbank entry, schema declaration or "
            "generated document, on any ref. `agents/lessons/ic_expert_L9.md` "
            "enumerates the REQUIRED L9 top-level keys and does not list it. "
            "The shipped submodule entry "
            "carries {name, instances, role, type, evidence, low_confidence, "
            "extraction_strategy, instance_count, desc} — no field can carry "
            "'this submodule's port map is boilerplate'. The container-type "
            "drift reported in #491 (list vs dict) was real but NOT the "
            "blocker: reshaping to dict{name: entry} left it at 0/36."),
    },
    "K5-M": {
        "was": "check_axi_not_threaded",
        "read": "L9.dtop_top_level.ports + L9.submodules[*].ports_mapped",
        "reason": (
            "Asserted that an AXI bundle at DTOP is threaded down into "
            "submodule port maps. The submodule half reads `ports_mapped` "
            "(never produced — see K5-C), so the assertion is unanswerable: "
            "with no per-submodule port map there is nothing that could "
            "show threading. The DTOP half alone cannot carry it."),
    },
    "K5-N": {
        "was": "check_memory_macro_placeholder",
        "read": "L1.class_path=memory-macro + L6.submodule_control_logic "
                "+ L9.submodules[*].ports_mapped",
        "reason": (
            "Body is entirely `ports_mapped` + `submodule_control_logic`. "
            "Worse than dead: its fallback branch counts a submodule with NO "
            "`ports_mapped` as a placeholder, so on the first memory-macro "
            "IC that ever shipped it would report 100% placeholders purely "
            "because the field does not exist — a latent false-positive "
            "generator, not merely a silent one. And no such IC can exist: "
            "`memory-macro` is not a class in agents/class_kb/class-tree.yaml, "
            "has no class_kb template, and appears nowhere in "
            "class_reference.yaml or the qbank — as a class label it existed "
            "only inside this checker."),
    },
    "K5-O": {
        "was": "check_tristate_not_hoisted",
        "read": "L9.dtop_top_level.tristate_rule",
        "reason": (
            "`tristate_rule` occurs in exactly 1 tracked file — this checker "
            "— and 0 / 196 tracked L9 docs. The check gates on the key being "
            "present, so it has never reached its own body."),
    },
    "K5-J": {
        "was": "check_bus_summary_not_expanded",
        "read": "L9.dtop_top_level.ports_summary",
        "reason": (
            "`ports_summary` occurs in exactly 1 tracked file — this checker "
            "— and 0 / 196 tracked L9 docs. NOTE: the ASSERTION is worth "
            "keeping (doc prose names a bus protocol the port list never "
            "expands). Re-authoring it against the prose field that DOES "
            "ship, `integration_overview` (158/196), was measured: "
            "population 11/196, 1 hit. That is a NEW check needing its own "
            "false-positive validation — reading `module_role` instead gives "
            "3 hits of which 2 are plainly false — so it is deliberately NOT "
            "smuggled into this fix. Filed as follow-up work instead."),
    },
    "K5-R": {
        "was": "check_ports_summary_signature_placeholder",
        "read": "L9.dtop_top_level.ports_summary",
        "reason": (
            "Same never-produced key as K5-J: `ports_summary`, 1 tracked "
            "file (this checker), 0 / 196 tracked L9 docs."),
    },
}


# ---------------------------------------------------------------------------
# L9 schema resolvers — the corpus ships schema v2 (flat), the original K5
# checks were written against schema v1 (nested under `dtop_top_level`).
# `l9_rtl_pin_consistency_check` already solved exactly this for ports in
# ORGANIC #490; we reuse its key union rather than inventing a second one.
# MEASURED: dtop_top_level 0/196, top_ports 141/196, ports 141/196,
# top_module_pins 138/196 — union non-empty on 31/196.
# ---------------------------------------------------------------------------
_L9_PORT_KEYS = ("top_ports", "ports", "top_level_ports", "top_module_pins")


def _flatten_ports(ports):
    """Normalize an L9 port container into a flat list of dicts."""
    if isinstance(ports, dict):
        flat = []
        for v in ports.values():
            if isinstance(v, list): flat.extend(v)
            elif isinstance(v, dict): flat.append(v)
        return flat
    if isinstance(ports, list): return ports
    return []


def _l9_ports(l9):
    """Every top-level port dict from ANY accepted L9 schema key.

    Union of the v2 flat keys and the v1 nested `dtop_top_level.ports`,
    deduped by name (first wins). Mirrors #490's `extract_l9_ports` so a
    doc written to either schema is read identically."""
    if not isinstance(l9, dict): return []
    raw = []
    for k in _L9_PORT_KEYS:
        raw.extend(_flatten_ports(l9.get(k)))
    dtop = l9.get("dtop_top_level")
    if isinstance(dtop, dict):
        raw.extend(_flatten_ports(dtop.get("ports")))
    out, seen = [], set()
    for e in raw:
        if not isinstance(e, dict): continue
        n = str(e.get("name") or e.get("port") or e.get("pin") or "").strip()
        if n and n in seen: continue
        if n: seen.add(n)
        out.append(e)
    return out


def _l9_submodules(l9):
    """L9.submodules as a flat list of entry dicts, whatever the container.

    #491: every shipped doc uses a LIST (36/196 non-empty); the original
    code accepted only a dict and so returned early on all of them. Bare
    strings are legal entries (16 across 2 docs) and normalize to
    {"name": <str>} rather than being silently dropped."""
    if not isinstance(l9, dict): return []
    subs = l9.get("submodules")
    entries = []
    if isinstance(subs, list): entries = subs
    elif isinstance(subs, dict):
        for k, v in subs.items():
            if isinstance(v, dict):
                e = dict(v)
                e.setdefault("name", k)
                entries.append(e)
            else:
                entries.append({"name": k})
        return entries
    out = []
    for e in entries:
        if isinstance(e, dict): out.append(e)
        elif isinstance(e, str) and e.strip(): out.append({"name": e.strip()})
    return out


def _l9_top_container(l9):
    """The v1 `dtop_top_level` mapping when present, else the doc itself.

    Lets a check read a DTOP-scoped field from either schema without
    duplicating the fallback at every call site."""
    if not isinstance(l9, dict): return {}
    dtop = l9.get("dtop_top_level")
    return dtop if isinstance(dtop, dict) else l9


# DISCLOSE (#491). `L6.submodule_control_logic` is NOT an invented key — it is
# declared across 23 tracked files and read by other LIVE gates
# (phase1_consistency_check, phase1_quality_parity_check). TWO real producers
# exist; neither is on the shipping path, which is why the corpus shows
# 0 / 201 tracked L6_CONTROL_LOGIC.json:
#
#   1. WAS `tools/phase1_engine/gap_detect.py::_apply_typical_scaffolds`, which
#      injected it for all 5 scaffolded classes. REMOVED in #493 — it was
#      reachable only from the `auto-fill` CLI verb (the shipping entry
#      `phase1_one_shot_runner` invokes `run-all`, whose `_cmd_run_all` calls
#      detect_gaps + render_layers WITHOUT auto_fill), it landed on 0/201
#      doc-sets, and the L6 map it injected was class-typical only in name:
#      the crypto-engine variant hung AES submodules (sbox / mixcol / encipher
#      / decipher) on the parent of hash-function, stream-cipher and rng. See
#      `gap_detect._RETIRED_MECHANISMS['typical_scaffolds']`.
#   2. `agents/lessons/ic_expert_L6.md` and `qbank/any-ic_L6.yaml` instruct the
#      ic-expert-agent to emit it, so hand-authored L6 docs carry it. This is
#      now the ONLY producer, and it is still off the shipping path.
#
# So this is a genuine PRODUCER GAP with a named cause, not a dead check —
# deleting it would be wrong. It is KEPT and now says it examined nothing.
_L6_SUBMODULE_MAP_ABSENT = (
    "L6.submodule_control_logic absent — the shipping Phase-1 runner does not "
    "emit it (measured 0/201 tracked L6_CONTROL_LOGIC.json at v1.7.68), though "
    "the ic-expert-agent L6 contract produces it off the shipping path. "
    "PRODUCER GAP, not a clean result")


def _l6_submodule_map(l6):
    """L6.submodule_control_logic as {name: cfg}, or None when absent."""
    subs = l6.get("submodule_control_logic") if isinstance(l6, dict) else None
    if isinstance(subs, dict) and subs: return subs
    return None


def check_templated_fsms(l6):
    subs = _l6_submodule_map(l6)
    if subs is None:
        return _na("K5-A", _L6_SUBMODULE_MAP_ABSENT)
    if len(subs) < 3:
        return _na("K5-A", f"only {len(subs)} submodule(s) in "
                           "L6.submodule_control_logic — the templated-FSM "
                           "pattern needs >=3 to be meaningful")
    state_groups = Counter()
    examined = 0
    for _, cfg in subs.items():
        if isinstance(cfg, dict):
            states = cfg.get("states")
            if isinstance(states, list) and states:
                examined += 1
                state_groups[tuple(sorted(str(s).upper() for s in states))] += 1
    if examined == 0:
        return _na("K5-A", f"{len(subs)} submodule(s) present but none "
                           "declares a non-empty `states` list")
    out = []
    for key, n in state_groups.items():
        if n >= 3:
            out.append({"id":"K5-A","severity":"warn",
                "msg":f"{n} submodules share identical states {list(key)} — templated default"})
    return _seen("K5-A", out, examined)


def parse_addr_range(s):
    if not isinstance(s, str): return None
    m = re.match(r'^\s*(0x[0-9a-fA-F]+|\d+)\s*(?:-\s*(0x[0-9a-fA-F]+|\d+))?\s*$', s.strip())
    if not m: return None
    def _int(x): return int(x,16) if x and x.lower().startswith('0x') else int(x)
    a = _int(m.group(1))
    b = _int(m.group(2)) if m.group(2) else a
    return (a, b)


def check_register_overlap(l4):
    out = []
    regmap = None
    for k in ("register_map", "otp_map_128x8", "control_registers_logical"):
        v = l4.get(k) if isinstance(l4, dict) else None
        if isinstance(v, list) and v: regmap = v; break
    if not regmap:
        return _na("K5-B", "L4 carries no non-empty register_map / "
                           "otp_map_128x8 / control_registers_logical")
    ranges = []
    for entry in regmap:
        if not isinstance(entry, dict): continue
        name = entry.get("name") or "unnamed"
        addr = entry.get("addr") or entry.get("offset") or entry.get("address")
        r = parse_addr_range(addr) if addr else None
        # Bank-select key: when an entry declares bank_select_reg + bank_select_value,
        # registers on different banks legitimately share an offset (e.g. SJA1000
        # PeliCAN RMC vs CDR at 0x1F, muxed by MOD.RM). Strategy-(c) per K5-B fix spec.
        bank_reg = entry.get("bank_select_reg")
        bank_val = entry.get("bank_select_value")
        bank_key = (bank_reg, str(bank_val)) if bank_reg is not None else None
        if r: ranges.append((name, r[0], r[1], bank_key))
    for i, (n1, s1, e1, b1) in enumerate(ranges):
        for n2, s2, e2, b2 in ranges[i+1:]:
            if s1 > e2 or s2 > e1 or n1 == n2: continue
            # Skip if both declare bank-select on the same reg with different values.
            if b1 is not None and b2 is not None and b1[0] == b2[0] and b1[1] != b2[1]:
                continue
            out.append({"id":"K5-B","severity":"warn",
                "msg":f"Register overlap: {n1}[0x{s1:X}-0x{e1:X}] vs {n2}[0x{s2:X}-0x{e2:X}]"})
    return _seen("K5-B", out, len(ranges),
                 f"{len(ranges)} of {len(regmap)} entries had a parseable address")


# K5-C check_generic_port_map — RETIRED (#491). See _RETIRED_CHECKS["K5-C"].
# Its only field, L9.submodules[*].ports_mapped, has never been emitted by any
# producer in any commit: 0 occurrences across the 114 shipped submodule
# entries, and the key appears in exactly one tracked file (this one). The
# list-vs-dict container drift reported in #491 was real but was NOT what made
# it silent — reshaping the corpus to dict{name: entry} still yielded 0/36.


def check_duplicate_port_keys(l9):
    """K5-D: an L9 port carrying BOTH `dir` and `direction`.

    REPAIRED (#491). Was gated on the v1 `dtop_top_level` container, which is
    absent from all 196 tracked L9 docs, so it returned [] on every one. Now
    reads the #490 port-key union. MEASURED after repair: population 31/196
    (110 docs ship `ports: []`), findings 0 — i.e. genuinely "checked 31,
    nothing wrong". The assertion is live, not theoretical: both spellings
    occur in the corpus (`direction` 652 entries, `dir` 106), just never yet
    on the same entry."""
    ports = _l9_ports(l9)
    if not ports:
        return _na("K5-D", "L9 carries no top-level ports under any accepted "
                           f"schema key ({', '.join(_L9_PORT_KEYS)}, "
                           "dtop_top_level.ports)")
    bad = [p for p in ports if isinstance(p, dict) and "dir" in p and "direction" in p]
    out = []
    if bad:
        out = [{"id":"K5-D","severity":"warn",
            "msg":f"{len(bad)}/{len(ports)} L9 top-level ports carry BOTH "
                  f"'dir' and 'direction'"}]
    return _seen("K5-D", out, len(ports))


def check_reset_polarity_split(docs):
    def find_rst(node):
        found = set()
        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(k, str) and k.lower() in ("rst_n","rst_i","reset"):
                        found.add(k.lower())
                    walk(v)
            elif isinstance(x, list):
                for v in x: walk(v)
            elif isinstance(x, str) and x.lower() in ("rst_n","rst_i"):
                found.add(x.lower())
        walk(node)
        return found
    l8 = docs.get("L8", {})
    l9 = docs.get("L9", {})
    if not l8 or not l9:
        missing = " and ".join(n for n, v in (("L8", l8), ("L9", l9)) if not v)
        return _na("K5-E", f"{missing} absent — a polarity SPLIT needs both "
                           "documents to compare")
    l8_r = find_rst(l8)
    l9_r = find_rst(l9)
    out = []
    if "rst_i" in l8_r and "rst_n" in l9_r and "rst_i" not in l9_r:
        out = [{"id":"K5-E","severity":"warn",
            "msg":"Reset polarity split: L8 rst_i vs L9 rst_n"}]
    return _seen("K5-E", out, 2,
                 f"L8 reset tokens={sorted(l8_r) or 'none'}, "
                 f"L9 reset tokens={sorted(l9_r) or 'none'}")


def check_fifo_bitfield_missing(docs):
    """K5-G: packet/FIFO register exposed without bit-field schema."""
    l4 = docs.get("L4", {})
    if not isinstance(l4, dict):
        return _na("K5-G", "L4 absent")
    out = []
    examined = 0
    for key in ("register_map", "control_registers_logical"):
        regs = l4.get(key)
        if not isinstance(regs, list): continue
        for r in regs:
            if not isinstance(r, dict): continue
            examined += 1
            name = str(r.get("name", "")).upper()
            if any(tag in name for tag in ("FIFO", "PACKET", "CMD", "DATA_PKT")):
                if not r.get("bitfields") and not r.get("fields") and not r.get("bit_fields"):
                    out.append({"id": "K5-G", "severity": "warn",
                        "msg": f"Packet/FIFO register '{r.get('name')}' lacks bitfield schema"})
    if examined == 0:
        return _na("K5-G", "L4 carries no register entries in register_map / "
                           "control_registers_logical")
    return _seen("K5-G", out, examined)


def check_mmio_vs_native_bus_conflict(docs):
    """K5-I: L4 describes MMIO view while L9 ports show native bus.

    REPAIRED (#491): reads the #490 port-key union instead of only the
    never-shipped `dtop_top_level.ports`. MEASURED after repair: population
    31/196, findings 0."""
    l4 = docs.get("L4", {})
    l9 = docs.get("L9", {})
    if not isinstance(l4, dict) or not isinstance(l9, dict):
        return _na("K5-I", "L4 or L9 absent — the conflict is between them")
    # Explicit override: L4 can declare that the register_map is a backdoor
    # view of the native handshake bus (no MMIO wrapper exists).
    if l4.get("native_bus_only"):
        return _na("K5-I", "L4.native_bus_only declares the register_map is a "
                           "backdoor view of the native bus — no conflict "
                           "possible by construction")
    # Likewise, L9 can declare an MMIO bus_interface block as authoritative.
    if _l9_top_container(l9).get("bus_interface"):
        return _na("K5-I", "L9 declares an authoritative bus_interface block")
    has_mmio_reg = bool(l4.get("register_map") or l4.get("control_registers_logical"))
    if not has_mmio_reg:
        return _na("K5-I", "L4 declares no register_map / "
                           "control_registers_logical — nothing to place on a bus")
    ports = _l9_ports(l9)
    if not ports:
        return _na("K5-I", "L9 carries no top-level ports under any accepted "
                           "schema key")
    port_names = {str(p.get("name", "")).lower() for p in ports if isinstance(p, dict)}
    mmio_hint = {"paddr","pwdata","prdata","psel","penable","pwrite","pready"}
    native_hint = {"cs","we","re","wr_data","rd_data","addr","valid","ready"}
    has_mmio_ports = bool(port_names & mmio_hint)
    has_native_ports = bool(port_names & native_hint)
    out = []
    if has_native_ports and not has_mmio_ports:
        out = [{"id": "K5-I", "severity": "warn",
            "msg": "L4 describes MMIO register_map but L9 ports expose native/handshake bus only — "
                   "RTL writer can't tell which interface the registers appear on"}]
    return _seen("K5-I", out, len(ports))


def check_scope_class_mismatch(docs):
    """K5-H: L1 class_path says simple/minimal but L6 shows a full SoC.

    DISCLOSE (#491): doubly conditional — needs a simple/minimal class_path
    AND L6.submodule_control_logic. The latter is never produced (0/201)."""
    l1 = docs.get("L1", {})
    l6 = docs.get("L6", {})
    if not isinstance(l1, dict):
        return _na("K5-H", "L1 absent")
    cls = str(l1.get("class_path", "")).lower()
    if not cls:
        return _na("K5-H", "L1.class_path empty — see K5-P")
    simple_markers = ("simple-cpu", "simple-peripheral", "minimal", "tiny")
    if not any(m in cls for m in simple_markers):
        return _na("K5-H", f"class_path {cls!r} is not simple/minimal — the "
                           "scope mismatch is defined only for those classes")
    subs = _l6_submodule_map(l6)
    if subs is None:
        return _na("K5-H", _L6_SUBMODULE_MAP_ABSENT)
    out = []
    if len(subs) >= 6:
        out = [{"id": "K5-H", "severity": "warn",
            "msg": f"L1 class_path suggests simple/minimal IC, but L6 has {len(subs)} "
                   f"submodules (JTAG/DM/IPIC-style SoC scope). Scope-class mismatch"}]
    return _seen("K5-H", out, len(subs))


# K5-J check_bus_summary_not_expanded — RETIRED (#491).
# K5-R check_ports_summary_signature_placeholder — RETIRED (#491).
# Both read L9.dtop_top_level.ports_summary, a key that occurs in exactly one
# tracked file (this one) and 0/196 tracked L9 docs. See _RETIRED_CHECKS —
# K5-J's underlying assertion is worth re-authoring against the prose field
# that DOES ship, but that is a new check needing its own FP validation and is
# deliberately not smuggled in here.


def check_soc_harness_no_grouping(docs):
    """K5-K: SoC-harness mixes power/io/mgmt in one flat ports list.

    DISCLOSE + REPAIR (#491): the port read now uses the #490 union, but the
    check remains class-gated on `soc-harness`, which 0/201 tracked L1 docs
    declare. That is honest conditionality (no harness-class IC has shipped),
    NOT an invented field — `soc-harness` is a real node in
    agents/class_kb/class-tree.yaml. It now says so instead of returning []."""
    l1 = docs.get("L1", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict) or not isinstance(l9, dict):
        return _na("K5-K", "L1 or L9 absent")
    cls = str(l1.get("class_path","")).lower()
    if "soc-harness" not in cls:
        return _na("K5-K", f"class_path {cls or '(empty)'!r} is not soc-harness "
                           "— pad grouping is only defined for harness ICs")
    # Grouped form: dict with named groups like power_group/io_group/mgmt_group
    for key in ("ports",) + _L9_PORT_KEYS:
        raw = _l9_top_container(l9).get(key) if key == "ports" else l9.get(key)
        if isinstance(raw, dict):
            keys = {str(k).lower() for k in raw.keys()}
            group_markers = {"power_group","io_group","mgmt_group",
                             "power","io","mgmt","management"}
            if keys & group_markers:
                return _seen("K5-K", [], len(_flatten_ports(raw)),
                             "ports are grouped by power/io/mgmt")
    flat = _l9_ports(l9)
    if not flat:
        return _na("K5-K", "L9 carries no top-level ports under any accepted "
                           "schema key")
    out = []
    if len(flat) >= 15:
        out = [{"id":"K5-K","severity":"warn",
            "msg":f"SoC-harness DTOP has {len(flat)} ports in one flat list (no power/io/mgmt grouping)"}]
    return _seen("K5-K", out, len(flat))


def check_pad_count_drift(docs):
    """K5-L: User brief vs Phase-1 pad-count drift (>=5 pads).

    REPAIR + DISCLOSE (#491): the L9 side now uses the #490 union. The L1 side
    is genuinely conditional — MEASURED 0/201 tracked L1 docs declare a pad
    count under any accepted key — so this check stays at population 0 and now
    SAYS so rather than returning []."""
    l1 = docs.get("L1", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict) or not isinstance(l9, dict):
        return _na("K5-L", "L1 or L9 absent")
    text = json.dumps(l1, default=str)
    m = re.search(r'MPRJ_IO_PADS\s*[=:]\s*(\d+)', text)
    declared = None
    if m:
        declared = int(m.group(1))
    else:
        # fallback: look for "pads": N or "pad_count": N in L1
        for key in ("pads","pad_count","io_pads","mprj_io_pads"):
            v = l1.get(key)
            if isinstance(v, int): declared = v; break
    if declared is None:
        return _na("K5-L", "L1 declares no pad count (MPRJ_IO_PADS / pads / "
                           "pad_count / io_pads / mprj_io_pads) — drift needs "
                           "a declared value to drift FROM")
    flat = _l9_ports(l9)
    if not flat:
        return _na("K5-L", "L9 carries no top-level ports under any accepted "
                           "schema key")
    pad_count = 0
    for p in flat:
        if not isinstance(p, dict): continue
        name = str(p.get("name","")).lower()
        if "pad" in name or "mprj_io" in name or "io[" in name:
            w = p.get("width")
            if isinstance(w, int) and w > 1: pad_count += w
            else: pad_count += 1
    if pad_count == 0:
        return _na("K5-L", f"L1 declares {declared} pads but none of the "
                           f"{len(flat)} L9 ports is pad-shaped — no comparable "
                           "quantity")
    delta = abs(pad_count - declared)
    out = []
    if delta >= 5:
        out = [{"id":"K5-L","severity":"warn",
            "msg":f"Pad-count drift: L1 declares {declared}, L9 has {pad_count} (delta {delta})"}]
    return _seen("K5-L", out, len(flat))


# K5-M check_axi_not_threaded — RETIRED (#491). See _RETIRED_CHECKS["K5-M"].
# K5-N check_memory_macro_placeholder — RETIRED (#491). See _RETIRED_CHECKS.
# K5-O check_tristate_not_hoisted — RETIRED (#491). See _RETIRED_CHECKS.
#
# All three were gated on keys no producer has ever emitted
# (`ports_mapped`, `tristate_rule`). K5-N was additionally a latent
# FALSE-POSITIVE generator: its "missing ports_mapped also counts as a
# placeholder" branch means the first memory-macro IC to ship would be
# reported as 100% placeholder submodules purely because the field does not
# exist. Retiring is the honest outcome, not a regression in coverage —
# there was no coverage.


def check_l1_class_path_missing(docs):
    """K5-P: L1.class_path is null/empty — silently disables class-keyed checkers.

    This is the one K5 check with a real, large population, and #491's audit
    confirms it is also the most load-bearing: MEASURED 163/201 tracked doc
    sets fire it. Its message now names the checks actually gated on
    class_path in the CURRENT check set (K5-F/H/K/S), not the retired ones."""
    # #491 round-2: `docs.get("L1", {})` cannot tell "L1 was never loaded"
    # from "L1 exists but declares no class_path" — the empty dict looks like
    # a document with a missing field, so a project with NO L1 at all used to
    # be reported as "L1 has no class_path field". That is the same
    # examined-nothing-but-spoke defect this issue is about, one level down.
    l1 = docs.get("L1")
    if "L1" not in docs or not isinstance(l1, dict):
        return _na("K5-P", "L1_DATASHEET.json absent — no document to carry a "
                           "class_path (this is NOT the same as a document "
                           "that omits the field)")
    gated = "K5-F/H/K/S"
    if "class_path" not in l1:
        return _seen("K5-P", [{"id":"K5-P","severity":"warn",
            "msg":f"L1 has no class_path field — disables {gated} class-keyed checkers"}], 1)
    v = l1.get("class_path")
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return _seen("K5-P", [{"id":"K5-P","severity":"warn",
            "msg":f"L1.class_path is null/empty — disables {gated} class-keyed checkers"}], 1)
    return _seen("K5-P", [], 1, f"class_path = {str(v)!r}")


def check_l6_states_schema_drift(docs):
    """K5-Q: L6.submodule_control_logic has states as list-of-dicts instead of
    list-of-strings.

    DISCLOSE (#491): sound check, never-produced input (0/201)."""
    l6 = docs.get("L6", {})
    if not isinstance(l6, dict):
        return _na("K5-Q", "L6 absent")
    subs = _l6_submodule_map(l6)
    if subs is None:
        return _na("K5-Q", _L6_SUBMODULE_MAP_ABSENT)
    drift = []
    examined = 0
    for name, cfg in subs.items():
        if not isinstance(cfg, dict): continue
        states = cfg.get("states")
        if isinstance(states, list) and states:
            examined += 1
            if any(isinstance(s, dict) for s in states):
                drift.append(name)
    if examined == 0:
        return _na("K5-Q", f"{len(subs)} submodule(s) present but none "
                           "declares a non-empty `states` list")
    out = []
    if drift:
        out = [{"id":"K5-Q","severity":"warn",
            "msg":f"L6 states schema drift: {len(drift)} submodule(s) have list-of-dicts states "
                  f"({', '.join(drift[:3])}{'...' if len(drift)>3 else ''}) — "
                  f"check_templated_fsms str-coerces and mis-classifies"}]
    return _seen("K5-Q", out, examined)


def check_soc_harness_no_interconnect(docs):
    """K5-S: soc-harness class with >=15 submodules but no interconnect topology.

    DISCLOSE + REPAIR (#491): the L9 submodule count now uses `_l9_submodules`
    so the shipped LIST container is counted (it was a dict-only read before).
    The check stays class-gated on `soc-harness`, which 0/201 tracked L1 docs
    declare — real class, no shipped IC of it — and now says so."""
    l1 = docs.get("L1", {})
    l6 = docs.get("L6", {})
    l9 = docs.get("L9", {})
    if not isinstance(l1, dict) or not isinstance(l9, dict):
        return _na("K5-S", "L1 or L9 absent")
    cls = str(l1.get("class_path","")).lower()
    if "soc-harness" not in cls:
        return _na("K5-S", f"class_path {cls or '(empty)'!r} is not soc-harness "
                           "— interconnect topology is only required of harness ICs")
    l6_subs = _l6_submodule_map(l6)
    l6_n = len(l6_subs) if l6_subs else 0
    l9_n = len(_l9_submodules(l9))
    if l6_n == 0 and l9_n == 0:
        return _na("K5-S", "neither L6.submodule_control_logic nor L9.submodules "
                           "enumerates any submodule")
    examined = max(l6_n, l9_n)
    if examined < 15:
        return _seen("K5-S", [], examined,
                     f"{examined} submodule(s) — below the >=15 threshold at "
                     "which a declared interconnect topology is required")
    # Look for interconnect topology fields anywhere in L9
    topo_keys = ("interconnect_topology","xbar_map","address_decode","bus_hierarchy")
    l9_text = json.dumps(l9, default=str).lower()
    if any(k in l9_text for k in topo_keys):
        return _seen("K5-S", [], examined, "interconnect topology declared")
    return _seen("K5-S", [{"id":"K5-S","severity":"warn",
        "msg":f"soc-harness class with {examined} submodules but L9 has no "
              f"interconnect_topology/xbar_map/address_decode/bus_hierarchy field"}],
        examined)


def check_crypto_params(docs):
    l1 = docs.get("L1", {})
    if not isinstance(l1, dict):
        return _na("K5-F", "L1 absent")
    cls_path = str(l1.get("class_path", "")).lower()
    if "crypto" not in cls_path:
        return _na("K5-F", f"class_path {cls_path or '(empty)'!r} is not a "
                           "crypto class")
    fam = str(l1.get("crypto_family", "")).lower()
    if fam not in ("block-cipher","hash-function","stream-cipher"):
        return _na("K5-F", f"L1.crypto_family {fam or '(absent)'!r} is not one "
                           "of block-cipher/hash-function/stream-cipher — the "
                           "key-schedule requirement is defined per family")
    keywords = ("key_schedule","round_constants","key_expansion",
                "round_keys","iv_init","h_init","h0","k_constants",
                "initial_hash","round_function")
    text = json.dumps(docs, default=str).lower()
    out = []
    if not any(kw in text for kw in keywords):
        out = [{"id":"K5-F","severity":"warn",
            "msg":f"Crypto IC ({fam}) missing key schedule / round constants"}]
    return _seen("K5-F", out, 1, f"crypto_family={fam}")


# ---------------------------------------------------------------------------
# v0.74 Task-C Stage-C3: consume fact-UUID markers emitted by Phase-2 RTL
#
# Convention (docs/design/PHASE1_FACT_UUID_PROPOSAL.md §3.1-3.3):
#
#     // phase1-fact: <uuid> path=<L.path> source=<provenance_source>
#     localparam BIT_PERIOD_CYCLES = 200;
#
# This check scans Verilog/SystemVerilog sources for the marker regex and
# cross-references each hit against fact_index.json + facts.yaml emitted
# by Phase-1 render. Three classifications:
#
#   K5-T  missing_fact_uuid     — UUID in RTL not present in fact_index
#                                (fact renamed/deleted since render)
#   K5-U  fact_value_mismatch   — RTL literal disagrees with current fact
#                                value (stale RTL, needs re-render)
#   K5-V  multi_fact_conflict   — multiple markers on same construct point
#                                at facts whose values are inconsistent
# ---------------------------------------------------------------------------
FACT_MARKER_RE = re.compile(
    r"//\s*phase1-fact:\s*(?P<uuid>[0-9a-fA-F-]{8,})\s+"
    r"path=(?P<path>[^\s]+)\s+"
    r"source=(?P<source>\w+)"
)


def _extract_rtl_literal(line: str):
    """Given the RTL line immediately after a marker, try to extract a
    literal value following `=`. Returns the raw string token or None.
    Handles `localparam NAME = 200;`, `assign x = 32'h1234;`, etc. —
    best-effort regex, not a real Verilog parser."""
    m = re.search(r"=\s*([^\s;,]+)", line)
    return m.group(1) if m else None


def _parse_rtl_for_markers(rtl_path):
    """Walk a dir (or single file) of .v / .sv, yield
    (file, line_no, marker_dict, following_line_or_None)."""
    out = []
    paths = []
    p = Path(rtl_path)
    if p.is_dir():
        paths += sorted(p.rglob("*.v")) + sorted(p.rglob("*.sv"))
    elif p.is_file():
        paths = [p]
    for f in paths:
        try:
            lines = f.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        # Group consecutive markers so multi-marker constructs are detected.
        i = 0
        while i < len(lines):
            m = FACT_MARKER_RE.search(lines[i])
            if not m:
                i += 1
                continue
            group = [{"line": i + 1, **m.groupdict()}]
            j = i + 1
            while j < len(lines):
                m2 = FACT_MARKER_RE.search(lines[j])
                if not m2:
                    break
                group.append({"line": j + 1, **m2.groupdict()})
                j += 1
            next_non_marker = lines[j] if j < len(lines) else ""
            for marker in group:
                marker["group_size"] = len(group)
            out.append({
                "file": str(f),
                "markers": group,
                "next_line": next_non_marker,
            })
            i = j + 1
    return out


def _coerce_value_for_compare(rtl_lit, fact_value):
    """Best-effort normalization so '200' and 200 compare equal, and
    Verilog hex like "8'h31" matches fact value "0x31". Returns
    (rtl_norm, fact_norm) for equality check."""
    if rtl_lit is None:
        return None, None
    rl = str(rtl_lit).strip().rstrip(";")
    fv = fact_value
    # Strip Verilog sized-hex prefix  '  ->  '
    m = re.match(r"^\d+'([bBhHoOdD])(.+)$", rl)
    if m:
        kind = m.group(1).lower()
        digits = m.group(2).replace("_", "")
        try:
            val = int(digits, {"b": 2, "o": 8, "d": 10, "h": 16}[kind])
            rl_num = val
        except ValueError:
            rl_num = None
    else:
        try: rl_num = int(rl)
        except ValueError:
            try: rl_num = int(rl, 0)   # 0x / 0b / 0o prefixes
            except (ValueError, TypeError): rl_num = None
    fv_num = None
    if isinstance(fv, (int, bool)) and not isinstance(fv, bool):
        fv_num = int(fv)
    elif isinstance(fv, str):
        try: fv_num = int(fv, 0)
        except (ValueError, TypeError): fv_num = None
    if rl_num is not None and fv_num is not None:
        return rl_num, fv_num
    return rl, str(fv) if fv is not None else None


def check_fact_uuid_markers(rtl_dir, fact_index_path, facts_yaml_path=None):
    """Scan RTL under rtl_dir for phase1-fact markers and classify each.

    fact_index_path : JSON file { path: uuid } emitted by render.
    facts_yaml_path : optional — used for value-mismatch detection.
                      Without it, only missing_fact_uuid is reported.
    Returns list of issue dicts.
    """
    if not Path(fact_index_path).exists():
        return [{"id": "K5-T", "severity": "warn",
                 "msg": f"fact_index.json not found at {fact_index_path} — "
                        "skipping marker check"}]
    index = json.loads(Path(fact_index_path).read_text())
    # Invert: uuid -> path
    uuid_to_path = {u: p for p, u in index.items()}

    facts_by_path = {}
    if facts_yaml_path and Path(facts_yaml_path).exists():
        # Lazy-import yaml; tools/phase1_engine/schema loads the whole graph.
        try:
            import yaml
            fg = yaml.safe_load(Path(facts_yaml_path).read_text())
            for fact in (fg or {}).get("facts", []) or []:
                facts_by_path[fact.get("path")] = fact.get("value")
        except Exception:
            pass

    issues = []
    entries = _parse_rtl_for_markers(rtl_dir)
    for entry in entries:
        f = entry["file"]
        markers = entry["markers"]
        next_line = entry["next_line"]
        rtl_lit = _extract_rtl_literal(next_line)

        # K5-T: unknown UUIDs
        for m in markers:
            if m["uuid"] not in uuid_to_path:
                issues.append({
                    "id": "K5-T", "severity": "warn",
                    "msg": f"{f}:{m['line']} marker points at unknown "
                           f"fact UUID {m['uuid']} (path was {m['path']}) — "
                           "fact may have been renamed or deleted since render",
                })

        # K5-U: value mismatch (only if we have facts.yaml and RTL literal)
        if facts_by_path and rtl_lit is not None:
            for m in markers:
                fact_path = m["path"]
                if fact_path not in facts_by_path:
                    continue
                fv = facts_by_path[fact_path]
                if fv is None:
                    continue
                rl_n, fv_n = _coerce_value_for_compare(rtl_lit, fv)
                if rl_n is not None and fv_n is not None and rl_n != fv_n:
                    issues.append({
                        "id": "K5-U", "severity": "warn",
                        "msg": f"{f}:{m['line']} RTL has {rtl_lit!r} but "
                               f"fact {fact_path} now = {fv!r} — "
                               "RTL is stale vs current facts.yaml",
                    })

        # K5-V: multi-marker group with inconsistent values
        if len(markers) >= 2 and facts_by_path:
            vals = {}
            for m in markers:
                if m["path"] in facts_by_path:
                    vals[m["path"]] = facts_by_path[m["path"]]
            distinct = set()
            for v in vals.values():
                try: distinct.add(json.dumps(v, sort_keys=True))
                except TypeError: distinct.add(repr(v))
            if len(distinct) > 1:
                issues.append({
                    "id": "K5-V", "severity": "warn",
                    "msg": f"{f}:{markers[0]['line']} {len(markers)} markers on "
                           f"same construct but facts disagree: {vals}",
                })
    return issues


_L_DOC_FILES = [("L1","L1_DATASHEET.json"),("L4","L4_REGMAP.json"),
                ("L6","L6_CONTROL_LOGIC.json"),("L8","L8_TIMING_WAVEFORM.json"),
                ("L9","L9_INTEGRATION_SPEC.json")]

# (check_id, callable) — the CURRENT check set. Retired checks are absent
# here and recorded in _RETIRED_CHECKS instead.
_CHECKS = [
    ("K5-A", lambda d: check_templated_fsms(d.get("L6", {}))),
    ("K5-B", lambda d: check_register_overlap(d.get("L4", {}))),
    ("K5-D", lambda d: check_duplicate_port_keys(d.get("L9", {}))),
    ("K5-E", check_reset_polarity_split),
    ("K5-F", check_crypto_params),
    ("K5-G", check_fifo_bitfield_missing),
    ("K5-H", check_scope_class_mismatch),
    ("K5-I", check_mmio_vs_native_bus_conflict),
    ("K5-K", check_soc_harness_no_grouping),
    ("K5-L", check_pad_count_drift),
    ("K5-P", check_l1_class_path_missing),
    ("K5-Q", check_l6_states_schema_drift),
    ("K5-S", check_soc_harness_no_interconnect),
]


def load_docs(gen_dir):
    docs = {}
    for L, fn in _L_DOC_FILES:
        p = Path(gen_dir) / fn
        if p.exists():
            try: docs[L] = lenient_load(p)
            except Exception: pass
    return docs


def run_on_with_census(gen_dir):
    """(findings, census) — the honest form.

    census = {"docs_loaded": [...], "checks": [ {check_id, applicable,
    examined, findings, note}, ... ], "examined_total": int,
    "checks_applicable": int, "retired": {...}}.

    #491: this is what lets a caller tell "checked, nothing wrong" from
    "nothing to check". `run_on` remains a findings-only wrapper so existing
    callers are untouched."""
    docs = load_docs(gen_dir)
    findings, per_check = [], []
    for check_id, fn in _CHECKS:
        try:
            res = fn(docs)
        except Exception as exc:                     # never let one check kill the gate
            per_check.append({"check_id": check_id, "applicable": False,
                              "examined": 0, "findings": 0,
                              "note": f"check raised {type(exc).__name__}: {exc}"})
            continue
        if not isinstance(res, CheckResult):
            # A check that has not been migrated cannot disclose; count it as
            # examined-unknown rather than silently claiming coverage.
            res = CheckResult(res, check_id=check_id, applicable=True,
                              examined=0, note="check did not report a census")
        if res.check_id != check_id:
            res.check_id = check_id
        findings.extend(res)
        per_check.append(res.census())
    census = {
        "docs_loaded": sorted(docs.keys()),
        "checks": per_check,
        "checks_total": len(_CHECKS),
        "checks_applicable": sum(1 for c in per_check if c["applicable"]),
        "examined_total": sum(c["examined"] for c in per_check),
        "retired": {k: v["was"] for k, v in _RETIRED_CHECKS.items()},
    }
    return findings, census


def run_on(gen_dir):
    """Findings only — unchanged signature for existing callers."""
    findings, _census = run_on_with_census(gen_dir)
    return findings


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    # v0.74 Task-C Stage-C3: optional fact-UUID marker scan over Phase-2 RTL
    ap.add_argument("--rtl",
                    help="directory (or single file) of Phase-2 RTL to scan "
                         "for phase1-fact: markers")
    ap.add_argument("--fact-index",
                    help="path to fact_index.json (emitted by phase1 render)")
    ap.add_argument("--facts",
                    help="optional path to facts.yaml — enables K5-U / K5-V "
                         "value-mismatch + multi-fact-conflict checks")
    args = ap.parse_args(argv)

    if args.all:
        targets = sorted((WORKTREE / "benchmark/phase1_v046").rglob("generated_docs"))
        total = 0; issues = Counter(); per_ic = {}
        for t in targets:
            if not t.is_dir(): continue
            total += 1
            fs = run_on(t)
            if fs:
                per_ic[t.parent.name] = fs
                for f in fs: issues[f["id"]] += 1
        print(f"Scanned {total} ICs")
        print(f"ICs with >=1 K5 issue: {len(per_ic)}")
        print(f"\nIssue totals:")
        for cat, n in sorted(issues.items()): print(f"  {cat}: {n}")
        print(f"\nTop 15 ICs:")
        for ic, fs in sorted(per_ic.items(), key=lambda x: -len(x[1]))[:15]:
            cats = ",".join(f['id'] for f in fs)
            print(f"  {len(fs):2}  {ic:<25} [{cats}]")
        return 0

    census = None
    if args.rtl and args.fact_index and not args.target:
        # Stand-alone Stage-C3 mode: scan RTL only, no L*.json doc checks.
        # No census: this mode runs the marker scan, not the K5 doc checks.
        fs = check_fact_uuid_markers(
            rtl_dir=args.rtl,
            fact_index_path=args.fact_index,
            facts_yaml_path=args.facts,
        )
    else:
        if not args.target: ap.error("--all or <dir> (or --rtl + --fact-index)")
        fs, census = run_on_with_census(Path(args.target))
        if args.rtl and args.fact_index:
            fs = list(fs) + check_fact_uuid_markers(
                rtl_dir=args.rtl,
                fact_index_path=args.fact_index,
                facts_yaml_path=args.facts,
            )
    if args.json:
        print(json.dumps({"findings": fs, "census": census} if census
                         else fs, indent=2, ensure_ascii=False))
    else:
        # ORGANIC #491 — a PASS must disclose its denominator. Printing
        # "No K5 quality issues detected." while every check examined
        # nothing is exactly the false certificate this gate used to emit.
        if census:
            checked = [c for c in census["checks"]
                       if c["applicable"] and c["examined"] > 0]
            vacuous = [c for c in census["checks"]
                       if not c["applicable"] or c["examined"] == 0]
            print(f"K5 census: docs loaded {census['docs_loaded'] or 'NONE'}; "
                  f"{len(checked)}/{census['checks_total']} checks examined "
                  f"anything; {census['examined_total']} unit(s) examined "
                  f"in total.")
            for c in checked:
                print(f"  CHECKED     {c['check_id']}: examined "
                      f"{c['examined']}, findings {c['findings']}"
                      + (f" ({c['note']})" if c['note'] else ""))
            for c in vacuous:
                print(f"  NOT CHECKED {c['check_id']}: {c['note'] or 'no data'}")
        if not fs:
            if census and not any(c["applicable"] and c["examined"] > 0
                                  for c in census["checks"]):
                print("NOT CHECKED — no K5 check could examine anything on "
                      "this project (see census above). This is NOT a clean "
                      "result.")
            else:
                print("No K5 quality issues detected "
                      f"({census['examined_total'] if census else 0} unit(s) "
                      "examined).")
        else:
            for f in fs: print(f"  [{f['severity']}] {f['id']}: {f['msg']}")

    # rc 2 = NOT CHECKED / VACUOUS. `flow_compliance_check` maps rc 2 to a
    # NAMED SKIP and anything that is neither 1 nor 2 to ("pass", None) — so
    # returning 0 here when nothing was examined is what made this gate a
    # permanent silent PASS inside the P0 umbrella. K5 findings stay
    # advisory (severity=warn by design), so a run that DID examine
    # something returns 0 whether or not it found anything.
    if census and census["examined_total"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
