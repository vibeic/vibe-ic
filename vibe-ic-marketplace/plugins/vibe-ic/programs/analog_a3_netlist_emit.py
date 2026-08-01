#!/usr/bin/env python3
"""analog_a3_netlist_emit.py — the A3 netlist PRODUCER that was missing.

WHAT WAS BROKEN — and it is sharper than "a file is absent"
===========================================================
`programs/` ships FOUR netlist checkers —
`analog_netlist_connectivity_check`, `analog_netlist_include_order_check`,
`analog_netlist_path_lint`, `analog_netlist_pdk_check` — and NO program that
generates a netlist. A3 was skill-only, so the runner correctly WAIVED it and
the checkers validated a file nothing wrote.

They were not idle, though. On a real run they examined the 126 flat corner
decks `analog_real_corner_sweep` leaves behind, found `files_with_subckt: 0`,
and printed PASS on all four. So the sign-off surface was green over a tree
containing zero analog block netlists.

WHAT THIS PROGRAM DOES
======================
It renders SPICE from the A2 topology IR — and it has **no per-type netlist
template of its own**. `analog_a2_topology_emit.LIBRARY` holds the circuit
classes; this program is a generic IR -> SPICE renderer plus a PDK binder plus
a verifier. That separation is deliberate: a producer that carried a
per-block-type deck table would be the thing being replaced, one directory
over. `analog_real_corner_sweep.T[...]` is that table, and it is why the
analog headline of a whole run was a self-test of the plugin's own template
library.

    phase3/analog/<block>/topology.json  (A2 IR — required)
    phase3/analog/<block>/spec.json      (A1 spec — REQUIRED, see below)
        -> phase3/analog/<block>/<block>.sp        the declared A3 artefact
           phase3/analog/<block>/tb_<block>.sp     its stimulus
           phase3/analog/<block>/netlist_provenance.json

THE CONTROL THAT STOPS THIS BECOMING A FANCIER TEMPLATE TABLE
=============================================================
**A block with no extractable spec gets no netlist.** If `spec.json` is
absent, this program writes `netlist_gap.json` with status
`NO_SPEC_NO_NETLIST` and emits nothing — even though the topology library
could render a perfectly valid `.sp` for the block's circuit class from the
class alone. That netlist would be a template with the design's block name
substituted into it, which is the exact defect this round exists to remove:
it would pass all five gates, it would simulate, and every number it produced
would be about the template.

The design content that DOES enter the netlist is recorded, per field, in the
provenance: which device parameters were solved against a bound spec value
(`spec_bound_params`) and which are library nominals
(`library_nominal_params`). For most classes the honest answer today is that
the structure is design-derived and the geometry is not — so the artefact says
that, and hands sizing to skill `analog-sizing`, rather than letting a reader
assume a simulated netlist was also a sized one.

SELF-VERIFICATION BEFORE THE ARTEFACT IS DECLARED
=================================================
An emitted `.sp` is put through the four netlist checkers AND the A3 gate, in
an isolated staging project so the verdict is about THIS file and not about
whatever else the run has left in the tree. A file that fails any of them is
DELETED and replaced by `netlist_gap.json` carrying the findings — a netlist
that cannot pass the checks that exist is worse than an absent one, because
the absent one is honestly WAIVED.

With `--verify-sim` the testbench is additionally run through ngspice in the
EDA container. Non-convergence deletes the artefact. An UNREACHABLE container
does not: that is a capability gap, not a netlist defect, and it is recorded
as `simulation_verified: false` /
`simulation_status: NOT_VERIFIED_NO_SIMULATOR` in both the sidecar and the
`.sp` header, so nobody can read an unsimulated deck as a simulated one.

Netlist STYLE RULES, each forced by a measured failure
======================================================
  * Passives are instantiated as PDK subcircuits with their full terminal
    list (a 3-terminal resistor, not an `R` card). `analog_netlist_
    connectivity_check._device_nets` parses ONLY `X` cards carrying >= 3 nets,
    so a 2-terminal `R` card is invisible to it and the feedback node it
    terminates was measured to raise a false `FLOATING_NODE: internal net
    'vfb' touched by only 1 device pin`.
  * A 2-terminal device (`cap`) is invisible to that same parser, so the
    renderer refuses to emit an internal net whose only OTHER pin comes from
    one. This is a checker blind spot being worked around, written down here
    so it is not rediscovered.
  * PMOS bodies tie to the positive rail and NMOS bodies to ground
    (`PMOS_BODY_TO_VSS` / `NMOS_BODY_TO_VDD`).
  * Every model token must be in `programs/pdk_registry.json#device_models`
    (`UNKNOWN_PDK_MODEL`), and absolute includes must live under the PDK root
    (`NON_WHITELISTED_ABSOLUTE_PATH`).

RC CONTRACT
===========
    rc 0  at least one selected block produced a verified `<block>.sp`
          (or already carried one this producer must not overwrite).
    rc 1  the inputs themselves are unusable (no project dir / no block list).
    rc 2  no selected block produced a netlist. `netlist_gap.json` written per
          block naming WHY; hand off to skill `analog-netlist-gen`.

chip-AGNOSTIC: circuit structure comes from the A2 IR, device names from the
resolved PDK, numbers from the A1 spec. No chip, PDK SKU, vendor or part
number appears below.

Usage:
    python3 analog_a3_netlist_emit.py <project> [--block NAME] [--pdk sky130]
            [--container vibeic-eda] [--verify-sim] [--json OUT]
"""
from __future__ import annotations

