#!/usr/bin/env python3
"""analog_a7_post_layout_emit.py — the deterministic A7 producer.

A7 (post-layout resimulation) had no producer: the runner WAIVED it to the
`analog-extraction-resim` skill, which hand-built a Magic RC recipe
(`magic_extract_spice_emit.build_extraction_tcl`). The tool does that job, so
the tool does it here:

  1. EXTRACT with LibreLane `Magic.RCX` (`python3 -m librelane.steps run`,
     through `librelane_contract.run_chain`) on the A5 GDS — one run per
     `ngspice` extraction style the A5 layout's OWN Magic technology declares
     (`extract / style ngspice variants (...)`), the device-only `lvs` variant
     excluded because it extracts no parasitics.
  2. AUDIT what Magic wrote with `magic_extract_spice_emit
     .audit_extracted_netlist`: 0 R and 0 C is refused (a re-simulation of it
     is the pre-layout circuit again, a false 0 % degradation); the depth
     achieved (RC / C_ONLY) is recorded.
  3. RESIMULATE with A4's own machinery (`analog_real_corner_sweep
     ._run_ngspice`): the block's A3 testbench, once as delivered (pre) and
     once with the extracted netlist behind a wrapper subcircuit that keeps
     the A3 port order (post), in the same container. The transient stops at
     the end of the last window a `meas` card reads, plus one sample clock
     (`measurement_span`), and every simulation records the SAME planning
     budget (`simulation_budget`). A stopped run is NOT_MEASURED with the
     time it reached; budget exhaustion requires proof of enforcement (T130).
  4. WRITE `phase3/analog/<block>/pre_vs_post.json` — one spec row per
     measurement per extraction style — naming the extracted netlist as its
     post-layout evidence. The A7 gate owns the verdict.

WHAT THE PRODUCER GUARANTEES BEYOND "IT RAN" (q7, T109):
  * NON-INTERFERENCE. Its working decks live in its own area,
    `phase3/librelane/analog/<block>/a7_resim/`, never under
    `phase3/analog/<block>/`: A3's gates rglob `phase3/analog` for `*.sp`,
    and 11 resimulation decks there grew one gate's population 13 -> 24 and
    flipped another to FAIL. Only `pre_vs_post.json` and
    `a7_post_layout.json` are written beside the block.
  * NO SILENT DROP. The extracted body sits one level down (`xrcx`) in the
    wrapper, so a testbench probe `v(<dut>.<n>)` of an internal net is
    rewritten to `v(<dut>.xrcx.<n>)` when `<n>` is a net of that style's
    extracted netlist (to the wrapper's node when `<n>` is one of the
    extracted subcircuit's ports). A probe whose net is ABSENT after
    extraction is taken out of the post deck and its measurement listed in
    `not_compared` with the reason. Any other measurement the pre run had and
    the post run lacks refuses `A7_POST_MEASUREMENT_MISSING`.
  * DEVICE INVENTORY. Each style's extracted PDK devices must equal the A3
    netlist's: for a model the layout's Magic technology declares a
    `mosfet`/`msubcircuit` device, the sum of w*m per (model, l) (Magic may
    split fingers); for every other model the (model, w, l) multiset with m
    expanded. A difference refuses `A7_RCX_DEVICE_INVENTORY_MISMATCH` — a
    resimulation of a circuit that lost or gained a device is not a
    post-layout measurement of this one.

Nothing here grades, and nothing here invents a value: the PDK and the Magic
technology come from A5's `layout_provenance.json` (the technology the layout
was drawn with), the ports and model binding from the A3 netlist, the stimulus
from the A3 testbench.

Opt-in: the analog runner calls this producer only when
`phase3/librelane_switch.json` selects `librelane` (or `dual`) for step `A7`.

Exit codes: 0 written; 1 the tool ran and its product is refused (named in
`a7_post_layout.json`); 2 honest gap (an upstream artefact this step reads is
absent); 69 environment refusal (the tool could not be reached); 75 a
simulation stopped before measurement (NOT_MEASURED; reason from evidence).
chip-AGNOSTIC.
"""
from __future__ import annotations

import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _analog_producer_common as _pc
from _analog_producer_common import layout_netlist_identity  # noqa: E402,F401
from _atomic_artefact import write_json, write_text
import _watchdog as wd
import step_metrics

PRODUCER = "analog_a7_post_layout_emit"
STEP = "A7"
RCX_STEP = "Magic.RCX"
#: The extraction variant that is device-only by Magic's own convention: it
#: carries no parasitic corner, so it is not an RCX corner.
_DEVICE_ONLY_VARIANT = "lvs"

_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)\s*(.*)$", re.I)
_STYLE_RE = re.compile(r"^\s*style\s+(\S+)(?:\s+variants\s+(.*))?$")
_INCLUDE_RE = re.compile(r"^\s*include\s+(\S+)\s*$")
_LIB_RE = re.compile(r"^(\s*\.(?:lib|include|inc)\s+)(\S+)(.*)$", re.I)


# ── pure helpers (tested directly) ─────────────────────────────────────────
def _joined_lines(text: str) -> List[str]:
    """SPICE continuation lines (`+`) joined onto their predecessor."""
    out: List[str] = []
    for raw in text.splitlines():
        if raw.startswith("+") and out:
            out[-1] += " " + raw[1:].strip()
        else:
            out.append(raw)
    return out


def _tech_text(tech: Path) -> str:
    """The technology file with its `include`s spliced in, relative to it."""
    seen: set = set()

    def read(path: Path) -> str:
        if path in seen or not path.is_file():
            return ""
        seen.add(path)
        parts = []
        for line in path.read_text(errors="replace").splitlines():
            m = _INCLUDE_RE.match(line)
            if m:
                name = m.group(1)
                cand = path.parent / name
                if not cand.suffix:
                    cand = cand.with_suffix(".tech")
                parts.append(read(cand))
            else:
                parts.append(line)
        return "\n".join(parts)
    return read(tech)


def extraction_styles(tech: Path) -> List[str]:
    """The `ngspice` extraction styles the technology declares, in its order.

    Read from the `extract` section only; `style ngspice variants (),(x)`
    yields `ngspice()`, `ngspice(x)`. The device-only variant is excluded.
    An absent or unreadable technology yields [] (the caller refuses).
    """
    styles: List[str] = []
    section = None
    for line in _tech_text(tech).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if section is None and re.fullmatch(r"[A-Za-z_]\w*", s):
            section = s
            continue
        if s == "end":
            section = None
            continue
        if section != "extract":
            continue
        m = _STYLE_RE.match(s)
        if not m or not m.group(1).startswith("ngspice"):
            continue
        base = m.group(1)
        if m.group(2):
            for v in re.findall(r"\(([^)]*)\)", m.group(2)):
                if v.strip() != _DEVICE_ONLY_VARIANT:
                    styles.append(f"{base}({v.strip()})")
        elif base not in styles:
            styles.append(base)
    return styles


def subckt_ports(text: str, name: str) -> Optional[List[str]]:
    for line in _joined_lines(text):
        m = _SUBCKT_RE.match(line)
        if m and m.group(1) == name:
            return [t for t in m.group(2).split() if "=" not in t]
    return None


def model_binding_lines(netlist_text: str, netlist_dir: Path,
                        new_dir: Path) -> List[str]:
    """The netlist's own `.lib`/`.include` cards before its first `.subckt`,
    with every RELATIVE target re-expressed relative to `new_dir` (ngspice
    resolves a relative target against the including file's directory)."""
    out: List[str] = []
    for line in _joined_lines(netlist_text):
        if _SUBCKT_RE.match(line):
            break
        m = _LIB_RE.match(line)
        if not m:
            continue
        target = m.group(2).strip("'\"")
        if not os.path.isabs(target):
            target = os.path.relpath((netlist_dir / target).resolve(), new_dir)
        out.append(f"{m.group(1)}{target}{m.group(3)}")
    return out


