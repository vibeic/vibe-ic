#!/usr/bin/env python3
"""si_signoff_timing_aware.py — OPEN-SOURCE timing-window-aware SI ADVISORY screen.

WHAT THIS IS
============
A deterministic, chip-AGNOSTIC signal-integrity (crosstalk-noise) ADVISORY
SCREEN that upgrades the legacy *floating-victim* coupling-ratio advisory bound
(the `_si_coupling_metrics` in phase3_one_shot_runner.py, where
`violations_count` is always 0) by adding switching-window decoupling, built
entirely from open-source tooling:

    OpenSTA  (per-pin arrival windows + slews; read_spef + report_arrival)
  + SPEF     (per-net ground cap Cg + per-net-pair coupling cap Cc, OpenRCX)
  + a lumped capacitive-divider noise model gated by aggressor/victim
    switching-window OVERLAP and driver damping.

WHAT IT CAN AND CANNOT CONCLUDE  (read this before quoting any number)
======================================================================
This open-source lumped screen is CONCLUSIVE IN ONE DIRECTION ONLY:

  * It CAN conclusively rule a coupling PAIR *safe* when the aggressor and
    victim switching windows DO NOT OVERLAP: a coupling event is then
    timing-impossible (decoupled). This is the real upgrade over the legacy
    floating-only advisory, which could not decouple anything. The decoupled
    count (`pairs_decoupled_by_window`) is a conclusive SAFE result.

  * It CANNOT conclusively PROVE a failure. The noise estimate is the
    capacitive-divider step `Cc/(Cc+Cg)*Vdd`, which is a *floating-victim
    UPPER BOUND*. On a real dense routed design a high coupling ratio (~0.99)
    on a DRIVEN net is NORMAL, not a proven SI failure: the driven victim is
    held by its driver's low impedance and sees far less than the floating
    divider step. The 0.5 driven-victim damping derate still massively
    over-estimates a driven victim's true transient noise. A true pass/fail
    needs foundry CCS-Noise / receiver noise-immunity models + RLC(K)
    extraction (mutual inductance, reflections) — which this honestly does
    NOT have. Those are a PHYSICAL need for foundry-calibrated models, not a
    commercial-tool lock-in.

So this screen NEVER emits a build-failing PASS/FAIL verdict. It emits a
single ADVISORY verdict (`SI_TIMING_AWARE_SCREEN`) plus two WATCH-LIST tiers:
  - HIGH: switching windows overlap AND the gated bound exceeds the margin
          -> "coupling-dominated, switching-window overlaps — flagged for
          commercial SI review". FLAGGED, not proven-failing.
  - LOW:  the floating bound exceeds the margin but window/driver gating
          cleared it (overlap impossible or below margin after gating).
It does not claim commercial equivalence and never fabricates a flag: a pair
is HIGH-flagged only when (overlap == True) AND (gated noise > margin).

THE TWO HALVES (per the task)
=============================
(1) PURE-PYTHON SCORER  — `score_si_timing_aware(...)` takes the OpenSTA
    timing JSON + the SPEF text (or pre-parsed structures) and returns a
    deterministic verdict dict. Offline-testable; no tools needed.
(2) OPENSTA TCL RECIPE  — `build_opensta_si_tcl(...)` emits the exact TCL
    the runner feeds to `sta` (read_liberty / read_verilog / link_design /
    read_sdc / read_spef / per-pin report_arrival+report_slews captured via
    sta::redirect_string) to PRODUCE that timing JSON. OpenSTA 2.7.0 has no
    `report_timing -json`, so we emit the JSON ourselves from the stable
    report-string API. The shape it emits is documented in `TIMING_JSON_SHAPE`.

PUBLIC API (what the phase3 runner calls)
=========================================
    run_si_signoff_timing_aware(
        spef_path: str | Path,
        timing_json_path: str | Path,
        *,
        vdd_v: float = 1.8,
        noise_margin_mv: float = 100.0,
        out_json: str | Path | None = None,
        out_rpt: str | Path | None = None,
    ) -> dict

To PRODUCE the timing JSON, the runner first writes+runs the TCL from
`build_opensta_si_tcl(...)` inside the OpenSTA container (it already has
`_docker_exec` + `_to_container_path`). See `TIMING_JSON_SHAPE` for the
schema the TCL emits and the scorer consumes.

CLI:
    python3 si_signoff_timing_aware.py score  <spef> <timing.json> [opts]
    python3 si_signoff_timing_aware.py emit-tcl <out.tcl> --liberty ... \\
            --netlist ... --top chip_top --sdc ... --spef ... --out-json ...

Exit codes (score): 0 always (this is an ADVISORY screen — it NEVER fails a
                     build). With the opt-in `--strict`, exit 1 iff the HIGH
                     watch-list is non-empty (for callers that want a hard
                     advisory gate). 2 IO / arg error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

PathLike = Union[str, Path]

# ---------------------------------------------------------------------------
# Schema the OpenSTA TCL emits and the scorer consumes. Documented so the
# runner and any offline test agree on the contract.
# ---------------------------------------------------------------------------
TIMING_JSON_SHAPE = {
    "tool": "OpenSTA",
    "design": "<top>",
    "time_unit": "ns",
    "vdd_v": 1.8,
    "pins": {
        "<pin_full_name>": {
            "arr_rise_min": "float|null (ns)",
            "arr_rise_max": "float|null (ns)",
            "arr_fall_min": "float|null (ns)",
            "arr_fall_max": "float|null (ns)",
            "slew_rise_max": "float|null (ns)",
            "slew_fall_max": "float|null (ns)",
            # setup (max-path) slack at this pin, ns. Present when the OpenSTA
            # build supports report_slack; null otherwise -> the delta-delay
            # screen degrades to ADVISORY for nets touching that pin (it cannot
            # prove a path is pushed negative without a slack basis). §4.05.
            "slack_max": "float|null (ns)",
        }
    },
}


# ===========================================================================
# SPEF parsing  (re-implemented standalone; mirrors phase3's _parse_spef_caps
# but additionally recovers per-net-pair coupling + the driver pin per net so
# we can build switching windows). IEEE-1481. Pure + deterministic.
# ===========================================================================
def parse_spef(text: str) -> dict:
    """Parse an IEEE-1481 SPEF into the structures the SI scorer needs.

    Returns a dict with:
      name_map  : {"*5": "mdc", ...}  (idx-name -> real signal name)
      cg        : {net: ground_cap_sum}
      cc        : {net: coupling_cap_sum}              (legacy ratio metric)
      pair_cc   : {frozenset({netA, netB}): Cc_sum}    (per-pair coupling)
      net_driver_pins  : {net: [driver_pin_full_name, ...]}  (CONN '... O')
      net_load_pins    : {net: [load_pin_full_name,  ...]}   (CONN '... I')
      c_unit_pf : float  (multiplier to convert SPEF cap values to pF)

    CRITICAL — node-to-net attribution (the correctness heart of this parser):
    A SPEF *CAP coupling line couples two NODES, e.g.
        `11 *3069:A *3064:A1 0.000251021`
    where `*3069:A` is the *A* pin of INSTANCE *3069 (NOT a net) — it is a LOAD
    on whatever D_NET's *CONN section lists it. Naively splitting at ':' (the
    legacy `_si_coupling_metrics` does this) attributes the coupling to the
    INSTANCE id `*3069`, which is meaningless as a net and makes every coupling
    look like it lands on an undriven floating net (=> spurious full-Vdd noise).
    So we instead build a NODE -> owning-D_NET map: every node token that
    appears inside a D_NET's *CONN (pins) or *CAP (ground-cap single nodes, RC
    subnodes) belongs to THAT net. Coupling pairs are then attributed via this
    map, so `*3069:A`'s coupling lands on the real driven net (e.g. *1 / busy).

    The CONN section also gives, per net, which instance/port pin DRIVES it (O)
    and which are LOADS (I) — that is how we know a net's switching window.

    NOTE on units: the Cc/(Cc+Cg) *ratio* is unit-cancelling, and the noise =
    ratio*Vdd is a fraction of Vdd, so no unit conversion is required for the
    noise estimate. c_unit_pf is surfaced only for diagnostics."""
    name_map: Dict[str, str] = {}
    cg: Dict[str, float] = {}
    cc: Dict[str, float] = {}
    pair_cc: Dict[frozenset, float] = {}
    net_driver_pins: Dict[str, List[str]] = {}
    net_load_pins: Dict[str, List[str]] = {}
    node_net: Dict[str, str] = {}        # node token -> owning D_NET id
    c_unit_pf = 1.0

    delimiter = ":"
    section: Optional[str] = None
    cur_net: Optional[str] = None
    # raw coupling lines deferred to a 2nd pass once node_net is complete
    raw_pairs: List[Tuple[str, str, float]] = []

    def _net(tok: str) -> str:
        """Best-effort net id for a node when it is NOT in node_net.

        For an RC subnode `*1:6` the prefix `*1` IS the net; for a bare net
        name (`busy`) the token itself is the net. This is the fallback only —
        the authoritative source is the node_net membership map."""
        return tok.split(delimiter, 1)[0] if delimiter in tok else tok

    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue

        # --- header directives ---
        if s.startswith("*DELIMITER"):
            toks = s.split()
            if len(toks) >= 2:
                delimiter = toks[1]
            continue
        if s.startswith("*C_UNIT"):
            # e.g. "*C_UNIT 1 PF" / "*C_UNIT 1 FF"
            toks = s.split()
            if len(toks) >= 3:
                try:
                    scale = float(toks[1])
                except ValueError:
                    scale = 1.0
                unit = toks[2].upper()
                # convert the named unit to pF
                per = {"PF": 1.0, "FF": 1e-3, "F": 1e12, "NF": 1e3}.get(unit, 1.0)
                c_unit_pf = scale * per
            continue
        if s.startswith("*NAME_MAP"):
            section = "name_map"
            continue

        # --- net section boundaries ---
        if s.startswith("*D_NET") or s.startswith("*D_PNET"):
            toks = s.split()
            cur_net = toks[1] if len(toks) >= 2 else None
            section = "dnet"
            continue
        if s.startswith("*CONN"):
            section = "conn"
            continue
        if s.startswith("*CAP"):
            section = "cap"
            continue
        if s.startswith("*RES"):
            section = "res"
            continue
        if s.startswith("*END"):
            section = "dnet" if cur_net else None
            cur_net = None
            continue
        if s.startswith("*PORTS"):
            section = None
            continue

        # --- section bodies ---
        if section == "name_map":
            # "*5 mdc"
            toks = s.split()
            if len(toks) >= 2 and toks[0].startswith("*"):
                name_map[toks[0]] = toks[1]
            continue

        if section == "conn" and cur_net is not None:
            # IMPORTANT — *P and *I direction semantics DIFFER:
            #   "*I *2998:A I ..."  -> INSTANCE pin; direction is net-relative:
            #        O = this instance pin DRIVES the net, I = it LOADS the net.
            #   "*P clk I"          -> top-level PORT; direction is the PORT's
            #        I/O: I = INPUT port (an external/off-chip driver of the net
            #        => DRIVER), O = OUTPUT port (driven internally => LOAD).
            # Conflating these (treating *P ... I as a load) makes every primary
            # input net look floating => spurious full-Vdd noise. We map each to
            # the correct driver/load role here.
            toks = s.split()
            if not toks:
                continue
            kind = toks[0]
            if kind not in ("*P", "*I"):
                continue
            if len(toks) < 3:
                continue
            pin_tok = toks[1]
            raw_dir = toks[2]
            # normalise to net-relative driver/load
            if kind == "*P":
                # input port (I) drives the net; output port (O) loads it
                is_driver = (raw_dir == "I")
            else:  # *I instance pin: O drives, I loads
                is_driver = (raw_dir == "O")
            # this pin-node electrically belongs to cur_net
            node_net[pin_tok] = cur_net
            # map idx-prefixed pin name to a readable full name where possible
            pin_name = _map_pin(pin_tok, name_map, delimiter)
            if is_driver:
                net_driver_pins.setdefault(cur_net, []).append(pin_name)
            else:
                net_load_pins.setdefault(cur_net, []).append(pin_name)
            continue

        if section == "cap":
            toks = s.split()
            # "idx node value"  or  "idx node1 node2 value"
            if len(toks) >= 3 and toks[0].lstrip("-").isdigit():
                try:
                    val = float(toks[-1])
                except ValueError:
                    continue
                nodes = toks[1:-1]
                if len(nodes) == 1:
                    # ground cap on a node OF cur_net -> credit cur_net.
                    n = cur_net if cur_net else _net(nodes[0])
                    if cur_net:
                        node_net[nodes[0]] = cur_net
                    cg[n] = cg.get(n, 0.0) + val
                elif len(nodes) == 2:
                    # one node is ON cur_net (the victim side of this D_NET),
                    # the other belongs to a different D_NET. Record cur_net
                    # membership for the local node, defer attribution to pass 2.
                    if cur_net:
                        node_net.setdefault(nodes[0], cur_net)
                    raw_pairs.append((nodes[0], nodes[1], val))
            continue

    # ----- pass 2: attribute coupling pairs to real D_NETs via node_net -----
    def _resolve(node: str) -> str:
        if node in node_net:
            return node_net[node]
        # fall back: bare net name or RC-subnode prefix
        return _net(node)

    for na, nb, val in raw_pairs:
        ra, rb = _resolve(na), _resolve(nb)
        cc[ra] = cc.get(ra, 0.0) + val
        cc[rb] = cc.get(rb, 0.0) + val
        if ra != rb:
            key = frozenset((ra, rb))
            pair_cc[key] = pair_cc.get(key, 0.0) + val

    return {
        "name_map": name_map,
        "cg": cg,
        "cc": cc,
        "pair_cc": pair_cc,
        "net_driver_pins": net_driver_pins,
        "net_load_pins": net_load_pins,
        "node_net": node_net,
        "c_unit_pf": c_unit_pf,
        "delimiter": delimiter,
    }


def _map_pin(pin_tok: str, name_map: Dict[str, str], delimiter: str) -> str:
    """Map a SPEF pin token to a readable full name.

    "*2998:A" -> "<mapped 2998>/A" when *2998 is in name_map, else "*2998:A".
    A top-level port like "mdc" passes through unchanged. We translate ':' to
    '/' so the pin name matches OpenSTA's get_full_name convention
    (instance/pin)."""
    if delimiter in pin_tok:
        base, _, leaf = pin_tok.partition(delimiter)
        if base in name_map:
            return f"{name_map[base]}/{leaf}"
        return pin_tok
    return pin_tok


# ===========================================================================
# Timing-window extraction from the OpenSTA timing JSON
# ===========================================================================
def load_timing_json(text_or_path: PathLike) -> dict:
    """Load the OpenSTA SI timing JSON. Accepts a path or a JSON string."""
    p = Path(str(text_or_path))
    if p.exists():
        data = json.loads(p.read_text())
    else:
        data = json.loads(str(text_or_path))
    if "pins" not in data or not isinstance(data["pins"], dict):
        raise ValueError("timing JSON missing a 'pins' object")
    return data


def _pin_window(pin_rec: dict) -> Optional[Tuple[float, float]]:
    """The switching window [t_lo, t_hi] (ns) of a pin from its rise/fall
    arrival min/max. We take the union of the rise and fall arrival ranges:
    the pin can transition anywhere in that interval. Returns None if no
    numeric arrival is present (e.g. an undriven / constant pin)."""
    vals: List[float] = []
    for k in ("arr_rise_min", "arr_rise_max", "arr_fall_min", "arr_fall_max"):
        v = pin_rec.get(k)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    if not vals:
        return None
    return (min(vals), max(vals))


def _pin_slew(pin_rec: dict) -> float:
    """Worst-case (max) slew of a pin in ns; 0.0 if unknown."""
    vals = [pin_rec.get("slew_rise_max"), pin_rec.get("slew_fall_max")]
    nums = [float(v) for v in vals if isinstance(v, (int, float))]
    return max(nums) if nums else 0.0


def _pin_slack(pin_rec: dict) -> Optional[float]:
    """Setup (max-path) slack of a pin in ns; None if the STA run did not
    supply a slack for it (older OpenSTA build without report_slack, or a pin
    off any timed path). None is HONEST: the delta-delay screen must not invent
    a slack it does not have."""
    v = pin_rec.get("slack_max")
    return float(v) if isinstance(v, (int, float)) else None


def compute_net_slacks(
    net_load_pins: Dict[str, List[str]],
    net_driver_pins: Dict[str, List[str]],
    timing_pins: Dict[str, dict],
) -> Dict[str, Optional[float]]:
    """Per net, the WORST (minimum) setup slack among its driver + load pins.

    A coupling delta-delay lands on the arrival at the net's load pins; the
    path most at risk of being pushed negative is the one with the least slack,
    so we take the min over the net's pins that HAVE a slack. Returns
    {net: slack_ns or None}; None means no pin of the net carried a slack (the
    delta-delay screen then cannot prove a push-negative for that net -> it
    contributes to an ADVISORY verdict, never a fabricated FAIL/PASS)."""
    out: Dict[str, Optional[float]] = {}
    nets = set(net_load_pins) | set(net_driver_pins)
    for net in nets:
        best: Optional[float] = None
        for pin in (net_load_pins.get(net, []) + net_driver_pins.get(net, [])):
            rec = timing_pins.get(pin)
            if rec is None:
                continue
            s = _pin_slack(rec)
            if s is None:
                continue
            best = s if best is None else min(best, s)
        out[net] = best
    return out


def compute_net_windows(
    net_driver_pins: Dict[str, List[str]],
    timing_pins: Dict[str, dict],
) -> Dict[str, dict]:
    """Per net, derive a switching window + driver slew from the net's DRIVER
    pin arrival window (the CONN 'O' pin). A net switches when its driver
    transitions, so the driver pin's arrival window IS the net's switching
    window. Pad the window by the driver slew (the transition takes ~slew to
    complete). Returns {net: {"win": (lo, hi), "slew": s, "driven": bool}}."""
    out: Dict[str, dict] = {}
    for net, drivers in net_driver_pins.items():
        best_win: Optional[Tuple[float, float]] = None
        best_slew = 0.0
        driven = bool(drivers)
        for dp in drivers:
            rec = timing_pins.get(dp)
            if rec is None:
                continue
            w = _pin_window(rec)
            s = _pin_slew(rec)
            if w is None:
                continue
            # window padded by slew on the trailing edge (transition duration)
            w = (w[0], w[1] + s)
            if best_win is None:
                best_win = w
            else:
                best_win = (min(best_win[0], w[0]), max(best_win[1], w[1]))
            best_slew = max(best_slew, s)
        out[net] = {"win": best_win, "slew": best_slew, "driven": driven}
    return out


def _windows_overlap(a: Optional[Tuple[float, float]],
                     b: Optional[Tuple[float, float]],
                     guard_ns: float = 0.0) -> bool:
    """Do two switching windows overlap (within a guard band)? If either
    window is unknown, we CONSERVATIVELY assume overlap (cannot prove
    decoupling) — honesty: an unknown window is not evidence of safety."""
    if a is None or b is None:
        return True
    return (a[0] - guard_ns) <= b[1] and (b[0] - guard_ns) <= a[1]


# ===========================================================================
# The core scorer
# ===========================================================================
def score_si_timing_aware(
    spef: Union[str, dict],
    timing: Union[str, dict, PathLike],
    *,
    vdd_v: float = 1.8,
    noise_margin_mv: float = 100.0,
    overlap_guard_ns: float = 0.0,
) -> dict:
    """Deterministic timing-window-aware SI screen.

    Args:
      spef    : SPEF text OR a pre-parsed dict from parse_spef().
      timing  : OpenSTA timing JSON path / JSON string / pre-loaded dict
                (shape == TIMING_JSON_SHAPE).
      vdd_v   : supply (default 1.8 V for sky130).
      noise_margin_mv : DC noise margin a glitch must exceed to count as a
                violation (default 100 mV ~ sky130 1.8 V std-cell guidance).
      overlap_guard_ns : slack added to the overlap test (0 = strict).

    Returns a verdict dict (the report body). The verdict is ALWAYS the single
    advisory value `SI_TIMING_AWARE_SCREEN` — there is no PASS/FAIL split that
    implies sign-off. The decision per coupling PAIR (aggressor a -> victim v):
        base_noise_v = Cc / (Cc + Cg_victim) * Vdd     # floating UPPER BOUND
        if NOT windows_overlap(win_a, win_v):  decoupled -> CONCLUSIVELY SAFE
        elif victim is DRIVEN:                  gated_noise = base * damping
        else (floating victim):                 gated_noise = base   # full
      A pair is flagged onto the HIGH watch-list only when overlap AND
      gated_noise > margin ("coupling-dominated, switching-window overlaps —
      flagged for commercial SI review"). HIGH-flagged is NOT a proven failure:
      the floating divider bound over-claims on driven nets, where a high
      coupling ratio in dense routing is normal. A pair lands on the LOW
      watch-list when the floating bound exceeds the margin but window/driver
      gating cleared it. The decoupled (non-overlapping) pairs are the only
      conclusively-safe result.

    Damping: a driven victim is held by its driver's low impedance, so the
    coupled step is attenuated. We use a conservative, monotone derate of 0.5
    (a driven net sees at most ~half the floating divider step for typical
    digital aggressor/victim driver-strength ratios). This is a SCREEN
    derate, NOT a solved attenuation — stated explicitly in the report."""
    if isinstance(spef, dict):
        sp = spef
    else:
        sp = parse_spef(spef)
    if isinstance(timing, dict):
        tj = timing
    else:
        tj = load_timing_json(timing)

    pins = tj.get("pins", {})
    vdd_mv = vdd_v * 1000.0
    DRIVEN_DAMPING = 0.5  # conservative screen derate for a driven victim

    cg = sp["cg"]
    pair_cc = sp["pair_cc"]
    name_map = sp.get("name_map", {})
    net_windows = compute_net_windows(sp["net_driver_pins"], pins)

    def _label(net: str) -> str:
        """Readable name for a SPEF net id: '*81' -> '_023_' when mapped."""
        return name_map.get(net, net)

    def _win(net: str) -> Optional[Tuple[float, float]]:
        rec = net_windows.get(net)
        return rec["win"] if rec else None

    def _driven(net: str) -> bool:
        rec = net_windows.get(net)
        return bool(rec and rec["driven"])

    # Two ADVISORY watch tiers (NEITHER is a proven/build-failing violation):
    #   high  = overlap AND gated bound > margin  ("flagged for commercial
    #           SI review"). FLAGGED != proven-failure: the floating divider
    #           bound over-claims on driven nets.
    #   low   = floating bound > margin but window/driver gating cleared it.
    watch_high: List[dict] = []
    watch_low: List[dict] = []
    decoupled_count = 0
    pairs_evaluated = 0
    max_gated_noise_mv = 0.0
    max_base_noise_mv = 0.0

    for pair, cc_val in pair_cc.items():
        n1, n2 = tuple(pair)
        # evaluate the pair in BOTH directions (each net is a victim once)
        for victim, aggressor in ((n1, n2), (n2, n1)):
            cg_v = cg.get(victim, 0.0)
            denom = cc_val + cg_v
            if denom <= 0:
                continue
            pairs_evaluated += 1
            base_v = (cc_val / denom) * vdd_v
            base_mv = base_v * 1000.0
            max_base_noise_mv = max(max_base_noise_mv, base_mv)

            win_v = _win(victim)
            win_a = _win(aggressor)
            overlap = _windows_overlap(win_a, win_v, overlap_guard_ns)
            if not overlap:
                decoupled_count += 1
                continue  # windows do not overlap -> coupling event impossible

            driven = _driven(victim)
            gated_mv = base_mv * (DRIVEN_DAMPING if driven else 1.0)
            max_gated_noise_mv = max(max_gated_noise_mv, gated_mv)

            if gated_mv > noise_margin_mv:
                priority = "high"
            elif base_mv > noise_margin_mv:
                priority = "low"
            else:
                continue  # below margin even at the floating bound -> not flagged

            entry = {
                "victim": _label(victim),
                "aggressor": _label(aggressor),
                "victim_spef_id": victim,
                "aggressor_spef_id": aggressor,
                "cc": round(cc_val, 6),
                "cg_victim": round(cg_v, 6),
                "base_noise_mv": round(base_mv, 2),
                "gated_noise_mv": round(gated_mv, 2),
                "victim_driven": driven,
                "victim_window_ns": list(win_v) if win_v else None,
                "aggressor_window_ns": list(win_a) if win_a else None,
                "priority": priority,
                # HONEST: a flagged pair is NOT a proven failure. The floating
                # capacitive-divider bound over-claims on a driven victim in
                # dense routing; this needs foundry CCS-Noise / RLC(K) models
                # for a true pass/fail.
                "note": (
                    "coupling-dominated, switching-window overlaps -- flagged "
                    "for commercial SI review (advisory; not a proven failure)"
                    if priority == "high" else
                    "floating-bound exceeds margin but window/driver gating "
                    "cleared it (advisory)"
                ),
            }
            if priority == "high":
                watch_high.append(entry)
            else:
                watch_low.append(entry)

    # stable ordering for determinism
    watch_high.sort(key=lambda e: (-e["gated_noise_mv"], e["victim"], e["aggressor"]))
    watch_low.sort(key=lambda e: (-e["base_noise_mv"], e["victim"], e["aggressor"]))
    watchlist = watch_high + watch_low

    nets_analyzed = len(set(cg) | {n for pr in pair_cc for n in pr})
    # ALWAYS advisory: there is no PASS/FAIL split that implies sign-off.
    verdict = "SI_TIMING_AWARE_SCREEN"

    return {
        "tool": "opensta-spef-timing-window-si-screen",
        "mode": "signal_integrity_crosstalk_timing_aware",
        "scope": (
            "Timing-window-aware SI ADVISORY screen. Upgrades the "
            "floating-victim coupling-ratio advisory bound by adding "
            "switching-window decoupling. This is a LUMPED capacitive-divider "
            "model gated by OpenSTA arrival windows + driver damping -- it is "
            "NOT a full RLC(K) transmission-line commercial SI sign-off "
            "(PrimeTime-SI / Quantus class) and does not claim commercial "
            "equivalence. It is CONCLUSIVE ONLY in the decoupled-safe "
            "direction (non-overlapping switching windows => a coupling event "
            "is timing-impossible => conclusively safe). The flagged / "
            "over-margin direction is NOT a proven failure: the floating "
            "capacitive-divider bound over-claims on a driven victim, where a "
            "high coupling ratio in dense routing is normal. That direction is "
            "an ADVISORY watch-list that needs foundry CCS-Noise / RLC(K) "
            "models for a true pass/fail -- a PHYSICAL need for "
            "foundry-calibrated models, not commercial-tool lock-in. No "
            "build-failing verdict is ever emitted; no fabricated flags."
        ),
        "method": (
            "base_noise = Cc/(Cc+Cg_victim)*Vdd (floating UPPER BOUND); gated "
            "by aggressor/victim switching-window overlap (no overlap => "
            "decoupled => conclusively safe) and driven-victim damping (derate "
            "%.2f). HIGH watch iff overlap AND gated bound > margin (flagged "
            "for commercial SI review, NOT a proven failure); LOW watch iff "
            "floating bound > margin but gating cleared it. Verdict is always "
            "the advisory SI_TIMING_AWARE_SCREEN." % DRIVEN_DAMPING
        ),
        "vdd_v": vdd_v,
        "noise_margin_mv": noise_margin_mv,
        "driven_damping_derate": DRIVEN_DAMPING,
        "nets_analyzed": nets_analyzed,
        "coupling_pairs": len(pair_cc),
        "pairs_evaluated": pairs_evaluated,
        # the only conclusive result: non-overlapping windows => safe.
        "pairs_decoupled_by_window": decoupled_count,
        "max_base_noise_mv": round(max_base_noise_mv, 2),
        "max_gated_noise_mv": round(max_gated_noise_mv, 2),
        # NOTE: flagged_* are ADVISORY watch-list counts, NOT proven failures.
        "watchlist_high_count": len(watch_high),
        "watchlist_low_count": len(watch_low),
        "watchlist_count": len(watchlist),
        "watchlist": watchlist[:200],
        "verdict": verdict,
    }


# ===========================================================================
# The coupling-based DELTA-DELAY screen  (a GENUINE PASS/FAIL/ADVISORY verdict)
# ===========================================================================
# Distinct from the crosstalk-NOISE screen above (a glitch on a quiet victim).
# Delta-delay is a TIMING effect: when an aggressor switches OPPOSITE to a
# victim WHILE the victim is transitioning, the coupling cap is Miller-
# multiplied (up to ~2x), which SLOWS the victim edge -> adds delay to the
# arrival at the victim's endpoint -> can push that path's setup slack NEGATIVE.
# Unlike the noise screen (which over-claims on driven nets and is therefore
# always ADVISORY), delta-delay CAN be PROVEN into a real FAIL when a slack
# basis is available: a net whose coupled delta-delay exceeds its path slack
# is a genuine setup finding, not a forced 0.
DELTA_DELAY_MILLER_FACTOR = 2.0   # worst-case opposite-switching Miller factor


def score_delta_delay(
    spef: Union[str, dict],
    timing: Union[str, dict, PathLike],
    *,
    vdd_v: float = 1.8,
    miller_factor: float = DELTA_DELAY_MILLER_FACTOR,
    overlap_guard_ns: float = 0.0,
) -> dict:
    """Coupling-based delta-delay screen -> a GENUINE PASS/FAIL/ADVISORY verdict.

    Per coupling PAIR (aggressor a, victim v) whose switching windows OVERLAP:

        ratio_v = Cc / (Cc + Cg_victim)          # coupled fraction of victim load
        delta_t = (miller_factor - 1) * ratio_v * slew_victim    # ns, >= 0

    Physical basis (lumped, disclosed): the victim edge time ~ R_drv * C_total,
    captured by its slew. An opposite-switching aggressor raises the effective
    coupling from ~1x Cc (already in the quiescent arrival) to ~miller_factor x
    Cc, i.e. an EXTRA (miller_factor-1)*Cc of load, a (miller_factor-1)*ratio_v
    fractional load increase, which lengthens the transition ~proportionally ->
    the extra delay is (miller_factor-1)*ratio_v*slew_victim. With the default
    miller_factor=2.0 the increment is ratio_v*slew_victim (a conservative
    screen bound).

    A pair is a PROVEN FINDING (setup pushout) iff:
        windows overlap  AND  the victim net has a known path slack  AND
        delta_t > slack_victim          (the delta-delay pushes it negative)

    Verdict (delta_delay_verdict):
      FAIL      >=1 pair pushes a path negative (proven with a real slack basis).
      PASS      a slack basis WAS available for the coupled/overlapping nets AND
                every overlapping pair's delta_t stays within slack (the timing
                margin covers the worst modelled delta-delay). Non-vacuous: PASS
                requires at least one overlapping pair to have been slack-checked.
      ADVISORY  no slack basis for the coupled nets (older OpenSTA build, or no
                overlapping coupled pair had slack) -> cannot PROVE a push-
                negative; the decoupled-safe pairs are still reported. This is
                the honest §4.05 outcome, NOT a forced 0 that hides risk.

    §4.05: a forced-0 that hides a real coupling risk is dishonest; here a real
    over-slack delta-delay always surfaces as FAIL, and inability to prove is
    ADVISORY (never silently PASS)."""
    sp = spef if isinstance(spef, dict) else parse_spef(spef)
    tj = timing if isinstance(timing, dict) else load_timing_json(timing)

    pins = tj.get("pins", {})
    cg = sp["cg"]
    pair_cc = sp["pair_cc"]
    name_map = sp.get("name_map", {})
    net_windows = compute_net_windows(sp["net_driver_pins"], pins)
    net_slacks = compute_net_slacks(
        sp["net_load_pins"], sp["net_driver_pins"], pins)

    def _label(net: str) -> str:
        return name_map.get(net, net)

    def _win(net: str) -> Optional[Tuple[float, float]]:
        rec = net_windows.get(net)
        return rec["win"] if rec else None

    def _slew(net: str) -> float:
        rec = net_windows.get(net)
        return float(rec["slew"]) if rec else 0.0

    findings: List[dict] = []          # PROVEN push-negative (FAIL drivers)
    watch: List[dict] = []             # over-slack-ambiguous / near-margin advisory
    pairs_overlapping = 0
    pairs_decoupled = 0
    pairs_slack_checked = 0
    max_delta_t_ns = 0.0
    incr = max(0.0, miller_factor - 1.0)

    for pair, cc_val in pair_cc.items():
        n1, n2 = tuple(pair)
        for victim, aggressor in ((n1, n2), (n2, n1)):
            cg_v = cg.get(victim, 0.0)
            denom = cc_val + cg_v
            if denom <= 0:
                continue
            win_v = _win(victim)
            win_a = _win(aggressor)
            if not _windows_overlap(win_a, win_v, overlap_guard_ns):
                pairs_decoupled += 1
                continue
            pairs_overlapping += 1
            ratio_v = cc_val / denom
            slew_v = _slew(victim)
            delta_t = incr * ratio_v * slew_v
            max_delta_t_ns = max(max_delta_t_ns, delta_t)
            slack_v = net_slacks.get(victim)
            entry = {
                "victim": _label(victim),
                "aggressor": _label(aggressor),
                "victim_spef_id": victim,
                "aggressor_spef_id": aggressor,
                "cc": round(cc_val, 6),
                "cg_victim": round(cg_v, 6),
                "coupled_ratio": round(ratio_v, 4),
                "victim_slew_ns": round(slew_v, 4),
                "delta_delay_ns": round(delta_t, 4),
                "victim_slack_ns": (round(slack_v, 4)
                                    if slack_v is not None else None),
            }
            if slack_v is None:
                # cannot prove a push-negative without a slack basis
                entry["status"] = "unprovable_no_slack"
                watch.append(entry)
                continue
            pairs_slack_checked += 1
            post_slack = slack_v - delta_t
            entry["post_coupling_slack_ns"] = round(post_slack, 4)
            if post_slack < 0.0:
                entry["status"] = "push_negative"
                entry["note"] = (
                    "coupled delta-delay exceeds path slack -> setup pushout "
                    "(PROVEN with the STA slack basis)")
                findings.append(entry)
            elif delta_t > 0 and post_slack < 0.5 * max(slack_v, 1e-9):
                entry["status"] = "eroded_margin"
                entry["note"] = ("delta-delay consumes >50% of the path slack "
                                 "(advisory watch, not a proven failure)")
                watch.append(entry)

    findings.sort(key=lambda e: e.get("post_coupling_slack_ns", 0.0))
    watch.sort(key=lambda e: -e["delta_delay_ns"])

    if findings:
        verdict = "FAIL"
    elif pairs_slack_checked > 0:
        verdict = "PASS"
    else:
        verdict = "ADVISORY"

    return {
        "tool": "opensta-spef-coupling-delta-delay-screen",
        "mode": "signal_integrity_delta_delay",
        "scope": (
            "Coupling-based delta-delay screen: a Miller-multiplied coupling "
            "cap on an overlapping aggressor slows the victim edge and can push "
            "the victim path's setup slack negative. This is a GENUINE verdict "
            "-- FAIL when a net's modelled delta-delay exceeds its STA path "
            "slack (proven push-negative), PASS when a slack basis exists and "
            "covers the worst modelled delta-delay, ADVISORY when no slack "
            "basis is available (cannot prove). It is a LUMPED estimate "
            "(delta_t=(MF-1)*Cc/(Cc+Cg)*slew), NOT a full RLC(K) / CCS-Noise "
            "commercial SI-timing sign-off, and does not claim commercial "
            "equivalence. §4.05: a real over-slack coupling risk always "
            "surfaces (never a forced 0); inability to prove is ADVISORY, "
            "never a silent PASS."),
        "method": (
            "delta_t = (miller_factor-1) * Cc/(Cc+Cg_victim) * slew_victim, "
            "evaluated only for aggressor/victim pairs whose STA switching "
            "windows overlap; compared against the victim net's worst path "
            "slack (min over its driver+load pins). MF=%.2f." % miller_factor),
        "vdd_v": vdd_v,
        "miller_factor": miller_factor,
        "coupling_pairs": len(pair_cc),
        "pairs_overlapping": pairs_overlapping,
        "pairs_decoupled_by_window": pairs_decoupled,
        "pairs_slack_checked": pairs_slack_checked,
        "max_delta_delay_ns": round(max_delta_t_ns, 4),
        "violations_count": len(findings),
        "violations": findings[:200],
        "watchlist_count": len(watch),
        "watchlist": watch[:100],
        "delta_delay_verdict": verdict,
        "verdict": verdict,
    }


# ===========================================================================
# The OpenSTA TCL recipe (PRODUCES the timing JSON the scorer consumes)
# ===========================================================================
def build_opensta_si_tcl(
    liberty: str,
    netlist: str,
    top: str,
    sdc: str,
    spef: str,
    out_json: str,
    *,
    vdd_v: float = 1.8,
    extra_lefs: Optional[List[str]] = None,
    extra_liberties: Optional[List[str]] = None,
) -> str:
    """Emit the EXACT OpenSTA TCL recipe that produces the SI timing JSON.

    All paths are used verbatim (the caller is responsible for translating
    host paths to container paths, e.g. via the runner's _to_container_path).

    The recipe:
      read_liberty -> read_verilog -> link_design -> read_sdc -> read_spef
      then walk every pin and capture report_arrival + report_slews via
      sta::redirect_string (OpenSTA 2.7.0 has NO `report_timing -json`, and
      report_* commands print rather than return; redirect_string is the
      version-stable way to capture their text). We parse the captured text
      in-TCL and emit TIMING_JSON_SHAPE.

    report_arrival text:  " (clk ^) r 0.42:1.58 f 0.39:1.98"
    report_slews   text:  "<pin> ^ 0.10:0.21 v 0.04:0.19"
    """
    libs = "\n".join(f"read_liberty {q}" for q in
                     ([liberty] + list(extra_liberties or [])))
    # NOTE: standalone OpenSTA (`sta`) has NO `read_lef` command — that is an
    # OpenROAD command. OpenSTA derives all timing from Liberty + Verilog +
    # SDC + SPEF; LEF carries only physical abstracts it neither reads nor
    # needs. Emitting `read_lef` here aborted the whole TCL at line 1 with
    # `Error: invalid command name "read_lef"`, leaving a sub-1KB stub log
    # that the STA substance gate (Steps 10/23) then flagged as a hand-typed
    # stub → FAIL, for EVERY project. `extra_lefs` is accepted for signature
    # compatibility but intentionally unused. (chip-AGNOSTIC fix)
    _ = extra_lefs
    return f"""# === Vibe-IC timing-window-aware SI screen — OpenSTA timing JSON emitter ===
# Produces the per-pin arrival-window + slew JSON consumed by
# si_signoff_timing_aware.score_si_timing_aware(). Chip-AGNOSTIC.
{libs}
read_verilog {netlist}
link_design {top}
read_sdc {sdc}
read_spef {spef}

proc _si_capture {{cmd args}} {{
  sta::redirect_string_begin
  catch {{eval $cmd $args}}
  return [sta::redirect_string_end]
}}
proc _si_jnum {{x}} {{ if {{$x eq ""}} {{ return "null" }} else {{ return $x }} }}

set _si_out [open {out_json} w]
puts $_si_out "{{"
puts $_si_out "  \\"tool\\": \\"OpenSTA\\","
puts $_si_out "  \\"design\\": \\"{top}\\","
puts $_si_out "  \\"time_unit\\": \\"ns\\","
puts $_si_out "  \\"vdd_v\\": {vdd_v},"
puts $_si_out "  \\"pins\\": {{"
set _si_first 1
set _si_n 0
# Emit one pin/port record (arrival windows + slews). Walk BOTH internal pins
# AND top-level ports so primary-input nets (driven by an input pad, arrival =
# input delay) also get a switching window — without ports they'd fall back to
# the conservative "unknown window => assume overlap" path.
proc _si_emit {{obj out first_var n_var}} {{
  upvar $first_var _si_first
  upvar $n_var _si_n
  set _si_pn [get_full_name $obj]
  set _si_arr [_si_capture report_arrival $obj]
  set _si_armn ""; set _si_armx ""; set _si_afmn ""; set _si_afmx ""
  regexp {{r ([-0-9.eE+]+):([-0-9.eE+]+)}} $_si_arr -> _si_armn _si_armx
  regexp {{f ([-0-9.eE+]+):([-0-9.eE+]+)}} $_si_arr -> _si_afmn _si_afmx
  if {{$_si_armn eq "" && $_si_afmn eq ""}} {{ return }}
  set _si_slw [_si_capture report_slews $obj]
  set _si_srmn ""; set _si_srmx ""; set _si_sfmn ""; set _si_sfmx ""
  regexp {{\\^ ([-0-9.eE+]+):([-0-9.eE+]+)}} $_si_slw -> _si_srmn _si_srmx
  regexp {{v ([-0-9.eE+]+):([-0-9.eE+]+)}} $_si_slw -> _si_sfmn _si_sfmx
  # Per-pin SETUP slack for the delta-delay screen: slack = required - arrival on
  # the LATE (max) path, worst of rise/fall. required from report_required (same
  # "r min:max f min:max" shape as report_arrival). null when unavailable (older
  # OpenSTA build / off-path pin) -> the delta-delay screen degrades to ADVISORY
  # for nets touching this pin (never a fabricated slack). §4.05.
  set _si_req [_si_capture report_required $obj]
  set _si_rrmx ""; set _si_rfmx ""
  regexp {{r ([-0-9.eE+]+):([-0-9.eE+]+)}} $_si_req -> _si_dummy _si_rrmx
  regexp {{f ([-0-9.eE+]+):([-0-9.eE+]+)}} $_si_req -> _si_dummy _si_rfmx
  set _si_slk ""
  if {{$_si_rrmx ne "" && $_si_armx ne ""}} {{ set _si_slk [expr {{$_si_rrmx - $_si_armx}}] }}
  if {{$_si_rfmx ne "" && $_si_afmx ne ""}} {{
    set _si_slkf [expr {{$_si_rfmx - $_si_afmx}}]
    if {{$_si_slk eq "" || $_si_slkf < $_si_slk}} {{ set _si_slk $_si_slkf }}
  }}
  if {{!$_si_first}} {{ puts $out "," }}
  set _si_first 0
  incr _si_n
  puts -nonewline $out "    \\"$_si_pn\\": {{\\"arr_rise_min\\": [_si_jnum $_si_armn], \\"arr_rise_max\\": [_si_jnum $_si_armx], \\"arr_fall_min\\": [_si_jnum $_si_afmn], \\"arr_fall_max\\": [_si_jnum $_si_afmx], \\"slew_rise_max\\": [_si_jnum $_si_srmx], \\"slew_fall_max\\": [_si_jnum $_si_sfmx], \\"slack_max\\": [_si_jnum $_si_slk]}}"
}}
foreach _si_p [get_pins -hierarchical *] {{ _si_emit $_si_p $_si_out _si_first _si_n }}
if {{![catch {{set _si_ports [get_ports *]}}]}} {{
  foreach _si_pp $_si_ports {{ _si_emit $_si_pp $_si_out _si_first _si_n }}
}}
puts $_si_out ""
puts $_si_out "  }}"
puts $_si_out "}}"
close $_si_out
puts "SI_TIMING_JSON_EMIT_DONE pins=$_si_n out={out_json}"
"""


# ===========================================================================
# Report emission + top-level runner (the function the phase3 runner calls)
# ===========================================================================
def _render_rpt(v: dict, spef_path: str, timing_path: str) -> str:
    high = [e for e in v["watchlist"] if e.get("priority") == "high"]
    lines = [
        "# Signal-integrity / crosstalk — TIMING-WINDOW-AWARE ADVISORY screen (OPEN-SOURCE)",
        "# si_signoff_timing_aware.py. Source: OpenSTA arrival windows + SPEF coupling caps.",
        f"# SPEF:   {spef_path}",
        f"# TIMING: {timing_path}",
        "#",
        "# SCOPE: this is a timing-window-aware ADVISORY SCREEN that upgrades the floating-",
        "#        victim coupling-ratio advisory bound by adding switching-window decoupling.",
        "#        It is a LUMPED capacitive-divider model gated by OpenSTA windows + driver",
        "#        damping. It is NOT a full RLC(K) transmission-line commercial SI sign-off",
        "#        and does NOT claim commercial equivalence.",
        "#        CONCLUSIVE ONLY in the decoupled-safe direction (non-overlapping windows =>",
        "#        a coupling event is timing-impossible => conclusively safe). The flagged /",
        "#        over-margin direction is NOT a proven failure -- the floating divider bound",
        "#        over-claims on a driven victim (high coupling ratio in dense routing is",
        "#        normal). It is an ADVISORY watch-list that needs foundry CCS-Noise / RLC(K)",
        "#        models for a true pass/fail (a PHYSICAL need for foundry-calibrated models,",
        "#        not commercial-tool lock-in). NO build-failing verdict is ever emitted.",
        "#",
        f"vdd_v: {v['vdd_v']}",
        f"noise_margin_mv: {v['noise_margin_mv']}",
        f"driven_damping_derate: {v['driven_damping_derate']}",
        f"nets_analyzed: {v['nets_analyzed']}",
        f"coupling_pairs: {v['coupling_pairs']}",
        f"pairs_evaluated: {v['pairs_evaluated']}",
        f"pairs_decoupled_by_window (CONCLUSIVELY SAFE): {v['pairs_decoupled_by_window']}",
        f"max_base_noise_mv (floating bound): {v['max_base_noise_mv']}",
        f"max_gated_noise_mv (driven+window): {v['max_gated_noise_mv']}",
        f"watchlist_high_count (overlap+over-margin; flagged, NOT proven-fail): {v['watchlist_high_count']}",
        f"watchlist_low_count (floating-bound over margin, gating cleared): {v['watchlist_low_count']}",
        f"crosstalk: {v['verdict']}",
    ]
    dd = v.get("delta_delay")
    if dd is not None:
        lines += [
            "#",
            "# --- COUPLING DELTA-DELAY screen (GENUINE PASS/FAIL/ADVISORY) ---",
            "# A Miller-multiplied coupling cap on an OVERLAPPING aggressor slows the",
            "# victim edge; delta_t=(MF-1)*Cc/(Cc+Cg)*slew is compared to the victim",
            "# net's STA path slack. FAIL = proven push-negative; PASS = slack basis",
            "# covers the worst delta-delay; ADVISORY = no slack basis (cannot prove).",
            f"delta_delay_miller_factor: {dd['miller_factor']}",
            f"delta_delay_pairs_overlapping: {dd['pairs_overlapping']}",
            f"delta_delay_pairs_decoupled (SAFE): {dd['pairs_decoupled_by_window']}",
            f"delta_delay_pairs_slack_checked: {dd['pairs_slack_checked']}",
            f"delta_delay_max_ns: {dd['max_delta_delay_ns']}",
            f"delta_delay_violations_count: {dd['violations_count']}",
            f"delta_delay: {dd['delta_delay_verdict']}",
        ]
        for e in dd.get("violations", [])[:20]:
            lines.append(
                f"#   VIOLATION victim={e['victim']} aggressor={e['aggressor']} "
                f"delta={e['delta_delay_ns']}ns slack={e['victim_slack_ns']}ns "
                f"post_slack={e.get('post_coupling_slack_ns')}ns")
    if high:
        lines.append("#")
        lines.append("# --- HIGH watch-list (overlap AND gated bound > margin; ADVISORY, "
                     "flagged for commercial SI review -- NOT a proven failure) ---")
        for e in high[:50]:
            lines.append(
                f"#   victim={e['victim']} aggressor={e['aggressor']} "
                f"gated={e['gated_noise_mv']}mV base={e['base_noise_mv']}mV "
                f"driven={e['victim_driven']}")
    lines.append("# end of si_crosstalk_timing_aware.rpt")
    return "\n".join(lines) + "\n"


def run_si_signoff_timing_aware(
    spef_path: PathLike,
    timing_json_path: PathLike,
    *,
    vdd_v: float = 1.8,
    noise_margin_mv: float = 100.0,
    out_json: Optional[PathLike] = None,
    out_rpt: Optional[PathLike] = None,
) -> dict:
    """PUBLIC API for the phase3 runner.

    Given a SPEF file and an OpenSTA SI timing JSON (produced by the TCL from
    build_opensta_si_tcl), score the timing-window-aware SI screen and
    optionally write the JSON + .rpt artifacts. Returns the verdict dict.

    The runner produces `timing_json_path` by writing the TCL from
    build_opensta_si_tcl(...) and running it with `sta`; then it calls this."""
    spef_path = Path(spef_path)
    spef_text = spef_path.read_text(errors="replace")
    sp = parse_spef(spef_text)          # parse once, share both screens
    tj = load_timing_json(timing_json_path)
    verdict = score_si_timing_aware(
        sp, tj,
        vdd_v=vdd_v, noise_margin_mv=noise_margin_mv,
    )
    # The GENUINE coupling-based delta-delay verdict (PASS/FAIL/ADVISORY),
    # distinct from the always-advisory noise screen above.
    dd = score_delta_delay(sp, tj, vdd_v=vdd_v)
    verdict["delta_delay"] = dd
    verdict["delta_delay_verdict"] = dd["delta_delay_verdict"]
    verdict["spef"] = str(spef_path)
    verdict["timing_json"] = str(timing_json_path)
    if out_json is not None:
        out_json = Path(out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(verdict, indent=2) + "\n")
    if out_rpt is not None:
        out_rpt = Path(out_rpt)
        out_rpt.parent.mkdir(parents=True, exist_ok=True)
        out_rpt.write_text(_render_rpt(verdict, str(spef_path),
                                       str(timing_json_path)))
    return verdict


# ===========================================================================
# CLI
# ===========================================================================
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="OPEN-SOURCE timing-window-aware SI (crosstalk) screen.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_s = sub.add_parser("score", help="score SI from a SPEF + OpenSTA timing JSON")
    sp_s.add_argument("spef")
    sp_s.add_argument("timing_json")
    sp_s.add_argument("--vdd", type=float, default=1.8)
    sp_s.add_argument("--margin-mv", type=float, default=100.0)
    sp_s.add_argument("--out-json", default=None)
    sp_s.add_argument("--out-rpt", default=None)
    sp_s.add_argument(
        "--strict", action="store_true",
        help="opt-in: exit 1 if the HIGH advisory watch-list is non-empty. "
             "DEFAULT is advisory (always exit 0) -- this screen never fails "
             "a build because the flagged direction is not a proven failure.")
    sp_s.add_argument(
        "--strict-delta", action="store_true",
        help="opt-in: exit 1 if the coupling DELTA-DELAY verdict is FAIL "
             "(a net whose modelled delta-delay is PROVEN to push a path "
             "negative against the STA slack basis). This IS a genuine "
             "failure, unlike the advisory noise watch-list.")

    sp_t = sub.add_parser("emit-tcl", help="emit the OpenSTA TCL that produces the timing JSON")
    sp_t.add_argument("out_tcl")
    sp_t.add_argument("--liberty", required=True)
    sp_t.add_argument("--netlist", required=True)
    sp_t.add_argument("--top", required=True)
    sp_t.add_argument("--sdc", required=True)
    sp_t.add_argument("--spef", required=True)
    sp_t.add_argument("--out-json", required=True)
    sp_t.add_argument("--vdd", type=float, default=1.8)
    sp_t.add_argument("--lef", action="append", default=[])
    sp_t.add_argument("--extra-liberty", action="append", default=[])

    args = ap.parse_args(argv)

    if args.cmd == "score":
        try:
            v = run_si_signoff_timing_aware(
                args.spef, args.timing_json,
                vdd_v=args.vdd, noise_margin_mv=args.margin_mv,
                out_json=args.out_json, out_rpt=args.out_rpt,
            )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"si_signoff: IO/parse error: {e}", file=sys.stderr)
            return 2
        dd = v.get("delta_delay", {})
        print(json.dumps({
            "verdict": v["verdict"],
            "watchlist_high_count": v["watchlist_high_count"],
            "watchlist_low_count": v["watchlist_low_count"],
            "watchlist_count": v["watchlist_count"],
            "pairs_evaluated": v["pairs_evaluated"],
            "pairs_decoupled_by_window": v["pairs_decoupled_by_window"],
            "max_base_noise_mv": v["max_base_noise_mv"],
            "max_gated_noise_mv": v["max_gated_noise_mv"],
            "delta_delay_verdict": v.get("delta_delay_verdict"),
            "delta_delay_violations_count": dd.get("violations_count"),
            "delta_delay_max_ns": dd.get("max_delta_delay_ns"),
            "delta_delay_pairs_slack_checked": dd.get("pairs_slack_checked"),
        }, indent=2))
        # The noise screen is ADVISORY (DEFAULT exit 0). The delta-delay screen
        # CAN be a genuine failure: opt-in --strict-delta exits 1 on a proven
        # push-negative. --strict keeps the legacy HIGH-noise-watch gate.
        if args.strict_delta and v.get("delta_delay_verdict") == "FAIL":
            return 1
        if args.strict and v["watchlist_high_count"] > 0:
            return 1
        return 0

    if args.cmd == "emit-tcl":
        tcl = build_opensta_si_tcl(
            args.liberty, args.netlist, args.top, args.sdc, args.spef,
            args.out_json, vdd_v=args.vdd,
            extra_lefs=args.lef, extra_liberties=args.extra_liberty,
        )
        Path(args.out_tcl).write_text(tcl)
        print(f"wrote {args.out_tcl}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
