#!/usr/bin/env python3
"""
fault_scan_chain_insert.py — REAL scan-chain insertion via `fault chain`.

Produces the IMPLEMENTATION netlist that carries the scan chain:

  <project>/phase2/stage2/dft/scan_netlist.v        (scan-inserted netlist)
  <project>/reports/phase2/dft/scan_chain.json      (MEASURED chain metadata)

WHY THIS PROGRAM EXISTS
-----------------------
Before it, `scan_netlist.v` was a BYTE COPY of `cut_netlist.v` — Fault's ATPG
*cut* view, in which every flip-flop has been replaced by a `<inst>.d`
pseudo-PI/PO pair.  That is a combinational transform for fault simulation; it
is not a netlist anyone can build.  Two things followed from it:

  * step 12 `opt_clean`ed the cut view into `post_dft_netlist.v`, so the
    artefact the flow calls "the post-DFT netlist" had ZERO flip-flops, and
    step 13 (`RTL == post-DFT netlist`) could not compare anything — a cut
    netlist is combinationally unequal to its RTL BY CONSTRUCTION;
  * place-and-route read `<top>_synth.v`, the PRE-DFT netlist, so the routed,
    tape-out-bound design carried NO SCAN CHAIN at all while ATPG reported
    stuck-at coverage on a netlist that never becomes silicon.

Standard ASIC practice is scan insertion BEFORE place-and-route: the routed
design carries the chain and the tape-out is production-testable, and the ATPG
cut view is DERIVED from the scan netlist rather than substituted for it.

WHAT IS MEASURED, NEVER ASSERTED
--------------------------------
`fault chain` prints its own chain counts, AND embeds a machine-readable
`/* FAULT METADATA: {...} */` header in the output netlist naming every chain
element in order.  This program reads BOTH and cross-checks them against the
flop count it counts in the INPUT netlist.  `chain_length_matches_flop_count`
is a MEASUREMENT — the run is not called good because the tool exited 0.

Exit 0 = a scan netlist was produced AND the chain covers every input flop.
Exit 1 = `fault chain` ran but the result does not measure clean (the JSON
         says exactly which check failed; no artefact is silently accepted).
Exit 2 = usage / IO / Docker error, or no Liberty resolvable for this PDK.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import _path_layout as _pl
import fault_atpg_run as _fatpg
import floorplan_contract as _fpc
import l_doc_consumer_contract as _ldoc
import pdk_cell_models as _pcm  # ciel version-hash live resolution (gf180)
import scan_mode_constraint as _smc


# ---------------------------------------------------------------------------
# Liberty resolution — `fault chain` REQUIRES --liberty (unlike `fault cut`)
# ---------------------------------------------------------------------------
# Container-absolute typical-corner Liberty per PDK, keyed by the SAME PDK ids
# `fault_atpg_run.PDK_CONFIG` uses, so a design can never resolve its cell
# MODEL from one library and its Liberty from another (the exact two-table
# defect ORGANIC #410 removed for the cell model).  A PDK absent from this
# table resolves nothing and the run REFUSES — it never substitutes another
# foundry's Liberty.
SCAN_LIBERTY = {
    "sky130": ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
               "sky130_fd_sc_hd__tt_025C_1v80.lib"),
    "gf180": ("/foss/pdks/ciel/gf180mcu/versions/"
              "8f2d1529c86235d726979eb9ecb7e9628108590b"
              "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
              "gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80.lib"),
    "ihp-sg13g2": ("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/"
                   "sg13g2_stdcell_typ_1p20V_25C.lib"),
    # NanGate45 / FreePDK45 (OpenROAD reference PDK). The container ships the
    # typical-corner Liberty; `fault chain` needs exactly this to stitch the
    # scan chain. Keyed by the same `nangate45` id fault_atpg_run.PDK_CONFIG now
    # uses, so cell-MODEL and Liberty can never resolve from different libraries
    # (the two-table invariant ORGANIC #410 established). See the PDK_CONFIG
    # note there: this makes scan insertion RUN on a mapped NanGate45 netlist
    # that was previously refused as pdk 'unmapped'.
    "nangate45": ("/foss/pdks/nangate45/libs.ref/NangateOpenCellLibrary/lib/"
                  "NangateOpenCellLibrary_typical.lib"),
}

# `fault chain`'s DFT port option names.  These are OPTION NAMES we pass, so
# the resulting port names are KNOWN, never sniffed out of the netlist.  The
# value is what functional mode drives them to (`sout` is an OUTPUT and is
# left dangling — it has no RTL counterpart).
FUNCTIONAL_MODE_TIEOFF = {"sin": 0, "shift": 0, "test": 0, "tck": 0}
SCAN_OUT_PORT = "sout"
DFT_PORTS = (*FUNCTIONAL_MODE_TIEOFF, SCAN_OUT_PORT)

SCAN_NETLIST_REL = "phase2/stage2/dft/scan_netlist.v"
SCAN_JSON_REL = "reports/phase2/dft/scan_chain.json"


def load_d09_dft_contract(project: Path, expected_clock=None, expected_reset=None,
                         reset_active_low=False) -> tuple[dict | None, list[str]]:
    """BLOCKING D09 intent admission; no topology or chain length is inferred.

    Reuse the spec's existing declaration artifact and its normal producer.
    Missing/forged authority is a refusal, never scan_test:false. Other DFT
    capabilities remain composable; this consumer decides scan only.
    """
    import spec_declaration_emit as declaration
    try:
        contract, why, _ = declaration.select_contract(project)
        if not contract or not any(f['name'] == 'dft' for f in contract['fields']):
            return None, ['D09_DFT_SPEC_MISSING: existing specification must declare dft']
        path = project / contract['artifact_path']
        if not path.resolve().is_relative_to(project.resolve()):
            raise ValueError('declaration escapes project')
        checked = declaration.verify_declaration(project, contract, path)
        if (checked['verdict'] != 'PASS' or checked['provenance_unverified']
                or checked['recovered_from_prose']):
            raise ValueError('normal declaration producer provenance is incomplete')
        sidecar = path.with_name(path.stem + '.provenance.json')
        claims = [json.loads(line) for line in (project / 'provenance.jsonl').read_text().splitlines()
                  if line.strip()]
        claims = [r for r in claims if r.get('tool') == 'spec_declaration_emit'
                  and str(path.relative_to(project)) in r.get('outputs', {})
                  and r.get('exit_code') == 0]
        if not claims:
            raise ValueError('normal declaration publication is missing')
        claim = claims[-1]
        digest = lambda p: 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()
        if claim.get('source_sha256') != digest(Path(declaration.__file__)):
            raise ValueError('declaration producer source differs')
        for output in (path, sidecar):
            if claim['outputs'].get(str(output.relative_to(project))) != digest(output):
                raise ValueError('declaration publication output differs')
        sources = {}
        for rel, expected in claim.get('inputs', {}).items():
            source = project / rel
            if source in (path, sidecar) or rel.startswith('phase1/generated_docs/'):
                continue
            if not source.resolve().is_relative_to(project.resolve()) or digest(source) != expected:
                raise ValueError('declaration source is foreign or changed: ' + rel)
            sources[rel] = expected
        if contract['source'] not in sources:
            raise ValueError('the specification is not bound by the publication')
        intent = json.loads(path.read_text())['dft']
        if not isinstance(intent, dict) or type(intent.get('scan_test')) is not bool:
            raise ValueError('scan_test must be an explicit Boolean')
        if any(k in intent for k in ('length', 'chain_length', 'scan_chains')):
            raise ValueError('caller-predeclared topology/length is not planned intent')
        binding = {'path': str(path.relative_to(project)),
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'sources': sources, 'intent': intent}
        if not intent['scan_test']:
            return binding, []
        definitions = intent.get('test_port_def', {})
        native = {'scan_enable': 'shift', 'scan_in': 'sin', 'scan_out': SCAN_OUT_PORT,
                  'test': 'test', 'tck': 'tck'}
        ports = {}
        if set(definitions) != set(native):
            raise ValueError('all five native test_port_def bindings are required')
        for role, name in native.items():
            entry = definitions[role]
            if (not isinstance(entry, dict) or entry.get('native') != name
                    or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', str(entry.get('public', '')))):
                raise ValueError('unsupported public/native test port binding: ' + role)
            ports[role] = entry['public']
        if len(set(ports.values())) != 5:
            raise ValueError('public scan interface ports must be distinct')
        mode = intent.get('test_mode', {})
        clock = mode.get('clock')
        reset = mode.get('reset', {})
        if (not isinstance(clock, str) or not clock
                or mode.get('clock_domains') != [clock] or mode.get('edge') != 'rising'):
            raise ValueError('unsupported or unknown clock/domain/edge strategy')
        if expected_clock is not None and clock != expected_clock:
            raise ValueError('test clock differs from the actual caller clock')
        selector = mode.get('clock_select', {})
        if (mode.get('scan_clock') != native['tck']
                or mode.get('scan_clock_domains') != [native['tck']]
                or mode.get('scan_edge') != 'rising'
                or selector.get('native') != native['test']
                or type(selector.get('functional_value')) is not int
                or type(selector.get('scan_value')) is not int
                or selector['functional_value'] != 0 or selector['scan_value'] != 1
                or clock in native.values()):
            raise ValueError('explicit distinct functional/scan clock and test-select roles required')
        if (reset.get('style') != 'synchronous' or type(reset.get('active_level')) is not int
                or reset['active_level'] not in (0, 1)
                or type(reset.get('shift_value')) is not int
                or reset.get('shift_value') != 1 - reset['active_level']
                or not isinstance(reset.get('signal'), str) or not reset['signal']):
            raise ValueError('unsupported or unknown reset strategy')
        if expected_reset is not None and (reset['signal'] != expected_reset
                or reset['active_level'] != int(not reset_active_low)):
            raise ValueError('test reset differs from the actual caller reset/polarity')
        if clock in ports.values() or reset['signal'] in ports.values():
            raise ValueError('test access aliases clock/reset')
        return binding, []
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, ['D09_DFT_AUTHORITY_INVALID: ' + str(exc)]


def _native_clock_controls(text: str, liberty_text: str, intent: dict) -> dict:
    """BLOCKING native evidence: prove the actual mux and every DFF clock.

    Reuse the existing netlist/Liberty readers and Boolean evaluator. Names
    in D09 are authority, not evidence that a mux or clock wire exists.
    """
    from itertools import product
    from lec_post_layout_check import (
        _parse_netlist_instances, _parse_liberty_pins, _LIB_CELL_RE, _brace_block, _LibertyFn, _vid)
    mode = intent['test_mode']
    functional, scan, select = mode['clock'], mode['scan_clock'], mode['clock_select']['native']
    for role, definition in intent['test_port_def'].items():
        direction = 'output' if role == 'scan_out' else 'input'
        if not re.search(r'\b' + direction + r'\s+(?:wire\s+)?'
                         + re.escape(definition['native']) + r'\s*;', text):
            raise ValueError('native test port absent/wrong direction: ' + role)
    if not re.search(r'\binput\s+(?:wire\s+)?' + re.escape(functional) + r'\s*;', text):
        raise ValueError('native functional clock is not an input')
    instances = _parse_netlist_instances(text)
    library = _parse_liberty_pins(liberty_text)
    if any(cell not in library for cell, _ in instances.values()):
        raise ValueError('unknown/unclassified native cell')
    sequential = _fatpg.liberty_sequential_cells(liberty_text, include_latches=True)
    semantics = {}
    for match in _LIB_CELL_RE.finditer(liberty_text):
        cell = match.group(1)
        if cell not in sequential:
            continue
        body, _ = _brace_block(liberty_text, match.end())
        ff = re.search(r'\bff\s*\(\s*"?([\w$]+)"?\s*,[^)]*\)\s*\{', body)
        if not ff:
            continue
        state, _ = _brace_block(body, ff.end())
        attrs = dict(re.findall(r'\b(clocked_on|next_state|clear|preset)\s*:\s*"([^"]*)"', state))
        outputs = [pin for pin, expr in library[cell]['outputs'].items() if expr == ff.group(1)]
        if (len(outputs) == 1 and all(re.fullmatch(r'[A-Za-z_][\w$]*', attrs.get(k, ''))
                                     for k in ('clocked_on', 'next_state'))):
            semantics[cell] = (attrs, outputs[0])
    flops = {name: (cell, pins) for name, (cell, pins) in instances.items() if cell in sequential}
    if not flops or any(cell not in semantics for cell, _ in flops.values()):
        raise ValueError('native sequential clock semantics unsupported/absent')
    drivers = {}
    for name, (cell, pins) in instances.items():
        for pin, expr in library[cell]['outputs'].items():
            net = pins.get(pin)
            if net is None or net in drivers:
                raise ValueError('native output missing or multiply driven')
            drivers[net] = None if cell in sequential else (expr, pins, library[cell]['inputs'])
    aliases = {_vid(a): _vid(b) for a, b in re.findall(r'\bassign\s+(\\\S+|[\w$]+)\s*=\s*(\\\S+|[\w$]+)\s*;', text)}

    def signal(net, values, trail=()):
        if net in values:
            return values[net]
        if net in ("1'b0", "1'b1", '0', '1'):
            return net in ("1'b1", '1')
        if net is None or net in trail:
            raise ValueError('missing/cyclic native control connection')
        if net in aliases:
            return signal(aliases[net], values, (*trail, net))
        driver = drivers.get(net)
        if driver is None:
            return net
        expr, pins, inputs = driver
        if not isinstance(expr, str):
            raise ValueError('unknown native pin function')
        fn = _LibertyFn(expr)
        if ''.join(fn.toks) != re.sub(r'\s+', '', expr):
            raise ValueError('unsupported native pin function')
        symbols = {p: values.get(pins.get(p), pins.get(p)) for p in inputs}
        symbols = {p: (v == "1'b1") if v in ("1'b0", "1'b1") else v for p, v in symbols.items()}
        leaves = sorted({v for v in symbols.values() if isinstance(v, str)})
        if None in symbols.values() or len(leaves) > 6:
            raise ValueError('unsupported native control cone')
        table = [(bits, fn({p: dict(zip(leaves, bits)).get(v, v) for p, v in symbols.items()}))
                 for bits in product((False, True), repeat=len(leaves))]
        if len({out for _, out in table}) == 1:
            return table[0][1]
        for i, leaf in enumerate(leaves):
            if all(out == bits[i] for bits, out in table):
                return signal(leaf, values, (*trail, net))
        return net  # opaque functional logic cannot prove a control/scan connection

    meta = parse_chain_metadata(text) or {}
    order = meta.get('order', [])
    if (not order or any(e.get('kind') not in ('dff', 'input', 'output') or e.get('width') != 1
                         for e in order)
            or sum(e['kind'] == 'dff' for e in order) != meta.get('internalCount')
            or sum(e['kind'] != 'dff' for e in order) != meta.get('boundaryCount')
            or len(order) != len(flops)
            or any(meta.get(k) != k for k in ('sin', 'sout', 'shift'))):
        raise ValueError('unknown/unclassified Fault order or native sequential census')
    reset = mode['reset']
    shift = intent['test_port_def']['scan_enable']['native']
    scan_values = {select: True, shift: True, reset['signal']: bool(reset['shift_value'])}
    previous, classified = meta['sin'], {}
    for entry in order:
        candidates = []
        for name, (cell, pins) in flops.items():
            attrs, output = semantics[cell]
            if name not in classified and signal(pins.get(attrs['next_state']), scan_values) == previous:
                candidates.append((name, cell, pins, attrs, output))
        if len(candidates) != 1:
            raise ValueError('Fault order does not uniquely classify every native flop')
        name, cell, pins, attrs, output = candidates[0]
        kind, q = entry['kind'], pins[output]
        if kind != 'dff' and pins.get(attrs['clocked_on']) != scan:
            raise ValueError('boundary flop does not use direct authorized scan clock')
        controls = {k: v for k, v in attrs.items() if k in ('clear', 'preset')}
        if kind == 'dff' and controls:
            raise ValueError('internal asynchronous controls contradict synchronous reset authority')
        if kind != 'dff':
            if (set(controls) != {'clear'} or ''.join(_LibertyFn(controls['clear']).toks)
                    != re.sub(r'\s+', '', controls['clear'])):
                raise ValueError('boundary reset/control semantics unsupported')
            for testing, resetting in product((False, True), repeat=2):
                values = {select: testing, shift: False, reset['signal']: resetting}
                env = {pin: signal(pins.get(pin), values) for pin in library[cell]['inputs']}
                used = set(_LibertyFn(controls['clear']).toks) & set(env)
                if (any(type(env[p]) is not bool for p in used)
                        or _LibertyFn(controls['clear'])(env) !=
                        (resetting == bool(reset['active_level']) and not testing)):
                    raise ValueError('boundary reset is not authorized reset gated by test')
            if kind == 'input':
                values = {select: False, shift: False, reset['signal']: bool(reset['shift_value'])}
                if (signal(pins[attrs['next_state']], values) != entry['name']
                        or signal(pins[attrs['next_state']], {**values, select: True}) != q):
                    raise ValueError('boundary input capture/test control differs from Fault order')
            elif signal(entry['name'], scan_values) != previous:
                raise ValueError('boundary output differs from Fault order connection')
        else:
            values = {select: False, shift: False, reset['signal']: bool(reset['active_level'])}
            if (type(signal(pins[attrs['next_state']], values)) is not bool
                    or type(signal(pins[attrs['next_state']],
                                   {**values, reset['signal']: bool(reset['shift_value'])})) is bool):
                raise ValueError('internal synchronous reset authority is unproved')
        classified[name] = {'kind': kind, 'order_name': entry['name'],
                            'clock': pins.get(attrs['clocked_on'])}
        previous = q
    if signal(meta['sout'], scan_values) != previous:
        raise ValueError('native chain does not terminate at authorized scan output')
    clocks = {v['clock'] for v in classified.values() if v['kind'] == 'dff'}
    if len(clocks) != 1 or None in clocks:
        raise ValueError('native internal flops do not share the authorized clock-source domain')
    clock_net = next(iter(clocks))
    matches = []
    for name, (cell, pins) in instances.items():
        if cell in sequential or cell not in library:
            continue
        inputs = library[cell]['inputs']
        if (len(inputs) != 3 or {pins.get(pin) for pin in inputs} != {functional, scan, select}):
            continue
        for output, expression in library[cell]['outputs'].items():
            if pins.get(output) != clock_net or not isinstance(expression, str):
                continue
            fn = _LibertyFn(expression)
            if ''.join(fn.toks) != re.sub(r'\s+', '', expression):
                continue
            if all(fn({pin: dict(zip((functional, scan, select), values))[pins[pin]] for pin in inputs})
                   == (values[1] if values[2] else values[0])
                   for values in product((False, True), repeat=3)):
                matches.append({'instance': name, 'cell': cell, 'output_pin': output})
    if len(matches) != 1:
        raise ValueError('native clock mux does not implement the declared clk/tck/test selection')
    return {'functional_clock': functional, 'scan_clock': scan, 'clock_select': select,
            'functional_value': 0, 'scan_value': 1, 'clock_net': clock_net,
            'mux': matches[0], 'flop_clocks': {name: classified[name]['clock'] for name in sorted(flops)},
            'flop_roles': classified}


def load_l20_scan_contract(project: Path, expected_clock: str | None = None,
                           expected_length: int | None = None
                           ) -> tuple[dict | None, list[str]]:
    """The one-chain contract this producer can implement, plus refusals.

    ``fault chain`` exposes one internal chain with fixed ``sin``/``sout``
    ports. Refuse unsupported shapes before launching the native tool. A
    declared shift frequency is implemented by a separate source-bound
    scan-mode SDC; it never replaces the functional-mode SDC.
    """
    path, doc = _ldoc.load_l_doc(project, "L20")
    if path is None or not isinstance(doc, dict):
        return None, ["canonical L20 scan contract is missing or unparseable"]
    try:
        raw = path.read_bytes()
        rel = path.relative_to(project).as_posix()
    except (OSError, ValueError):
        return None, ["canonical L20 scan contract cannot be read in-project"]
    fields = _ldoc.l_doc_fields(doc)
    chains = fields.get("scan_chains") if isinstance(fields, dict) else None
    if not isinstance(chains, list) or len(chains) != 1:
        count = len(chains) if isinstance(chains, list) else 0
        return None, [
            f"fault chain supports exactly one declared scan chain; L20 has {count}"]
    chain = chains[0]
    if not isinstance(chain, dict):
        return None, ["L20 scan_chains[0] is not a typed record"]
    problems: list[str] = []
    name = chain.get("name")
    length = chain.get("length")
    scan_in = chain.get("scan_in")
    scan_out = chain.get("scan_out")
    clock = chain.get("clock")
    if not isinstance(name, str) or not name.strip():
        problems.append("L20 scan chain has no non-empty canonical name")
    if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
        problems.append("L20 scan chain length is not a positive integer")
    if scan_in != "sin":
        problems.append(
            f"L20 scan_in={scan_in!r}; fault chain implements fixed port 'sin'")
    if scan_out != "sout":
        problems.append(
            f"L20 scan_out={scan_out!r}; fault chain implements fixed port 'sout'")
    if not isinstance(clock, str) or not clock.strip():
        problems.append("L20 scan chain clock is empty")
    elif expected_clock is not None and clock != expected_clock:
        problems.append(
            f"L20 clock={clock!r} does not match Step 11 clock={expected_clock!r}")
    if expected_length is not None and length != expected_length:
        problems.append(
            f"L20 length={length!r} does not match mapped-netlist flop count "
            f"{expected_length}")
    frequency_values = [chain.get(key) for key in (
        "frequency_mhz", "shift_frequency_mhz", "shift_freq_mhz")
        if chain.get(key) not in (None, "")]
    if len(frequency_values) > 1:
        problems.append("L20 declares more than one scan-shift frequency field")
    frequency = frequency_values[0] if frequency_values else None
    frequency_text, _period = _smc.frequency_period(frequency)
    if frequency is not None and frequency_text is None:
        problems.append("L20 scan-shift frequency is not finite and positive")
    if problems:
        return None, problems
    canonical = {
        "name": name.strip(), "length": length, "scan_in": scan_in,
        "scan_out": scan_out, "clock": clock,
    }
    if frequency_text is not None:
        canonical["frequency_mhz"] = frequency_text
    return {
        "path": rel,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "chain_count": 1,
        "chain": canonical,
    }, []


def reconcile_l20_scan_contract(binding: dict, report: dict) -> dict:
    """Compare native measurements to the exact L20 declaration. PURE."""
    chain = binding.get("chain") if isinstance(binding, dict) else None
    chain = chain if isinstance(chain, dict) else {}
    ports = set(report.get("dft_ports") or [])
    measured_count = 1 if isinstance(report.get("internal_chain_length"), int) else 0
    problems: list[str] = []
    if measured_count != binding.get("chain_count"):
        problems.append(
            f"measured chain count {measured_count} != declared "
            f"{binding.get('chain_count')}")
    if report.get("internal_chain_length") != chain.get("length"):
        problems.append(
            f"measured chain length {report.get('internal_chain_length')!r} != "
            f"declared {chain.get('length')!r}")
    for key in ("scan_in", "scan_out"):
        if chain.get(key) not in ports:
            problems.append(
                f"measured DFT ports do not contain declared {key}="
                f"{chain.get(key)!r}")
    if report.get("clock") != chain.get("clock"):
        problems.append(
            f"measured clock {report.get('clock')!r} != declared "
            f"{chain.get('clock')!r}")
    expected_frequency = chain.get("frequency_mhz")
    constraint = report.get("scan_mode_constraint")
    if expected_frequency is not None:
        frequency, period = _smc.frequency_period(expected_frequency)
        if not isinstance(constraint, dict):
            problems.append("declared scan-shift frequency has no constraint receipt")
        else:
            expected_fields = {
                "clock": chain.get("clock"), "frequency_mhz": frequency,
                "period_ns": period, "l20_path": binding.get("path"),
                "l20_sha256": binding.get("sha256"),
            }
            for key, value in expected_fields.items():
                if constraint.get(key) != value:
                    problems.append(
                        f"scan-mode constraint {key}={constraint.get(key)!r} != "
                        f"declared {value!r}")
    elif constraint is not None:
        problems.append("scan-mode constraint exists without a declared frequency")
    return {
        "ok": not problems,
        "declared": chain,
        "measured": {
            "chain_count": measured_count,
            "length": report.get("internal_chain_length"),
            "dft_ports": sorted(ports),
            "clock": report.get("clock"),
        },
        "problems": problems,
    }


def l20_binding_is_current(project: Path, report: dict) -> tuple[bool, str]:
    """Re-derive the current contract and compare its path, bytes and fields."""
    if isinstance(report, dict) and 'd09_contract' in report:
        current_d09, problems = load_d09_dft_contract(project)
        if problems or current_d09 != report['d09_contract']:
            return False, 'current D09 authority differs from the scan receipt'
        try:
            for path, expected in report['measured_artifacts'].items():
                item = project / path
                if (not item.resolve().is_relative_to(project.resolve())
                        or hashlib.sha256(item.read_bytes()).hexdigest() != expected):
                    return False, 'foreign/stale mapped scan artifact or native report'
            native_output = report['measured_artifacts']['phase2/stage2/dft/scan_chain_work/chained.v']
            if (report.get('published') and hashlib.sha256(
                    (project / SCAN_NETLIST_REL).read_bytes()).hexdigest() != native_output):
                return False, 'published scan netlist differs from the native output'
            proof = _native_clock_controls(
                (project / 'phase2/stage2/dft/scan_chain_work/chained.v').read_text(),
                (project / report['clock_control_library']).read_text(), current_d09['intent'])
            if (proof != report.get('native_clock_controls')
                    or report.get('functional_clock') != proof['functional_clock']
                    or report.get('clock') != proof['scan_clock']):
                return False, 'native clock/control roles differ from source authority/receipt'
        except (OSError, ValueError, KeyError, TypeError):
            return False, 'native scan artifact/report binding is missing'
    recorded = report.get("l20_contract") if isinstance(report, dict) else None
    if not isinstance(recorded, dict):
        return False, "scan report carries no L20 path/SHA binding"
    current, problems = load_l20_scan_contract(
        project, expected_clock=report.get("clock"),
        expected_length=report.get("input_flop_count"))
    if problems or current is None:
        return False, "; ".join(problems or ["current L20 is unsupported"])
    if current != recorded:
        return False, "current L20 path, SHA-256, or typed chain differs from receipt"
    reconciliation = report.get("l20_reconciliation")
    measured = reconcile_l20_scan_contract(current, report)
    if (not isinstance(reconciliation, dict)
            or reconciliation != measured or not measured.get("ok")):
        return False, "scan report does not carry a passing L20 reconciliation"
    constraint_ok, constraint_reason = _smc.validate(
        project, current, report.get("scan_mode_constraint"))
    if not constraint_ok:
        return False, constraint_reason
    return True, "current L20 bytes and measured scan chain reconcile"


# ---------------------------------------------------------------------------
# PURE parsers / measurers — unit-tested directly, no Docker, no filesystem
# ---------------------------------------------------------------------------

# `fault chain` stdout, verbatim shape:
#   Internal scan chain successfully constructed. Length: 64
#   Boundary scan cells successfully chained. Length:  34
#   Total scan-chain length:  98
_INTERNAL_RE = re.compile(r"Internal scan chain[^\n]*?Length:\s*(\d+)", re.I)
_BOUNDARY_RE = re.compile(r"Boundary scan cells[^\n]*?Length:\s*(\d+)", re.I)
_TOTAL_RE = re.compile(r"Total scan-chain length:\s*(\d+)", re.I)

_FAULT_META_RE = re.compile(
    r"/\*\s*FAULT METADATA:\s*'(?P<json>.*?)'\s*END FAULT METADATA\s*\*/",
    re.S)


def parse_chain_log(text: str) -> dict:
    """Chain counts scraped from `fault chain`'s OWN stdout.  PURE.

    Missing keys stay None — an absent count is never defaulted to 0, because
    0 is a meaningful (and disastrous) chain length and must not be
    manufacturable by a parse miss.
    """
    def _one(rx):
        m = rx.search(text or "")
        return int(m.group(1)) if m else None
    return {"internal": _one(_INTERNAL_RE),
            "boundary": _one(_BOUNDARY_RE),
            "total": _one(_TOTAL_RE)}


def parse_chain_metadata(netlist_text: str) -> dict | None:
    """The `/* FAULT METADATA: {...} END FAULT METADATA */` block `fault chain`
    embeds in its own output.  Returns the decoded dict, or None when absent or
    unparseable.  PURE.

    This is the ARTEFACT's own account of the chain — independent of the
    stdout scrape, which is why both are recorded and cross-checked.
    """
    m = _FAULT_META_RE.search(netlist_text or "")
    if not m:
        return None
    try:
        return json.loads(m.group("json"))
    except (ValueError, TypeError):
        return None


def chain_order_counts(meta: dict | None) -> dict:
    """Per-`kind` tally of the metadata's ordered chain element list.  PURE."""
    if not isinstance(meta, dict):
        return {}
    order = meta.get("order")
    if not isinstance(order, list):
        return {}
    return dict(Counter(str(e.get("kind")) for e in order
                        if isinstance(e, dict)))


