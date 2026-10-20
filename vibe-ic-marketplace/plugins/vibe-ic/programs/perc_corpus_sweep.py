#!/usr/bin/env python3
"""perc_corpus_sweep.py — run the v0.2.4-2.11 PERC-equivalent sign-off chain across a CORPUS
of already-routed designs, deterministically, with NO container needed.

ROLE: producer/classifier

Issue #1980 moved this sweep out of the gate denominator. The Step-31 output
record retains WELLTAP_GAP / cross-domain INCOMPLETE findings; the separate
`sweep_reach_check` program owns the refusal predicate.
Captured v0.2.12 from the 2026-06-01 Shape-A 21-IC benchmark_ic sweep
(benchmark_ic/RESULT_PERC_CORPUS_v0211.md): that sweep was driven by an ad-hoc /tmp script.
This promotes it to a first-class, tested plugin capability so any corpus PERC sweep is one
command — `python3 perc_corpus_sweep.py <dir1> [<dir2> ...]` — instead of a throwaway.

For each design directory it finds the most-routed DEF (prefers `*routed*` > `chip_top` >
`post_hold`) under `<dir>/phase3/**` and runs the SHIPPED pure structural checks from
`phase3_one_shot_runner.py` (imported, NOT re-implemented):
  - well-tap presence (latch-up)         → _welltap_presence_check
  - ESD pad-ring presence                → _esd_pad_ring_presence
  - ESD discharge-path topology          → _esd_discharge_topology (only if a pad ring exists)
  - cross-voltage-domain                 → _xdomain_levelshifter_check

HONESTY (inherited from the checks): these are open-source STRUCTURAL screens, NOT a commercial
PERC run. A WELLTAP_GAP / XDOMAIN_GAP is a conclusive structural exposure; PRESENT/OK results are
NECESSARY-BUT-NOT-SUFFICIENT (device-physics stays MANUAL). A corpus-wide GAP is NOT proof of a
current-runner bug — validate against a FRESH same-version control before triaging (the
stale-artifact lesson from the v0.2.11 sweep, where 14/14 0-tap were pre-tapcell-fix DEFs).

ARTIFACT-VINTAGE GUARD (suggested_fix #4 of ORGANIC-20260601-...-stale-pre-tapcell-fix):
each sweep also runs `artifact_vintage_guard`, which WARNs when a routed DEF with > N std
cells has 0 valid taps AND an older/sibling DEF in the same lineage is ALSO 0-tap — the
structural signature of a STALE pre-tapcell-fix artifact (the whole lineage never ran the
tapcell step), as opposed to a LIVE current-runner regression. It never fails a build; it is
a triage WARN so a corpus PERC number is not mis-cited as a current-quality signal.

REACH (v1.9.79+): a corpus sweep whose targets carry no routed DEF used to print a table of
`no routed DEF` rows and exit 0 — the same exit code, to every automated consumer, as a sweep
that ran the PERC chain on every IC and found nothing wrong. It now accounts for how many
targets actually entered `sweep_one` (`_sweep_reach.SweepReach`) and routes rc 2 +
`VACUOUS_PASS:` through the shipped `_vacuous_exit` convention when that count is ZERO. A
PARTIAL sweep still exits 0: most corpora contain core macros and pre-layout blocks the chain
genuinely cannot reach, and failing those would be a worse defect than the silence it replaces.

Usage:
    python3 perc_corpus_sweep.py <design_dir> [<design_dir> ...]   # JSONL per IC + summary
    python3 perc_corpus_sweep.py --json <dir> ...                  # JSON array only, no summary
    python3 perc_corpus_sweep.py --def <routed.def> --name <id>    # single explicit DEF
    python3 perc_corpus_sweep.py --vintage <routed.def>            # ONLY the vintage guard, JSON
    python3 perc_corpus_sweep.py --no-vintage <dir> ...           # skip the vintage guard
    python3 perc_corpus_sweep.py --report R.json <dir> ...        # rows + reach block, for
                                                                  # sweep_reach_check --report
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sweep_reach as _sr  # noqa: E402  (aggregate reach disclosure)
import _pad_ring as _pr  # noqa: E402  (the one LEF MACRO CLASS parser)
import phase3_one_shot_runner as _p  # noqa: E402  (shipped PERC functions — single source)


# ------------------------------------------------------- physical classes of the masters
# vibe-ic tail-b U22 (measured on the spm IC/DIE run cx_spmic2_run, 2026-09-28): the sweep
# reported `welltap: ZERO_TAPS` on a routed DEF carrying 36,186 instances of the PDK's own
# `CLASS core WELLTAP` cell (a tap named without a `tap` token), and `pads: 8` /
# `esd_cells: 0` "Likely ESD GAP" -- eight distinct IO MASTERS, four of them corner/spacer
# fillers, counted as signal pads, and an ESD verdict of MISSING read from cell NAMES that
# simply do not spell a clamp. What a master IS comes from its LEF CLASS, and which cell is
# the well tap is the PDK's own WELLTAP_CELL; both are read from the run tree, never from a
# cell-name literal.
_LEF_MAX_BYTES = 64 * 1024 * 1024
#: LEF CLASS strings of a bond pad (LEF 5.8 `PAD` subtypes).
_PAD_SIGNAL_CLASSES = ("PAD", "PAD INPUT", "PAD OUTPUT", "PAD INOUT", "PAD AREAIO")
_PAD_POWER_CLASSES = ("PAD POWER",)
#: Ring structure that is not a bond pad: spacers and the four IO corners.
_PAD_STRUCTURAL_CLASSES = ("PAD SPACER", "ENDCAP TOPLEFT", "ENDCAP TOPRIGHT",
                           "ENDCAP BOTTOMLEFT", "ENDCAP BOTTOMRIGHT")
_WELLTAP_CLASS = "CORE WELLTAP"


def _welltap_cells_of(value: Any) -> List[str]:
    if isinstance(value, str):
        return [v for v in value.split() if v]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str) and v]
    return []


def physical_classes(design_dir: Optional[str]) -> Dict[str, Any]:
    """`{classes: {master: LEF CLASS}, welltap_cells: [...], sources: {...}}` for a run tree.

    * LEF CLASS of every MACRO in any LEF the run tree carries (the pad ring's IO LEFs are
      staged into it), parsed by `_pad_ring.parse_lef_macro_classes`.
    * the PDK's configured `WELLTAP_CELL` from the run's LibreLane step configs.
    A `CORE WELLTAP` master and the configured WELLTAP_CELL are both well taps. Nothing is
    guessed: an empty result leaves every reader on its previous (name-hint) behaviour."""
    out: Dict[str, Any] = {"classes": {}, "welltap_cells": [],
                           "sources": {"lef": [], "welltap_cell_config": []}}
    if not design_dir or not os.path.isdir(design_dir):
        return out
    root = Path(design_dir)
    classes: Dict[str, str] = {}
    for lef in sorted(root.rglob("*.lef")):
        try:
            if not lef.is_file() or lef.stat().st_size > _LEF_MAX_BYTES:
                continue
            got = _pr.parse_lef_macro_classes(lef.read_text(errors="replace"))
        except OSError:
            continue
        if got:
            classes.update(got)
            out["sources"]["lef"].append(str(lef.relative_to(root)))
    welltap = {m for m, c in classes.items() if c == _WELLTAP_CLASS}
    cfg_cells: set = set()
    for cfg in sorted(root.glob("phase3/librelane/**/config.json")):
        try:
            doc = json.loads(cfg.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("WELLTAP_CELL"):
            cells = _welltap_cells_of(doc.get("WELLTAP_CELL"))
            if cells:
                cfg_cells.update(cells)
                out["sources"]["welltap_cell_config"].append(str(cfg.relative_to(root)))
    out["sources"]["welltap_cell_config"] = out["sources"]["welltap_cell_config"][:5]
    out["classes"] = classes
    out["welltap_cells"] = sorted(welltap | cfg_cells)
    out["welltap_from_lef_class"] = sorted(welltap)
    out["welltap_from_pdk_config"] = sorted(cfg_cells)
    return out


def pad_ring_census(components: List["tuple"], classes: Dict[str, str],
                    esd_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pad and ESD counts per INSTANCE, the pad role taken from the master's LEF CLASS.

    Returns None-equivalent `{"source": None}` when no component's master has a PAD/IO-corner
    class, so the caller keeps the name-hint reader. ESD per pad instance:
      * `identified`   -- the master is ESD-bearing by the shipped ESD reader;
      * `negated`      -- the master's name explicitly disclaims ESD (noesd, ...);
      * `unidentified` -- neither: nothing in the run tree states whether this pad carries
                          ESD, so it is NOT counted as a missing clamp.
    esd_presence: PRESENT (>= 1 identified), MISSING (every pad negated), else
    NOT_DETERMINED -- never "MISSING" read from a name that merely does not spell a clamp."""
    signal: List[str] = []
    power: List[str] = []
    structural: List[str] = []
    for inst, master in components:
        c = classes.get(master)
        if c in _PAD_SIGNAL_CLASSES:
            signal.append(master)
        elif c in _PAD_POWER_CLASSES:
            power.append(master)
        elif c in _PAD_STRUCTURAL_CLASSES:
            structural.append(master)
    pads = signal + power
    if not pads and not structural:
        return {"source": None}
    def protected(m):
        if esd_evidence is not None and m in esd_evidence:
            return esd_evidence[m]["presence"] == "PRESENT"
        return _p._classify_io_cell(m) == "esd_pad"
    identified = [m for m in pads if protected(m)]
    negated = [m for m in pads
               if any(t in m.lower() for t in _p._ESD_NEGATION_HINTS)]
    unidentified = [m for m in pads if m not in identified and m not in negated]
    # Masters that belong to the ring but whose LEF CLASS names no bond-pad / ring role:
    # an IO-family name with no PAD/corner class, or a non-CORE macro class (e.g. a bare
    # pad shipped as CLASS BLOCK). Never read as "no pad ring".
    known = set(_PAD_SIGNAL_CLASSES) | set(_PAD_POWER_CLASSES) | set(_PAD_STRUCTURAL_CLASSES)
    unclassified = sorted({
        m for _i, m in components
        if classes.get(m) not in known
        and (_p._classify_io_cell(m) != "other"
             or (classes.get(m) or "").split(" ")[0] in ("BLOCK", "COVER", "RING"))})
    if not pads:
        # Classified corners/spacers with no classified bond pad: the ring exists and its
        # pads' roles are unknown -- NOT_DETERMINED naming them, never N/A.
        presence, status = "NOT_DETERMINED", "MANUAL_REVIEW"
    elif identified:
        presence, status = "PRESENT", "MANUAL_REVIEW"
    elif negated and not unidentified:
        presence, status = "MISSING", "MANUAL_REVIEW"
    else:
        presence, status = "NOT_DETERMINED", "MANUAL_REVIEW"
    return {
        "source": "lef_class",
        "status": status,
        "esd_presence": presence,
        "pads": len(pads),
        "signal_pads": len(signal),
        "power_pads": len(power),
        "structural": len(structural),
        "pad_masters": sorted(set(pads)),
        "esd_cells": len(identified),
        "esd_negated": len(negated),
        "esd_unidentified": len(unidentified),
        "esd_unidentified_masters": sorted(set(unidentified)),
        "unclassified_masters": unclassified,
        "note": (("the ring has " + str(len(structural)) + " classified corner/spacer "
                  "instance(s) but no master with a bond-pad LEF CLASS; unclassified ring "
                  "master(s): " + (", ".join(unclassified) or "none named") + " -- pad and "
                  "ESD roles NOT_DETERMINED, not N/A") if not pads else
                 ("pad roles from LEF CLASS (PAD INPUT/OUTPUT/INOUT/AREAIO = signal, "
                 "PAD POWER = power, PAD SPACER / IO corner = structural, not a pad); counts "
                 "are instances. ESD content is not stated for "
                 f"{len(unidentified)} pad instance(s) by any artefact in the run tree: "
                 "NOT_DETERMINED, not MISSING -- confirm from the IO library's ESD "
                 "documentation." if unidentified and not identified else
                 "pad roles from LEF CLASS; counts are instances")),
    }