import argparse
import ast as _ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

PRODUCER = "analog_a3_netlist_emit"
PROVENANCE_SCHEMA = 1
SKILL = "analog-netlist-gen"

_CANONICAL_ANALOG = "phase3/analog"
_DECLARED_ANALOG = "phase1/analog"
_REGISTRY = _HERE / "pdk_registry.json"
DEFAULT_CONTAINER = os.environ.get("VIBEIC_ANALOG_CONTAINER", "vibeic-eda")

# Role -> the device-class tokens a foundry SPICE lib spells its subcircuits
# with. Structural, not a vendor literal — the same vocabulary
# `analog_pdk_deck_context._ROLE_TOKENS` uses, extended with the passive roles
# the topology IR can ask for.
_ROLE_TOKENS = {
    "nmos": ("nfet", "nmos", "nch"),
    "pmos": ("pfet", "pmos", "pch"),
    "res": ("res_", "rpoly", "rppd", "rhigh", "rsil", "resistor"),
    "cap": ("cap_mim", "mimcap", "cap_cmim", "moscap"),
}
# Within a role, prefer the most ordinary flavour: a plain core-voltage device
# over a high-voltage / low-Vt / isolated variant. Deterministic and stated,
# so the choice is auditable instead of alphabetical.
_ROLE_PREFER = {
    "nmos": ("01v8", "03v3", "lv_"),
    "pmos": ("01v8", "03v3", "lv_"),
    "res": ("res_high_po_0p35", "res_generic_po", "rhigh"),
    "cap": ("cap_mim", "cap_cmim"),
}
_ROLE_AVOID = ("_lvt", "_hvt", "_nvt", "_zvt", "_iso", "_dss", "20v0",
               "g5v0", "05v0", "06v0", "11v0", "_var", "hv_")


# ── small helpers ─────────────────────────────────────────────────────────
def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_ALLOWED_NODES = (_ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Name,
                  _ast.Load, _ast.Constant, _ast.Add, _ast.Sub, _ast.Mult,
                  _ast.Div, _ast.Pow, _ast.USub, _ast.UAdd)


def safe_eval(expr: str, env: Dict[str, float]) -> float:
    """Arithmetic over named values only. The IR is data read off disk, so it
    must never be executable: no calls, attributes or subscripts."""
    tree = _ast.parse(str(expr), mode="eval")
    for node in _ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"disallowed node {type(node).__name__}")
        if isinstance(node, _ast.Name) and node.id not in env:
            raise KeyError(node.id)
    return float(eval(compile(tree, "<ir-expr>", "eval"),  # noqa: S307
                      {"__builtins__": {}}, dict(env)))


def _fmt(v: float) -> str:
    """A geometry number SPICE reads back the same way it was computed."""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6g}"


