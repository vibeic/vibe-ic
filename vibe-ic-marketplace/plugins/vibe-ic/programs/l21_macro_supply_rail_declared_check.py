#!/usr/bin/env python3
"""l21_macro_supply_rail_declared_check.py — L21 SEMANTIC completeness gate.

ENFORCEMENT: advisory

WHY THIS GATE EXISTS (the measured defect it is distilled from)
---------------------------------------------------------------
The pre-existing global check `phase1_doc_input_completeness_check` models
completeness as "does this vendor token appear as a substring in ANY L doc JSON
serialization". A hard macro's supply pin name appeared in L1_DATASHEET (7x) and
L2_FRS (8x), so the check reported CAPTURED — while L21_POWER_INTENT, the layer
the BACKEND consumes, contained it 0 times. Consequence chain, all measured:

    L21 declares no rail for the macro's supply pin
      -> the PDN carries no such rail
      -> synthesis ties the macro's POWER-typed terminal off with a TIEHI cell
      -> a SIGNAL net lands on a POWER-typed terminal
      -> TritonRoute aborts the WHOLE detailed route (not just that net)
      -> 3278 signal nets, 0 routed, LVS unreachable

...discovered FIVE steps downstream behind an opaque router error. So the
principle this gate embodies is:

    A layer is complete when the requirement is present IN THE LAYER THAT
    CONSUMES IT, in an actionable form — not when a token appears somewhere.

THE CONSUMER CONTRACT THIS GATE ASSERTS
---------------------------------------
`phase3_one_shot_runner._macro_supply_gc_plan(macro_lef_texts, power_nets,
ground_nets)` decides, for EVERY hard-macro pin the macro's own LEF types
`USE POWER` / `USE GROUND`, whether it binds to a supply rail. The match is
NAME-EQUALITY against the declared nets OF THE SAME USE. A pin that matches
nothing becomes `HARDMACRO_SUPPLY_UNCONNECTED` and is (honestly) left floating —
which is the exact input state of the failure chain above.

So the load-bearing clause is:

    every supply/ground pin that ANY instantiated hard macro types USE POWER /
    USE GROUND in that design's OWN macro LEF must appear as a declared rail of
    the SAME use in L21.power_domains[].

Everything this gate needs is DERIVED from the design's own machine-readable
inputs — the macro's own LEF `MACRO/PIN/USE` records and the design's own
RTL/netlist instantiations. There is no PDK name, design name, vendor part
number or hardcoded pin/signal literal anywhere in this file. A design that
ships no hard macro with PG pins SKIPs (rc=2) and is byte-identically
unaffected.

WHAT IT CHECKS
--------------
  L21-1  (rc=1)    For every instantiated hard-macro pin typed USE POWER /
                   USE GROUND in the design's OWN macro LEF, L21.power_domains[]
                   must declare a rail of the SAME use with the SAME name.
                   This is the clause whose absence aborts detailed routing.
  L21-2  (rc=1)    Every declared power_domains[] entry must carry a name, a
                   primary POWER net and a primary GROUND net — otherwise the
                   rail set the consumer name-matches against is not derivable
                   from the layer at all. (Only evaluated on entries that exist,
                   so it cannot fire on a design with no domains.)
  L21-3  (rc=1)    Every declared isolation_cells[] / level_shifters[] entry
                   must carry its domain binding, and every isolation cell must
                   carry a clamp_value — an isolation strategy with no clamp
                   value is not actionable by the UPF emitter. (Only evaluated
                   on entries that exist.)
  L21-4  (note)    Reports `extraction_status` / `upf_path` observations that
                   contextualise a finding. Never changes the exit code.

WHAT ITS VERDICT ACTUALLY DOES — MEASURED, NOT CLAIMED (#316)
--------------------------------------------------------------
ADVISORY. Wired as `advisory_program_exit_zero` in
`flow/phase1_phase2_phase3.yaml` step 0, so it RUNS on every real project and
its findings are reported, and rc=1 does not fail the step.

The first draft of this file declared "THIS GATE BLOCKS" and said it was
registered in `flow_compliance_check._STRUCTURAL_RTL_GATES`. It was registered
nowhere. #316's independent verification found that same contradiction in 9 of
its 30 gates — a gate that says it stops a run and does not — which is #306's
finding (62 of 72 gates unable to block) reproduced on brand-new code. So the
declaration above is now the machine-readable one
`flow_gate_enforcement_audit.py` reads, and that audit FAILS if this file ever
declares blocking again without a runner that invokes it inline.

Advisory is also what the measurement supports. Swept over every published cell
under `benchmark-data/`, this gate FAILs two of them —
`edge_llm_accel` (`fakeram45_2048x39` VDD/VSS) and `u_hawaii_adc` (`ldo`
IOVDD/VSS, `delta_sigma` VDD/VSS), both with `power_domains: []` — and SKIPs the
rest. Wired blocking today it would turn two shipped campaign cells red as a
side effect of landing a gate, which is a flow-owner decision and not this
file's to take. Promoting it is a one-line change once those two cells declare
their rails; `programs/tests/test_issue316_layergates_on_published_cells.py`
pins both findings so the promotion can be argued from a measurement.

The honest escape hatch is a NAMED, REVIEWED waiver, not silence: a macro may
carry a dedicated programming/HV supply this design genuinely provides no rail
for. Set `l21_macro_supply_rail_absent_disclosed` in `<project>/waivers.json`
to a >=40-char justification and the gate reports PASS_WITH_WAIVERS (rc=0) while
still printing every finding, so the gap is disclosed rather than invisible.
That is the difference between "reported, never faked" and the original defect.

SINGLE DETERMINISTIC TRACK — NO AI BACKUP
-----------------------------------------
This gate is 100% deterministic: LEF grammar + JSON schema walk. It deliberately
has NO "AI second track". The completeness report that preceded this work shipped
`ai_captured_tokens_count: 0` — an AI backup track that contributed nothing to
the 52 tokens the program flagged, i.e. a dual-track that was really one track.
A single honest track is better than a second one that produces nothing.

NOT A DUPLICATE OF
------------------
  * `power_domain_signal_crossing_check` — wired only into flow step M2, whose
    stage condition is files_exist:[phase1/analog/analog_block_list.json], so it
    is SKIPPED ENTIRELY for a pure-digital design, and it self-guards to SKIP
    when there is no UPF and no L21 domain. It never reaches the failing case.
  * `ip_integration_check` — its L21-vs-macro-Liberty supply check is WARNING
    severity only and is gated on condition_files_exist:[input/pdk_local,
    phase3/analog/hardmacro].
  * `l21_to_upf_emit` — an EMITTER, not a gate: it exits rc=2/SKIP precisely
    when power_domains is empty, i.e. it is silent exactly when the layer is
    hollow. (It is also not referenced anywhere in
    flow/phase1_phase2_phase3.yaml, so the UPF is never emitted by the flow.)

USAGE
-----
    python3 l21_macro_supply_rail_declared_check.py <project_dir> [--json OUT]

EXIT CODES
----------
    0 = PASS (or PASS_WITH_WAIVERS)
    1 = FAIL (blocks)
    2 = not applicable / input missing (SKIP)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # emitter/checker doctrine: reuse the CONSUMER's own LEF walk.
    from phase3_one_shot_runner import (  # type: ignore
        _parse_macro_supply_pins as _consumer_parse_macro_supply_pins,
    )
except Exception:  # pragma: no cover - fallback keeps the gate usable stand-alone
    _consumer_parse_macro_supply_pins = None  # type: ignore

WAIVER_KEY = "l21_macro_supply_rail_absent_disclosed"
WAIVER_MIN = 40

L21_NAMES = ("L21_POWER_INTENT.json", "L21_POWER_INTENT.JSON")

# Design-OWNED macro LEF roots. These mirror the roots the backend itself
# consumes (`phase3_one_shot_runner._collect_project_macros` reads
# `input/pdk_local/**`; the mixed-signal track reads
# `phase3/analog/hardmacro/**`). All are project-relative; none names a vendor.
_MACRO_LEF_GLOBS: Tuple[str, ...] = (
    "input/pdk_local/**/*.lef",
    "input/macros/**/*.lef",
    "input/hardmacro/**/*.lef",
    "phase3/analog/hardmacro/**/*.lef",
    "phase2/analog/hardmacro/**/*.lef",
)

# Where the design's own instantiations live (RTL first, then gate netlist).
_INSTANCE_TEXT_GLOBS: Tuple[str, ...] = (
    "phase2/stage1/rtl/**/*.v",
    "phase2/stage1/rtl/**/*.sv",
    "phase2/stage2/synth/**/*.v",
    "phase3/stage3/pnr/**/*.v",
)

# LEF CLASS values that denote a hard macro (as opposed to a std cell, whose
# CLASS is CORE, or a filler/tap, whose CLASS is CORE SPACER/WELLTAP). Pure LEF
# grammar; PDK-agnostic.
_HARD_MACRO_CLASSES = ("BLOCK", "RING", "PAD", "COVER")

_POWER_NET_KEYS = (
    "power_net", "power_nets", "primary_power", "primary_power_net",
    "power", "supply_net", "supply_nets", "vdd", "vdd_net", "pwr_net",
    "power_supply", "primary_supply",
)
_GROUND_NET_KEYS = (
    "ground_net", "ground_nets", "primary_ground", "primary_ground_net",
    "ground", "gnd", "gnd_net", "vss", "vss_net", "ground_supply",
)
_NAME_KEYS = ("name", "domain", "domain_name", "id", "power_domain")
_NESTED_SUPPLY_KEYS = ("supply", "supplies", "nets", "rails")
_ISO_DOMAIN_KEYS = ("domain", "power_domain", "from_domain", "source_domain",
                    "from", "src_domain")
_ISO_CLAMP_KEYS = ("clamp_value", "clamp", "isolation_value", "clamp_val")
_LS_DOMAIN_KEYS = ("domain", "from_domain", "source_domain", "from",
                   "src_domain", "power_domain")
_LS_TO_DOMAIN_KEYS = ("to_domain", "dest_domain", "target_domain", "to",
                      "dst_domain")


# --------------------------------------------------------------------------- #
# LEF parsing
# --------------------------------------------------------------------------- #
def _parse_macro_supply_pins(lef_text: str) -> Dict[str, List[Tuple[str, str]]]:
    """``{MACRO_NAME: [(pin_name, USE), ...]}`` for every USE POWER/GROUND pin.

    Delegates to `phase3_one_shot_runner._parse_macro_supply_pins` — the exact
    function the backend uses to build its connect plan — so the gate and the
    consumer can never drift. The inline fallback below is a byte-equivalent
    MACRO/PIN/USE walk kept only so the gate still runs stand-alone."""
    if _consumer_parse_macro_supply_pins is not None:
        return _consumer_parse_macro_supply_pins(lef_text)
    result: Dict[str, List[Tuple[str, str]]] = {}
    cur_macro: Optional[str] = None
    cur_pin: Optional[str] = None
    cur_use: Optional[str] = None
    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        m = re.match(r"MACRO\s+(\S+)", s)
        if m:
            cur_macro = m.group(1)
            result.setdefault(cur_macro, [])
            cur_pin = cur_use = None
            continue
        if (cur_macro and s.startswith("END ")
                and s.split()[1:2] == [cur_macro]):
            cur_macro = cur_pin = cur_use = None
            continue
        if cur_macro is None:
            continue
        m = re.match(r"PIN\s+(\S+)", s)
        if m:
            cur_pin = m.group(1)
            cur_use = None
            continue
        if cur_pin and s.startswith("END ") and s.split()[1:2] == [cur_pin]:
            if cur_use in ("POWER", "GROUND"):
                result[cur_macro].append((cur_pin, cur_use))
            cur_pin = cur_use = None
            continue
        if cur_pin is None:
            continue
        m = re.match(r"USE\s+(\S+)", s)
        if m:
            cur_use = m.group(1).rstrip(";").upper()
    return {k: v for k, v in result.items() if v}


def _macro_classes(lef_text: str) -> Dict[str, str]:
    """``{MACRO_NAME: CLASS}`` from a LEF. Pure LEF grammar."""
    out: Dict[str, str] = {}
    cur: Optional[str] = None
    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        m = re.match(r"MACRO\s+(\S+)", s)
        if m:
            cur = m.group(1)
            continue
        if cur and s.startswith("END ") and s.split()[1:2] == [cur]:
            cur = None
            continue
        if cur is None:
            continue
        m = re.match(r"CLASS\s+(\S+)", s)
        if m:
            out[cur] = m.group(1).rstrip(";").upper()
    return out


def _collect_design_macro_pg_pins(
        project: Path) -> Tuple[Dict[str, List[Tuple[str, str]]], List[str]]:
    """Return ``({master: [(pin, USE)...]}, [lef_path...])`` for every HARD
    macro the design's OWN macro LEFs declare with USE POWER / USE GROUND pins.

    A std-cell library LEF (CLASS CORE) is excluded by LEF grammar, not by
    filename — so a PDK that ships its std cells under one of these roots does
    not pollute the hard-macro set."""
    pins: Dict[str, List[Tuple[str, str]]] = {}
    used_lefs: List[str] = []
    seen: Set[Path] = set()
    for pat in _MACRO_LEF_GLOBS:
        for lef in sorted(project.glob(pat)):
            if not lef.is_file() or lef in seen:
                continue
            seen.add(lef)
            try:
                text = lef.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            classes = _macro_classes(text)
            contributed = False
            for master, pinlist in _parse_macro_supply_pins(text).items():
                cls = classes.get(master, "")
                # No CLASS record at all -> treat as a hard macro (many vendor
                # macro LEFs omit it); an explicit CORE class is a std cell.
                if cls and not any(cls.startswith(c)
                                   for c in _HARD_MACRO_CLASSES):
                    continue
                if pinlist:
                    pins.setdefault(master, [])
                    for entry in pinlist:
                        if entry not in pins[master]:
                            pins[master].append(entry)
                    contributed = True
            if contributed:
                used_lefs.append(str(lef.relative_to(project)))
    return pins, used_lefs


def _instantiated_masters(project: Path,
                          masters: Sequence[str]) -> Optional[Set[str]]:
    """Subset of `masters` instantiated in the design's own RTL / netlist.

    Returns None when NO RTL or netlist text is available yet (the gate may run
    before RTL generation) — the caller then treats every design-staged macro as
    in scope, which is the conservative reading of a design that deliberately
    staged that macro."""
    texts: List[str] = []
    for pat in _INSTANCE_TEXT_GLOBS:
        for f in sorted(project.glob(pat))[:400]:
            if not f.is_file():
                continue
            try:
                texts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
    if not texts:
        return None
    blob = "\n".join(texts)
    hit: Set[str] = set()
    for m in masters:
        if re.search(r"\b" + re.escape(m) + r"\b", blob):
            hit.add(m)
    return hit


# --------------------------------------------------------------------------- #
# L21 schema walk
# --------------------------------------------------------------------------- #
def _as_name_list(value) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        s = value.strip()
        if s:
            out.append(s)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_as_name_list(v))
    elif isinstance(value, dict):
        for key in ("name", "net", "net_name", "value"):
            if key in value:
                out.extend(_as_name_list(value[key]))
                break
    return out


def _nets_from_entry(entry: dict, keys: Sequence[str]) -> List[str]:
    out: List[str] = []
    for k in keys:
        if k in entry:
            out.extend(_as_name_list(entry[k]))
    for nk in _NESTED_SUPPLY_KEYS:
        nested = entry.get(nk)
        if isinstance(nested, dict):
            for k in keys:
                if k in nested:
                    out.extend(_as_name_list(nested[k]))
    # de-dup, order-preserving
    seen: Set[str] = set()
    uniq: List[str] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _l21_fields(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    fields = doc.get("fields")
    if isinstance(fields, dict):
        return fields
    return doc


def _declared_rails(fields: dict) -> Tuple[Set[str], Set[str], List[dict]]:
    domains = fields.get("power_domains")
    if not isinstance(domains, list):
        domains = []
    entries = [d for d in domains if isinstance(d, dict)]
    power: Set[str] = set()
    ground: Set[str] = set()
    for d in entries:
        power.update(_nets_from_entry(d, _POWER_NET_KEYS))
        ground.update(_nets_from_entry(d, _GROUND_NET_KEYS))
    return power, ground, entries


def _entry_name(entry: dict) -> Optional[str]:
    for k in _NAME_KEYS:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return False, ""
    if not isinstance(doc, dict):
        return False, ""
    v = doc.get(WAIVER_KEY)
    if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
        return True, v.strip()
    return False, ""


def _find_l21(project: Path) -> Optional[Path]:
    for name in L21_NAMES:
        p = project / "phase1" / "generated_docs" / name
        if p.is_file():
            return p
    for hit in sorted(project.glob("**/generated_docs/L21_*.json")):
        if hit.is_file():
            return hit
    return None


# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="L21 power-intent macro-supply-rail semantic gate")
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = args.project.resolve()
    if not project.is_dir():
        print("[SKIP] l21_macro_supply_rail_declared_check: "
              f"not a directory: {project}")
        return 2

    macro_pins, lef_paths = _collect_design_macro_pg_pins(project)
    l21_path = _find_l21(project)

    report: Dict[str, object] = {
        "gate": "l21_macro_supply_rail_declared_check",
        "project": str(project),
        "macro_lefs": lef_paths,
        "findings": [],
        "advisories": [],
    }

    if not macro_pins:
        print("[SKIP] l21_macro_supply_rail_declared_check: the design stages "
              "no hard-macro LEF declaring USE POWER / USE GROUND pins "
              "(nothing for the backend to name-match against).")
        report["verdict"] = "SKIP"
        _emit(args.json, report)
        return 2

    inst = _instantiated_masters(project, sorted(macro_pins))
    if inst is None:
        in_scope = sorted(macro_pins)
        scope_note = ("no RTL/netlist text available yet — every design-staged "
                      "hard macro treated as in scope")
    else:
        in_scope = sorted(m for m in macro_pins if m in inst)
        scope_note = (f"{len(in_scope)}/{len(macro_pins)} staged hard macro(s) "
                      "instantiated in the design's own RTL/netlist")
    report["scope_note"] = scope_note
    report["in_scope_masters"] = in_scope

    if not in_scope:
        print("[SKIP] l21_macro_supply_rail_declared_check: "
              f"{scope_note}; no instantiated hard macro with PG pins.")
        report["verdict"] = "SKIP"
        _emit(args.json, report)
        return 2

    if l21_path is None:
        print("[SKIP] l21_macro_supply_rail_declared_check: "
              "no L21_POWER_INTENT.json in this project.")
        report["verdict"] = "SKIP"
        _emit(args.json, report)
        return 2

    try:
        doc = json.loads(l21_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        print(f"[FAIL] l21_macro_supply_rail_declared_check: {l21_path} is not "
              f"parseable JSON ({exc}); the backend's rail contract is "
              "unreadable.")
        report["verdict"] = "FAIL"
        report["findings"] = [{"rule": "L21-0", "message": f"unparseable: {exc}"}]
        _emit(args.json, report)
        return 1

    fields = _l21_fields(doc)
    power_rails, ground_rails, domain_entries = _declared_rails(fields)
    findings: List[Dict[str, str]] = []

    # ---- L21-1: macro PG pin must have a declared rail of the SAME use ---- #
    for master in in_scope:
        for pin, use in macro_pins[master]:
            rails = power_rails if use == "POWER" else ground_rails
            if pin not in rails:
                findings.append({
                    "rule": "L21-1",
                    "master": master,
                    "pin": pin,
                    "use": use,
                    "message": (
                        f"hard macro `{master}` types pin `{pin}` as USE {use} "
                        f"in its OWN macro LEF, but L21.power_domains[] "
                        f"declares no {use} rail named `{pin}`. "
                        "_macro_supply_gc_plan name-matches this pin against "
                        "the declared rails of the same use; with no match it "
                        "becomes HARDMACRO_SUPPLY_UNCONNECTED, synthesis ties "
                        "the terminal off with TIEHI/TIELO, a SIGNAL net lands "
                        "on a POWER-typed terminal and TritonRoute aborts the "
                        "WHOLE detailed route."),
                })

    # ---- L21-2: every declared domain must be actionable ---- #
    for i, entry in enumerate(domain_entries):
        missing: List[str] = []
        if _entry_name(entry) is None:
            missing.append("name")
        if not _nets_from_entry(entry, _POWER_NET_KEYS):
            missing.append("primary power net")
        if not _nets_from_entry(entry, _GROUND_NET_KEYS):
            missing.append("primary ground net")
        if missing:
            findings.append({
                "rule": "L21-2",
                "entry": _entry_name(entry) or f"power_domains[{i}]",
                "message": (
                    f"power_domains[{i}] "
                    f"({_entry_name(entry) or 'unnamed'}) is missing "
                    f"{', '.join(missing)} — the rail set the backend "
                    "name-matches against is not derivable from this entry."),
            })

    # ---- L21-3: declared isolation / level-shifter entries must be typed --- #
    for i, entry in enumerate(fields.get("isolation_cells") or []):
        if not isinstance(entry, dict):
            findings.append({
                "rule": "L21-3", "entry": f"isolation_cells[{i}]",
                "message": (f"isolation_cells[{i}] is not an object; an "
                            "isolation strategy must be typed to be "
                            "actionable.")})
            continue
        missing = []
        if not any(k in entry and entry[k] not in (None, "")
                   for k in _ISO_DOMAIN_KEYS):
            missing.append("domain")
        if not any(k in entry and entry[k] not in (None, "")
                   for k in _ISO_CLAMP_KEYS):
            missing.append("clamp_value")
        if missing:
            findings.append({
                "rule": "L21-3", "entry": f"isolation_cells[{i}]",
                "message": (f"isolation_cells[{i}] is missing "
                            f"{', '.join(missing)} — an isolation cell with no "
                            "clamp value / domain binding cannot be emitted "
                            "into UPF.")})
    for i, entry in enumerate(fields.get("level_shifters") or []):
        if not isinstance(entry, dict):
            findings.append({
                "rule": "L21-3", "entry": f"level_shifters[{i}]",
                "message": (f"level_shifters[{i}] is not an object; a level "
                            "shifter must be typed to be actionable.")})
            continue
        if not any(k in entry and entry[k] not in (None, "")
                   for k in _LS_DOMAIN_KEYS) and not any(
                       k in entry and entry[k] not in (None, "")
                       for k in _LS_TO_DOMAIN_KEYS):
            findings.append({
                "rule": "L21-3", "entry": f"level_shifters[{i}]",
                "message": (f"level_shifters[{i}] declares no domain binding — "
                            "a level shifter with no from/to domain cannot be "
                            "placed on a crossing.")})

    # ---- L21-4: advisories (never change the exit code) ---- #
    advisories: List[str] = []
    status = doc.get("extraction_status")
    if isinstance(status, str) and status.upper().startswith("NOT_YET"):
        advisories.append(
            f"extraction_status={status} and emitted_by="
            f"{doc.get('emitted_by')!r}: this L21 is still the untouched "
            "post-process skeleton, so an empty power_domains[] here is "
            "indistinguishable from a legitimately single-domain design.")
    # DELIBERATELY NOT READ: `fields["upf_path"]`.
    #
    # The first draft raised an advisory when it was null. `l_doc_field_
    # producer_check` refused that reader and was right: upf_path is present
    # as a KEY in 15 published L21 docs and carries a value in ZERO of them,
    # so the advisory fires on every project and distinguishes nothing — an
    # empty value read as if it were a measurement, which is the exact shape
    # (#309/#348: L21 `declared_rails`, read by the phase-3 supply gate,
    # populated in 3 of 30 docs) that gate exists to stop. That no UPF is ever
    # emitted is a real gap, but it is a property of the emitter, not of the
    # design under test; it is documented in "NOT A DUPLICATE OF" above and
    # belongs in a gate on `l21_to_upf_emit`, not in a per-run note here.
    report["advisories"] = advisories
    report["findings"] = findings
    report["declared_power_rails"] = sorted(power_rails)
    report["declared_ground_rails"] = sorted(ground_rails)
    report["macro_pg_pins"] = {m: macro_pins[m] for m in in_scope}

    if not findings:
        report["verdict"] = "PASS"
        _emit(args.json, report)
        print("[PASS] l21_macro_supply_rail_declared_check: every USE "
              "POWER/GROUND pin of the "
              f"{len(in_scope)} instantiated hard macro(s) "
              f"({scope_note}) has a same-use rail declared in "
              f"L21.power_domains[] "
              f"(POWER={sorted(power_rails)}, GROUND={sorted(ground_rails)}).")
        for a in advisories:
            print(f"  [note] {a}")
        return 0

    waived, why = _waived(project)
    report["verdict"] = "PASS_WITH_WAIVERS" if waived else "FAIL"
    _emit(args.json, report)
    head = ("PASS_WITH_WAIVERS" if waived else "[FAIL]")
    print(f"{head} l21_macro_supply_rail_declared_check: "
          f"{len(findings)} L21 power-intent finding(s) "
          f"({scope_note}; macro LEFs: {lef_paths}).")
    for f in findings:
        print(f"  - {f['rule']}: {f['message']}")
    for a in advisories:
        print(f"  [note] {a}")
    if waived:
        print(f"  waiver `{WAIVER_KEY}` set: {why[:120]}")
        return 0
    print("  Fix: declare the missing rail(s) in L21.power_domains[] (the "
          "layer the backend's supply contract is read from), or set waiver "
          f"`{WAIVER_KEY}` (>={WAIVER_MIN} chars) to DISCLOSE that this design "
          "genuinely provides no such rail.")
    return 1


def _emit(path: Optional[Path], report: Dict[str, object]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