def perc_io_evidence(design_dir: Path, pdk_dir: Optional[str]) -> Dict[str, Any]:
    """Read the run's IO views through the existing PDK discovery/read authority.

    Presence only: direct bond-to-rail drain-SAB MOS/diodes, or a diode across
    LEF-declared power/ground rails. No size, rating or robustness is inferred.
    Unreadable/missing netlists never acquire a pdk_netlist evidence label.
    """
    phys = physical_classes(str(design_dir))
    classes = dict(phys['classes'])
    roles, bonds, subckts, sub_sources = {}, {}, {}, {}
    sources, errors, limits = [], [], []
    lefs = [design_dir / f for f in phys['sources']['lef']]
    netlists, liberties = [], []
    tree = Path(pdk_dir) if pdk_dir else None
    if tree:
        try:
            lefs += _pr.discover_io_lefs(str(tree.parent), tree.name)
            netlists = _pr.discover_io_netlists(str(tree.parent), tree.name)
            liberties = _pr.discover_io_liberty(str(tree.parent), tree.name)
        except OSError as exc:
            errors.append(str(exc))

    def read(path, kind):
        try:
            text = _pr._ask(path, 'read')
            source = {'path': str(path), 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                      'kind': kind}
            sources.append(source)
            return text, source
        except OSError as exc:
            errors.append(f'{path}: {exc}')
            return None, None

    for path in dict.fromkeys(lefs):
        text, _ = read(path, 'lef')
        if text is not None:
            classes.update(_pr.parse_lef_macro_classes(text))
            roles.update(_pr.parse_lef_pin_roles(text))
    for path in liberties:
        text, _ = read(path, 'liberty_roles')
        if text is not None:
            for master, cell in _pr.parse_liberty_supply_view(text)['cells'].items():
                for pins in cell.values():
                    for pin, attrs in pins.items():
                        if str(attrs.get('is_pad', '')).lower() == 'true':
                            bonds.setdefault(master, set()).add(pin)
    for path in netlists:
        text, source = read(path, 'io_netlist')
        if text is not None:
            for master, body in _pr.parse_spice_subckts(text).items():
                subckts.setdefault(master, body)
                sub_sources.setdefault(master, source)
    evidence = {}
    for master in classes:
        if classes[master] not in _PAD_SIGNAL_CLASSES + _PAD_POWER_CLASSES:
            continue
        devices = []
        source = sub_sources.get(master)
        ports, body = subckts.get(master, ([], []))
        uses = {p: u for p, (_d, u) in roles.get(master, {}).items()}
        supply = {p for p in ports if uses.get(p) in ('POWER', 'GROUND')}
        bond = bonds.get(master, set())
        if len(bond) != 1:
            bond = set()
        for t in body:
            # A model is the last positional token before parameters. A gate
            # or bulk-only PAD connection is not a discharge path.
            positional = []
            for token in t[1:]:
                if '=' in token:
                    break
                positional.append(token)
            if len(positional) < 3:
                continue
            nodes, model = positional[:-1], positional[-1].lower()
            kind = None
            if (len(nodes) == 4 and re.search(r'(?:^|_)dss$', model)
                    and ((nodes[0] in bond and nodes[2] in supply)
                         or (nodes[2] in bond and nodes[0] in supply))):
                kind = 'bond_drain_sab_mos'
            if len(nodes) == 2 and (t[0][:1].lower() == 'd' or model.startswith('diode_')):
                a, b = nodes
                if (a in bond and b in supply) or (b in bond and a in supply):
                    kind = 'bond_rail_diode'
                if (classes[master] in _PAD_POWER_CLASSES
                        and {uses.get(a), uses.get(b)} == {'POWER', 'GROUND'}
                        and (a in bond or b in bond)):
                    kind = 'rail_diode'
            if kind:
                devices.append({'element': t[0], 'model': model, 'nodes': nodes, 'kind': kind})
        negated = any(t in master.lower() for t in _p._ESD_NEGATION_HINTS)
        fallback = source is None and _p._classify_io_cell(master) == 'esd_pad'
        evidence[master] = {
            'presence': ('MISSING' if negated else 'PRESENT' if devices or fallback
                         else 'NOT_DETERMINED'),
            'basis': ('explicit_noesd' if negated else 'pdk_netlist' if devices
                      else 'pdk_netlist_unproven' if source else 'name_hint_fallback'),
            'devices': devices, 'source': source}
    # L19 owns physical constraints; L9 may carry an explicit integration
    # contract. Read the same field in either; retain every authority, never
    # silently prefer a weaker limit. Provider bridge declarations use it too.
    gd = _p._pl.generated_docs_dir(design_dir)
    contracts = sorted(gd.glob('L19*.json')) + sorted(gd.glob('L9*.json'))
    if tree:
        contracts.append(tree / 'bridge/signoff_config.json')
    for path in contracts:
        try:
            if not _pr._ask(path, 'is_file'):
                continue
            text, source = read(path, 'supply_limit_contract')
            doc = json.loads(text) if text is not None else {}
            if 'io_supply_pad_sufficiency' in doc:
                limits.append({'declaration': doc['io_supply_pad_sufficiency'], 'source': source})
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f'{path}: {exc}')
    return {'classes': classes, 'pin_roles': roles,
            'bond_pins': {m: sorted(v) for m, v in bonds.items()},
            'esd_evidence': evidence, 'limits': limits, 'sources': sources, 'errors': errors}