# ── inputs ────────────────────────────────────────────────────────────────
def block_entries(project: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    for rel in (f"{_CANONICAL_ANALOG}/analog_block_list.json",
                f"{_DECLARED_ANALOG}/analog_block_list.json"):
        data = _read_json(project / rel)
        if data is None:
            continue
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if isinstance(blocks, list):
            return ([b for b in blocks if isinstance(b, dict)], rel)
    data = _read_json(project / "phase1/generated_docs/L5_ADI_SPEC.json")
    if isinstance(data, dict) and isinstance(data.get("analog_blocks"), list):
        return ([b for b in data["analog_blocks"] if isinstance(b, dict)],
                "phase1/generated_docs/L5_ADI_SPEC.json")
    return ([], None)


def spec_values(spec: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    specs = spec.get("specs")
    if isinstance(specs, list):
        for s in specs:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            for k in ("target", "typ", "value", "min", "max"):
                v = s.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[str(s["name"])] = float(v)
                    break
    return out


# ── PDK binding ───────────────────────────────────────────────────────────
def _registry_entry(selector: str) -> Tuple[Optional[str], Dict[str, Any]]:
    data = _read_json(_REGISTRY)
    sel = str(selector or "").strip().lower()
    for ent in (data or {}).get("pdks") or []:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name") or "")
        if name and (name.lower() == sel or name.lower().startswith(sel)
                     or sel.startswith(name.lower())):
            return name, ent
    return None, {}


def resolve_role_models(family_entry: Dict[str, Any], roles: List[str],
                        ctx_device_map: Dict[str, str]
                        ) -> Tuple[Dict[str, str], List[str]]:
    """{role: model name} for the resolved family, plus the roles that could
    NOT be resolved. Prefers whatever the deck-context resolver already
    elected, then falls back to the registry's declared device list. A role
    that resolves to nothing is reported, never substituted."""
    models = [m for m in (family_entry.get("device_models") or [])
              if isinstance(m, str)]
    out: Dict[str, str] = {}
    unresolved: List[str] = []
    for role in roles:
        if ctx_device_map.get(role):
            out[role] = ctx_device_map[role]
            continue
        toks = _ROLE_TOKENS.get(role, ())
        cands = [m for m in models
                 if any(t in m.lower() for t in toks)]
        if not cands:
            unresolved.append(role)
            continue
        pref = _ROLE_PREFER.get(role, ())

        def rank(m: str) -> tuple:
            low = m.lower()
            exact = next((i for i, p in enumerate(pref) if p in low),
                         len(pref))
            avoid = sum(1 for a in _ROLE_AVOID if a in low)
            return (exact, avoid, len(low), low)

        out[role] = sorted(cands, key=rank)[0]
    return out, unresolved


def resolve_pdk_context(project: Path, pdk: str, container: str,
                        roles: List[str]) -> Dict[str, Any]:
    """model lib + corner section + per-role model names, through the EXISTING
    family-agnostic resolvers so a project that declares a native target never
    gets one foundry's device tokens against another's model lib."""
    ctx_json: Dict[str, Any] = {}
    device_map: Dict[str, str] = {}
    model_lib: Optional[str] = None
    typ_section: Optional[str] = None
    device_terminals: Dict[str, int] = {}
    geometry_units: Dict[str, str] = {}
    status = "OK"
    work_items: List[str] = []
    family = pdk
    try:
        import analog_pdk_deck_context as _apdc
        res = None
        try:
            import analog_pdk_availability as _apa
            declared = _declared_pdk_target(project)
            if declared:
                res = _apa.resolve_pdk(declared, project=project,
                                       container=container)
        except Exception:
            res = None
        ctx = _apdc.resolve_deck_context(pdk, res=res,
                                         required=tuple(r for r in roles
                                                        if r in ("nmos",
                                                                 "pmos")))
        ctx_json = ctx.as_json()
        status = ctx_json.get("status") or "OK"
        family = ctx_json.get("family") or pdk
        model_lib = ctx_json.get("model_lib")
        typ_section = ctx_json.get("typ_section")
        device_map = dict(ctx_json.get("device_map") or {})
        device_terminals = dict(ctx_json.get("device_terminals") or {})
        geometry_units = dict(ctx_json.get("device_geometry_units") or {})
        work_items = list(ctx_json.get("work_items") or [])
    except Exception as exc:                                  # pragma: no cover
        status = "NEEDS_NATIVE_TEMPLATE"
        work_items = [f"deck-context resolver unavailable: {exc}"]

    fam_name, fam_entry = _registry_entry(family or pdk)
    models, unresolved = resolve_role_models(fam_entry, roles, device_map)
    return {
        "status": status,
        "family": family,
        "registry_family": fam_name,
        "model_lib": model_lib,
        "typ_section": typ_section,
        "corner_sections": ctx_json.get("corner_sections") or [],
        "role_models": models,
        "unresolved_roles": unresolved,
        "device_terminals": device_terminals,
        "geometry_units": geometry_units,
        "analog_device_params": fam_entry.get("analog_device_params") or {},
        "work_items": work_items,
        "deck_context": ctx_json,
    }


def _declared_pdk_target(project: Path) -> Optional[str]:
    d = _read_json(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")
    if isinstance(d, dict):
        f = d.get("fields")
        if isinstance(f, dict) and isinstance(f.get("pdk_target"), str):
            return f["pdk_target"] or None
    return None


# ── rendering ─────────────────────────────────────────────────────────────
def _resolve_params(ir: Dict[str, Any], sv: Dict[str, float]
                    ) -> Tuple[Dict[str, Dict[str, float]], List[str],
                               List[str], Dict[str, Any]]:
    """Apply the IR's device_param_exprs. Returns (overrides, spec_bound,
    library_nominal, env)."""
    env: Dict[str, Any] = {}
    env.update(ir.get("constants") or {})
    env.update({k: v for k, v in (ir.get("knobs") or {}).items()
                if isinstance(v, (int, float))})
    env.update(sv)
    overrides: Dict[str, Dict[str, float]] = {}
    spec_bound: List[str] = []
    knob_src = ir.get("knob_sources") or {}
    for e in ir.get("device_param_exprs") or []:
        try:
            val = safe_eval(e["expr"], env)
        except Exception:
            continue
        overrides.setdefault(e["device"], {})[e["param"]] = val
        names = set()
        try:
            names = {n.id for n in _ast.walk(_ast.parse(e["expr"], "<e>",
                                                        "eval"))
                     if isinstance(n, _ast.Name)}
        except SyntaxError:
            pass
        if any(n in sv for n in names) or any(
                knob_src.get(n) == "spec" for n in names):
            spec_bound.append(f"{e['device']}.{e['param']}")
    nominal = [f"{d['name']}.{p}"
               for d in ir.get("devices") or []
               for p in ("w", "l", "m")
               if d.get(p) is not None
               and f"{d['name']}.{p}" not in spec_bound]
    return overrides, sorted(spec_bound), sorted(nominal), env


def _validate_ir(ir: Dict[str, Any], pdkctx: Dict[str, Any]) -> List[str]:
    """Structural problems that must stop emission. Every one of these was a
    real failure mode measured on a hand-built fixture."""
    problems: List[str] = []
    role_terms = ir.get("role_terminals") or {}
    ports = set(ir.get("ports") or [])
    rails = set((ir.get("rails") or {}).values())
    declared_internal = set(ir.get("internal_nets") or [])
    pin_count: Dict[str, int] = {}
    visible_pin_count: Dict[str, int] = {}
    for d in ir.get("devices") or []:
        role = d.get("role")
        nets = d.get("nets") or []
        want = role_terms.get(role)
        if want is not None and len(nets) != want:
            problems.append(
                f"device `{d.get('name')}` role `{role}` declares "
                f"{len(nets)} nets, the role's subcircuit takes {want}")
        ctx_terms = (pdkctx.get("device_terminals") or {}).get(role)
        if ctx_terms and want and ctx_terms != want:
            problems.append(
                f"resolved `{role}` subcircuit takes {ctx_terms} terminals "
                f"but the IR is written for {want}; ngspice would abort "
                f"'Too few parameters for subcircuit'")
        for n in nets:
            pin_count[n] = pin_count.get(n, 0) + 1
            if len(nets) >= 3:          # the connectivity parser's own floor
                visible_pin_count[n] = visible_pin_count.get(n, 0) + 1
        if role == "pmos" and nets and nets[-1] not in rails:
            problems.append(f"device `{d.get('name')}` is a PMOS whose body "
                            f"net `{nets[-1]}` is not a declared rail")
        if role == "nmos" and nets and nets[-1] not in rails:
            problems.append(f"device `{d.get('name')}` is an NMOS whose body "
                            f"net `{nets[-1]}` is not a declared rail")
    for net in sorted(declared_internal):
        if visible_pin_count.get(net, 0) < 2:
            problems.append(
                f"internal net `{net}` is touched by "
                f"{visible_pin_count.get(net, 0)} pin(s) that the "
                f"connectivity checker can see (2-terminal devices are "
                f"invisible to it) — it would be reported FLOATING_NODE")
    for p in sorted(ports - rails):
        if pin_count.get(p, 0) < 1:
            problems.append(f"port `{p}` is declared and never connected — "
                            f"UNUSED_PORT")
    if pdkctx.get("unresolved_roles"):
        problems.append(
            "device role(s) " + ", ".join(pdkctx["unresolved_roles"]) +
            f" do not resolve to a model in the `{pdkctx.get('registry_family')}`"
            " device list")
    if not pdkctx.get("model_lib"):
        problems.append("no model library resolves for the requested PDK; a "
                        "netlist with no `.lib` is NO_MODEL_INCLUDE")
    return problems


def render_netlist(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                   prov_lines: List[str],
                   overrides: Dict[str, Dict[str, float]]) -> str:
    block = ir["block"]
    metric = any(u == "metric" for u in
                 (pdkctx.get("geometry_units") or {}).values())
    L: List[str] = [f"* {block} — analog block netlist "
                    f"({ir['block_type']} class)",
                    f"* topology: {ir['topology']}"]
    L += [f"* {ln}" for ln in prov_lines]
    L.append("*")
    if not metric:
        L.append(".option scale=1u")
    section = pdkctx.get("typ_section") or ""
    L.append(f".lib {pdkctx['model_lib']} {section}".rstrip())
    L.append("")
    L.append(f".subckt {block} {' '.join(ir['ports'])}")
    for d in ir["devices"]:
        model = pdkctx["role_models"][d["role"]]
        parts = [f"x{d['name']}"] + list(d["nets"]) + [model]
        for p in ("w", "l"):
            v = (overrides.get(d["name"], {}).get(p, d.get(p)))
            if v is None:
                continue
            parts.append(f"{p}={_fmt(float(v))}u" if metric
                         else f"{p}={_fmt(float(v))}")
        m = overrides.get(d["name"], {}).get("m", d.get("m"))
        if m is not None:
            parts.append(f"m={_fmt(float(m))}")
        for k, v in (d.get("params") or {}).items():
            parts.append(f"{k}={v}")
        L.append(" ".join(parts))
    L.append(f".ends {block}")
    L.append("")
    # Deliberately NO `.end`: this file is `.include`d by its testbench, and a
    # terminating card there truncates the caller's netlist.
    return "\n".join(L)


def render_testbench(ir: Dict[str, Any], pdkctx: Dict[str, Any],
                     env: Dict[str, Any], prov_lines: List[str]
                     ) -> Tuple[Optional[str], Dict[str, Any], List[str]]:
    """Returns (text, tb_env, notes). None when the IR declares no testbench —
    an honest absence, not an invented stimulus."""
    tb = ir.get("testbench")
    if not isinstance(tb, dict):
        return None, {}, ["the topology IR declares no testbench"]
    block = ir["block"]
    notes: List[str] = []
    e: Dict[str, Any] = dict(env)
    nominal = (pdkctx.get("analog_device_params") or {}).get(
        "nominal_supply_v")
    if isinstance(nominal, (int, float)):
        e["nominal_supply_v"] = float(nominal)
    supply = None
    for expr in tb.get("supply_exprs") or []:
        try:
            supply = safe_eval(expr, {k: v for k, v in e.items()
                                      if isinstance(v, (int, float))})
            notes.append(f"supply = {expr} = {supply:g} V")
            break
        except Exception:
            continue
    if supply is None:
        return None, {}, ["no supply expression in the topology IR resolves "
                          "against the bound spec and the PDK constants"]
    e["supply"] = supply
    for name, expr in (tb.get("env_exprs") or {}).items():
        try:
            e[name] = safe_eval(expr, {k: v for k, v in e.items()
                                       if isinstance(v, (int, float))})
            notes.append(f"{name} = {expr} = {e[name]:g}")
        except Exception:
            return None, {}, [f"testbench value `{name}` needs `{expr}`, "
                              f"which the bound spec does not supply"]
    fmt = {k: (_fmt(v) if isinstance(v, float) else v) for k, v in e.items()}
    L: List[str] = [f"* tb_{block} — stimulus for the A3 block netlist"]
    L += [f"* {ln}" for ln in prov_lines]
    L.append("*")
    for ln in tb.get("conditions") or []:
        L.append(f"* condition: {ln.format(**fmt)}")
    L.append(f".include {block}.sp")
    for ln in tb.get("stimulus") or []:
        L.append(ln.format(**fmt))
    ports = []
    for p in ir["ports"]:
        ports.append("0" if p == (ir.get("rails") or {}).get("vss") else p)
    L.append(f"xdut {' '.join(ports)} {block}")
    for ln in tb.get("cards") or []:
        L.append(ln.format(**fmt))
    L.append(".control")
    for ln in tb.get("control") or []:
        L.append(ln.format(**fmt))
    L.append(".endc")
    L.append(".end")
    L.append("")
    return "\n".join(L), e, notes


# ── self-verification ─────────────────────────────────────────────────────
_CHECKERS = (
    ("a3_gate", "analog_a3_netlist_gen_check.py", True),
    ("pdk", "analog_netlist_pdk_check.py", False),
    ("connectivity", "analog_netlist_connectivity_check.py", False),
    ("include_order", "analog_netlist_include_order_check.py", False),
    ("path_lint", "analog_netlist_path_lint.py", False),
)


def verify_with_checkers(block: str, sp_text: str, tb_text: Optional[str]
                         ) -> Tuple[bool, List[Dict[str, Any]]]:
    """Run the real checkers over a staging project holding ONLY this block's
    netlist, so the verdict is about this file and not about whatever else the
    run has left in the tree."""
    findings: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="a3verify_") as td:
        proj = Path(td)
        bdir = proj / _CANONICAL_ANALOG / block
        bdir.mkdir(parents=True, exist_ok=True)
        (proj / _CANONICAL_ANALOG / "analog_block_list.json").write_text(
            json.dumps({"blocks": [{"name": block}]}), encoding="utf-8")
        (bdir / f"{block}.sp").write_text(sp_text, encoding="utf-8")
        if tb_text:
            (bdir / f"tb_{block}.sp").write_text(tb_text, encoding="utf-8")
        ok = True
        for label, prog, per_block in _CHECKERS:
            path = _HERE / prog
            if not path.is_file():
                continue
            cmd = [sys.executable, str(path), str(proj)]
            if per_block:
                cmd += ["--block", block]
            try:
                cp = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=300)
            except (OSError, subprocess.SubprocessError) as exc:
                findings.append({"checker": label, "rc": None,
                                 "detail": f"could not run: {exc}"})
                ok = False
                continue
            if cp.returncode != 0:
                ok = False
                findings.append({
                    "checker": label, "rc": cp.returncode,
                    "detail": ((cp.stderr or cp.stdout or "").strip()
                               [-800:] or "non-zero exit, no output")})
            else:
                findings.append({"checker": label, "rc": 0,
                                 "detail": (cp.stdout or "").strip()[-200:]})
    return ok, findings


def _docker_ok(container: str) -> bool:
    try:
        cp = subprocess.run(["docker", "exec", container, "true"],
                            capture_output=True, text=True, timeout=60)
        return cp.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def verify_with_ngspice(container: str, block: str, sp_text: str,
                        tb_text: str) -> Dict[str, Any]:
    """Run the testbench in the EDA container. An unreachable container is a
    CAPABILITY gap (`NOT_VERIFIED_NO_SIMULATOR`), never a netlist defect."""
    if shutil.which("docker") is None or not _docker_ok(container):
        return {"simulation_verified": False,
                "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                "detail": f"container `{container}` is not reachable"}
    stage = f"/tmp/a3emit_{block}_{int(time.time())}"
    try:
        subprocess.run(["docker", "exec", container, "mkdir", "-p", stage],
                       capture_output=True, text=True, timeout=120)
        with tempfile.TemporaryDirectory(prefix="a3sim_") as td:
            local = Path(td)
            (local / f"{block}.sp").write_text(sp_text, encoding="utf-8")
            (local / f"tb_{block}.sp").write_text(tb_text, encoding="utf-8")
            for f in (f"{block}.sp", f"tb_{block}.sp"):
                subprocess.run(["docker", "cp", str(local / f),
                                f"{container}:{stage}/{f}"],
                               capture_output=True, text=True, timeout=300)
        # `sh -lc` is deliberately NOT used: a login shell sources the EDA
        # image's profile, which was measured to abort with a syntax error
        # under dash and swallow the probe's answer, so every block came back
        # NOT_VERIFIED_NO_SIMULATOR on a container that had ngspice.
        ng = None
        for cand in ("ngspice", "/foss/tools/bin/ngspice"):
            probe = subprocess.run(
                ["docker", "exec", container, "sh", "-c",
                 f"command -v {cand} >/dev/null 2>&1 && echo yes || echo no"],
                capture_output=True, text=True, timeout=120)
            if "yes" in (probe.stdout or ""):
                ng = cand
                break
        if ng is None:
            return {"simulation_verified": False,
                    "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                    "detail": "no ngspice in the container"}
        cp = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             f"cd {stage} && {ng} -b tb_{block}.sp 2>&1"],
            capture_output=True, text=True, timeout=900)
        out = (cp.stdout or "") + (cp.stderr or "")
        tail = out.strip().splitlines()[-25:]
        bad = ("doAnalyses: iteration limit reached" in out
               or "singular matrix" in out.lower()
               or "Too few parameters" in out
               or "aborted" in out.lower()
               or "MEAS" not in out)
        meas = [ln.strip() for ln in out.splitlines() if "MEAS" in ln]
        return {
            "simulation_verified": (cp.returncode == 0 and not bad),
            "simulation_status": ("CONVERGED" if (cp.returncode == 0 and
                                                  not bad)
                                  else "DID_NOT_CONVERGE"),
            "ngspice_rc": cp.returncode,
            "measurements": meas,
            "log_tail": tail,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"simulation_verified": False,
                "simulation_status": "NOT_VERIFIED_NO_SIMULATOR",
                "detail": f"container invocation failed: {exc}"}
    finally:
        try:
            subprocess.run(["docker", "exec", container, "rm", "-rf", stage],
                           capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            pass


# ── gap artefact ──────────────────────────────────────────────────────────
def write_gap(bdir: Path, project: Path, block: str, btype: str, status: str,
              reason: str, **extra) -> Path:
    body = {
        "block": block,
        "block_type": btype,
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "produced_at": _now(),
            "fields_bound": [],
            "fields_defaulted": [],
            "defaults_used": False,
        },
        "status": status,
        "netlist_written": False,
        "reason": reason,
        "ai_handoff": {
            "track": "skill",
            "skill": SKILL,
            "required_output": f"{_CANONICAL_ANALOG}/{block}/{block}.sp",
            "reason": reason,
        },
    }
    body.update(extra)
    bdir.mkdir(parents=True, exist_ok=True)
    p = bdir / "netlist_gap.json"
    p.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def _drop_stale(bdir: Path, block: str) -> List[str]:
    """Remove artefacts a PREVIOUS run of this producer left behind whose
    inputs no longer support them. Another author's file is never touched."""
    dropped = []
    for name in (f"{block}.sp", f"tb_{block}.sp", "netlist_provenance.json"):
        p = bdir / name
        if not p.is_file():
            continue
        try:
            if PRODUCER in p.read_text(encoding="utf-8", errors="replace"):
                p.unlink()
                dropped.append(name)
        except OSError:
            pass
    return dropped


# ── per-block driver ──────────────────────────────────────────────────────
def emit_for_block(project: Path, entry: Dict[str, Any], pdk: str,
                   container: str, verify_sim: bool) -> Dict[str, Any]:
    name = str(entry.get("name") or entry.get("block") or entry.get("type"))
    bdir = project / _CANONICAL_ANALOG / name
    sp_path = bdir / f"{name}.sp"
    rec: Dict[str, Any] = {"block": name}

    if sp_path.is_file():
        text = sp_path.read_text(encoding="utf-8", errors="replace")
        if PRODUCER not in text:
            rec.update(action="kept_preexisting", emitted=False,
                       netlist=str(sp_path.relative_to(project)))
            return rec

    ir_path = bdir / "topology.json"
    ir = _read_json(ir_path) if ir_path.is_file() else None
    btype = str((ir or {}).get("block_type")
                or entry.get("type") or "unknown")
    if not isinstance(ir, dict):
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "NO_TOPOLOGY_IR",
                        ("no `topology.json` for this block: the A2 producer "
                         "either has no library entry for its circuit class "
                         "or has not run. A3 renders SPICE from the A2 IR and "
                         "carries no per-type template of its own, so there "
                         "is nothing to render."),
                        expected_input=f"{_CANONICAL_ANALOG}/{name}/topology.json")
        rec.update(action="gap", emitted=False, status="NO_TOPOLOGY_IR",
                   gap_path=str(gap.relative_to(project)))
        return rec

    spec_path = bdir / "spec.json"
    spec = _read_json(spec_path) if spec_path.is_file() else None
    if not isinstance(spec, dict) or not spec_values(spec):
        # ── THE CONTROL. The library could render this block's circuit class
        # right now. Doing so would produce a template with the design's block
        # name substituted into it: it would pass all five gates, it would
        # simulate, and every number it produced would be about the template.
        dropped = _drop_stale(bdir, name)
        gap = write_gap(
            bdir, project, name, btype, "NO_SPEC_NO_NETLIST",
            ("no A1 spec is bound for this block, so no design number can "
             "enter its netlist. The topology library COULD render its "
             "circuit class — and that netlist would be a template with this "
             "block's name substituted into it, indistinguishable to every "
             "downstream gate from a designed one. It is deliberately not "
             "emitted."),
            expected_input=f"{_CANONICAL_ANALOG}/{name}/spec.json",
            topology_available=True,
            topology=ir.get("topology"),
            stale_artefacts_removed=dropped,
            unblocked_by=("an A1 spec for this block — from "
                          "`analog_a1_spec_emit` when the documents attribute "
                          "one, or from skill `analog-spec-extract` when they "
                          "do not"))
        rec.update(action="gap", emitted=False, status="NO_SPEC_NO_NETLIST",
                   gap_path=str(gap.relative_to(project)))
        return rec

    sv = spec_values(spec)
    roles = sorted({d["role"] for d in ir.get("devices") or []})
    pdkctx = resolve_pdk_context(project, pdk, container, roles)
    if pdkctx["status"] != "OK":
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "NEEDS_NATIVE_TEMPLATE",
                        ("the declared PDK target resolves to a family whose "
                         "deck context is incomplete; emitting one foundry's "
                         "device tokens against another's model library is "
                         "forbidden"),
                        deck_context=pdkctx.get("deck_context"),
                        work_items=pdkctx.get("work_items"))
        rec.update(action="gap", emitted=False,
                   status="NEEDS_NATIVE_TEMPLATE",
                   gap_path=str(gap.relative_to(project)))
        return rec

    problems = _validate_ir(ir, pdkctx)
    if problems:
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "IR_NOT_RENDERABLE",
                        ("the topology IR cannot be rendered into a netlist "
                         "that the shipped netlist checkers would accept"),
                        problems=problems)
        rec.update(action="gap", emitted=False, status="IR_NOT_RENDERABLE",
                   gap_path=str(gap.relative_to(project)), problems=problems)
        return rec

    overrides, spec_bound, nominal, env = _resolve_params(ir, sv)
    # ONE word a reader does not have to reconstruct from two lists. The
    # structure always follows from the block's circuit class; whether any
    # bound spec value reached the DEVICES is the question that separates a
    # designed netlist from a class netlist carrying a design's name, and it
    # must be answerable without inference.
    design_content = ("structure_and_geometry" if spec_bound
                      else "structure_only")
    ir_prov = ir.get("_provenance") or {}
    defaulted = list(ir_prov.get("fields_defaulted") or [])
    handoff = ir_prov.get("ai_handoff")
    if nominal and not handoff:
        # Any device parameter the bound spec did not reach is unsolved
        # SIZING. That is judgment the deterministic track does not do, so the
        # artefact has to name who does — otherwise a netlist that simulates
        # reads as a netlist that was designed.
        handoff = {
            "track": "skill",
            "skill": "analog-sizing",
            "reason": (
                f"{len(nominal)} device parameter(s) carry the topology "
                f"library's nominal value because no bound spec value "
                f"determines them; solving them against the spec is sizing "
                f"judgment"),
            "scope": "device_geometry",
            "unsized_params": nominal,
        }

    prov_lines = [
        f"_provenance: producer={PRODUCER} schema={PROVENANCE_SCHEMA}",
        f"_provenance: produced_at={_now()}",
        f"_provenance: topology_ir={_CANONICAL_ANALOG}/{name}/topology.json "
        f"sha256={_sha256(ir_path)}",
        f"_provenance: spec={_CANONICAL_ANALOG}/{name}/spec.json "
        f"sha256={_sha256(spec_path)}",
        f"_provenance: spec_values_bound={sorted(sv.keys())}",
        f"_provenance: design_content={design_content}",
        f"_provenance: spec_bound_params={spec_bound or 'none'}",
        f"_provenance: library_nominal_params={nominal or 'none'}",
        f"_provenance: knobs_defaulted_by_library={defaulted or 'none'}",
        f"_provenance: pdk_family={pdkctx.get('registry_family') or pdkctx.get('family')}",
        f"_provenance: model_lib={pdkctx.get('model_lib')} "
        f"section={pdkctx.get('typ_section')}",
        f"_provenance: role_models={pdkctx.get('role_models')}",
    ]
    if handoff:
        prov_lines.append(
            f"_provenance: ai_handoff=skill:{handoff.get('skill')} "
            f"reason={handoff.get('reason')}")
    else:
        prov_lines.append("_provenance: ai_handoff=none")
    prov_lines.append(
        "_provenance: device geometry above is the topology library nominal "
        "EXCEPT the spec_bound_params listed; sizing to the bound spec is "
        "skill `analog-sizing`, not this producer")

    sp_text = render_netlist(ir, pdkctx, prov_lines, overrides)
    tb_text, tb_env, tb_notes = render_testbench(ir, pdkctx, env, prov_lines)

    ok, findings = verify_with_checkers(name, sp_text, tb_text)
    if not ok:
        _drop_stale(bdir, name)
        gap = write_gap(bdir, project, name, btype, "NETLIST_REJECTED_BY_CHECKS",
                        ("the rendered netlist does not pass the shipped "
                         "netlist checkers, so it was not emitted: a netlist "
                         "that cannot pass the checks that exist is worse "
                         "than an absent one, which is honestly WAIVED"),
                        checker_findings=findings)
        rec.update(action="gap", emitted=False,
                   status="NETLIST_REJECTED_BY_CHECKS",
                   gap_path=str(gap.relative_to(project)),
                   checker_findings=findings)
        return rec

    sim: Dict[str, Any] = {"simulation_verified": False,
                           "simulation_status": "NOT_ATTEMPTED"}
    if verify_sim and tb_text:
        sim = verify_with_ngspice(container, name, sp_text, tb_text)
        if sim.get("simulation_status") == "DID_NOT_CONVERGE":
            _drop_stale(bdir, name)
            gap = write_gap(bdir, project, name, btype,
                            "NETLIST_NOT_SIMULATABLE",
                            ("the rendered netlist passed every static check "
                             "and did not converge in the simulator, so it "
                             "was not emitted"),
                            checker_findings=findings, simulation=sim)
            rec.update(action="gap", emitted=False,
                       status="NETLIST_NOT_SIMULATABLE",
                       gap_path=str(gap.relative_to(project)))
            return rec
    elif verify_sim and not tb_text:
        sim = {"simulation_verified": False,
               "simulation_status": "NOT_VERIFIED_NO_TESTBENCH",
               "detail": "; ".join(tb_notes)}

    sp_text = sp_text.replace(
        f"* _provenance: ai_handoff",
        f"* _provenance: simulation_verified={sim.get('simulation_verified')}"
        f" status={sim.get('simulation_status')}"
        f"\n* _provenance: ai_handoff", 1)

    bdir.mkdir(parents=True, exist_ok=True)
    sp_path.write_text(sp_text, encoding="utf-8")
    if tb_text:
        (bdir / f"tb_{name}.sp").write_text(tb_text, encoding="utf-8")
    sidecar = {
        "block": name,
        "block_type": btype,
        "_provenance": {
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "produced_at": _now(),
            "rendered_from": {
                "topology_json": {
                    "path": f"{_CANONICAL_ANALOG}/{name}/topology.json",
                    "sha256": _sha256(ir_path)},
                "spec_json": {
                    "path": f"{_CANONICAL_ANALOG}/{name}/spec.json",
                    "sha256": _sha256(spec_path)},
            },
            "has_own_netlist_template": False,
            "design_content": design_content,
            "design_content_meaning": (
                "structure_and_geometry — at least one device parameter was "
                "solved against a bound spec value"
                if spec_bound else
                "structure_only — the circuit class came from the topology "
                "library and NO bound spec value reached any device "
                "parameter; the geometry below is a library nominal. The "
                "netlist exists because a spec IS bound for this block (see "
                "fields_bound), but it is not sized to it."),
            "fields_bound": sorted(sv.keys()),
            "fields_defaulted": defaulted,
            "defaults_used": bool(defaulted),
            "spec_bound_params": spec_bound,
            "library_nominal_params": nominal,
            "ai_handoff": handoff,
            "limits": (
                "the STRUCTURE is the topology library's circuit class and "
                "the bound spec values entered only the parameters listed in "
                "spec_bound_params; every other geometry is a library "
                "nominal, not a solution of this design's spec."),
        },
        "pdk": {k: pdkctx[k] for k in
                ("family", "registry_family", "model_lib", "typ_section",
                 "corner_sections", "role_models")},
        "testbench": {"path": (f"tb_{name}.sp" if tb_text else None),
                      "conditions": tb_notes},
        "verification": {"checkers": findings, "simulation": sim},
        "outputs": [f"{name}.sp"] + ([f"tb_{name}.sp"] if tb_text else []),
    }
    (bdir / "netlist_provenance.json").write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    gapf = bdir / "netlist_gap.json"
    if gapf.is_file():
        gapf.unlink()
    rec.update(action="emitted", emitted=True,
               netlist=str(sp_path.relative_to(project)),
               testbench=(f"tb_{name}.sp" if tb_text else None),
               spec_bound_params=spec_bound,
               simulation_status=sim.get("simulation_status"))
    return rec