def post_layout_netlist(block: str, ports: List[str], rcx_text: str,
                        binding: List[str]) -> Tuple[str, Dict[str, str]]:
    """The extracted netlist behind a wrapper with the A3 port order.

    The extracted subcircuit is renamed `<block>__rcx`. Each of its ports that
    IS a declared port name connects to that port; every other port (a split
    node Magic exported) becomes a node private to the wrapper, so no
    extracted resistance is shorted out. A declared port the extraction does
    not expose is refused: the circuit could not be driven as A3 drives it.
    """
    lines = _joined_lines(rcx_text)
    rcx_ports = None
    body: List[str] = []
    for line in lines:
        m = _SUBCKT_RE.match(line)
        if m and m.group(1) == block and rcx_ports is None:
            rcx_ports = m.group(2).split()
            body.append(f".subckt {block}__rcx {' '.join(rcx_ports)}")
            continue
        body.append(line)
    if rcx_ports is None:
        raise ValueError(f"A7_RCX_NO_SUBCKT: the extracted netlist defines no "
                         f".subckt {block}")
    missing = [p for p in ports if p not in rcx_ports]
    if missing:
        raise ValueError(f"A7_RCX_PORT_MISSING: declared port(s) {missing} are "
                         f"not ports of the extracted .subckt {block}")
    mapping: Dict[str, str] = {}
    conn = []
    for i, p in enumerate(rcx_ports):
        node = p if p in ports else f"rcx_int_{i}"
        mapping[p] = node
        conn.append(node)
    text = "\n".join(
        [f"* post-layout netlist for {block}: LibreLane {RCX_STEP} output "
         f"behind a wrapper with the A3 port order ({PRODUCER})"]
        + binding + [""] + body + [""]
        + [f".subckt {block} {' '.join(ports)}",
           f"xrcx {' '.join(conn)} {block}__rcx", f".ends {block}", ""])
    return text, mapping


def post_layout_testbench(tb_text: str, block: str, post_name: Optional[str],
                          tb_dir: Path, new_dir: Path) -> str:
    """The A3 testbench relocated to `new_dir`, with its one include of
    `<block>.sp` pointed at `post_name` (the post-layout netlist) — or, when
    `post_name` is None, at the delivered netlist itself (the pre-layout run,
    kept out of the block directory other readers glob). Every other relative
    card is re-expressed for `new_dir`. Refused unless the block netlist is
    included exactly once."""
    hits = 0
    out = []
    for line in tb_text.splitlines():
        m = _LIB_RE.match(line)
        if m:
            target = m.group(2).strip("'\"")
            if Path(target).name == f"{block}.sp":
                hits += 1
                if post_name is None:
                    post_name = os.path.relpath(
                        (tb_dir / target).resolve(), new_dir)
                out.append(f"{m.group(1)}{post_name}{m.group(3)}")
                continue
            if not os.path.isabs(target):
                target = os.path.relpath((tb_dir / target).resolve(), new_dir)
            out.append(f"{m.group(1)}{target}{m.group(3)}")
            continue
        out.append(line)
    if hits != 1:
        raise ValueError(f"A7_TB_INCLUDE_AMBIGUOUS: the A3 testbench includes "
                         f"{block}.sp {hits} time(s); exactly one is required")
    return "\n".join(out) + "\n"


def compare(pre: Dict[str, Optional[float]], post: Dict[str, Optional[float]],
            style: str, not_compared: Optional[Dict[str, str]] = None,
            missing: Optional[List[str]] = None,
            rail_supply_v: Optional[float] = None,
            rail_margin_fraction: Optional[float] = None) -> List[dict]:
    """One row per measurement both runs produced. NOTHING IS DROPPED
    SILENTLY: a measurement with no pre-layout value, or taken out of the post
    deck because its net is absent after extraction (`not_compared` on the
    way in), is written to `not_compared` with its reason; one the post run
    lacks for any other reason is appended to `missing` — the caller refuses
    on it."""
    rows = []
    skipped = not_compared if not_compared is not None else {}
    lost = missing if missing is not None else []
    for name in sorted(pre):
        a = pre[name]
        b = post.get(name)
        if a is None:
            skipped[name] = "no pre-layout value (the A3 testbench's own " \
                            "run did not produce it)"
            continue
        if name in skipped:
            continue
        if b is None:
            lost.append(name)
            continue
        row = {"name": f"{name}@{style}", "metric": name, "extraction_style": style,
               "pre_value": a, "post_value": b}
        if re.match(r"^railx_(?:min|max)_", name, re.I) and \
                rail_supply_v and rail_margin_fraction:
            # A rail extremum near ground has no useful relative denominator.
            # Measure its absolute voltage movement against the supply and
            # the same declared rail margin used by A3's transient check.
            margin_v = rail_supply_v * rail_margin_fraction
            row["delta_pct"] = 100.0 * (b - a) / margin_v
            row["comparison_basis"] = "absolute_voltage_over_supply_margin"
            row["rail_supply_v"] = rail_supply_v
            row["rail_margin_v"] = margin_v
            row["rail_reference_v"] = margin_v
            row["rail_delta_v"] = b - a
        elif a == 0 and b == 0:
            row["delta_pct"] = 0.0
        elif a != 0:
            row["delta_pct"] = 100.0 * (b - a) / abs(a)
        rows.append(row)
    return rows


def rail_reference_voltage(tb_text: str) -> Optional[float]:
    """Read the positive supply A3 actually drives, including its PWL ramp."""
    for line in _joined_lines(tb_text):
        fields = line.strip().split(None, 3)
        if len(fields) != 4 or fields[0].lower() != "v_vdd" \
                or fields[2] != "0":
            continue
        source = fields[3].strip()
        if source.lower().startswith("pwl(") and source.endswith(")"):
            values = source[4:-1].replace(",", " ").split()
            volts = [spice_number(values[i]) for i in range(1, len(values), 2)]
            positive = [v for v in volts if v is not None and v > 0]
            return max(positive) if positive else None
        value = spice_number(source)
        return value if value is not None and value > 0 else None
    return None


def _declared_rail_reference(tb_text: str) -> tuple[Optional[float], Optional[float]]:
    """Pair A3's driven supply with its declared transient rail margin."""
    supply_v = rail_reference_voltage(tb_text)
    if supply_v is None:
        return None, None
    import analog_a3_netlist_emit as a3
    fraction = float(a3.TRAN_RAIL_MARGIN_FRACTION)
    if not math.isfinite(fraction) or fraction <= 0:
        return None, None
    return supply_v, fraction


#: SPICE magnitude suffixes, longest first (`meg` before `m`).
_SPICE_SCALE = (("meg", 1e6), ("mil", 25.4e-6), ("t", 1e12), ("g", 1e9),
                ("k", 1e3), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9),
                ("p", 1e-12), ("f", 1e-15), ("a", 1e-18))
_NUM_RE = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)([a-z]*)$",
                     re.I)


def spice_number(text: str) -> Optional[float]:
    """A SPICE value (`115.384u`, `0.11538m`, `2e-6`) as a float, or None."""
    m = _NUM_RE.match((text or "").strip().strip("'\""))
    if not m:
        return None
    val, suf = float(m.group(1)), m.group(2).lower()
    for s, k in _SPICE_SCALE:
        if suf.startswith(s):
            return val * k
    return val


def _subckt_body(text: str, name: str) -> Optional[List[str]]:
    body: Optional[List[str]] = None
    for line in _joined_lines(text):
        m = _SUBCKT_RE.match(line)
        if m and body is None and m.group(1) == name:
            body = []
            continue
        if body is not None:
            if re.match(r"^\s*\.ends\b", line, re.I):
                return body
            body.append(line)
    return body


def device_instances(text: str, name: str) -> List[dict]:
    """Every PDK-device instance (an `X` card whose model is not a subcircuit
    of the same file) in `.subckt name`: `{model, w, l, m}` in SI units."""
    defined = {m.group(1).lower() for m in
               (_SUBCKT_RE.match(ln) for ln in _joined_lines(text)) if m}
    out: List[dict] = []
    for line in _subckt_body(text, name) or []:
        toks = line.split()
        if not toks or toks[0][0] not in "xX":
            continue
        pos = [t for t in toks[1:] if "=" not in t]
        if not pos or pos[-1].lower() in defined:
            continue
        params = {k.lower(): v for k, v in
                  (t.split("=", 1) for t in toks[1:] if "=" in t)}
        out.append({"model": pos[-1].lower(),
                    "w": spice_number(params.get("w", "")),
                    "l": spice_number(params.get("l", "")),
                    "m": spice_number(params.get("m", "1")) or 1.0})
    return out


def summed_device_models(tech_text: str) -> set:
    """Models the Magic technology extracts as MOS devices (`device mosfet`
    or `device msubcircuit`): their fingers may be split, so their width is
    compared as a sum. Read from the technology's own `extract` section."""
    out = set()
    for line in (tech_text or "").splitlines():
        t = line.split()
        if len(t) >= 3 and t[0] == "device" and t[1] in ("mosfet",
                                                          "msubcircuit"):
            out.add(t[2].lower())
    return out


def _close(a: Optional[float], b: Optional[float], rel: float = 1e-3,
           abs_tol: float = 0.0) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(rel * max(abs(a), abs(b), 1e-30), abs_tol)