def io_supply_pad_sufficiency(components, def_text: str, library) -> Dict[str, Any]:
    """Advisory PERC row; declared count violations contribute AUTOMATED FAIL.

    Counts are physical instances in each resolvable (power_net, ground_net).
    LEF USE identifies rails; Liberty is_pad identifies a supply pad's bond.
    Ambiguous/unconnected domains stay unknown. PASS means the declared count
    comparison only, never ESD/IR/SSN sign-off. There is no default ratio.

    Contract: io_supply_pad_sufficiency.domains[] contains power_net,
    ground_net, max_signal_pads_per_power_pad and/or
    max_signal_pads_per_ground_pad. Limits must be finite positive numbers.
    """
    classes, roles = library['classes'], library['pin_roles']
    census = pad_ring_census(components, classes)
    pads = [(i, m) for i, m in components
            if classes.get(m) in _PAD_SIGNAL_CLASSES + _PAD_POWER_CLASSES]
    unknown = [i for i, m in components if m in census.get('unclassified_masters', [])]
    if not census.get('source'):
        unknown = [i for i, m in components
                   if _p._classify_io_cell(m) in ('esd_pad', 'nonesd_pad')]
    # Retain PIN identity (the old topology reader deliberately drops it).
    # DEF wildcard terminals apply only to masters that declare that pin.
    pin_nets = {}
    for tag in ('NETS', 'SPECIALNETS'):
        section = re.search(r'^\s*' + tag + r'\b.*?^\s*END\s+' + tag + r'\b',
                            def_text, re.M | re.S)
        if not section:
            continue
        for ent in re.split(r'\n\s*-\s+', section.group())[1:]:
            net = ent.split()[0]
            for inst, pin in _p._NET_TERMINAL_RE.findall(ent):
                if inst != 'PIN':
                    pin_nets.setdefault((inst, pin), set()).add(net)
    domains = {}
    unresolved_supply_pair = False
    unknown_supply_pairs = set()
    for inst, master in pads:
        nets = {'POWER': set(), 'GROUND': set()}
        missing = False
        for pin, (_direction, use) in roles.get(master, {}).items():
            if use in nets:
                connected = pin_nets.get((inst, pin), pin_nets.get(('*', pin), set()))
                missing |= len(connected) != 1
                nets[use].update(connected)
        if missing or any(len(v) != 1 for v in nets.values()):
            unknown.append(inst)
            if classes[master] in _PAD_POWER_CLASSES:
                unresolved_supply_pair = True
            continue
        key = (next(iter(nets['POWER'])), next(iter(nets['GROUND'])))
        signal = classes[master] in _PAD_SIGNAL_CLASSES
        if not signal:
            bonds = library['bond_pins'].get(master, [])
            bond = bonds[0] if len(bonds) == 1 else None
            use = roles.get(master, {}).get(bond, ('', ''))[1]
            if use not in nets:
                unknown.append(inst)
                unknown_supply_pairs.add(key)
                continue
        row = domains.setdefault(key, {'power_net': key[0], 'ground_net': key[1],
                                      'signal_pads': 0, 'power_pads': 0, 'ground_pads': 0,
                                      'comparisons': []})
        if signal:
            row['signal_pads'] += 1
        else:
            row['power_pads' if use == 'POWER' else 'ground_pads'] += 1
    bad, incomplete = False, bool(unknown or not census.get('source'))
    for key, row in domains.items():
        # Unknown bond roles affect their known pair only. An unresolved pair
        # may belong to any candidate domain and must remain conservative.
        unknown_supply = unresolved_supply_pair or key in unknown_supply_pairs
        compared = set()
        for contract in library['limits']:
            declaration = contract['declaration']
            limits = declaration.get('domains', []) if isinstance(declaration, dict) else []
            if not isinstance(limits, list):
                incomplete = True
                continue
            for limit in limits:
                if not isinstance(limit, dict) or (limit.get('power_net'), limit.get('ground_net')) != key:
                    continue
                for polarity, count in (('power', 'power_pads'), ('ground', 'ground_pads')):
                    name = 'max_signal_pads_per_' + polarity + '_pad'
                    value = limit.get(name)
                    if value is None:
                        continue
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not math.isfinite(value) or value <= 0):
                        incomplete = True
                        continue
                    failed = row['signal_pads'] > value * row[count]
                    bad |= failed and not unknown_supply
                    compared.add(polarity)
                    row['comparisons'].append({'limit': name, 'value': value,
                                               'result': ('NOT_DETERMINED' if unknown_supply
                                                          else 'FAIL' if failed else 'PASS'),
                                               'source': contract['source']})
        if compared != {'power', 'ground'}:
            incomplete = True
    result = 'FAIL' if bad else 'MANUAL_REVIEW' if incomplete or not domains else 'PASS'
    if not pads and not census.get('source') and not any(
            _p._classify_io_cell(m) != 'other' for _, m in components):
        result = 'N/A'
    rows = list(domains.values())
    detail = '; '.join(f"{r['power_net']}/{r['ground_net']}: {r['signal_pads']} signal, "
                       f"{r['power_pads']} power, {r['ground_pads']} ground pad instances"
                       for r in rows)
    return {'category': 'io_supply_pad_sufficiency',
            'status': 'AUTOMATED' if result in ('PASS', 'FAIL') else result,
            'result': result, 'tool': 'DEF instances + LEF roles + Liberty bond terminals',
            'signal_pads': census.get('signal_pads'), 'power_pads': census.get('power_pads'),
            'domains': rows, 'unknown_domain_instances': sorted(unknown),
            'authority': library['limits'], 'library_errors': library['errors'],
            'note': (detail + f'; {len(unknown)} unknown-domain instance(s). ' +
                     ('Declared count comparison only; ESD/IR/SSN robustness remains manual.'
                      if result in ('PASS', 'FAIL') else
                      'Supply sufficiency NOT_DETERMINED: no complete applicable declared limits '
                      'or domain evidence; MANUAL_REVIEW. No default ratio.'))}


