#!/usr/bin/env python3
"""
power_domain_signal_crossing_check.py — M2 gate (DERIVATION engine).

M2 — cross-power-domain SIGNAL crossing derivation + UPF-strategy audit
=======================================================================

This is the DERIVATION counterpart to the three existing M2 auditors
(``power_domain_crossing_check`` / ``level_shifter_required_check`` /
``isolation_cell_required_check``).  Those three consume a PRE-ENUMERATED
``power_domain.json#crossings`` list in which every crossing record must
already self-declare its rail voltages (``vdd_from`` / ``vdd_to``) and its
power-down flags (``from_power_down`` / ``to_power_down``), and they verify
that a matching INSERTED cell exists in the ``level_shifter.json`` /
``isolation.json`` sidecars.

That leaves a specific residual hole this program fills:

  1.  Nothing DERIVES the crossing's protection *requirement* from the power
      domain DEFINITIONS themselves — the nominal supply VOLTAGE and the
      power-STATE table (an ``add_power_state`` with an OFF / CORRUPT state
      means the domain can be powered down).  If the crossing-list producer
      forgets to annotate ``vdd_from`` / ``to_power_down`` on a record, the
      three auditors silently treat it as needing no protection.  This engine
      LOOKS UP voltage + off-capability from the domain model, so a bare
      connectivity crossing ``{net, driver_domain, receiver_domain}`` (exactly
      what a net-connectivity extractor emits) is enough.

  2.  The three auditors check the presence of an INSERTED cell (sidecar).
      This engine instead checks the UPF *STRATEGY* — a ``set_isolation
      -domain PD_x`` / ``set_level_shifter -domain PD_x`` scoped to the
      crossing's source or destination domain — i.e. it audits the power
      INTENT, catching a crossing whose domains differ in voltage / border a
      power-gated domain but for which the UPF declares no covering strategy
      at all.

Requirement model (chip-AGNOSTIC, IEEE-1801 aligned)
---------------------------------------------------
For a net driven in domain A and received in domain B (A != B):
  * needs LEVEL SHIFTER  iff  nominal_voltage(A) != nominal_voltage(B)
  * needs ISOLATION      iff  A or B is power-down-capable (has an OFF /
                             CORRUPT power state, or is flagged switchable)
A crossing is PROTECTED iff every protection it requires is covered by a UPF
strategy scoped to the relevant domain (source domain for iso, either domain
for a level shifter — matching how UPF ``-domain`` scoping works).

Inputs (layered, first available wins for each facet; all chip-AGNOSTIC)
-----------------------------------------------------------------------
  * Power domains + power states + strategies:
        phase2/stage2/constraints/*.upf   (parsed: create_power_domain
        [-elements], create_supply_net -voltage, add_power_state OFF/voltage,
        set_isolation -domain, set_level_shifter -domain)
        OR phase1/generated_docs/L21_POWER_INTENT.json#fields
  * Net connectivity (the crossings themselves):
        reports/analog/mixed_signal/pd_connectivity.json
            {"nets":[{"net","driver_domain","receiver_domain(s)"}]}
        OR L21 fields.signal_crossings / power_domain_signal_crossings
        OR derived from a flat structural netlist + the UPF -elements
        instance->domain map (best-effort; needs output-port hints).

Behaviour
---------
* NOT_APPLICABLE / PASS (rc=0) — a single-power-domain design (0 or 1 domain)
  has no inter-domain crossing; that is an honest PASS, never a fake FAIL.
* SKIP (rc=2) — no power-intent artefact at all (no UPF, no L21 domains) AND
  step not waived.
* WAIVED (rc=0) — waivers.json declares the step waived.
* PASS (rc=0) — every derived signal crossing is covered by a UPF strategy.
* FAIL (rc=1) — one or more derived crossings needs isolation / level-shifter
  but the UPF declares no covering strategy (the exact silicon hazard).

chip-AGNOSTIC.  No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 power_domain_signal_crossing_check.py <project_dir> \
        [--json reports/phase2/gates/power_domain_signal_crossing.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_GATE_NAME = "power_domain_signal_crossing_check"
_GATE_LABEL = "power_domain_signal_crossing"
_DEFAULT_JSON = "reports/phase2/gates/power_domain_signal_crossing.json"
_UPF_GLOB = "phase2/stage2/constraints"
_L21_REL = "phase1/generated_docs/L21_POWER_INTENT.json"
_CONN_REL = "reports/analog/mixed_signal/pd_connectivity.json"
_CONN_REL_LEGACY = "reports/mixed_signal/pd_connectivity.json"
_WAIVER_RATIONALE = "Cross-power-domain signal-crossing derivation not shipped."


# ---------------------------------------------------------------------------
# waivers
# ---------------------------------------------------------------------------
def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text()).get("waived_steps") or []
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        if str(w.get("id", "")).strip() == step_label \
                or step_label in str(w.get("ticket", "")):
            return w
    return None


# ---------------------------------------------------------------------------
# domain model (name -> {voltage, off_capable, elements})
# ---------------------------------------------------------------------------
def _norm(s):
    """Canonical domain token: strip a leading PD_ prefix, lowercase."""
    s = str(s).strip()
    if s.lower().startswith("pd_"):
        s = s[3:]
    return s.lower()


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        m = re.search(r"[-+]?\d*\.?\d+", str(v))
        return float(m.group()) if m else None


# -- UPF parsing ------------------------------------------------------------
_RE_PD = re.compile(r"create_power_domain\s+(\S+)(.*)")
_RE_ELEMENTS = re.compile(r"-elements\s*\{([^}]*)\}")
_RE_SUPPLY = re.compile(
    r"create_supply_net\s+(\S+)\s+-domain\s+(\S+)(.*)")
_RE_VOLT = re.compile(r"-voltage\s+([-+]?\d*\.?\d+)")
_RE_PSTATE = re.compile(r"add_power_state\s+(\S+)(.*)")
_RE_STATE_BLOCK = re.compile(r"-state\s*\{([^}]*)\}")
_RE_ISO = re.compile(r"set_isolation\b.*?-domain\s+(\S+)")
_RE_LS = re.compile(r"set_level_shifter\b.*?-domain\s+(\S+)")
_OFF_TOKENS = ("off", "corrupt", "power_off", "shutdown", "power == off")


def parse_upf(text):
    """Parse the power-intent facets we need out of a UPF string.

    Returns (domains, iso_domains, ls_domains) where domains maps a
    normalised domain name -> {"voltage": float|None, "off_capable": bool,
    "elements": set[str]}.
    """
    domains = {}
    iso_domains = set()
    ls_domains = set()
    supply_domain = {}   # supply-net name -> domain token

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        m = _RE_PD.match(line)
        if m:
            dom = _norm(m.group(1))
            d = domains.setdefault(
                dom, {"voltage": None, "off_capable": False, "elements": set()})
            em = _RE_ELEMENTS.search(m.group(2))
            if em:
                for e in em.group(1).split():
                    d["elements"].add(e.strip())
            continue

        m = _RE_SUPPLY.match(line)
        if m:
            net, dom, rest = m.group(1), _norm(m.group(2)), m.group(3)
            supply_domain[net] = dom
            domains.setdefault(
                dom, {"voltage": None, "off_capable": False, "elements": set()})
            vm = _RE_VOLT.search(rest)
            if vm and domains[dom]["voltage"] is None:
                domains[dom]["voltage"] = float(vm.group(1))
            continue

        m = _RE_PSTATE.match(line)
        if m:
            # add_power_state may target "<domain>" or "<domain>.primary"
            dom = _norm(m.group(1).split(".", 1)[0])
            rest = m.group(2)
            d = domains.setdefault(
                dom, {"voltage": None, "off_capable": False, "elements": set()})
            body = rest.lower()
            for sm in _RE_STATE_BLOCK.finditer(rest):
                sb = sm.group(1).lower()
                if any(tok in sb for tok in _OFF_TOKENS):
                    d["off_capable"] = True
                vm = _RE_VOLT.search(sm.group(1)) or re.search(
                    r"\b([01]\.\d+|\d\.\d+)\b", sm.group(1))
                if vm and d["voltage"] is None:
                    d["voltage"] = _num(vm.group(1))
            if any(tok in body for tok in _OFF_TOKENS):
                d["off_capable"] = True
            continue

        for m in _RE_ISO.finditer(line):
            iso_domains.add(_norm(m.group(1)))
        for m in _RE_LS.finditer(line):
            ls_domains.add(_norm(m.group(1)))

    return domains, iso_domains, ls_domains


# -- L21 parsing ------------------------------------------------------------
_L21_OFF_KEYS = ("switchable", "power_down", "can_power_down", "off_capable",
                 "power_gateable", "has_power_gate", "gated")


def parse_l21(fields):
    """Extract (domains, iso_domains, ls_domains) from an L21 fields dict.

    #312-family: `isolation_cells` and `level_shifters` are read here and
    populated by NO producer — measured across 311 real L-docs, the keys are
    present in 27 and carry a value in 0. On this fallback path both sets are
    therefore ALWAYS empty, and `crossing_missing` reads an empty set as "no
    strategy scopes this domain" — so every crossing that requires protection
    is reported UNPROTECTED. That is a false FAIL, and it can only fire on
    exactly the designs that reach this path (a populated `power_domains`,
    itself present in only 3 of 30).

    An absent field means the layer SAYS NOTHING about protection, which is
    not the same as saying there is none. `l21_states_protection` reports
    which of the two it was, so the caller can decline to judge instead of
    manufacturing a finding out of a missing producer."""
    domains = {}
    iso_domains = set()
    ls_domains = set()
    for d in fields.get("power_domains") or []:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        # #598: a RAIL declaration is not a domain. `l21_macro_supply_rail_synth`
        # emits one entry per macro GROUND pin so the Phase-3 consumer can bind
        # it, and it carries the design's primary `power_net` because that
        # consumer requires one. Read as a domain it becomes a phantom named
        # after a ground pin, holding the 1.2 V core rail at 0.0 V.
        if d.get("is_power_domain") is False:
            continue
        name = _norm(d["name"])
        # `voltage_v` FIRST: it is what every producer actually writes
        # (l21_doc_supply_rail_synth, l21_macro_supply_rail_synth,
        # phase1_layer_demand_probe, phase1_doc_one_shot_runner), and none of
        # the three names read here was ever one of them. Measured across the
        # repo: 4 producers write `voltage_v`, 0 write `voltage`. Every domain
        # therefore arrived with `voltage: null`, and a level shifter is
        # required exactly when two voltages DIFFER — so with all of them
        # unknown, `needs_ls` could never once be True.
        volt = _num(d.get("voltage_v", d.get("voltage",
                    d.get("nominal_voltage", d.get("supply_voltage")))))
        off = any(bool(d.get(k)) for k in _L21_OFF_KEYS)
        # power_states list: an OFF/CORRUPT state marks the domain switchable
        for st in (d.get("power_states") or []):
            s = json.dumps(st).lower() if not isinstance(st, str) else st.lower()
            if any(tok in s for tok in _OFF_TOKENS):
                off = True
        elements = set()
        for e in (d.get("elements") or d.get("instances") or []):
            if isinstance(e, str):
                elements.add(e)
        domains[name] = {"voltage": volt, "off_capable": off,
                         "elements": elements}
    global _L21_STATED_PROTECTION
    _L21_STATED_PROTECTION = bool(fields.get("isolation_cells")
                                  or fields.get("level_shifters"))
    for iso in fields.get("isolation_cells") or []:
        if isinstance(iso, dict) and iso.get("domain"):
            iso_domains.add(_norm(iso["domain"]))
    for ls in fields.get("level_shifters") or []:
        if isinstance(ls, dict):
            for k in ("domain", "from", "to"):
                if ls.get(k):
                    ls_domains.add(_norm(ls[k]))
    return domains, iso_domains, ls_domains


# ---------------------------------------------------------------------------
# connectivity (the crossings)
# ---------------------------------------------------------------------------
def _crossing_records(conn_obj, l21_fields):
    """Normalise a connectivity source into a flat list of
    {net, driver_domain, receiver_domain} records.  A record with multiple
    receiver domains is fanned out into one record per receiver."""
    out = []

    def _emit(net, drv, recvs):
        if not drv or not recvs:
            return
        for r in recvs:
            if r:
                out.append({"net": str(net), "driver_domain": _norm(drv),
                            "receiver_domain": _norm(r)})

    def _recvs(rec):
        r = rec.get("receiver_domain", rec.get("receiver_domains",
                    rec.get("to", rec.get("sink_domain"))))
        if isinstance(r, str):
            return [r]
        if isinstance(r, list):
            return r
        return []

    src = None
    if isinstance(conn_obj, dict):
        src = conn_obj.get("nets") or conn_obj.get("crossings") \
            or conn_obj.get("signals")
    if src is None and isinstance(l21_fields, dict):
        src = l21_fields.get("signal_crossings") \
            or l21_fields.get("power_domain_signal_crossings")
    for rec in (src or []):
        if not isinstance(rec, dict):
            continue
        drv = rec.get("driver_domain", rec.get("from",
              rec.get("source_domain", rec.get("driver"))))
        _emit(rec.get("net", rec.get("signal", rec.get("name", "<net>"))),
              drv, _recvs(rec))
    return out


# -- structural-netlist derivation (optional, best-effort) ------------------
_RE_INST = re.compile(
    r"^\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*;",
    re.DOTALL | re.MULTILINE)
_RE_CONN = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")


def derive_crossings_from_netlist(netlist_text, inst_domain, output_ports):
    """Best-effort: derive {net,driver_domain,receiver_domain} crossings from
    a flat structural Verilog netlist.

    inst_domain  : {instance_name -> domain_token}
    output_ports : {module_type -> set(output_port_names)}

    A net's driver domain is the domain of the instance connecting it through
    an output port; its receiver domains are the domains of instances that
    connect it through non-output ports.  Only inter-domain nets are returned.
    Returns [] when port directions are unknown (never guesses a direction).
    """
    if not output_ports:
        return []
    drivers = {}      # net -> domain
    receivers = {}    # net -> set(domain)
    for mtype, iname, body in _RE_INST.findall(netlist_text):
        dom = inst_domain.get(iname)
        if dom is None:
            continue
        dom = _norm(dom)
        outs = output_ports.get(mtype, set())
        for port, net in _RE_CONN.findall(body):
            net = net.strip()
            if not net:
                continue
            if port in outs:
                drivers[net] = dom
            else:
                receivers.setdefault(net, set()).add(dom)
    out = []
    for net, drv in drivers.items():
        for rdom in receivers.get(net, set()):
            if rdom != drv:
                out.append({"net": net, "driver_domain": drv,
                            "receiver_domain": rdom})
    return out


# ---------------------------------------------------------------------------
# requirement + audit
# ---------------------------------------------------------------------------
def required_protection(drv, recv, domains):
    """Return (needs_iso, needs_ls) for a crossing, looked up from the domain
    model (voltage + off-capability), NOT from per-crossing annotations."""
    da = domains.get(drv, {})
    db = domains.get(recv, {})
    va, vb = da.get("voltage"), db.get("voltage")
    needs_ls = False
    if va is not None and vb is not None:
        needs_ls = abs(va - vb) > 1e-9
    needs_iso = bool(da.get("off_capable") or db.get("off_capable"))
    return needs_iso, needs_ls


# True once an L21 parse has seen a NON-EMPTY isolation/level-shifter list.
# False means the power-intent layer said nothing about protection at all.
_L21_STATED_PROTECTION = True


def l21_states_protection() -> bool:
    """Did the last L21 parse find ANY protection statement? False means the
    layer is silent, not that the design is unprotected."""
    return _L21_STATED_PROTECTION


def crossing_missing(crossing, domains, iso_domains, ls_domains):
    """Return the list of protections a crossing REQUIRES but the UPF strategy
    does not cover.  Empty list => protected."""
    drv = crossing["driver_domain"]
    recv = crossing["receiver_domain"]
    if drv == recv:
        return []                      # intra-domain — not a crossing
    needs_iso, needs_ls = required_protection(drv, recv, domains)
    missing = []
    if needs_iso and not ({drv, recv} & iso_domains):
        missing.append("isolation")
    if needs_ls and not ({drv, recv} & ls_domains):
        missing.append("level_shifter")
    return missing


def audit(domains, iso_domains, ls_domains, crossings):
    """Audit every derived crossing.  Returns (findings, n_inter, n_unprot)."""
    findings = []
    n_inter = 0
    n_unprot = 0
    for c in crossings:
        if c["driver_domain"] == c["receiver_domain"]:
            continue
        n_inter += 1
        missing = crossing_missing(c, domains, iso_domains, ls_domains)
        if missing:
            n_unprot += 1
            needs_iso, needs_ls = required_protection(
                c["driver_domain"], c["receiver_domain"], domains)
            why = []
            if needs_iso:
                why.append("borders a power-down-capable domain")
            if needs_ls:
                why.append("crosses a voltage boundary")
            if not l21_states_protection():
                # The layer is SILENT about protection (the fields exist in
                # the schema and no producer fills them). Reporting
                # UNPROTECTED here states a fact the input never provided.
                findings.append({
                    "severity": "WARNING",
                    "rule": "PROTECTION_UNSTATED",
                    "message": (
                        f"net '{c['net']}' crosses {c['driver_domain']} -> "
                        f"{c['receiver_domain']} ({'; '.join(why)}), and the "
                        f"power-intent layer states NO isolation or "
                        f"level-shifter strategy at all — so whether it is "
                        f"protected CANNOT be determined from this input. "
                        f"Not reported as unprotected: an absent statement "
                        f"is not a statement of absence.")})
                continue
            findings.append({
                "severity": "ERROR", "rule": "UNPROTECTED_SIGNAL_CROSSING",
                "message": (
                    f"net '{c['net']}' crosses {c['driver_domain']} -> "
                    f"{c['receiver_domain']} ({'; '.join(why)}) but no UPF "
                    f"{missing} strategy scopes either domain — cross-power-"
                    f"domain signal is unprotected.")})
    return findings, n_inter, n_unprot


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def _load_json(path):
    try:
        return json.loads(path.read_text()), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _find_upf(project):
    d = project / _UPF_GLOB
    if d.is_dir():
        cands = sorted(d.glob("*.upf"))
        if cands:
            return cands[0]
    return None


def _load_power_model(project):
    """Return (domains, iso_domains, ls_domains, source_label, err)."""
    upf = _find_upf(project)
    if upf is not None:
        try:
            text = upf.read_text(errors="replace")
        except OSError as exc:
            return {}, set(), set(), None, f"UPF read error: {exc}"
        dom, iso, ls = parse_upf(text)
        if dom:
            return dom, iso, ls, str(upf.relative_to(project)), None
    l21 = project / _L21_REL
    if l21.is_file():
        obj, err = _load_json(l21)
        if err is None and isinstance(obj, dict):
            fields = obj.get("fields", obj)
            dom, iso, ls = parse_l21(fields)
            if dom:
                return dom, iso, ls, str(l21.relative_to(project)), None
    return {}, set(), set(), None, None


def _load_connectivity(project):
    for rel in (_CONN_REL, _CONN_REL_LEGACY):
        p = project / rel
        if p.is_file():
            obj, err = _load_json(p)
            if err:
                return None, str(p.relative_to(project)), err
            return obj, str(p.relative_to(project)), None
    return None, None, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=_DEFAULT_JSON)
    ap.add_argument("--step-label", default=_GATE_LABEL)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    waiver = _step_waived(project, args.step_label)
    domains, iso_domains, ls_domains, src, err = _load_power_model(project)

    findings = []
    n_inter = 0
    if err is not None:
        verdict, rc = "FAIL", 1
        findings = [{"severity": "ERROR", "rule": "MALFORMED_ARTEFACT",
                     "message": err}]
    elif not domains and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                     "message": f"waiver={waiver.get('ticket','?')}: "
                                f"{waiver.get('reason','?')}"}]
    elif not domains:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "NO_POWER_INTENT",
                     "message": "no UPF and no L21 power_domains — no power "
                                "intent to derive crossings from."}]
    elif len(domains) < 2:
        verdict, rc = "PASS", 0
        findings = [{"severity": "INFO", "rule": "NOT_APPLICABLE",
                     "message": f"single power domain ({next(iter(domains))}) "
                                f"— no inter-domain signal crossing possible."}]
    else:
        conn_obj, conn_src, conn_err = _load_connectivity(project)
        if conn_err:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "MALFORMED_ARTEFACT",
                         "message": f"pd_connectivity.json unparseable: {conn_err}"}]
        else:
            l21_fields = None
            l21 = project / _L21_REL
            if l21.is_file():
                o, e = _load_json(l21)
                if e is None and isinstance(o, dict):
                    l21_fields = o.get("fields", o)
            crossings = _crossing_records(conn_obj, l21_fields)
            findings, n_inter, n_unprot = audit(
                domains, iso_domains, ls_domains, crossings)
            if n_unprot > 0:
                verdict, rc = "FAIL", 1
            elif not crossings:
                # #598: NOTHING WAS EXAMINED. Reaching here means >= 2 domains
                # are declared and not one crossing could be derived — the
                # domains carry no `elements`, so no instance could be placed
                # in one. "0 crossings, all protected" is a claim about a
                # denominator that was never established, and it was being
                # counted as a substantive PASS.
                verdict, rc = "PASS", 0
                findings.append({
                    "severity": "WARNING", "rule": "NO_CROSSINGS_DERIVED",
                    "message": (
                        f"{len(domains)} power domain(s) declared and NO signal "
                        f"crossing could be derived at all — the domains carry "
                        f"no element/instance list, so no net can be attributed "
                        f"to one. Nothing about isolation or level shifting was "
                        f"checked here; this is an absent basis, not a clean "
                        f"result.")})
            else:
                verdict, rc = "PASS", 0
                unknown_v = sorted(n for n, d in domains.items()
                                   if d.get("voltage") is None)
                if unknown_v:
                    # A level shifter is required exactly when two voltages
                    # DIFFER. An unknown voltage cannot differ from anything, so
                    # that half of the check is silently inert for these.
                    findings.append({
                        "severity": "WARNING", "rule": "VOLTAGE_UNSTATED",
                        "message": (
                            f"{len(unknown_v)} of {len(domains)} domain(s) state "
                            f"no voltage ({', '.join(unknown_v)}), so the "
                            f"level-shifter half of this check could not fire "
                            f"for any crossing touching them. Isolation was "
                            f"still checked.")})
                findings.append({
                    "severity": "INFO", "rule": "ALL_CROSSINGS_PROTECTED",
                    "message": (f"{n_inter} inter-domain signal crossing(s) "
                                f"derived from {len(crossings)} examined; all "
                                f"covered by a UPF isolation / level-shifter "
                                f"strategy.")})

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "power_intent_source": src,
        "domains": {k: {"voltage": v["voltage"],
                        "off_capable": v["off_capable"]}
                    for k, v in domains.items()},
        "isolation_strategy_domains": sorted(iso_domains),
        "level_shifter_strategy_domains": sorted(ls_domains),
        "inter_domain_crossings": n_inter,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "findings": findings,
    }
    out_path = Path(args.json)
    if not out_path.is_absolute():
        out_path = project / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    for f in findings:
        if f.get("severity") in ("ERROR", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