def run(project: Path, only: Optional[str], pdk: str, container: str,
        verify_sim: bool) -> Tuple[int, Dict[str, Any]]:
    entries, src = block_entries(project)
    if not entries:
        return 1, {"producer": PRODUCER, "verdict": "NO_INPUT",
                   "reason": "no analog block list and no L5 analog_blocks[]",
                   "records": []}
    if only:
        entries = [e for e in entries
                   if (e.get("name") or e.get("block") or e.get("type"))
                   == only]
        if not entries:
            return 1, {"producer": PRODUCER, "verdict": "NO_SUCH_BLOCK",
                       "reason": f"block `{only}` is not declared in {src}",
                       "records": []}
    records = [emit_for_block(project, e, pdk, container, verify_sim)
               for e in entries]
    emitted = [r for r in records if r.get("emitted")]
    kept = [r for r in records if r.get("action") == "kept_preexisting"]
    gaps = [r for r in records if r.get("action") == "gap"]
    report = {
        "producer": PRODUCER,
        "block_list_source": src,
        "verdict": "EMITTED" if (emitted or kept) else "ALL_GAP",
        "blocks_total": len(records),
        "blocks_emitted": len(emitted),
        "blocks_kept_preexisting": len(kept),
        "blocks_gap": len(gaps),
        "gap_status": {r["block"]: r.get("status") for r in gaps},
        "ai_handoff_blocks": [r["block"] for r in gaps],
        "suggested_skill": SKILL if gaps else None,
        "records": records,
    }
    return (0 if (emitted or kept) else 2), report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=PRODUCER, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", default=None)
    ap.add_argument("--pdk", default=os.environ.get("VIBEIC_ANALOG_PDK",
                                                    "sky130"))
    ap.add_argument("--container", default=DEFAULT_CONTAINER)
    ap.add_argument("--verify-sim", action="store_true",
                    help="additionally run the generated testbench through "
                         "ngspice in the EDA container; a deck that does not "
                         "converge is not emitted")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 1
    rc, report = run(project, args.block, args.pdk, args.container,
                     args.verify_sim)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    if rc == 0:
        print(f"{PRODUCER}: {report['blocks_emitted']} netlist(s) emitted "
              f"and verified, {report['blocks_gap']} honest gap(s) "
              f"(hand off to `{SKILL}`)")
    elif rc == 2:
        print(f"{PRODUCER}: NO netlist emitted — "
              f"{report['blocks_gap']} netlist_gap.json written "
              f"({report['gap_status']}); invoke skill `{SKILL}`",
              file=sys.stderr)
    else:
        print(f"{PRODUCER}: {report.get('verdict')} — "
              f"{report.get('reason')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