def _pick_routed_def(design_dir: str) -> Optional[str]:
    """Find the most-routed DEF under <design_dir>/phase3/**. Prefers a routed DEF, then a
    chip_top DEF, then post_hold, then any DEF. Returns None if the dir has no phase3 DEF."""
    cands = glob.glob(os.path.join(design_dir, "phase3", "**", "*.def"), recursive=True)
    if not cands:
        return None

    def _score(f: str) -> int:
        b = os.path.basename(f).lower()
        return (("routed" in b) * 4 + ("chip_top" in b) * 2 + ("post_hold" in b) * 1
                - ("floorplan" in b) * 3)   # floorplan DEF is pre-tapcell → deprioritise
    return sorted(cands, key=_score, reverse=True)[0]


# --------------------------------------------------------------- artifact-vintage guard
# suggested_fix #4 of ORGANIC-20260601-benchmark-ic-corpus-stale-pre-tapcell-fix:
# distinguish a STALE pre-tapcell artifact (a routed DEF whose whole lineage never ran the
# tapcell step) from a LIVE current-runner regression (a one-off 0-tap in an otherwise
# tap-bearing pipeline). Purely structural + chip-AGNOSTIC: no design/vendor literal, no
# version string parsed from the file (none is recorded reliably). The "older-version /
# sibling 0-tap" signal is derived from the DEF lineage itself.
_STALE_STD_CELL_MIN = 200   # below this a 0-tap DEF is a legit small block, not a regression