def count_flops(netlist_text: str) -> int:
    """Flip-flop INSTANCE count in a technology-mapped netlist.  PURE.

    Reuses `fault_atpg_run`'s flop-instantiation regex and its
    already-PDK-agnostic flop-cell detector, so this program and the ATPG
    producer can never disagree about what a flop is.
    """
    cells = _fatpg.detect_dff_cells(netlist_text or "")
    wanted = {c.strip() for c in cells.split(",") if c.strip()}
    if not wanted:
        return 0
    n = 0
    for line in (netlist_text or "").splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_$]*)\s+\\?\S+\s*\(", line)
        if m and m.group(1) in wanted:
            n += 1
    return n


# `fault chain` re-synthesises after inserting the chain and, in doing so,
# wraps the original module in an instance of its own.  Every internal wire
# therefore comes out renamed `\<instance>.<original name>`.  That prefix is
# what breaks yosys `equiv_make`'s BY-NAME gold/gate matching in step 13, so
# LEC has to reproduce it on the gold side.  It is MEASURED here, from the
# artefact, and recorded — never hard-coded into the LEC script.
def measure_internal_prefix(netlist_text: str,
                            dominance: int = 4) -> str | None:
    """The dotted prefix `fault chain` put on every internal wire name, or None.

    Returns the leading segment of escaped identifiers of the form
    `\\<seg>.<rest>` ONLY when one segment dominates the next-most-common by
    at least `dominance`x.  A netlist with no clear single wrapper instance
    yields None and the caller must then NOT claim a prefix — a wrong prefix
    would silently lower the number of compared LEC points rather than error.
    PURE.
    """
    ids = re.findall(r"\\([^\s;,()\[\]]+)", netlist_text or "")
    segs = Counter(i.split(".")[0] for i in ids if "." in i)
    if not segs:
        return None
    ranked = segs.most_common(2)
    top, top_n = ranked[0]
    if len(ranked) > 1 and top_n < ranked[1][1] * dominance:
        return None
    return top


def assess(chain_log: dict, meta: dict | None, input_flops: int) -> dict:
    """Turn the three independent measurements into a verdict.  PURE.

    The ONE thing this must never do is call a run good because the tool
    exited 0.  `ok` is True only when a chain length was actually measured and
    it accounts for every flop in the input netlist.
    """
    meta_internal = (meta or {}).get("internalCount")
    meta_boundary = (meta or {}).get("boundaryCount")
    log_internal = chain_log.get("internal")
    # Prefer the artefact's own metadata; fall back to the stdout scrape.
    internal = meta_internal if isinstance(meta_internal, int) else log_internal
    boundary = meta_boundary if isinstance(meta_boundary, int) else \
        chain_log.get("boundary")

    problems: list[str] = []
    if internal is None:
        problems.append(
            "no internal scan-chain length could be measured — neither the "
            "`fault chain` stdout count line nor the output netlist's FAULT "
            "METADATA header yielded one")
    if (isinstance(meta_internal, int) and isinstance(log_internal, int)
            and meta_internal != log_internal):
        problems.append(
            f"chain length disagrees between the tool's stdout "
            f"({log_internal}) and the netlist's own FAULT METADATA "
            f"({meta_internal})")
    if isinstance(internal, int):
        if input_flops <= 0:
            problems.append(
                "no flip-flops were counted in the INPUT netlist, so the "
                "chain length cannot be validated against anything")
        elif internal != input_flops:
            problems.append(
                f"scan chain covers {internal} flop(s) but the input netlist "
                f"instantiates {input_flops} — {input_flops - internal} "
                f"flip-flop(s) are NOT on the chain and are untestable")
    return {
        "internal_chain_length": internal,
        "boundary_chain_length": boundary,
        "input_flop_count": input_flops,
        "chain_length_matches_flop_count": (
            isinstance(internal, int) and input_flops > 0
            and internal == input_flops),
        "chain_log_counts": chain_log,
        "metadata_counts": {"internalCount": meta_internal,
                            "boundaryCount": meta_boundary},
        "metadata_order_kinds": chain_order_counts(meta),
        "problems": problems,
        "ok": not problems,
    }


def cell_histogram(netlist_text: str) -> dict:
    """`{cell_name: instance_count}` for a mapped netlist.  PURE.

    Used to record the AREA COST of scan insertion as an instance-count delta,
    so a reader can see what the chain actually costs without re-running
    anything.
    """
    hist: Counter = Counter()
    for line in (netlist_text or "").splitlines():
        m = re.match(r"\s*([A-Za-z][A-Za-z0-9_$]*__?[A-Za-z0-9_$]+)\s+\\?\S+\s*\(",
                     line)
        if m:
            hist[m.group(1)] += 1
    return dict(hist)


def resolve_liberty(pdk: str, override: str | None) -> tuple[str | None, str]:
    """(container-absolute Liberty path, provenance note).  PURE.

    An explicit `--liberty` always wins.  Otherwise the PDK id indexes
    SCAN_LIBERTY.  An unknown PDK resolves NOTHING — see the table comment.
    """
    if override:
        return override, "explicit --liberty"
    lib = SCAN_LIBERTY.get(pdk)
    if lib:
        return lib, f"SCAN_LIBERTY[{pdk!r}]"
    return None, (f"no Liberty configured for pdk {pdk!r} "
                  f"(known: {sorted(SCAN_LIBERTY)}) — pass --liberty")


# The project's OWN staged Liberty dir. A design on a PDK not in SCAN_LIBERTY
# (a foundry PDK the container does not ship, sniffed to 'unmapped') stages its
# corner libraries here — the SAME dir the pre-layout STA and pvt_matrix steps
# already read. Using it is NOT the cross-foundry substitution the SCAN_LIBERTY
# comment forbids: it is the design's own PDK, mounted under /work, so the chain
# is built from the very cells the netlist is mapped to.
_STAGED_LIBERTY_DIR = "input/pdk/liberty"
# Typical (TT) process-corner designators — the corner SCAN_LIBERTY itself pins
# for every built-in PDK (all its entries are `__tt_`/`_typ_`). Matched with the
# same general convention used elsewhere; no PDK / vendor cell is hard-coded.
_TYP_CORNER_RE = re.compile(
    r"(?:^|[_/\-.\s:,=])(tt|typical|typ|nom)(?:[_/\-.\s:,=]|$)", re.IGNORECASE)


def staged_own_liberty(project: Path) -> tuple[str | None, str]:
    """(container /work Liberty path, note) for the project's OWN staged corner
    libraries, or (None, note). PURE w.r.t. the project input.

    Picks the TYPICAL corner when the file names disclose one; if exactly one
    library is staged it is used unambiguously. Two-or-more staged with NO
    identifiable typical corner is AMBIGUOUS and REFUSES (None) rather than
    guess a corner — the same refuse-don't-guess stance as `resolve_liberty`.
    """
    lib_dir = project / _STAGED_LIBERTY_DIR
    if not lib_dir.is_dir():
        return None, f"no {_STAGED_LIBERTY_DIR}/ staged"
    libs = sorted(lib_dir.glob("*.lib"))
    if not libs:
        return None, f"no *.lib in {_STAGED_LIBERTY_DIR}/"
    typ = [p for p in libs if _TYP_CORNER_RE.search(p.name)]
    if len(typ) == 1:
        chosen = typ[0]
    elif len(libs) == 1:
        chosen = libs[0]
    else:
        return None, (
            f"{len(libs)} staged libraries and no single TYPICAL corner "
            f"identifiable by name ({[p.name for p in libs]}) — refusing to "
            f"guess a corner")
    return (f"/work/{_STAGED_LIBERTY_DIR}/{chosen.name}",
            f"project-staged {_STAGED_LIBERTY_DIR}/{chosen.name} (own PDK)")


# ---------------------------------------------------------------------------
# `inout` port handling — `fault chain` cannot parse a bidirectional port
# ---------------------------------------------------------------------------
# The pure netlist port helpers (find_inout_ports / port_is_connected /
# port_list_successor / strip_inout_ports / restore_inout_ports) live in
# `_dft_netlist_ports.py`, shared with `fault_atpg_run.py`'s ATPG cut — both
# fault entry points abort on an inout port.  Re-exported here so this module's
# callers and its tests keep referring to them unqualified.
from _dft_netlist_ports import (  # noqa: E402,F401
    find_inout_ports, port_is_connected, port_list_successor,
    strip_inout_ports, restore_inout_ports)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def decide_skip_boundary(project: Path, mode: str,
                         top_module: str | None) -> tuple[bool, dict]:
    """Resolve the `--skip-boundary` decision.  PURE w.r.t. the project input.

    `mode` is one of "auto" (default), "on", "off":
      * "on"  — always skip the boundary register (explicit override);
      * "off" — never skip it (explicit override, restores legacy default);
      * "auto" — DETERMINISTIC selection: skip iff the design is a fixed-pinout
        wrapper (see floorplan_contract.is_fixed_pinout_wrapper), because its
        ports are a parent interface, not chip pads.  No agent chooses this.

    Returns (skip: bool, evidence: dict).  The evidence records the mode and,
    in auto mode, the fixed-pinout contract that drove the decision — so a
    reader can audit WHY the boundary register was or was not inserted.
    """
    if mode == "on":
        return True, {"mode": "on",
                      "reason": "explicit --skip-boundary=on override"}
    if mode == "off":
        return False, {"mode": "off",
                       "reason": "explicit --skip-boundary=off override "
                                 "(legacy default: boundary scan inserted)"}
    # auto
    try:
        is_fixed, ev = _fpc.is_fixed_pinout_wrapper(project, top_module)
    except Exception as exc:                                   # noqa: BLE001
        # A detection failure must NEVER silently drop the boundary register —
        # fall back to the legacy default (insert it) and say why.
        return False, {"mode": "auto", "detection_error": str(exc),
                       "reason": "fixed-pinout detection failed → legacy "
                                 "default (boundary scan inserted)"}
    ev = dict(ev)
    ev["mode"] = "auto"
    return is_fixed, ev


# `--skip-boundary` was added to the `fault` fork after image 0.2.52 (present in
# 0.2.54+; MEASURED: `fault chain --help` on 0.2.52 does NOT list it, on 0.2.54
# does — same 0.9.4 binary string, rebuilt between tags). The boundary decision
# in `decide_skip_boundary` is PURE w.r.t. the project and image-INDEPENDENT, so
# on a fixed-pinout wrapper `auto` decides skip=True regardless of image. If that
# runs against an older `fault` the binary REJECTS the flag: MEASURED
#   `Error: Unknown option '--skip-boundary'` -> RC=64, no netlist produced.
# Without this classifier the failure surfaces as the generic "produced no scan
# netlist" and the wrapper that MOST needs skip-boundary silently loses its scan
# chain, the real cause (image too old) buried in log_tail with no remedy. This
# is chip-AGNOSTIC — it keys on the TOOL's own error string, not on any design.
_SKIP_BOUNDARY_UNSUPPORTED_RE = re.compile(
    r"(?:unknown|unrecognized|unexpected|invalid)\s+option[^\n]*--skip-boundary",
    re.IGNORECASE)


def skip_boundary_unsupported_in_log(log: str) -> bool:
    """True iff `fault chain`'s output shows it rejected `--skip-boundary` as an
    unsupported option.  PURE — a string check on the tool's own error,
    unit-testable without Docker.

    This detects the SYMPTOM only.  It does NOT establish the cause: the same
    error is produced both by a build that genuinely predates the flag and by a
    step that ran a DIFFERENT IMAGE than the run declared (measured: a run
    pinned to and verifying 0.2.58 executed this step in stock
    `hpretl/iic-osic-tools:latest`).  The caller names the image it used and
    lists both causes; do not re-collapse them to one here."""
    return bool(_SKIP_BOUNDARY_UNSUPPORTED_RE.search(log or ""))


# `fault chain` builds the scan wrapper's module HEADER from the design's own
# port list plus the scan pins (sin/sout/shift/tck/test), but declares the
# chain's reset in the BODY under the fixed name `rst`. When the design's reset
# is called anything else — `rst_ni`, `resetn`, `rst_n`, … — `rst` is declared
# and never listed, so fault's own yosys re-synthesis rejects the netlist it
# just wrote and NOTHING is published.
#
# MEASURED (vibe-ic, opentitan_aes x sky130A, image ghcr.io/vibeic/vibeic-eda:
# 0.2.54): `fault chain` reported "Internal scan chain successfully
# constructed. Length: 66 / Boundary scan cells ... 105 / Total ... 171" and
# then died with
#   chained.v.chain-intermediate.v:10209: ERROR: Module port `\rst' is not
#   declared in module header.
# The chain was BUILT and thrown away. Before this classifier the report said
# only "`fault chain` produced no scan netlist" + a log tail, so the next blind
# run could not tell this from a genuine no-flops design.
_MISSING_HEADER_PORT_RE = re.compile(
    r"Module port `\\?([^']+?)'\s+is not declared in module header", re.I)


def chain_resynth_missing_header_ports(log: str) -> list:
    """Port names `fault chain`'s own re-synthesis rejected as body-declared
    but absent from the wrapper's module header, in first-seen order.

    PURE — a string check on the tool's own error, unit-testable without
    Docker. Empty list means this failure mode is not present."""
    seen: list = []
    for m in _MISSING_HEADER_PORT_RE.finditer(log or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


# The SECOND way `fault chain` builds a chain and then throws it away.
#
# fault's internal yosys re-synthesis must bind every module the netlist
# instantiates. A hard macro supplied to the flow as LEF + Liberty only — an
# ordinary design input, and what every SRAM/OTP/PHY IP ships — has no Verilog
# model in that yosys invocation, so `hierarchy -check` aborts. The chain is
# already built when this happens.
#
# Before this classifier the report carried only
#     "`fault chain` produced no scan netlist"
# which is TRUE and ADJACENT: it names the missing artefact, not the reason,
# and is byte-indistinguishable from a design that legitimately has no
# flip-flops to chain. Downstream, `cut_netlist.v` is then absent and the DT1 /
# DT2 transition- and path-delay steps record "NEVER RAN — precondition unmet",
# so the whole DFT tail reads as a capability that was never exercised rather
# than as one input the tool was never given.
#
# MEASURED (a design whose OTP macro is staged as LEF + Liberty with no Verilog
# model, ghcr.io/vibeic/vibeic-eda:0.2.65) — the tool's own lines:
#     Internal scan chain successfully constructed. Length: 271
#     Boundary scan cells successfully chained. Length:  3
#     Total scan-chain length:  274
#     Resynthesizing with yosys…
#     ERROR: Module `\<MACRO>' referenced in module `\<top>.original' in cell
#            `\<inst>' is not part of the design.
#     A yosys error has occurred.
#
# chip-AGNOSTIC: a pure string check on yosys' own error text. No vendor, SKU,
# process node or part number participates.
_UNRESOLVED_MODULE_RE = re.compile(
    r"Module\s+`\\?([^']+?)'\s+referenced\s+in\s+module\s+`\\?[^']*?'"
    r"\s+in\s+cell\s+`\\?[^']*?'\s+is\s+not\s+part\s+of\s+the\s+design",
    re.I)

#: `fault chain` prints this only after it has actually constructed a chain.
#: It is what licenses the "BUILT then discarded" claim — without it this
#: program would be asserting a build it never saw evidence of.
_CHAIN_TOTAL_LEN_RE = re.compile(
    r"Total\s+scan-chain\s+length:\s*(\d+)", re.I)


def chain_resynth_unresolved_modules(log: str) -> list:
    """Module names `fault chain`'s own re-synthesis could not bind, in
    first-seen order.

    These are modules the netlist INSTANTIATES but for which that yosys
    invocation was handed no model — typically a hard macro supplied as
    LEF/Liberty only. PURE — a string check on the tool's own error,
    unit-testable without Docker. Empty list means this failure mode is not
    present."""
    seen: list = []
    for m in _UNRESOLVED_MODULE_RE.finditer(log or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def chain_reported_total_length(log: str):
    """The total scan-chain length `fault chain` reported CONSTRUCTING, or
    None when it never said it built one.

    Guards the `chain_built_then_discarded` claim: a report that asserts a
    chain was built and discarded, on a log that never showed a chain being
    built, would be this program inventing the very kind of adjacent fact the
    classifier exists to remove. PURE."""
    last = None
    for last in _CHAIN_TOTAL_LEN_RE.finditer(log or ""):
        pass
    return int(last.group(1)) if last else None


def run_chain(project: Path, netlist_rel: str, clock: str,
              pdk: str, reset: str | None = None,
              reset_active_low: bool = False,
              liberty_override: str | None = None,
              dff_cells_override: str | None = None,
              pdk_dir: Path | None = None,
              skip_boundary: str = "auto",
              top_module: str | None = None,
              require_l20_contract: bool = False,
              timeout: int = 900) -> tuple[int, dict]:
    """Insert a real scan chain.  Returns (exit_code, report_dict).

    Never raises for a tool failure: every outcome comes back as a report the
    caller can write verbatim, so an absent artefact is never silence.

    `skip_boundary` ("auto"|"on"|"off", see decide_skip_boundary) governs
    whether `fault chain` inserts a top-level boundary-scan register.  In the
    default "auto" mode a fixed-pinout wrapper (FP_DEF_TEMPLATE) DETERMINISTIC-
    ally selects `--skip-boundary`; every other design keeps the legacy
    default.  The internal scan chain is inserted either way.
    """
    # Same resolver the ATPG producer uses — `fault chain` needs a
    # library-mapped netlist for exactly the reason `fault cut` does, so the
    # two must never pick different files.
    netlist_rel, switch_note = _fatpg.resolve_mapped_netlist(project,
                                                             netlist_rel)
    src = project / netlist_rel
    if not src.is_file():
        return 2, {"stage": "input", "error": f"netlist not found: {netlist_rel}"}
    netlist_text = src.read_text(encoding="utf-8", errors="replace")

    l20_contract = None
    scan_mode_constraint = None
    d09_contract = None
    if require_l20_contract:
        d09_contract, d09_problems = load_d09_dft_contract(
            project, expected_clock=clock, expected_reset=reset,
            reset_active_low=reset_active_low)
        if d09_contract is not None and not d09_contract['intent']['scan_test']:
            return 0, {'verdict': 'NOT_APPLICABLE', 'published': False,
                       'reason_code': 'D09_SCAN_TEST_DISABLED', 'native_started': False}
        if d09_contract is not None and not reset:
            return 1, {'stage': 'd09_contract', 'published': False,
                       'error': 'D09_DFT_AUTHORITY_INVALID: actual reset missing'}
        if d09_contract is None and not all(
                p.startswith('D09_DFT_SPEC_MISSING:') for p in d09_problems):
            return 1, {'stage': 'd09_contract', 'published': False,
                       'problems': d09_problems}
        l20_problems = []
        if d09_contract is None:
            l20_contract, l20_problems = load_l20_scan_contract(
                project, expected_clock=clock,
                expected_length=count_flops(netlist_text))
        if l20_problems or (d09_contract is None and l20_contract is None):
            return 1, {
                "stage": "l20_contract", "netlist": netlist_rel,
                "clock": clock, "problems": l20_problems,
                "error": "L20 topology is incompatible with this one-chain producer",
                "published": False,
            }
        _constraint_text, scan_mode_constraint, constraint_problems = (
            _smc.render(l20_contract) if l20_contract else (None, None, []))
        if constraint_problems:
            return 1, {
                "stage": "scan_mode_constraint", "netlist": netlist_rel,
                "clock": clock, "problems": constraint_problems,
                "error": "L20 scan-shift timing constraint could not be emitted",
                "published": False,
            }

    if _fatpg.is_generic_unmapped(netlist_text):
        return 2, {
            "stage": "input",
            "netlist": netlist_rel,
            "error": "netlist is a technology-GENERIC yosys netlist "
                     "($_DFF_/$_NAND_ …).  `fault chain` needs Liberty cell "
                     "names to build the chain; scan insertion must run after "
                     "technology mapping.",
        }

    pdk_cfg = _fatpg.PDK_CONFIG.get(pdk)
    if pdk_cfg is None:
        sniffed = _fatpg.sniff_pdk_from_netlist(netlist_text)
        if sniffed:
            pdk, pdk_cfg = sniffed, _fatpg.PDK_CONFIG[sniffed]

    liberty, lib_note = resolve_liberty(pdk, liberty_override)
    if liberty and pdk == "gf180" and not liberty_override:
        # Same staleness as fault_atpg_run's cell-model resolution — ciel's
        # gf180mcu path is content-addressed and SCAN_LIBERTY's hash is a
        # point-in-time fallback. Re-resolve live before trusting it.
        liberty = _pcm.materialize_gf180_paths(
            [liberty],
            lambda argv, t: _fatpg._run_docker(project, argv, timeout=t,
                                               pdk_dir=pdk_dir))[0]
    if not liberty:
        # PDK not in SCAN_LIBERTY and no explicit --liberty: fall back to the
        # design's OWN staged corner libraries. A foundry PDK the container does
        # not ship sniffs to 'unmapped', and the runner forwards no --liberty
        # for it — yet the design stages its libraries under input/pdk/liberty/
        # (the same dir STA/pvt already read). Without this, scan insertion is
        # unreachable for every non-built-in PDK that stages its own libs, which
        # then leaves step 11 MISSING and VOIDS the whole DFT-dependent tail.
        staged, staged_note = staged_own_liberty(project)
        if staged:
            liberty, lib_note = staged, staged_note
    if not liberty:
        return 2, {"stage": "liberty", "netlist": netlist_rel, "pdk": pdk,
                   "error": lib_note}

    # Flop cells: explicit override, else auto-detect from THIS netlist unioned
    # with the PDK seed — identical policy to `fault cut`, one implementation.
    if dff_cells_override:
        dff_cells = dff_cells_override
    else:
        detected = _fatpg.detect_dff_cells(netlist_text)
        seed = pdk_cfg.get("dff_cells") if pdk_cfg else None
        dff_cells = _fatpg.merge_dff_cells(seed, detected) or (seed or "DFF")

    dft_dir = _pl.dft_dir(project)
    dft_dir.mkdir(parents=True, exist_ok=True)
    # `fault chain` drops `<out>+attrs` and `<out>.chain-intermediate.v`
    # alongside its output.  Keep them out of the canonical dft dir by writing
    # into a scratch subdir, then publish only the netlist itself.
    work_rel = "phase2/stage2/dft/scan_chain_work"
    (project / work_rel).mkdir(parents=True, exist_ok=True)
    out_rel = f"{work_rel}/chained.v"

    # `fault chain` aborts on any `inout` port (see find_inout_ports).  Strip
    # UNCONNECTED inout ports from the netlist fault reads; connected ones stay
    # (and are reported).  The stripped ports are restored into fault's output.
    inout_ports = find_inout_ports(netlist_text)
    stripped_inout: dict = {}
    stripped_successors: dict = {}
    connected_inout: list = []
    fault_input_rel = netlist_rel
    for _name, _decl in inout_ports.items():
        if port_is_connected(netlist_text, _name):
            connected_inout.append(_name)
        else:
            stripped_inout[_name] = _decl
            stripped_successors[_name] = port_list_successor(netlist_text, _name)
    if stripped_inout:
        stripped_text = strip_inout_ports(netlist_text, list(stripped_inout))
        # Redirect ONLY if every targeted port actually left the netlist —
        # otherwise leave fault to fail honestly on the original.
        if not (set(find_inout_ports(stripped_text)) & set(stripped_inout)):
            fault_input_rel = f"{work_rel}/fault_input.v"
            (project / fault_input_rel).write_text(stripped_text,
                                                   encoding="utf-8")
        else:
            stripped_inout.clear()

    # Boundary-scan decision — DETERMINISTIC in the default "auto" mode: a
    # fixed-pinout wrapper (FP_DEF_TEMPLATE) gets `--skip-boundary`.  Recorded
    # in the report so the choice is auditable, never a silent flag.
    skip_boundary_flag, skip_boundary_evidence = decide_skip_boundary(
        project, skip_boundary, top_module)

    cmd = ["fault", "chain",
           "--liberty", liberty,
           "--clock", clock,
           "--dff", dff_cells,
           "-o", f"/work/{out_rel}"]
    if skip_boundary_flag:
        cmd.append("--skip-boundary")
    if reset:
        cmd += ["--reset", reset]
        if reset_active_low:
            cmd += ["--reset-active-low"]
    cmd.append(f"/work/{fault_input_rel}")

    # This is the ONE supervisor for the actual engine.  The caller waits for
    # this producer as an ordinary child; it must not wrap us in a second host
    # process-tree watchdog because Docker/containerd reparents the engine and
    # makes that outer view look idle while the named container is progressing.
    # The former timeout remains a recorded budget, not a terminating clock.
    ec, out, err = _fatpg._run_docker(
        project, cmd, pdk_dir=pdk_dir, supervised=True,
        ceiling_s=float(timeout))
    log = (out + "\n" + err)
    produced = project / out_rel
    if ec != 0 or not produced.is_file():
        err_report = {"stage": "chain", "exit": ec, "netlist": netlist_rel,
                      "pdk": pdk, "liberty": liberty, "dff_cells": dff_cells,
                      "skip_boundary": skip_boundary_flag,
                      "skip_boundary_mode": skip_boundary,
                      "skip_boundary_evidence": skip_boundary_evidence,
                      "log_tail": log[-1500:],
                      "error": "`fault chain` produced no scan netlist"}
        if skip_boundary_flag and skip_boundary_unsupported_in_log(log):
            # DEGRADE LOUDLY, never silently: the deterministic decision was to
            # skip the boundary register (correct for a fixed-pinout wrapper),
            # but THIS build of `fault` predates `--skip-boundary` and rejected
            # it. Say the cause and BOTH remedies, so the next blind run's
            # failure is self-explaining instead of a generic "no scan netlist".
            err_report["skip_boundary_unsupported_by_binary"] = True
            # NAME THE IMAGE THAT ACTUALLY RAN. The previous wording asserted a
            # cause it never measured — "this build of the `fault` binary
            # predates the flag" — and the first thing a reader does with that
            # is check their image and find it is new enough. MEASURED on
            # caravel_user_project x sky130A (v1.9.65): the run was pinned to,
            # and reports/container_image.json VERIFIED,
            # the vibeic-eda fork at tag 0.2.58 (spelled without the registry
            # prefix on purpose: this is a HISTORICAL MEASUREMENT, not a live
            # image pointer for `sync_image_version.py` to keep in step), whose
            # `fault chain --help` DOES
            # list `--skip-boundary` — while this step resolved its own image
            # independently and ran stock hpretl/iic-osic-tools:latest, which
            # does not. "Your image is too old" was false; "a different image
            # ran than the one you pinned" was true. A diagnostic that names the
            # wrong cause costs more than one that names none, so this states
            # the image identity as the FIRST fact and offers the version
            # explanation only as one of the possibilities.
            err_report.update(_fatpg.atpg_engine_identity())
            err_report["image_used"] = err_report.get("image")
            # THE FIRST FACT IS ROUTE-DEPENDENT. This message's own reasoning
            # is that "a diagnostic that names the wrong cause costs more than
            # one that names none" — so on the LOCAL route it must not open by
            # naming an image (none ran) and must not hand the operator a
            # `docker run` command (there is no docker client). Cause (2) is
            # about image RESOLUTION and cannot apply when no image was
            # resolved, so it is dropped there rather than left to mislead.
            if err_report.get("exec_route") == "local":
                _ran_in = (
                    f"No image ran: there is no docker client on PATH, so the "
                    f"engine executed on this filesystem at "
                    f"{err_report.get('engine_path')!r} — verify it with "
                    f"`fault chain --help | grep skip-boundary`")
                _causes = (
                    f"ONE cause applies here: the `fault` on this filesystem is "
                    f"a build that predates the flag (added to the fork after "
                    f"0.2.52; MEASURED absent on 0.2.52, present on 0.2.54+). "
                    f"The image-resolution cause cannot apply — no image was "
                    f"resolved or started.")
                _remedies = (
                    f"Remedies: (a) run in an image whose `fault chain --help` "
                    f"lists the flag (>=0.2.54); or (b) set "
                    f"VIBEIC_DFT_SKIP_BOUNDARY=off to accept legacy "
                    f"boundary-scan insertion")
            else:
                _ran_in = (
                    f"The image this step ran in was {_fatpg.DOCKER_IMAGE!r} — "
                    f"verify it with `docker run --rm --entrypoint bash "
                    f"{_fatpg.DOCKER_IMAGE} -lc 'fault chain --help' | grep "
                    f"skip-boundary`")
                _causes = (
                    f"TWO distinct causes produce this exact error: (1) the "
                    f"image is a build that predates the flag (added to the "
                    f"fork after 0.2.52; MEASURED absent on 0.2.52, present on "
                    f"0.2.54+); or (2) THIS STEP RAN A DIFFERENT IMAGE THAN THE "
                    f"RUN DECLARED — it resolves an image of its own by "
                    f"local-tag presence and falls back to the upstream "
                    f"distribution, which ships stock tools without this "
                    f"project's forks, so a run pinned to a new-enough image "
                    f"can still land here. Compare the value above against "
                    f"reports/container_image.json:image_ref.")
                _remedies = (
                    f"Remedies: (a) make this step use the run's image — set "
                    f"VIBEIC_fatpg.DOCKER_IMAGE to it (the one-shot runner now "
                    f"exports this automatically from the verified container); "
                    f"(b) run in an image whose `fault chain --help` lists the "
                    f"flag (>=0.2.54); or (c) set VIBEIC_DFT_SKIP_BOUNDARY=off "
                    f"to accept legacy boundary-scan insertion")
            err_report["error"] = (
                f"`fault chain` rejected `--skip-boundary`. {_ran_in} before "
                f"concluding anything about the binary's age. {_causes} The "
                f"fixed-pinout wrapper's correct DFT is internal-scan-only, "
                f"which needs `--skip-boundary`. {_remedies} — but on a "
                f"fixed-pinout wrapper that re-introduces the SS-corner setup "
                f"violation (#604) and a large area blow-up.")
            return 1, err_report
        _missing_hdr = chain_resynth_missing_header_ports(log)
        if _missing_hdr:
            # DEGRADE LOUDLY: the chain was CONSTRUCTED and then discarded by
            # fault's own re-synthesis. Say so, name the port, and name the
            # remedy — otherwise this is indistinguishable from a design that
            # legitimately has no scan chain to build.
            err_report["chain_resynth_missing_header_ports"] = _missing_hdr
            err_report["chain_built_then_discarded"] = True
            err_report["error"] = (
                f"`fault chain` BUILT the scan chain and then rejected its own "
                f"intermediate netlist: port(s) {_missing_hdr} are declared in "
                f"the wrapper's body but absent from its module header, so the "
                f"re-synthesis fault runs internally fails and nothing is "
                f"published. This is an upstream `fault chain` wrapper defect, "
                f"not a property of this design: fault names the chain reset "
                f"`rst` in the body while the header carries the design's own "
                f"reset name, so EVERY design whose reset is not literally "
                f"`rst` (rst_ni, rst_n, resetn, reset, …) hits it. The chain "
                f"itself is sound — see the constructed/boundary/total lengths "
                f"in log_tail. Remedies: (a) run in an image whose `fault "
                f"chain` emits the port in the header; or (b) re-drive the "
                f"design with its reset port named `rst`. VERIFIED on "
                f"opentitan_aes x sky130A: adding the missing name to the "
                f"header makes the identical intermediate elaborate under "
                f"`yosys hierarchy -check` with rc=0.")
            return 1, err_report
        _unresolved = chain_resynth_unresolved_modules(log)
        if _unresolved:
            # DEGRADE LOUDLY, exactly as the header-port branch above does.
            # The generic "produced no scan netlist" is true and useless here:
            # it describes the absent artefact, not the one missing input that
            # caused it, and it reads the same as a design with no flops.
            err_report["chain_resynth_unresolved_modules"] = _unresolved
            _total_len = chain_reported_total_length(log)
            if _total_len is not None:
                # Only claim BUILT-then-discarded when the tool itself said it
                # built one. Otherwise name the unresolved module and stop.
                err_report["chain_built_then_discarded"] = True
                err_report["chain_reported_total_length"] = _total_len
            err_report["error"] = (
                f"`fault chain`'s own yosys re-synthesis could not bind "
                f"module(s) {_unresolved}: the netlist INSTANTIATES them but "
                f"that yosys invocation was handed no model for them, so "
                f"`hierarchy -check` aborts and nothing is published"
                + (f" — AFTER the chain was successfully constructed "
                   f"(total scan-chain length {_total_len}; see log_tail). "
                   if _total_len is not None else ". ")
                + f"This is a MISSING INPUT, not a property of this design "
                f"and not an engine crash: a hard macro staged as LEF + "
                f"Liberty only (SRAM / OTP / PHY IP normally is) has no "
                f"Verilog view for `fault chain` to elaborate. Consequence if "
                f"unread: `cut_netlist.v` is never written, so the DT1 "
                f"transition-fault and DT2 path-delay steps both record "
                f"'NEVER RAN — precondition unmet' and the DFT tail looks "
                f"like an unexercised capability rather than one absent "
                f"input. Remedies: (a) give the re-synthesis a blackbox stub "
                f"for the macro built from its Liberty/LEF port list — the "
                f"flow already emits exactly this for the back end as "
                f"reports/phase3/physical_cell_stubs.v, and phase 3 already "
                f"discovers the macro library set via _discover_local_macros "
                f"over input/pdk_local/; or (b) stage a synthesizable "
                f"(blackbox-annotated) Verilog view of the macro alongside "
                f"its LEF/Liberty. NOTE `fault chain --help` declares "
                f"'-l, --liberty <liberty>  Liberty file. (Required.)' — "
                f"singular and NOT repeatable, so passing the macro's Liberty "
                f"as a second --liberty is not available.")
            return 1, err_report
        if connected_inout:
            # A CONNECTED bidirectional port cannot be stripped losslessly and
            # `fault chain` cannot represent it — name it, do not hide it.
            err_report["connected_inout_ports_unhandled"] = connected_inout
            err_report["error"] += (
                f" — netlist has CONNECTED inout port(s) {connected_inout} that "
                f"`fault chain` cannot classify and this program cannot strip "
                f"losslessly (they carry real nets). Scan insertion on a design "
                f"with a driven bidirectional top-level port is an open backlog "
                f"item (bidirectional boundary-scan cell).")
        # Preserve the supervisor's semantic rc (notably RC_STALLED=199) so
        # the parent can distinguish a measured stall from an ordinary tool
        # failure. A zero exit with a missing output remains a producer failure.
        return ec if ec != 0 else 1, err_report

    chained_text = produced.read_text(encoding="utf-8", errors="replace")
    if stripped_inout:
        # Restore the stripped inout port(s) into fault's published netlist, at
        # their original position, with their exact original declaration.
        chained_text = restore_inout_ports(chained_text, stripped_inout,
                                           stripped_successors)
        missing = [n for n in stripped_inout
                   if n not in find_inout_ports(chained_text)]
        if missing:
            # A published netlist MUST carry every original design port — never
            # ship one silently missing a pin.
            return 1, {"stage": "restore", "exit": ec, "netlist": netlist_rel,
                       "inout_ports_stripped": list(stripped_inout),
                       "error": f"failed to restore inout port(s) {missing} "
                                f"into the scan netlist — refusing to publish a "
                                f"netlist missing a design port"}
        produced.write_text(chained_text, encoding="utf-8")
    meta = parse_chain_metadata(chained_text)
    verdict = assess(parse_chain_log(log), meta, count_flops(netlist_text))
    if d09_contract is not None:
        # Both the output's native element census and its actual mapped flop
        # census must agree with the existing stdout/metadata reconciliation.
        native_elements = chain_order_counts(meta).get('dff', 0)
        internal, boundary = verdict['internal_chain_length'], verdict['boundary_chain_length']
        if (type(internal) is not int or type(boundary) is not int or native_elements != internal
                or count_flops(chained_text) != internal + boundary
                or any((meta or {}).get(k) != k for k in ('sin', 'sout', 'shift'))):
            verdict['ok'] = False
            verdict['problems'].append('D23_INCOMPLETE_MAPPING: native elements/ports/mapped output disagree')

    before, after = cell_histogram(netlist_text), cell_histogram(chained_text)
    n_before, n_after = sum(before.values()), sum(after.values())

    report = {
        "tool": "fault chain",
        # WHAT RAN, not what would have. On the local route there is no
        # image and `DOCKER_IMAGE` is a registry-fallback name that was
        # never used — see `_fatpg.atpg_engine_identity`.
        **_fatpg.atpg_engine_identity(),
        "input_netlist": netlist_rel,
        "input_netlist_switch_note": switch_note,
        "output_netlist": SCAN_NETLIST_REL,
        "pdk": pdk,
        "liberty": liberty,
        "liberty_source": lib_note,
        "dff_cells": dff_cells,
        "clock": clock,
        "reset": reset,
        # Whether the top-level boundary-scan register was inserted, and WHY.
        # `--skip-boundary` is the deterministic choice for a fixed-pinout
        # wrapper (ports are a parent interface, not chip pads) — it removes
        # the SS-corner setup violation (#604) and the +707% area blow-up while
        # the internal scan chain is preserved.
        "skip_boundary": skip_boundary_flag,
        "skip_boundary_mode": skip_boundary,
        "skip_boundary_evidence": skip_boundary_evidence,
        "chain_exit": ec,
        # `inout` port handling (see find_inout_ports): which bidirectional
        # ports were stripped for `fault chain` and restored into its output,
        # and which connected ones could not be handled.
        "inout_ports_stripped_and_restored": list(stripped_inout),
        "inout_ports_connected_unhandled": connected_inout,
        "fault_input_netlist": fault_input_rel,
        # The five ports `fault chain` adds.  KNOWN because they are the
        # option names this program passes, not sniffed from the netlist.
        "dft_ports": list(DFT_PORTS),
        "functional_mode_tieoff": dict(FUNCTIONAL_MODE_TIEOFF),
        "scan_out_port": SCAN_OUT_PORT,
        # MEASURED from the artefact — LEC needs it to restore gold/gate name
        # correspondence (see fault_scan_chain_insert.measure_internal_prefix).
        "internal_wire_prefix": measure_internal_prefix(chained_text),
        "area_instances_before": n_before,
        "area_instances_after": n_after,
        "area_instances_delta": n_after - n_before,
        "area_instances_delta_pct": (
            round(100.0 * (n_after - n_before) / n_before, 2)
            if n_before else None),
        "cells_added": {k: after[k] - before.get(k, 0)
                        for k in after if after[k] != before.get(k, 0)},
        "log_tail": log[-1500:],
        **verdict,
    }
    if l20_contract is not None:
        report["l20_contract"] = l20_contract
        if scan_mode_constraint is not None:
            report["scan_mode_constraint"] = scan_mode_constraint
        reconciliation = reconcile_l20_scan_contract(l20_contract, report)
        report["l20_reconciliation"] = reconciliation
        if not reconciliation["ok"]:
            report["problems"].extend(reconciliation["problems"])
            report["ok"] = False
    if not report["ok"]:
        # A chain that does not account for every flop is NOT published as the
        # implementation netlist — publishing it would put an untestable
        # design into PnR under a name that says it is testable.
        report["published"] = False
        return 1, report

    if d09_contract is not None:
        import l_doc_generator_stamp as stamp
        import _atomic_artefact as atomic
        current, problems = load_d09_dft_contract(project)
        if problems or current != d09_contract:
            return 1, {**report, 'published': False,
                       'problems': ['D09 authority changed during native insertion']}
        try:
            if Path(liberty).is_file():
                library_text = Path(liberty).read_text()
            else:
                import shlex
                lib_rc, library_text, _ = _fatpg._run_docker(
                    project, ['cat', shlex.quote(liberty)], pdk_dir=pdk_dir)
                if lib_rc:
                    raise ValueError('native control Liberty cannot be read')
            proof = _native_clock_controls(chained_text, library_text, d09_contract['intent'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return 1, {**report, 'published': False,
                       'problems': ['D23_NATIVE_CONTROL_AUTHORITY: ' + str(exc)]}
        library_rel = work_rel + '/clock_control.lib'
        atomic.write_text(project / library_rel, library_text)
        report.update(functional_clock=clock, clock=proof['scan_clock'],
                      native_clock_controls=proof, clock_control_library=library_rel)
        # The existing L20 producer stamp records a derivation. Its length
        # is the native measurement above, never an author/pre-synthesis value.
        l20_path = _pl.generated_docs_dir(project) / 'L20_DFT_SCAN_TOPOLOGY.json'
        doc = json.loads(l20_path.read_text()) if l20_path.is_file() else {'doc_id': 'L20', 'fields': {}}
        raw_log = work_rel + '/native_chain.log'
        atomic.write_text(project / raw_log, log)
        measured = {out_rel: hashlib.sha256(produced.read_bytes()).hexdigest(),
                    raw_log: hashlib.sha256((project / raw_log).read_bytes()).hexdigest(),
                    library_rel: hashlib.sha256((project / library_rel).read_bytes()).hexdigest()}
        doc.update(applicability='APPLICABLE', extraction_status='EXTRACTED',
                   source_documents=[d09_contract['path']],
                   extraction_evidence={'d09_contract': d09_contract, 'native_artifacts': measured,
                                        'native_clock_controls': proof})
        fields = doc.setdefault('fields', {})
        fields.pop('dft_intent_status', None)
        fields.update(dft_present=True, scan_chains=[{
            'name': meta['sin'], 'length': report['internal_chain_length'],
            'scan_in': meta['sin'], 'scan_out': meta['sout'], 'clock': proof['scan_clock'],
            'functional_clock': clock}],
            notes='Native mapped scan topology; timing and coverage are separate measurements.')
        stamp.dump(l20_path, doc)
        l20_contract, problems = load_l20_scan_contract(project, proof['scan_clock'], report['internal_chain_length'])
        if problems:
            return 1, {**report, 'published': False, 'problems': problems}
        report.update(d09_contract=d09_contract, l20_contract=l20_contract,
                      test_port_def=d09_contract['intent']['test_port_def'],
                      measured_artifacts=measured)
        report['l20_reconciliation'] = reconcile_l20_scan_contract(l20_contract, report)

    if l20_contract is not None:
        # Publish the producer-owned timing actuator only after the native
        # chain and its reconciliation have passed. A failed run must not
        # replace a prior valid canonical constraint.
        emitted_constraint, constraint_problems = _smc.emit(
            project, l20_contract)
        if constraint_problems or emitted_constraint != scan_mode_constraint:
            report["problems"].extend(
                constraint_problems
                or ["published scan-mode receipt differs from prepared receipt"])
            report["ok"] = False
            report["published"] = False
            return 1, report
        current, reason = l20_binding_is_current(project, report)
        if not current:
            (project / _smc.SCAN_MODE_SDC_REL).unlink(missing_ok=True)
            report["problems"].append(reason)
            report["ok"] = False
            report["published"] = False
            return 1, report

    (project / SCAN_NETLIST_REL).write_bytes(produced.read_bytes())
    report["published"] = True
    return 0, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--netlist", default="phase2/stage2/synth/netlist.v",
                   help="Synth netlist, relative to project_dir.  A generic "
                        "netlist is self-healed to its tech-mapped sibling by "
                        "fault_atpg_run.resolve_mapped_netlist.")
    p.add_argument("--clock", required=True)
    p.add_argument("--reset")
    p.add_argument("--reset-active-low", action="store_true")
    p.add_argument("--pdk", default="unmapped",
                   help="PDK id (same vocabulary as fault_atpg_run).  An "
                        "unknown id is re-derived from the netlist's cell "
                        "names; if that fails the run REFUSES rather than "
                        "substituting another library's Liberty.")
    p.add_argument("--liberty", default=None,
                   help="Container-absolute .lib path.  Wins over SCAN_LIBERTY.")
    p.add_argument("--dff-cells", default=None)
    p.add_argument("--skip-boundary", choices=("auto", "on", "off"),
                   default="auto",
                   help="Insert a top-level boundary-scan register? "
                        "'auto' (default) skips it iff the design is a "
                        "fixed-pinout wrapper (FP_DEF_TEMPLATE) — its ports "
                        "are a parent interface, not chip pads; 'on' always "
                        "skips; 'off' always inserts (legacy default).")
    p.add_argument("--top-module", default=None,
                   help="Top module name — used by 'auto' skip-boundary "
                        "detection to match the fixed-pinout DEF template to "
                        "THIS top.")
    p.add_argument("--l20-contract", action="store_true",
                   help="Require and reconcile the current canonical L20 "
                        "one-chain contract before publishing.")
    p.add_argument("--pdk-dir", default=None)
    p.add_argument("--json", default=SCAN_JSON_REL,
                   help=f"Report JSON path relative to project "
                        f"(default {SCAN_JSON_REL})")
    p.add_argument(
        "--timeout", type=int, default=900,
        help=("Recorded runtime ceiling in seconds. Crossing it is reported "
              "but does not terminate a progressing fault-chain container; "
              "the container-aware stall supervisor remains authoritative."))
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fault_scan_chain_insert: not a directory: {project}",
              file=sys.stderr)
        return 2

    ec, report = run_chain(
        project, args.netlist, args.clock, args.pdk,
        reset=args.reset, reset_active_low=args.reset_active_low,
        liberty_override=args.liberty, dff_cells_override=args.dff_cells,
        pdk_dir=Path(args.pdk_dir).resolve() if args.pdk_dir else None,
        skip_boundary=args.skip_boundary, top_module=args.top_module,
        require_l20_contract=args.l20_contract,
        timeout=args.timeout)

    out = project / args.json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if ec == 0:
        print(f"fault_scan_chain_insert: chain length="
              f"{report['internal_chain_length']} internal + "
              f"{report['boundary_chain_length']} boundary; input flops="
              f"{report['input_flop_count']}; "
              f"matches={report['chain_length_matches_flop_count']}; "
              f"skip_boundary={report['skip_boundary']} "
              f"(mode={report['skip_boundary_mode']}); "
              f"area {report['area_instances_before']} -> "
              f"{report['area_instances_after']} instances "
              f"({report['area_instances_delta_pct']}%)")
    else:
        for pr in report.get("problems") or [report.get("error", "failed")]:
            print(f"fault_scan_chain_insert: {pr}", file=sys.stderr)
        print(f"  (see: {out})", file=sys.stderr)
    return ec


if __name__ == "__main__":
    sys.exit(main())