def device_inventory(a3: List[dict], rcx: List[dict], summed: set,
                     *, layout_grid_m: float = 0.0) -> dict:
    """Compare two device inventories (see the module docstring). Values are
    matched with a 1e-3 relative tolerance: Magic writes 5 significant
    digits (`115.384u` comes back `0.11538m`). For non-summed devices, A5's
    attested Magic layout grid also permits at most half a grid of drawing
    snap. No grid is inferred when A5 did not attest one."""
    if not math.isfinite(layout_grid_m) or layout_grid_m < 0:
        raise ValueError("layout_grid_m must be a finite nonnegative length")
    snap_tol = layout_grid_m / 2 + (1e-15 if layout_grid_m else 0.0)
    diffs: List[str] = []
    models = sorted({d["model"] for d in a3} | {d["model"] for d in rcx})
    for model in models:
        mine = [d for d in a3 if d["model"] == model]
        theirs = [d for d in rcx if d["model"] == model]
        if model in summed:
            def by_l(devs):
                acc: List[List[float]] = []
                for d in devs:
                    wm = (d["w"] or 0.0) * d["m"]
                    for row in acc:
                        if _close(row[0], d["l"]):
                            row[1] += wm
                            break
                    else:
                        acc.append([d["l"], wm])
                return sorted(acc, key=lambda r: (r[0] is None, r[0] or 0))
            x, y = by_l(mine), by_l(theirs)
            if len(x) != len(y) or not all(
                    _close(p[0], q[0]) and _close(p[1], q[1])
                    for p, q in zip(x, y)):
                diffs.append(f"{model}: sum(w*m) per l A3={x} extracted={y}")
        else:
            def expand(devs):
                return sorted(((d["w"] or 0.0), (d["l"] or 0.0))
                              for d in devs for _ in range(int(round(d["m"]))))
            x, y = expand(mine), expand(theirs)
            if len(x) != len(y) or not all(
                    _close(p[0], q[0], abs_tol=snap_tol)
                    and _close(p[1], q[1], abs_tol=snap_tol)
                    for p, q in zip(x, y)):
                diffs.append(f"{model}: (w, l) multiset A3={len(x)} "
                             f"extracted={len(y)} device(s) differ")
    out = {"result": "MISMATCH" if diffs else "MATCH",
           "a3_devices": len(a3), "extracted_devices": len(rcx),
           "summed_models": sorted(summed & set(models)),
           "differences": diffs}
    if layout_grid_m:
        out["layout_grid_um"] = layout_grid_m * 1e6
        out["maximum_grid_snap_um"] = snap_tol * 1e6
    return out


def rcx_nets(rcx_text: str, block: str) -> Tuple[set, set]:
    """(ports, internal nets) of the extracted `.subckt block`, lower-cased."""
    ports: set = set()
    nets: set = set()
    for line in _joined_lines(rcx_text):
        m = _SUBCKT_RE.match(line)
        if m and m.group(1) == block:
            ports = {t.lower() for t in m.group(2).split() if "=" not in t}
            break
    for line in _subckt_body(rcx_text, block) or []:
        toks = line.split()
        if not toks or toks[0][0] in "*.+":
            continue
        kind = toks[0][0].lower()
        pos = [t for t in toks[1:] if "=" not in t]
        if kind == "x":
            nets.update(t.lower() for t in pos[:-1])
        elif kind in "rcl":
            nets.update(t.lower() for t in pos[:2])
        elif kind in "mdq":
            nets.update(t.lower() for t in pos[:-1])
    return ports, nets - ports


def dut_instances(tb_text: str, block: str) -> List[str]:
    """Instance names of `block` in a testbench, lower-cased."""
    out = []
    for line in _joined_lines(tb_text):
        toks = line.split()
        if toks and toks[0][0] in "xX":
            pos = [t for t in toks[1:] if "=" not in t]
            if pos and pos[-1] == block:
                out.append(toks[0].lower())
    return out


_PROBE_RE = re.compile(r"\bv\(\s*([A-Za-z_][\w]*)\.([^\s,()]+)\s*\)", re.I)
_MEAS_NAME_RE = re.compile(r"^\s*\.?meas(?:ure)?\s+\w+\s+(\w+)", re.I)
_LET_RE = re.compile(r"^\s*let\s+(\w+)\s*=(.*)$", re.I)
_ECHO_VAR_RE = re.compile(r"\$&(\w+)")


def remap_probes(tb_text: str, block: str, ports: set, internal: set,
                 mapping: Dict[str, str]) -> Tuple[str, Dict[str, str]]:
    """The post-layout testbench's internal-node probes, pointed into the
    extracted body. Returns (text, {measurement: reason}) where the second
    maps every measurement taken out because its net is absent."""
    duts = set(dut_instances(tb_text, block))
    low_map = {k.lower(): v for k, v in mapping.items()}
    absent: set = set()

    def sub(m: "re.Match") -> str:
        inst, node = m.group(1), m.group(2)
        if inst.lower() not in duts:
            return m.group(0)
        n = node.lower()
        if n in low_map and n in ports:
            return f"v({inst}.{low_map[n]})"
        if n in internal:
            return f"v({inst}.xrcx.{node})"
        absent.add(f"{inst.lower()}.{n}")
        return m.group(0)

    dropped: Dict[str, str] = {}
    out: List[str] = []
    for line in tb_text.splitlines():
        new = _PROBE_RE.sub(sub, line)
        gone = [f"{mm.group(1).lower()}.{mm.group(2).lower()}"
                for mm in _PROBE_RE.finditer(line)
                if f"{mm.group(1).lower()}.{mm.group(2).lower()}" in absent]
        low = line.strip().lower()
        if gone and low.startswith(".save"):
            keep = [t for t in new.split()[1:]
                    if not any(g in t.lower() for g in gone)]
            new = ".save " + " ".join(keep) if keep else "* " + line
        elif gone:
            mm = _MEAS_NAME_RE.match(line)
            lm = _LET_RE.match(line)
            name = (mm.group(1) if mm else lm.group(1) if lm else None)
            if name:
                dropped[name.lower()] = (
                    f"probes {', '.join(sorted(set(gone)))}: the net is absent "
                    f"from the extracted netlist")
            new = "* A7: net absent after extraction: " + line
        else:
            lm = _LET_RE.match(line)
            if lm and any(re.search(rf"\b{re.escape(d)}\b", lm.group(2), re.I)
                          for d in dropped):
                dropped[lm.group(1).lower()] = "depends on a measurement " \
                    "whose net is absent after extraction"
                new = "* A7: depends on an absent net: " + line
            elif low.startswith("echo") and any(
                    v.lower() in dropped for v in _ECHO_VAR_RE.findall(line)):
                out_keys: dict = {}
                new = _echo_without(line, dropped, out_keys)
                for k in out_keys:
                    dropped.setdefault(k, "echoes a measurement whose net is "
                                          "absent after extraction")
        out.append(new)
    return "\n".join(out) + ("\n" if tb_text.endswith("\n") else ""), dropped


def _echo_without(line: str, dropped: Dict[str, str], keys: dict) -> str:
    """An `echo "MEAS k1=" $&v1 " k2=" $&v2` card without the pairs whose
    variable was taken out; the removed keys are recorded in `keys`."""
    parts = re.split(r"(\$&\w+)", line)
    out = [parts[0]]
    i = 1
    while i < len(parts):
        var, text = parts[i][2:], parts[i + 1] if i + 1 < len(parts) else ""
        if var.lower() in dropped:
            km = re.search(r"(\w+)=\s*\"?\s*$", out[-1])
            if km:
                keys[km.group(1).lower()] = True
                out[-1] = out[-1][:km.start()] + out[-1][km.end():]
            out.append(text)
        else:
            out.extend([parts[i], text])
        i += 2
    return "".join(out)


def layout_tech(bdir: Path) -> Path:
    """The Magic technology A5 drew the block with, from its own record
    (`layout_provenance.json` -> `pdk_sources.magic_tech`). The PDK and its
    root follow from the path: `<pdk_root>/<pdk>/libs.tech/magic/<tech>`."""
    lay = bdir / "layout_provenance.json"
    try:
        tech = Path(json.loads(lay.read_text())["pdk_sources"]["magic_tech"])
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ValueError(f"{lay.name} names no pdk_sources.magic_tech "
                         f"({exc})") from exc
    if len(tech.parents) < 4 or tech.parents[1].name != "libs.tech":
        raise ValueError(f"{tech} is not <pdk_root>/<pdk>/libs.tech/magic/…")
    return tech