def _count_std_cells(components: List["tuple"]) -> int:
    """Placed transistor-bearing std cells (same exclusion rule as _welltap_presence_check —
    drop tap/fill/decap/diode/endcap/boundary/antenna physical-only masters)."""
    return sum(1 for _i, m in components
               if not _p._WELLTAP_TOKEN_RE.search(m.lower())
               and not any(t in m.lower() for t in ("decap", "fill", "diode", "tapvpwr",
                                                     "_endcap", "boundary", "antenna")))


def _stage_score(basename: str) -> int:
    """Pipeline-stage ordinal from a DEF basename (floorplan < placed < cts < hold < routed
    < chip_top). Used only to order sibling DEFs oldest→newest for the lineage scan."""
    b = basename.lower()
    for tok, rank in (("floorplan", 0), ("placed", 1), ("cts", 2), ("post_hold", 3),
                      ("hold", 3), ("routed", 4), ("chip_top", 5)):
        if tok in b:
            return rank
    return 2   # unknown mid-pipeline


def artifact_vintage_guard(routed_def: str,
                           sibling_defs: Optional[List[str]] = None,
                           std_cell_min: int = _STALE_STD_CELL_MIN,
                           welltap_cells: Optional[List[str]] = None) -> Dict[str, Any]:
    """WARN when a routed DEF with > std_cell_min placed std cells has 0 valid well/substrate
    taps AND an *older* sibling DEF (an earlier pipeline stage, or an older-version artifact of
    the same design) is ALSO 0-tap — the signature of a STALE pre-tapcell-fix artifact whose
    whole lineage never ran the tapcell step (the v0.1.46/v0.1.49 fix), as opposed to a LIVE
    current-runner regression.

    DISCRIMINATOR (chip-AGNOSTIC, purely structural):
      * a CURRENT run inserts taps from the `placed` stage onward (the FRESH spm control:
        floorplan=0 → placed/cts/hold/routed all=67). So in a healthy lineage the routed DEF
        is tap-bearing; a 0-tap routed DEF whose *earlier* sibling stages are ALSO 0-tap means
        the tapcell step never fired anywhere in the lineage = stale pre-fix artifact.
      * if the routed DEF HAS taps → not stale (verdict OK, never warns).
      * if std-cell count <= std_cell_min → legit small / floorplan block where 0 taps is not
        yet a regression signal (a floorplan DEF is pre-tapcell BY DESIGN) → verdict OK.
      * if there is NO 0-tap sibling (e.g. the only DEF is this one, or every sibling is
        tap-bearing) → cannot prove stale-vs-regression from lineage alone → verdict
        SUSPECT_LIVE (treat as a possible live regression: re-run a FRESH control to triage).

    verdict ∈ {OK, STALE_PRE_TAPCELL (warn), SUSPECT_LIVE (warn — needs fresh control), NA}.
    This NEVER fails a build; it is a triage WARN so a corpus PERC number is not mis-cited as a
    current-quality signal (the stale-artifact lesson, RESULT_PERC_CORPUS_v0211.md)."""
    rp = Path(routed_def)
    out: Dict[str, Any] = {"def": str(routed_def), "verdict": "NA", "warn": False}
    if not rp.is_file():
        out["reason"] = "routed DEF not found"
        return out
    comps = _p._parse_def_components(rp)
    wt = _p._welltap_presence_check(comps, rated_tap_masters=welltap_cells)
    n_std = _count_std_cells(comps)
    out.update({"n_std_cells": n_std, "n_tap": wt["n_tap"], "welltap": wt["status"]})

    if wt["status"] != "WELLTAP_GAP":
        # PRESENT (taps inserted → not stale) or NA (no std cells → not a placed block)
        out["verdict"] = "OK"
        out["reason"] = ("routed DEF is tap-bearing — not a stale pre-tapcell artifact"
                         if wt["status"] == "WELLTAP_PRESENT"
                         else "no placed std cells — not a placed block (vintage N/A)")
        return out

    if n_std <= std_cell_min:
        out["verdict"] = "OK"
        out["reason"] = (f"only {n_std} std cell(s) (<= {std_cell_min}) — legit small / "
                         "floorplan-class block; 0 taps not yet a regression signal")
        return out

    # routed DEF: many std cells, 0 valid taps. Scan the lineage for an OLDER 0-tap sibling.
    sibs = sibling_defs if sibling_defs is not None else _sibling_defs_for(routed_def)
    routed_rank = _stage_score(rp.name)
    older_zero_tap: List[str] = []
    for sf in sibs:
        sp = Path(sf)
        if sp.resolve() == rp.resolve() or not sp.is_file():
            continue
        if _stage_score(sp.name) > routed_rank:
            continue   # only OLDER-or-equal stages count as the prior-vintage lineage
        scomps = _p._parse_def_components(sp)
        if _p._welltap_presence_check(
                scomps, rated_tap_masters=welltap_cells)["n_tap"] == 0:
            older_zero_tap.append(sp.name)

    if older_zero_tap:
        out["verdict"] = "STALE_PRE_TAPCELL"
        out["warn"] = True
        out["older_zero_tap_siblings"] = sorted(older_zero_tap)
        out["reason"] = (
            f"{n_std} std cells, 0 taps, AND {len(older_zero_tap)} older/sibling DEF(s) "
            f"also 0-tap ({', '.join(sorted(older_zero_tap)[:4])}) — the tapcell step never "
            "ran anywhere in this lineage = STALE pre-tapcell-fix artifact. Regenerate "
            "through the current runner before citing its PERC number as a current-quality "
            "signal; this is NOT proof of a live current-runner bug.")
        return out

    out["verdict"] = "SUSPECT_LIVE"
    out["warn"] = True
    out["reason"] = (
        f"{n_std} std cells, 0 taps, but NO older 0-tap sibling found in the lineage — cannot "
        "prove stale-vs-regression structurally. Treat as a POSSIBLE live regression and "
        "re-run a FRESH same-version control to triage (stale-artifact lesson).")
    return out