def _style_slug(style: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", style).strip("_") or "default"


# ── how long each simulation runs, and for how long it may (T130) ─────────
#: WHY THE RUN IS CUT TO WHAT IT MEASURES. MEASURED (lane mig109, 8hd-3,
#: delta_sigma on ihp-sg13g2): the A3 testbench asks for `tran 5n 28673000n`
#: -- 28,673 clocks of a 1 MHz modulator, a record `record_constraints` sized
#: for the A4 GRADED measurement -- while every windowed `meas` card it
#: carries reads `from=523240n to=1025000n`, about 500 clocks. The pre-layout
#: run alone went 32.5 h without finishing, with five post-layout styles
#: queued behind it, because it ran ~28x past the last point any card reads.
#: A7 compares what the deck MEASURES, so the transient stops at the end of
#: the last measurement window plus a stated settle margin, unless a card
#: genuinely needs a longer record (named, with its source, below).
#:
#: The margin is ONE period of the deck's own sample clock (the one top-level
#: pulse source), so the window's last sample is an interior point of the
#: record and not the run's final breakpoint; a deck with no such clock gets
#: `_SETTLE_FRACTION` of the window end instead.
_SETTLE_CLOCKS = 1
_SETTLE_FRACTION = 0.01

#: The planning budget recorded for each A7 simulation when the block declares none: a
#: floor for start-up (model load, operating point) plus a per-clock cost.
#: MEASURED on 8hd-3 (32 cores, load < 3, image vibeic-eda 0.3.79): the
#: delta_sigma pre-layout deck advances ~9.2 s of wall per simulated 1 us
#: clock. The default allows 30 s per clock -- about three times that, because
#: an extracted netlist carries hundreds of R and C the pre-layout run does
#: not -- and applies the SAME budget to the pre deck and every post deck, so
#: no style is given more time than another. A project that knows better
#: states it in `phase3/analog/simulation_budgets.json` (`declared_budget`).
BUDGET_FLOOR_S = 600
BUDGET_S_PER_CLOCK = 30.0
SPEC_BUDGET_KEY = "simulation_budget_s"
#: Where a PROJECT states a budget that survives A1 re-emitting `spec.json`.
BUDGETS_FILE = "simulation_budgets.json"

#: The producer's fourth outcome: a simulation was stopped without a complete
#: measurement. It is NOT_MEASURED, and the stop is called budget_exhausted
#: only when a positive, enforced deadline is proved spent. The normal A7
#: route is progress-supervised and its budget is recorded, not enforced.
EX_BUDGET_EXHAUSTED = 75
NOT_MEASURED_TOKEN = "NOT_MEASURED:"

_TRAN_CARD_RE = re.compile(r"^(\s*\.?tran\s+)(\S+)(\s+)(\S+)(.*)$", re.I)
_TRAN_MEAS_RE = re.compile(r"^\s*\.?meas(?:ure)?\s+tran\s+(\w+)\s+(.*)$", re.I)
#: Keyword position only (whitespace on the left): a node spelled `to` or
#: `trig` inside `v(<dut>.<node>)` is a name, not a keyword.
_KV_RE = re.compile(r"(?:^|\s)(from|to|at|td)\s*=\s*(\S+)", re.I)
_EVENT_RE = re.compile(r"(?:^|\s)(trig|targ|when)\s", re.I)
#: Cards anchored at the END of the run, or reading the WHOLE record: moving
#: the end changes what they read (`fourier`/`four` the last periods; `fft`,
#: `spec`, `psd`, `linearize` the whole vector; a `meas` over another analysis
#: such as `meas sp` after an `fft`).
_END_ANCHORED_RE = re.compile(
    r"^\s*\.?(fourier|four|fft|spec|psd|linearize)\b", re.I)
_OTHER_MEAS_RE = re.compile(r"^\s*\.?meas(?:ure)?\s+(?!tran\b)(\w+)\s+(\w+)",
                            re.I)
#: A `let` that reduces a simulated VECTOR (`let m = mean(v(out))`) reads the
#: whole record; one over scalars (`let dens = vavg / 1.2`) does not.
_VECTOR_LET_RE = re.compile(r"^\s*let\s+(\w+)\s*=.*\b[vi]\s*\(", re.I)
#: Cards that dump the record over whatever span the run has.
_RECORD_RE = re.compile(r"^\s*\.?(wrdata|write|print|plot)\b", re.I)
#: ngspice's own progress line in batch mode: `Reference value :  4.05e-06`.
_REFERENCE_RE = re.compile(r"Reference value\s*:\s*([-+0-9.eE]+)")


def _seconds(tok: str) -> Optional[float]:
    import analog_adc_enob_corner_check as _enob
    return _enob._si(tok)


def _ns_token(seconds: float) -> str:
    ns = seconds * 1e9
    return (f"{int(round(ns))}n" if abs(ns - round(ns)) < 1e-6
            else f"{ns:.6f}".rstrip("0").rstrip(".") + "n")


def measurement_span(tb_text: str) -> dict:
    """What the deck's own cards need of the transient, in seconds.

    A card is CUT to only when it is PROVABLY covered; anything else keeps the
    declared stop, by name (review wave 5, T130):
      * WINDOWED -- a `meas tran` with `to=` or `at=` and no event clause; its
        end is the LATEST time it references (from/to/at/td). The latest end
        over all such cards, plus the settle margin, is the stop;
      * SPAN-FOLLOWING -- a `meas tran` with no time at all (the `railx_*`
        rail extremes): it reads the whole run, so pre and post read the SAME
        span, and it never sets the stop;
      * HOLDS -- an event card (`trig`/`targ`/`when`: its `at=`/`td=` is where
        the search STARTS), a `from=`-only card (it reads to the END of the
        run), a time this reader cannot evaluate (`to={tend}`), a `meas` over
        another analysis, a `let` that reduces a simulated vector, and an
        end-anchored or whole-record command (`fourier`, `fft`, `spec`, `psd`,
        `linearize`).
    `wrdata`/`print` dump whatever span the run has; A7 compares none of them,
    so they follow the span and are listed as doing so. Cards inside an
    `.include`d file are not seen: the A3 testbench writes its cards inline."""
    lines = _joined_lines(tb_text or "")
    trans = [line for line in lines if _TRAN_CARD_RE.match(line)]
    declared = (_seconds(_TRAN_CARD_RE.match(trans[0]).group(4))
                if trans else None)
    # ONE READER for the stop and its rewrite: the card is cut only where
    # `bound_transient` can rewrite it, i.e. its stop sits on the card's own
    # line. A `.tran 5n` / `+ 28673000n` split is read here but not cut.
    rewritable = any(_TRAN_CARD_RE.match(raw)
                     for raw in (tb_text or "").splitlines())
    windowed: List[dict] = []
    following: List[str] = []
    holds: List[dict] = []
    records: List[str] = []
    for line in lines:
        if line.lstrip().startswith("*"):
            continue
        m = _TRAN_MEAS_RE.match(line)
        if m:
            name, rest = m.group(1).lower(), m.group(2)
            kv = {k.lower(): v for k, v in _KV_RE.findall(rest)}
            times = {k: _seconds(v) for k, v in kv.items()}
            if _EVENT_RE.search(rest):
                # A TRIG/TARG/WHEN card reads until an EVENT; its `at=`/`td=`
                # is where the search STARTS, not where the card ends.
                holds.append({"card": name, "reason": (
                    "event-located (trig/targ/when): where it reads depends "
                    "on the circuit, and its at=/td= is where it starts")})
            elif any(t is None for t in times.values()):
                holds.append({"card": name, "reason": (
                    "a time this reader cannot evaluate ("
                    + ", ".join(f"{k}={kv[k]}" for k, t in times.items()
                                if t is None) + ")")})
            elif "to" in times or "at" in times:
                # Covered only when EVERY time it references is inside the
                # stop: the latest one is its end.
                windowed.append({"meas": name, "end_s": max(times.values())})
            elif "from" in times:
                holds.append({"card": name, "reason": (
                    f"reads from from={kv['from']} to the END of the run: a "
                    f"shorter run changes (or empties) its window")})
            else:
                following.append(name)
            continue
        om = _OTHER_MEAS_RE.match(line)
        if om:
            holds.append({"card": om.group(2).lower(), "reason": (
                f"a `meas {om.group(1).lower()}` over an analysis of the "
                f"whole transient record")})
            continue
        lm = _VECTOR_LET_RE.match(line)
        if lm:
            holds.append({"card": lm.group(1).lower(), "reason": (
                "a `let` that reduces a simulated vector over the whole "
                "record")})
            continue
        if _END_ANCHORED_RE.match(line):
            holds.append({"card": line.split()[0].lower(), "reason": (
                "anchored at the end of the run, or reads the whole record: "
                "a shorter run changes what it analyses")})
        elif _RECORD_RE.match(line):
            records.append(line.split()[0].lower())
    span = {"declared_stop_s": declared, "windowed": windowed,
            "span_following": following, "record_dumps": records,
            "holds_declared_record": holds}
    if declared is None:
        span.update(stop_s=None, rule="no_transient_card")
        return span
    if len(trans) != 1:
        span.update(stop_s=declared, rule="more_than_one_transient_card")
        return span
    if not rewritable:
        span.update(stop_s=declared,
                    rule="transient_card_continued_across_lines")
        return span
    if holds:
        span.update(stop_s=declared, rule="a_card_needs_the_declared_record")
        return span
    if not windowed:
        span.update(stop_s=declared, rule="no_windowed_measurement")
        return span
    import analog_adc_enob_corner_check as _enob
    last = max(w["end_s"] for w in windowed)
    card = _enob.sample_clock_card(tb_text or "")
    if card is not None:
        margin = _SETTLE_CLOCKS * card[1]
        source = f"{_SETTLE_CLOCKS} period of the deck's sample clock card"
    else:
        margin = _SETTLE_FRACTION * last
        source = (f"{_SETTLE_FRACTION:g} of the last window end (the deck "
                  f"names no single top-level pulse clock)")
    stop = last + margin
    span.update(last_window_end_s=last, settle_margin_s=margin,
                settle_margin_source=source,
                last_window_meas=[w["meas"] for w in windowed
                                  if w["end_s"] == last])
    if stop >= declared:
        span.update(stop_s=declared,
                    rule="declared_record_already_within_the_last_window")
    else:
        span.update(stop_s=stop, rule="last_measurement_window_plus_settle")
    return span


def bound_transient(tb_text: str) -> Tuple[str, dict]:
    """The testbench with its transient stopped where `measurement_span`
    says, and the span record. Only the stop token is rewritten; the step and
    anything after the stop survive."""
    span = measurement_span(tb_text)
    if span.get("stop_s") is None or span["stop_s"] == span["declared_stop_s"]:
        return tb_text, span
    out, done = [], False
    for line in (tb_text or "").splitlines():
        m = None if done else _TRAN_CARD_RE.match(line)
        if m:
            line = (m.group(1) + m.group(2) + m.group(3)
                    + _ns_token(span["stop_s"]) + m.group(5))
            done = True
        out.append(line)
    return "\n".join(out) + "\n", span


def declared_budget(project: Path, block: str) -> Optional[Tuple[float, dict]]:
    """The budget the PROJECT states for this block's simulations, or None.

    Read from `phase3/analog/simulation_budgets.json` (`{"<block>": seconds}`),
    a file no producer writes -- unlike `spec.json`, which A1 rewrites whole on
    a re-emit, so a key a user added there does not survive the next one."""
    path = project / "phase3" / "analog" / BUDGETS_FILE
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    val = doc.get(block) if isinstance(doc, dict) else None
    if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
        return float(val), {"source": f"phase3/analog/{BUDGETS_FILE}:{block}"}
    return None


def simulation_budget(spec: Optional[dict], tb_text: str,
                      stop_s: Optional[float],
                      declared: Optional[Tuple[float, dict]] = None
                      ) -> Tuple[float, dict]:
    """(seconds, source) for ONE A7 simulation. Never 0: 0 is "no deadline".

    In order: the project's `simulation_budgets.json` entry (`declared`), the
    block's `spec.json` `simulation_budget_s`, then a default -- per clock the
    (bounded) deck simulates; with no single clock card, per nanosecond of the
    declared transient (A4's `SIM_DEADLINE_S_PER_TRAN_NS`, no ceiling); with no
    readable transient at all (an op/ac/dc deck, or a parameterised stop),
    the floor. Every default is at least `BUDGET_FLOOR_S`."""
    if declared is not None:
        return declared
    value = (spec or {}).get(SPEC_BUDGET_KEY)
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and value > 0:
        return float(value), {"source": f"spec.json:{SPEC_BUDGET_KEY}"}
    import analog_adc_enob_corner_check as _enob
    import analog_real_corner_sweep as ars
    card = _enob.sample_clock_card(tb_text or "")
    if card is not None and stop_s:
        clocks = stop_s / card[1]
        return (BUDGET_FLOOR_S + clocks * BUDGET_S_PER_CLOCK,
                {"source": "default_per_clock", "clocks": clocks,
                 "floor_s": BUDGET_FLOOR_S,
                 "s_per_clock": BUDGET_S_PER_CLOCK})
    if stop_s:
        return (BUDGET_FLOOR_S + stop_s * 1e9 * ars.SIM_DEADLINE_S_PER_TRAN_NS,
                {"source": "default_per_transient_ns", "floor_s": BUDGET_FLOOR_S,
                 "s_per_ns": ars.SIM_DEADLINE_S_PER_TRAN_NS})
    return float(BUDGET_FLOOR_S), {"source": "default_floor (no readable "
                                             "transient)"}


def simulated_time_reached_s(raw: str) -> Optional[float]:
    """The last `Reference value` ngspice printed: how far the transient got
    before it was stopped. None when it printed none."""
    last = None
    for m in _REFERENCE_RE.finditer(raw or ""):
        last = m.group(1)
    try:
        return float(last) if last is not None else None
    except ValueError:
        return None


# ── the producer ───────────────────────────────────────────────────────────
def _budget_spent_proven(sim: dict, budget: dict) -> bool:
    status = sim.get("status") or {}
    enforced_s = status.get("deadline_s")
    try:
        return (bool(sim.get("stopped")) and not sim.get("stalled")
                and bool(enforced_s)
                and not status.get("run_to_completion")
                and abs(float(enforced_s)
                        - float(budget.get("seconds") or 0)) <= 1
                and float(sim["wall_s"]) >= float(enforced_s) - 1)
    except (TypeError, ValueError, KeyError):
        return False


def _write_terminal(record: dict, out: Path,
                    metric_counts: Optional[dict] = None) -> None:
    """Keep the canonical block record and emit this invocation's facts.

    The record is phase3/analog/<block>/a7_post_layout.json. Fixed metrics
    name the last block explicitly; they are not a whole-A7 aggregate.
    None overwrites unavailable counts from an earlier successful invocation.
    """
    write_json(out, record)
    step_metrics.emit_best_effort(out.parent.parent.parent.parent, STEP, {
        "block": record["block"], "producer_result": record["result"],
        "rule": record.get("rule"), "reason_class": record.get("reason_class"),
        "pair_count": None, "measured_style_count": None,
        "completed_style_count": None, **(metric_counts or {}),
    })


def _not_measured(record: dict, out: Path, deck: Path, sim: dict,
                  project: Path, metric_counts: Optional[dict] = None) -> int:
    """Classify a stopped run from its actual supervision, not its exit alone."""
    span, budget = record.get("transient_span", {}), record.get("budget", {})
    reached, requested = sim["reached_s"], span.get("stop_s")
    status = sim.get("status") or {}
    enforced_s = status.get("deadline_s")
    if sim.get("stalled"):
        record.update({
            "result": "NOT_MEASURED", "reason_class": "progress_stalled",
            "rule": "A7_SIMULATION_PROGRESS_STALLED",
            "progress_stalled": {
                "deck": str(deck.relative_to(project)), "log": sim["log"],
                "simulated_time_reached_s": reached,
                "simulated_time_requested_s": requested,
                "wall_s": round(sim["wall_s"], 3),
                "simulator_rc": status.get("rc"),
                "recorded_budget_s": budget.get("seconds"),
            },
        })
        detail = (f"{deck.name}: simulator made no progress and was stopped "
                  f"after {sim['wall_s']:.3f} s ({sim['log']})")
        record["detail"] = detail
        _write_terminal(record, out, metric_counts)
        print(f"{NOT_MEASURED_TOKEN} {PRODUCER} "
              f"A7_SIMULATION_PROGRESS_STALLED: {detail}", file=sys.stderr)
        return EX_BUDGET_EXHAUSTED
    if not _budget_spent_proven(sim, budget):
        record.update({
            "result": "NOT_MEASURED", "reason_class": "execution_error",
            "rule": "A7_SIMULATION_STOPPED_EXTERNALLY",
            "external_stop": {
                "deck": str(deck.relative_to(project)), "log": sim["log"],
                "simulated_time_reached_s": reached,
                "simulated_time_requested_s": requested,
                "wall_s": round(sim["wall_s"], 3),
                "simulator_rc": status.get("rc"),
                "recorded_budget_s": budget.get("seconds"),
                "run_to_completion": status.get("run_to_completion"),
                "enforced_deadline_s": enforced_s,
            },
        })
        detail = (f"{deck.name}: stopped after {sim['wall_s']:.3f} s wall "
                  f"with no proven spent deadline; reached {reached} s of "
                  f"{requested} s requested ({sim['log']})")
        record["detail"] = detail
        _write_terminal(record, out, metric_counts)
        print(f"{NOT_MEASURED_TOKEN} {PRODUCER} "
              f"A7_SIMULATION_STOPPED_EXTERNALLY: {detail}", file=sys.stderr)
        return EX_BUDGET_EXHAUSTED
    need = (sim["wall_s"] * requested / reached
            if reached and requested else None)
    budget["enforced"] = True
    budget["policy"] = "simulator_reported_enforced_deadline"
    record.update({
        "result": "NOT_MEASURED", "reason_class": "budget_exhausted",
        "rule": "A7_SIM_BUDGET_EXHAUSTED",
        "budget_exhausted": {
            "deck": str(deck.relative_to(project)), "log": sim["log"],
            "simulated_time_reached_s": reached,
            "simulated_time_requested_s": requested,
            "wall_s": round(sim["wall_s"], 1),
            "enforced_deadline_s": float(enforced_s),
            "budget_s": budget.get("seconds"),
            "budget_source": budget.get("source"),
            "remedy": (
                f"state `\"{record['block']}\": <seconds>` in phase3/analog/"
                f"{BUDGETS_FILE} (read before spec.json, and written by no "
                f"producer) at or above the wall this run extrapolates to"
                + (f" (~{need:.0f} s at the rate it reached)" if need else "")
                + ", or re-run on a host with less load"
                + ("; the deck's span is already cut to what it measures"
                   if span.get("rule") == "last_measurement_window_plus_settle"
                   else f"; the deck's declared span was kept "
                        f"({span.get('rule')})"))}})
    detail = (f"{deck.name}: simulated "
              f"{reached if reached is not None else 'an unread'} s of "
              f"{requested} s requested in {sim['wall_s']:.0f} s wall "
              f"(budget {budget.get('seconds')} s from "
              f"{budget.get('source')})")
    record["detail"] = detail
    _write_terminal(record, out, metric_counts)
    print(f"{NOT_MEASURED_TOKEN} {PRODUCER} A7_SIM_BUDGET_EXHAUSTED: {detail}",
          file=sys.stderr)
    return EX_BUDGET_EXHAUSTED


def declared_measurements(tb_text: str) -> List[str]:
    """The names of the `meas` cards the deck declares (comments skipped),
    lower-cased as ngspice prints them."""
    out = []
    for line in _joined_lines(tb_text or ""):
        if line.lstrip().startswith("*"):
            continue
        m = _MEAS_NAME_RE.match(line)
        if m and m.group(1).lower() not in out:
            out.append(m.group(1).lower())
    return out


def _unmeasured(record: dict, out: Path, rule: str, reason_class: str,
                detail: str, metric_counts: Optional[dict] = None,
                **facts) -> int:
    """NOT_MEASURED for a reason other than a spent budget (T131): the step ran
    and a row it declared is genuinely absent, so it may not PASS on the rest
    -- and nothing about the circuit was learned, so it is not a FAIL."""
    record.update({"result": "NOT_MEASURED", "reason_class": reason_class,
                   "rule": rule, "detail": detail, **facts})
    _write_terminal(record, out, metric_counts)
    print(f"{NOT_MEASURED_TOKEN} {PRODUCER} {rule}: {detail}", file=sys.stderr)
    return EX_BUDGET_EXHAUSTED


def _refuse(record: dict, out: Path, rule: str, detail: str, rc: int,
            result: Optional[str] = None,
            metric_counts: Optional[dict] = None) -> int:
    record.update({"result": result or ("REFUSED" if rc == 1 else "NOT_PRODUCED"),
                   "rule": rule, "detail": detail})
    _write_terminal(record, out, metric_counts)
    token = _pc.HONEST_GAP_TOKEN if rc == 2 else (
        _pc.ENV_REFUSED_TOKEN if rc == _pc.EX_ENV_REFUSED else "FAIL:")
    print(f"{token} {PRODUCER} {rule}: {detail}", file=sys.stderr)
    return rc


def run(project: Path, block: str, container: str, image: str,
        styles: Optional[List[str]] = None) -> int:
    import librelane_contract as lc
    import magic_extract_spice_emit as mx
    import analog_real_corner_sweep as ars
    import _designs_root as dr

    bdir = project / "phase3" / "analog" / block
    # NON-INTERFERENCE: the working decks never land under phase3/analog,
    # which A3's gates rglob. Only the two records below are the block's.
    work = project / "phase3" / "librelane" / "analog" / block / "a7_resim"
    record_path = bdir / "a7_post_layout.json"
    record: dict = {"producer": PRODUCER, "schema": 1, "block": block,
                    "step": STEP, "image": image, "extraction_tool": RCX_STEP}
    gds = bdir / f"{block}.gds"
    netlist = bdir / f"{block}.sp"
    tb = bdir / f"tb_{block}.sp"
    lay = bdir / "layout_provenance.json"
    for need, owner in ((gds, "A5"), (lay, "A5"), (netlist, "A3"), (tb, "A3")):
        if not need.is_file():
            return _refuse(record, record_path, "A7_INPUT_ABSENT",
                           f"{need.relative_to(project)} (owed by {owner})", 2)
    # The extracted netlist and every post-layout comparison are bound to the
    # exact A5 GDS bytes consumed by Magic.RCX. A later replacement at the
    # same path must not leave a clean pre_vs_post record certifying it.
    layout_sha256 = hashlib.sha256(gds.read_bytes()).hexdigest()
    record["layout_path"] = str(gds.relative_to(project))
    record["layout_sha256"] = layout_sha256
    # THE PAIR MUST BE ONE DESIGN before anything is extracted or simulated:
    # a layout of an earlier netlist extracts faithfully and then disagrees
    # with the current one, which reads as a layout that lost devices.
    try:
        lay_doc = json.loads(lay.read_text())
    except (OSError, ValueError):
        lay_doc = {}
    ident, ident_detail = layout_netlist_identity(
        lay_doc if isinstance(lay_doc, dict) else {},
        netlist.read_text(errors="replace"))
    # A legacy path names mutable bytes. If A3 rewrites that path in place,
    # reading it now can appear to MATCH even though A5 drew an older deck.
    # Only A5's successful, content-bound draw record proves this pairing.
    if ident == "MATCH" and not (
            isinstance(lay_doc, dict)
            and lay_doc.get("producer") == "analog_a5_layout_emit"
            and lay_doc.get("result") == "OK"
            and isinstance(lay_doc.get("netlist_content_sha256"), str)
            and lay_doc["netlist_content_sha256"]):
        ident = "UNVERIFIED"
        ident_detail = ("a mutable legacy netlist path or incomplete A5 "
                        "record cannot prove which netlist this layout drew")
    record["layout_netlist_identity"] = {"state": ident, "detail": ident_detail}
    if ident == "STALE":
        return _refuse(record, record_path, "A7_LAYOUT_NOT_OF_THIS_NETLIST",
                       f"{gds.relative_to(project)} was drawn from a different "
                       f"netlist than {netlist.relative_to(project)} ("
                       f"{ident_detail}); re-run A5 on the current A3 netlist",
                       2)
    if ident != "MATCH":
        return _refuse(record, record_path, "A7_LAYOUT_IDENTITY_UNVERIFIED",
                       f"{gds.relative_to(project)} cannot be proved to be "
                       f"a layout of {netlist.relative_to(project)} ("
                       f"{ident_detail}); re-run A5 to record the current "
                       "netlist identity", 2)
    try:
        tech = layout_tech(bdir)
    except ValueError as exc:
        return _refuse(record, record_path, "A7_LAYOUT_TECH_UNDECLARED",
                       f"{lay.relative_to(project)}: {exc}", 2)
    # <pdk_root>/<pdk>/libs.tech/magic/<tech>: the layout's own PDK.
    pdk, pdk_root = tech.parents[2].name, str(tech.parents[3])
    record.update({"pdk": pdk, "pdk_root": pdk_root, "magic_tech": str(tech)})
    ports = subckt_ports(netlist.read_text(errors="replace"), block)
    if not ports:
        return _refuse(record, record_path, "A7_NETLIST_NO_SUBCKT",
                       f"{netlist.name} defines no .subckt {block}", 2)
    work.mkdir(parents=True, exist_ok=True)
    if styles is None:
        # The technology is read inside the image: it is the image's PDK.
        cp = ars._docker(container, f"cat {tech} "
                         f"$(sed -n 's/^ *include  *//p' {tech} | "
                         f"sed 's#^#{tech.parent}/#; s#$#.tech#') 2>/dev/null")
        if cp.returncode != 0 or not cp.stdout.strip():
            return _refuse(record, record_path, "A7_TECH_UNREADABLE",
                           f"{tech} could not be read in {container}",
                           _pc.EX_ENV_REFUSED)
        flat = work / "magic_tech.flat"
        write_text(flat, cp.stdout)
        styles = extraction_styles(flat)
    if not styles:
        return _refuse(record, record_path, "A7_NO_EXTRACTION_STYLE",
                       f"{tech} declares no ngspice extraction style", 1)
    record["extraction_styles"] = styles
    flat_tech = work / "magic_tech.flat"
    summed = summed_device_models(
        flat_tech.read_text(errors="replace") if flat_tech.is_file()
        else _tech_text(tech))
    a3_devices = device_instances(netlist.read_text(errors="replace"), block)

    host_root = dr.resolve_host_root(project, container)
    # ONE span and ONE recorded budget for the pre deck and every post deck:
    # the comparison reads the same window in each.  The budget is evidence,
    # never a wall-clock kill; a progressing circuit simulation is supervised
    # for stalls by the container runner (#2051/#2062).
    tb_text, span = bound_transient(tb.read_text(errors="replace"))
    net_text = netlist.read_text(errors="replace")
    spec_path = bdir / "spec.json"
    try:
        spec = json.loads(spec_path.read_text()) if spec_path.is_file() else {}
    except (OSError, ValueError):
        spec = {}
    budget_s, budget_src = simulation_budget(
        spec if isinstance(spec, dict) else {}, tb_text, span.get("stop_s"),
        declared_budget(project, block))
    rail_supply_v, rail_margin_fraction = _declared_rail_reference(tb_text)
    if rail_supply_v is not None and rail_margin_fraction is not None:
        record["rail_reference"] = {
            "supply_v": rail_supply_v,
            "margin_fraction": rail_margin_fraction,
            "comparison_scale_v": rail_supply_v * rail_margin_fraction,
            "source": "A3 testbench v_vdd and A3 transient rail margin",
        }
    record["transient_span"] = span
    record["budget"] = {"seconds": round(budget_s, 1), **budget_src,
                        "applies_to": "each simulation (pre and every post)",
                        "enforced": False,
                        "policy": "planning_only_progress_supervised"}

    def simulate(deck: Path) -> dict:
        t0 = time.monotonic()
        ok, meas, raw, status = ars._run_ngspice(
            container, ars._container_path(container, host_root, deck),
            deck_text=deck.read_text(errors="replace"),
            run_to_completion=True)
        wall = time.monotonic() - t0
        write_text(deck.with_suffix(".ngspice.log"), raw or "")
        if wall > budget_s:
            record.setdefault("planning_budget_overruns", []).append({
                "deck": str(deck.relative_to(project)),
                "wall_s": round(wall, 3), "recorded_budget_s": budget_s,
                "simulator_completed": bool(ok),
            })
        return {"ok": ok, "meas": meas, "status": status, "wall_s": wall,
                "stopped": bool((status or {}).get("stopped")),
                "stalled": bool((status or {}).get("progress_stalled") or
                                (status or {}).get("rc") == wd.RC_STALLED),
                "reached_s": simulated_time_reached_s(raw),
                "log": str(deck.with_suffix(".ngspice.log").relative_to(project))}

    try:
        pre_tb = work / f"tb_{block}_pre.sp"
        write_text(pre_tb, post_layout_testbench(tb_text, block, None, bdir,
                                                 work))
    except ValueError as exc:
        return _refuse(record, record_path, str(exc).split(":", 1)[0],
                       str(exc), 1)
    pre = simulate(pre_tb)
    record["pre_wall_s"] = round(pre["wall_s"], 1)
    if pre["stopped"] or pre["stalled"]:
        return _not_measured(record, record_path, pre_tb, pre, project)
    if not pre["ok"]:
        return _refuse(record, record_path, "A7_PRE_SIM_FAILED",
                       f"the A3 testbench did not simulate ({pre['log']})", 1)
    record["pre"] = {"testbench": str(pre_tb.relative_to(project)),
                     "relocated_from": str(tb.relative_to(project)),
                     "measurements": pre["meas"], "log": pre["log"]}
    # T131: EVERY declared row is read, or the step says it was not. A `meas`
    # card that produced no pre-layout value leaves a hole the 10 % rule would
    # pass over silently.
    got = {k.lower() for k, v in (pre["meas"] or {}).items() if v is not None}
    absent = [n for n in declared_measurements(tb_text) if n not in got]
    if absent:
        # Keep the hole visible, but continue the post runs. A measured
        # degradation on another row is a FAIL and must outrank this gap.
        record["absent_measurements"] = absent

    specs: List[dict] = []
    corners: List[dict] = []
    exhausted: List[tuple] = []
    not_compared: Dict[str, str] = {}
    state_in = work / "state_in.json"
    write_json(state_in, {"gds": str(gds.resolve()), "metrics": {}})
    for style in styles:
        slug = _style_slug(style)
        src = work / f"rcx_{slug}.src.json"
        write_json(src, {"meta": {"version": 2, "step": RCX_STEP},
                         "DESIGN_NAME": block, "PDK": pdk,
                         "MAGIC_RCX_EXTRACT_STYLE": style})
        try:
            cfg = lc.resolve_step_config(project, image, src,
                                         work / f"rcx_{slug}.json",
                                         pdk_root=pdk_root)
            resolved = json.loads(cfg.read_text())
            if resolved.get("MAGIC_TECH") not in (None, str(tech)):
                return _refuse(record, record_path, "A7_TECH_MISMATCH",
                               f"LibreLane resolved MAGIC_TECH="
                               f"{resolved.get('MAGIC_TECH')} but A5 drew with "
                               f"{tech}", 1)
            resolved.setdefault("meta", {})["step"] = RCX_STEP
            write_json(cfg, resolved)
            folders = lc.run_chain(project, image, [(RCX_STEP, cfg, state_in)],
                                   namespace=f"analog/{block}/a7_{slug}",
                                   pdk_root=pdk_root)
        except lc.Refusal as exc:
            # A tool the contract STOPPED (no progress, or a probe past its
            # deadline) never answered: the environment tier with that
            # reason, never the `FAIL:` an extraction finding earns.
            stopped = lc.tool_stop_reason(exc.code)
            if stopped:
                record.update({"reason_class": stopped})
                return _refuse(record, record_path, exc.code, str(exc),
                               _pc.EX_ENV_REFUSED, result="NOT_MEASURED")
            rc = _pc.EX_ENV_REFUSED if exc.code in (
                "LL_IMAGE_INCAPABLE", "LL_CONFIG_RESOLVE_FAILED") else 1
            return _refuse(record, record_path, exc.code, str(exc), rc)
        folder = folders[-1]
        state = json.loads((folder / "state_out.json").read_text())
        rcx = Path(state.get("spice_rcx") or "")
        if not rcx.is_file():
            return _refuse(record, record_path, "A7_RCX_NO_NETLIST",
                           f"{RCX_STEP} state names no SPICE_RCX view "
                           f"({folder})", 1)
        rcx_text = rcx.read_text(errors="replace")
        audit = mx.audit_extracted_netlist(rcx_text, spice_file=str(rcx))
        corner = {"extraction_style": style,
                  "step_dir": str(folder.relative_to(project)),
                  "extracted_netlist": str(rcx.relative_to(project)),
                  "depth": audit.depth, "audit_passed": audit.passed,
                  "resistors": audit.summary.get("resistors"),
                  "capacitors": audit.summary.get("capacitors")}
        corners.append(corner)
        if not audit.passed:
            record["corners"] = corners
            return _refuse(record, record_path, "A7_RCX_PARASITIC_FREE",
                           f"{rcx.name}: depth {audit.depth} — a re-simulation "
                           f"of it is the pre-layout circuit again", 1)
        try:
            rcx_text, corner["resistor_bodies"] = mx.bind_step_resistor_bodies(
                folder, block, rcx_text)
        except ValueError as exc:
            record["corners"] = corners
            return _refuse(record, record_path, str(exc).split(":", 1)[0], str(exc), 1)
        bound = work / f"{block}_rcx_{slug}.spice"
        write_text(bound, rcx_text)
        corner["native_netlist"] = corner["extracted_netlist"]
        corner["extracted_netlist"] = str(bound.relative_to(project))
        try:
            lambda_per_um = float(lay_doc.get("lambda_per_um") or 0)
        except (TypeError, ValueError):
            lambda_per_um = 0.0
        layout_grid_m = (1e-6 / lambda_per_um
                         if math.isfinite(lambda_per_um) and lambda_per_um > 0
                         else 0.0)
        inventory = device_inventory(
            a3_devices, device_instances(rcx_text, block), summed,
            layout_grid_m=layout_grid_m)
        corner["device_inventory"] = inventory
        if inventory["result"] != "MATCH":
            record["corners"] = corners
            return _refuse(record, record_path,
                           "A7_RCX_DEVICE_INVENTORY_MISMATCH",
                           f"{rcx.name}: {'; '.join(inventory['differences'])}"
                           + ("" if ident == "MATCH" else
                              f" [layout/netlist identity {ident}: "
                              f"{ident_detail}]"),
                           1)
        try:
            post_text, mapping = post_layout_netlist(
                block, ports, rcx_text,
                model_binding_lines(net_text, bdir, work))
            post_net = work / f"{block}_post_{slug}.sp"
            write_text(post_net, post_text)
            post_tb = work / f"tb_{block}_post_{slug}.sp"
            rports, rinternal = rcx_nets(rcx_text, block)
            post_tb_text, dropped = remap_probes(
                post_layout_testbench(tb_text, block, post_net.name, bdir,
                                      work),
                block, rports, rinternal, mapping)
            write_text(post_tb, post_tb_text)
        except ValueError as exc:
            record["corners"] = corners
            rule = str(exc).split(":", 1)[0]
            return _refuse(record, record_path, rule, str(exc), 1)
        corner["post_layout_netlist"] = str(post_net.relative_to(project))
        corner["private_nodes"] = sum(1 for p, n in mapping.items() if p != n)
        post = simulate(post_tb)
        corner["post_log"] = post["log"]
        corner["post_wall_s"] = round(post["wall_s"], 1)
        corner["post_measurements"] = post["meas"]
        if post["stopped"] or post["stalled"]:
            # ONE STYLE'S STOP VOIDS ONLY THAT STYLE. The styles
            # already measured keep their rows, and the ones after it still
            # run: throwing their rows away would turn a degradation this
            # step MEASURED into "not measured" (review wave 5, T130).
            stop_kind = ("progress_stalled" if post["stalled"] else
                         "budget_exhausted" if _budget_spent_proven(
                             post, record["budget"]) else "external_stop")
            corner[stop_kind] = {
                "simulated_time_reached_s": post["reached_s"],
                "wall_s": round(post["wall_s"], 1)}
            exhausted.append((style, post_tb, post))
            not_compared[f"*@{style}"] = (
                f"{stop_kind}: {post_tb.name} simulated "
                f"{post['reached_s']} s of {span.get('stop_s')} s in "
                f"{post['wall_s']:.0f} s wall ({post['log']})")
            continue
        if not post["ok"]:
            record["corners"] = corners
            return _refuse(record, record_path, "A7_POST_SIM_FAILED",
                           f"{post_tb.name} did not simulate ({post['log']})", 1)
        skipped: Dict[str, str] = dict(dropped)
        lost: List[str] = []
        measured_rows = compare(pre["meas"], post["meas"], style, skipped, lost,
                                rail_supply_v, rail_margin_fraction)
        for row in measured_rows:
            row["extracted_netlist"] = corner["extracted_netlist"]
            row["post_layout_netlist"] = corner["post_layout_netlist"]
        specs.extend(measured_rows)
        if skipped:
            corner["not_comparable_post_layout"] = skipped
            not_compared.update({f"{k}@{style}": v for k, v in skipped.items()})
        if lost:
            record["corners"] = corners
            return _refuse(record, record_path, "A7_POST_MEASUREMENT_MISSING",
                           f"{post_tb.name}: the pre-layout run measured "
                           f"{lost} and the post-layout run did not, on nets "
                           f"the extraction kept ({post['log']})", 1)
    record["corners"] = corners
    record["compared_specs_count"] = len(specs)
    metric_counts = {
        "pair_count": len(specs),
        "measured_style_count": len({row["extraction_style"] for row in specs}),
        "completed_style_count": len(corners) - len(exhausted),
    }
    if exhausted and not specs:
        _style, post_tb, post = exhausted[0]
        record["stopped_styles"] = [e[0] for e in exhausted]
        return _not_measured(record, record_path, post_tb, post, project,
                             metric_counts=metric_counts)
    if not specs:
        if absent:
            return _unmeasured(
                record, record_path, "A7_PRE_MEASUREMENT_ABSENT",
                "partial_population",
                f"{pre_tb.name}: no comparable post-layout row and "
                f"{len(absent)} declared pre-layout measurement(s) absent "
                f"({', '.join(absent[:8])})",
                absent_measurements=absent, metric_counts=metric_counts)
        return _refuse(record, record_path, "A7_NOTHING_COMPARED",
                       "pre and post runs share no numeric measurement", 1,
                       metric_counts=metric_counts)
    if absent and not exhausted:
        import analog_a7_post_layout_resim_check as _gate
        deltas, _pairs = _gate._check_specs(specs)
        worst = max(deltas) if deltas else 0.0
        if worst > _gate.DEFAULT_MAX_DELTA_PCT:
            bad = sorted(s["name"] for s in specs
                         if any(d > _gate.DEFAULT_MAX_DELTA_PCT
                                for d in _gate._check_specs([s])[0]))
            return _refuse(
                record, record_path, "A7_POSTSIM_DELTA_TOO_BIG",
                f"measured post-layout degradation {bad[:8]} exceeds "
                f"{_gate.DEFAULT_MAX_DELTA_PCT}% (max {worst:.2f}%); "
                f"pre-layout rows absent: {absent[:8]}", 1,
                metric_counts=metric_counts)
        return _unmeasured(
            record, record_path, "A7_PRE_MEASUREMENT_ABSENT",
            "partial_population",
            f"{pre_tb.name}: {len(absent)} declared measurement(s) produced "
            f"no pre-layout value ({', '.join(absent[:8])}"
            f"{', ...' if len(absent) > 8 else ''}; {pre['log']})",
            absent_measurements=absent, metric_counts=metric_counts)
    measured_styles = {row["extraction_style"] for row in specs}
    typical = next(c for c in corners
                   if c.get("extraction_style") in measured_styles)
    write_json(bdir / "pre_vs_post.json", {
        "block": block,
        "_provenance": {
            "producer": PRODUCER, "schema": 1,
            "extracted_netlist": typical["extracted_netlist"],
            "post_layout_netlist": typical["post_layout_netlist"],
            "extraction_tool": f"LibreLane {RCX_STEP}", "image": image,
            "layout_path": str(gds.relative_to(project)),
            "layout_sha256": layout_sha256,
            "record": str(record_path.relative_to(project)),
            **({"not_compared": not_compared} if not_compared else {}),
        },
        "extraction_depth": sorted({c["depth"] for c in corners}),
        "specs": specs,
    })
    if not_compared:
        record["not_comparable_post_layout"] = not_compared
    if exhausted:
        # Every measured row is on disk. The verdict is the A7 gate's own
        # rule over them: a row already past it is a measured FAIL; otherwise
        # the step is NOT_MEASURED, naming only the styles that ran out.
        import analog_a7_post_layout_resim_check as _gate
        deltas, _pairs = _gate._check_specs(specs)
        worst = max(deltas) if deltas else 0.0
        record["stopped_styles"] = [e[0] for e in exhausted]
        if worst > _gate.DEFAULT_MAX_DELTA_PCT:
            bad = sorted((s.get("name") for s in specs
                          if abs(s.get("delta_pct", float("inf"))) >
                          _gate.DEFAULT_MAX_DELTA_PCT), key=str)
            return _refuse(
                record, record_path, "A7_POSTSIM_DELTA_TOO_BIG",
                f"measured on the styles that completed: {bad[:8]} exceed "
                f"{_gate.DEFAULT_MAX_DELTA_PCT}% (max {worst:.2f}%); "
                f"{record['stopped_styles']} stopped before measurement", 1,
                metric_counts=metric_counts)
        _style, post_tb, post = exhausted[0]
        return _not_measured(record, record_path, post_tb, post, project,
                             metric_counts=metric_counts)
    record["result"] = "PRODUCED"
    _write_terminal(record, record_path, metric_counts)
    print(f"[{PRODUCER}] block={block} {len(corners)} extraction style(s), "
          f"{len(specs)} spec row(s) -> phase3/analog/{block}/pre_vs_post.json")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = _pc.ProducerArgumentParser(prog=PRODUCER, description=__doc__.split("\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--container", required=True)
    ap.add_argument("--image", required=True,
                    help="the EDA image by digest (LibreLane runs in a fresh "
                         "container of it)")
    ap.add_argument("--style", action="append", default=None,
                    help="extraction style(s); default: every ngspice style "
                         "the layout's Magic technology declares")
    a = ap.parse_args(argv)
    return run(a.project.resolve(), a.block, a.container, a.image, a.style)


if __name__ == "__main__":
    sys.exit(main())