def _sibling_defs_for(routed_def: str) -> List[str]:
    """All other DEFs in the same directory as the routed DEF — the design's pipeline-stage
    lineage (floorplan/placed/cts/hold/routed/chip_top). Chip-agnostic: just same-dir DEFs."""
    rp = Path(routed_def)
    return [str(f) for f in sorted(rp.parent.glob("*.def")) if f.resolve() != rp.resolve()]


def sweep_one(def_path: str, name: Optional[str] = None,
              vintage: bool = True,
              design_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run the full PERC structural chain on ONE routed DEF. Pure; no container.

    When `vintage` is True (default) it also runs the artifact-vintage guard
    (suggested_fix #4) over the DEF's same-dir lineage and attaches the verdict, so a
    corpus PERC number is auto-flagged as stale-pre-tapcell vs a possible live regression."""
    p = Path(def_path)
    out: Dict[str, Any] = {"name": name or p.stem, "def": str(def_path),
                           "perc_chain_ran": False}
    if not p.is_file():
        out["error"] = "DEF not found"
        return out
    # From here down the PERC decision point IS entered. The flag is set
    # structurally, at the point of entry — never inferred later from the
    # presence or absence of an `error` string, because deriving a reach claim
    # from prose is the same defect one layer down (_vacuous_exit's rule).
    out["perc_chain_ran"] = True
    comps = _p._parse_def_components(p)
    out["components"] = len(comps)
    phys = physical_classes(design_dir)
    welltap_cells = phys["welltap_cells"] or None
    out["physical_classes"] = {
        "welltap_cells": phys["welltap_cells"],
        "welltap_from_lef_class": phys.get("welltap_from_lef_class", []),
        "welltap_from_pdk_config": phys.get("welltap_from_pdk_config", []),
        "lef_sources": len(phys["sources"]["lef"]),
        "welltap_config_sources": phys["sources"]["welltap_cell_config"]}
    census = pad_ring_census(comps, phys["classes"])
    esd = _p._esd_pad_ring_presence(comps)
    if census.get("source"):
        out["esd_presence"] = {k: v for k, v in census.items() if k != "note"}
        out["esd_presence"]["note"] = census["note"]
    else:
        out["esd_presence"] = {"status": esd["status"],
                               "esd_presence": esd.get("esd_presence"),
                               "pads": esd["pad_count"], "esd_cells": esd["esd_count"],
                               "source": "name_hint_masters"}
    if out["esd_presence"]["status"] != "N/A":
        nt = _p._parse_def_net_terminals(p.read_text(errors="ignore"))
        topo = _p._esd_discharge_topology(comps, nt)
        out["esd_topology"] = {"status": topo["status"], "gaps": len(topo["gaps"]),
                               "unrated": topo["unrated_clamps"][:4]}
    wt = _p._welltap_presence_check(comps, rated_tap_masters=welltap_cells)
    out["welltap"] = {"status": wt["status"], "n_tap": wt["n_tap"],
                      "reason": wt.get("reason", "")}
    xd = _p._xdomain_levelshifter_check(p, comps)
    out["xdomain"] = {"status": xd["status"], "result": xd["result"],
                      "n_power_domains": len(xd["power_domains"]),
                      "n_ground_domains": len(xd["ground_domains"]),
                      "n_crossing": xd["n_crossing"], "source": xd["domain_source"]}
    if vintage:
        vg = artifact_vintage_guard(str(p), welltap_cells=welltap_cells)
        out["vintage"] = {"verdict": vg["verdict"], "warn": vg["warn"],
                          "reason": vg.get("reason", ""),
                          "older_zero_tap_siblings": vg.get("older_zero_tap_siblings", [])}
    return out


def sweep_dirs(dirs: List[str], vintage: bool = True) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in dirs:
        name = os.path.basename(d.rstrip("/"))
        dp = _pick_routed_def(d)
        if dp is None:
            rows.append({"name": name, "def": None, "error": "no routed DEF",
                         "perc_chain_ran": False})
            continue
        rows.append(sweep_one(dp, name=name, vintage=vintage, design_dir=d))
    return rows


def reach_of(rows: List[Dict[str, Any]]) -> "_sr.SweepReach":
    """How many corpus targets actually entered the PERC chain.

    Reads each row's structural `perc_chain_ran` flag — set inside `sweep_one`
    at the point of entry — rather than re-deriving the answer from the row's
    prose. A corpus of 21 ICs none of which carries a routed DEF produces 21
    rows, a full table and, before this, rc 0.
    """
    reach = _sr.SweepReach(unit="design directory", decision_points=("perc_chain",))
    for r in rows:
        if r.get("perc_chain_ran"):
            reach.reached(r.get("name") or r.get("def"), point="perc_chain")
        else:
            reach.not_reached(r.get("name") or r.get("def") or "<unnamed>",
                              str(r.get("error") or "no routed DEF found"))
    if not rows:
        reach.declare_empty_corpus(
            "no design directory or --def target was supplied to the sweep")
    return reach


def summarize(rows: List[Dict[str, Any]]) -> str:
    """Human summary + systemic counts (the corpus-scale signal)."""
    swept = [r for r in rows if "error" not in r]
    no_def = [r for r in rows if r.get("error")]
    lines = [f"{'IC':28s} {'comps':>7s}  {'ESD':9s} {'welltap':14s} xdomain(pwr/gnd,cross)"]
    for r in sorted(swept, key=lambda x: -x.get("components", 0)):
        e = r.get("esd_presence", {}); w = r.get("welltap", {}); x = r.get("xdomain", {})
        lines.append(f"{r['name']:28s} {r.get('components', 0):7d}  "
                     f"{str(e.get('status', '')):9s} {str(w.get('status', '')):14s} "
                     f"{x.get('status', '')}({x.get('n_power_domains', '')}/"
                     f"{x.get('n_ground_domains', '')},{x.get('n_crossing', '')})")
    gap = sum(1 for r in swept if r.get("welltap", {}).get("status") == "WELLTAP_GAP")
    na = sum(1 for r in swept if r.get("esd_presence", {}).get("status") == "N/A")
    xna = sum(1 for r in swept if r.get("xdomain", {}).get("status") == "N/A")
    xinc = sum(1 for r in swept if r.get("xdomain", {}).get("status") == "INCOMPLETE")
    v_stale = sum(1 for r in swept
                  if r.get("vintage", {}).get("verdict") == "STALE_PRE_TAPCELL")
    v_susp = sum(1 for r in swept
                 if r.get("vintage", {}).get("verdict") == "SUSPECT_LIVE")
    lines += [
        "", "=== systemic ===",
        f"  {reach_of(rows).line()}",
        f"  swept: {len(swept)}   no-DEF (excluded): {len(no_def)}",
        f"  welltap WELLTAP_GAP (0-tap latch-up exposure): {gap}/{len(swept)}",
        f"  ESD N/A (core macro, no pad ring): {na}/{len(swept)}",
        f"  xdomain N/A (single supply): {xna}/{len(swept)}   INCOMPLETE: {xinc}/{len(swept)}",
        f"  vintage STALE_PRE_TAPCELL (whole-lineage 0-tap, regenerate before citing): "
        f"{v_stale}/{len(swept)}",
        f"  vintage SUSPECT_LIVE (0-tap routed, no 0-tap sibling — needs fresh control): "
        f"{v_susp}/{len(swept)}",
        "  NOTE: a corpus-wide GAP is NOT a current-runner bug until checked vs a FRESH",
        "        same-version control (stale-artifact lesson, RESULT_PERC_CORPUS_v0211.md).",
        "  NOTE: vintage=STALE_PRE_TAPCELL is the structural proof the lineage predates the",
        "        tapcell-insertion fix; vintage=SUSPECT_LIVE means triage as a possible",
        "        regression (re-run a fresh control) rather than assume stale.",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dirs", nargs="*", help="design directories (each with phase3/**/*.def)")
    ap.add_argument("--def", dest="def_path", help="a single explicit routed DEF")
    ap.add_argument("--name", help="name for the single --def design")
    ap.add_argument("--json", action="store_true", help="emit a JSON array only (no summary)")
    ap.add_argument("--no-vintage", action="store_true",
                    help="skip the artifact-vintage (stale-pre-tapcell) guard")
    ap.add_argument("--vintage", dest="vintage_def",
                    help="run ONLY the artifact-vintage guard on one routed DEF + print JSON")
    ap.add_argument("--report", metavar="PATH",
                    help="write {rows, reach} here — the document "
                         "`sweep_reach_check.py --report` consumes")
    args = ap.parse_args(argv)

    if args.vintage_def:
        # Single-target diagnostic mode, not a corpus sweep: there is no
        # aggregate to be vacuous about, so the reach contract does not apply.
        print(json.dumps(artifact_vintage_guard(args.vintage_def), indent=2))
        return 0

    do_vintage = not args.no_vintage
    if args.def_path:
        rows = [sweep_one(args.def_path, name=args.name, vintage=do_vintage)]
    elif args.dirs:
        rows = sweep_dirs(args.dirs, vintage=do_vintage)
    else:
        ap.error("give one or more design dirs, or --def <routed.def>")
        return 2

    reach = reach_of(rows)
    if args.json:
        # The stdout document stays the ROW ARRAY its consumers already parse;
        # the reach block rides on --report so adopting the contract cannot
        # break a caller that indexes rows by position.
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(json.dumps(r))
        print("\n" + summarize(rows), file=sys.stderr)
    if args.report:
        import _gate_authorship as _ga
        doc: Dict[str, Any] = {"program": "perc_corpus_sweep",
                               "sweep": "perc_corpus_sweep", "rows": rows}
        _sr.attach(doc, reach)
        _ga.stamp(doc)
        Path(args.report).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    # A sweep that entered the PERC chain on NOTHING is not a clean corpus
    # result; rc 2 + the sentinel are the two signals flow_compliance_check
    # actually consumes. A partial sweep (>= 1 target reached) stays rc 0.
    reach.announce("perc_corpus_sweep")
    return reach.exit_code(passed=True)


if __name__ == "__main__":
    raise SystemExit(main())
