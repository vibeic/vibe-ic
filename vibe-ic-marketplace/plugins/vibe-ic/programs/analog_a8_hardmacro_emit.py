#!/usr/bin/env python3
"""analog_a8_hardmacro_emit.py — A8 PRODUCER for an ANALOG block: emit the real
hardmacro abstract kit from the block's own signed-off layout.

WHY THIS EXISTS, MEASURED. A8's gate consumes `analog/hardmacro/<block>/` and
its LEF is what step 14 (floorplan) needs to reserve area for an analog macro —
without it OpenROAD refuses the digital top with `ORD-2013: no LEF master`. Two
producers were shipped and NEITHER could serve an analog block:

  * `digital_hardmacro_gen` writes a REAL abstract, by Magic, through the PDK's
    own magicrc — but it makes a DEF a precondition (exit 1, "no DEF"), because
    it derives a digital macro's pins and obstruction from the placed DEF. An
    analog block has no DEF and never will; it is drawn, not placed.
  * the runner's deterministic stub writes a 100x100 LEF with no pins. It exists
    so the flow can be exercised, and its own text says so.

So the analog track's only route to an abstract was the stub, and A8 sat at
VACUOUS_PASS ("defer to skill") while Phase 3 stayed blocked on the missing
master. The capability was never absent: `lef write -hide` reads the pins from
the layout's own port labels and needs no DEF at all. Measured on this
campaign's LDO: 4 pins, real SIZE, real OBS, 1754 bytes, from the sign-off GDS.

WHAT IT EMITS, per block, into `phase3/analog/hardmacro/<block>/`:
    <block>.lef   Magic `lef write -hide` on the block's sign-off GDS
    <block>.gds   the sign-off GDS itself (the abstract's implementation)
    <block>.v     the interface module — ports from the block's own topology IR
    <block>.lib   interface Liberty — pg_pins for the declared rails, and one
                  pin per remaining port

DIRECTIONS. An analog port has no digital direction, and inventing one would be
a design claim this program is not entitled to make. Every non-rail port is
therefore `inout`, which is what an analog macro's interface IS; the rails come
from the block's own `rails` declaration and become PG pins.

Exit codes: 0 emitted (or already complete), 1 a named precondition of the KIT
is missing (no GDS / no port list), 2 a CAPABILITY is absent (no Magic, no
magicrc) — disclosed, never a silent success.

chip-AGNOSTIC: no chip, vendor, SKU or process literal; the PDK arrives as the
magicrc the design's own PDK root provides.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROGRAMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_DIR))


def _docker_exec(container: str, cmd: str, timeout: int = 900):
    argv = (["docker", "exec", container, "bash", "-lc", cmd] if container
            else ["bash", "-lc", cmd])
    try:
        cp = subprocess.run(argv, capture_output=True, text=True,
                            timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return cp.returncode, cp.stdout or "", cp.stderr or ""


def layout_tech(bdir: Path) -> Optional[str]:
    """The technology the block's layout was DRAWN in, from its own .mag.

    This is the design's declaration, and it is the right one: an abstract has
    to be written by the same technology the layout was drawn in, and the
    layout says which that is on line 2 of every .mag Magic writes. The
    alternative — an L19 target — is optional and, on the design measured
    here, absent; picking "the only PDK installed" is not available either,
    because a full EDA image installs several (four, here).
    """
    for cand in sorted(bdir.glob("*.mag")):
        for line in cand.read_text(errors="replace").splitlines()[:5]:
            if line.startswith("tech "):
                return line.split(None, 1)[1].strip()
    return None


def magicrc_for(pdk_root: str, container: str, tech: Optional[str] = None
                ) -> Optional[str]:
    """The PDK's own magicrc, LOCATED (never reconstructed), on the side the
    tools are on. `tech` selects among several installed technologies; without
    it, ambiguity is REFUSED rather than resolved by sort order."""
    rc, out, _err = _docker_exec(
        container,
        f"ls {shlex.quote(pdk_root)}/libs.tech/magic/*.magicrc 2>/dev/null; "
        f"ls {shlex.quote(pdk_root)}/*/libs.tech/magic/*.magicrc 2>/dev/null")
    hits = [l.strip() for l in (out or "").splitlines() if l.strip()]
    own = [h for h in hits if h.startswith(pdk_root.rstrip("/") + "/libs.tech/")]
    if own:
        return sorted(own)[0]
    if tech:
        named = [h for h in hits
                 if Path(h).stem == tech or f"/{tech}/" in h]
        if len(named) == 1:
            return named[0]
        if named:
            return sorted(named)[0]
        return None
    return sorted(hits)[0] if len(hits) == 1 else None


def block_ports(topology: Dict) -> Tuple[List[str], List[str]]:
    """(rails, signals) from a block's topology IR.

    The rails are the block's OWN `rails` declaration, so a design that names
    its supplies differently needs no change here; every other declared port is
    a signal.
    """
    ports = [str(p) for p in (topology.get("ports") or [])]
    rails = [str(v) for v in (topology.get("rails") or {}).values()]
    rails = [r for r in ports if r in set(rails)]
    return rails, [p for p in ports if p not in set(rails)]


def build_lef_tcl(block: str, gds: str, out_lef: str) -> str:
    """The Magic TCL. `-hide` is the abstract form — upstream's own default."""
    return "\n".join([
        "drc off",
        f"gds read {gds}",
        f"load {block}",
        f"lef write {out_lef} -hide",
        'puts "A8_LEF_OK"',
        "quit -noprompt",
        "",
    ])


def interface_verilog(block: str, rails: List[str], signals: List[str]) -> str:
    """The macro's interface module. Not a behavioural model and not a stub —
    an analog macro's `.v` IS its interface, which is what a digital top needs
    to elaborate around it."""
    ports = rails + signals
    lines = [
        f"// {block} — analog hardmacro interface, generated from the block's",
        "// own topology IR and its signed-off layout. Analog ports carry no",
        "// digital direction, so each is declared `inout`; the supplies are",
        "// the block's own declared rails.",
        "`timescale 1ns / 1ps",
        f"module {block} (",
    ]
    lines += ["    %s%s" % (p, "," if i < len(ports) - 1 else "")
              for i, p in enumerate(ports)]
    lines.append(");")
    for p in rails:
        lines.append(f"    inout {p};   // supply")
    for p in signals:
        lines.append(f"    inout {p};   // analog")
    lines.append(f"endmodule // {block}")
    lines.append("")
    return "\n".join(lines)


def interface_liberty(block: str, rails: List[str], signals: List[str]) -> str:
    """Interface Liberty: the PG pins a digital flow must connect, and one pin
    per analog port. No timing arc is asserted — an analog macro has none to
    declare at this level, and inventing one would be a lie a signoff tool
    would then act on."""
    out = [f'library ({block}_interface) {{',
           '  delay_model : table_lookup;',
           '  time_unit : "1ns";',
           '  voltage_unit : "1V";',
           '  current_unit : "1mA";',
           '  capacitive_load_unit (1, pf);',
           f'  cell ({block}) {{',
           '    is_macro_cell : true;',
           '    interface_timing : false;']
    for i, p in enumerate(rails):
        out += [f'    pg_pin ({p}) {{',
                f'      pg_type : "{"primary_power" if i == 0 else "primary_ground"}";',
                f'      voltage_name : "{p}";',
                '    }']
    for p in signals:
        out += [f'    pin ({p}) {{',
                '      direction : inout;',
                '      is_analog : true;',
                '    }']
    out += ['  }', '}', '']
    return "\n".join(out)


# ── pin access: an abstract whose obstruction abuts its pins has none ──────

_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)", re.M)
_END_PIN_RE = re.compile(r"^\s*END\s+(\S+)\s*$", re.M)
_LAYER_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;", re.M)
_RECT_RE = re.compile(
    r"^\s*RECT\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*;", re.M)


def _rect_minus(a, b):
    """`a` minus `b`, as up to four axis-aligned rectangles."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if bx2 <= ax1 or bx1 >= ax2 or by2 <= ay1 or by1 >= ay2:
        return [a]
    out = []
    if by1 > ay1:
        out.append((ax1, ay1, ax2, min(by1, ay2)))
    if by2 < ay2:
        out.append((ax1, max(by2, ay1), ax2, ay2))
    ylo, yhi = max(ay1, by1), min(ay2, by2)
    if yhi > ylo:
        if bx1 > ax1:
            out.append((ax1, ylo, min(bx1, ax2), yhi))
        if bx2 < ax2:
            out.append((max(bx2, ax1), ylo, ax2, yhi))
    return [r for r in out if r[2] > r[0] and r[3] > r[1]]


def carve_pin_access(lef_text: str, clearance: float) -> Tuple[str, int]:
    """Cut a `clearance` halo around every PIN out of the OBS on its layer.

    MEASURED, and it is the difference between an abstract and a placeable
    one: `lef write -hide` emits the macro's internal metal as OBS tiled right
    up to each pin — the cut-out around one pin was the pin rectangle itself
    plus 0.1 um, which is less than a via. OpenROAD's detailed router refused
    every macro with `DRT-0073 No access point for <inst>/<pin>`, after
    floorplan, PDN, CTS and global route had all completed. Magic's own
    `-pinonly` is not the remedy — it shrinks the pin to a sliver and still
    writes the obstruction.

    Dropping the obstruction entirely is also not the remedy: an analog
    block's internal metal is a real blockage, and letting the router cross it
    is how a clean-looking die gets coupling nobody modelled. So the halo is
    carved and everything else stays.

    Returns (text, n_rects_removed_or_split).
    """
    out_lines = []
    # pass 1 — collect pin rects per layer
    pins: Dict[str, List[Tuple[float, float, float, float]]] = {}
    in_pin = False
    layer = None
    for line in lef_text.splitlines():
        if _PIN_RE.match(line):
            in_pin, layer = True, None
        elif re.match(r"^\s*OBS\b", line):
            in_pin, layer = False, None
        elif in_pin and _LAYER_RE.match(line):
            layer = _LAYER_RE.match(line).group(1)
        elif in_pin and layer and _RECT_RE.match(line):
            g = [float(v) for v in _RECT_RE.match(line).groups()]
            pins.setdefault(layer, []).append(tuple(g))
    if not pins:
        return lef_text, 0
    halos = {L: [(x1 - clearance, y1 - clearance, x2 + clearance,
                  y2 + clearance) for (x1, y1, x2, y2) in rs]
             for L, rs in pins.items()}
    # pass 2 — rewrite the OBS section
    changed = 0
    in_obs = False
    layer = None
    for line in lef_text.splitlines():
        if re.match(r"^\s*OBS\b", line):
            in_obs, layer = True, None
            out_lines.append(line)
            continue
        if in_obs and re.match(r"^\s*END\s*$", line):
            in_obs, layer = False, None
            out_lines.append(line)
            continue
        if in_obs and _LAYER_RE.match(line):
            layer = _LAYER_RE.match(line).group(1)
            out_lines.append(line)
            continue
        m = _RECT_RE.match(line) if in_obs else None
        if m and layer in halos:
            rects = [tuple(float(v) for v in m.groups())]
            for h in halos[layer]:
                nxt = []
                for r in rects:
                    nxt += _rect_minus(r, h)
                rects = nxt
            indent = line[:len(line) - len(line.lstrip())]
            if len(rects) != 1 or rects[0] != tuple(
                    float(v) for v in m.groups()):
                changed += 1
            for (x1, y1, x2, y2) in rects:
                out_lines.append("%sRECT %.3f %.3f %.3f %.3f ;"
                                 % (indent, x1, y1, x2, y2))
            continue
        out_lines.append(line)
    return "\n".join(out_lines) + "\n", changed


def emit_block(project: Path, block: str, container: str, pdk_root: str,
               ) -> Dict:
    bdir = project / "phase3" / "analog" / block
    gds = bdir / f"{block}.gds"
    topo = bdir / "topology.json"
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    if not gds.is_file():
        return {"block": block, "emitted": False, "rc": 1,
                "reason": f"no sign-off GDS at {gds.name}"}
    if not topo.is_file():
        return {"block": block, "emitted": False, "rc": 1,
                "reason": "no topology.json — no declared port list to bind"}
    rails, signals = block_ports(json.loads(topo.read_text()))
    if not (rails + signals):
        return {"block": block, "emitted": False, "rc": 1,
                "reason": "topology.json declares no ports"}
    tech = layout_tech(bdir)
    rcfile = magicrc_for(pdk_root, container, tech)
    if rcfile is None:
        return {"block": block, "emitted": False, "rc": 2,
                "reason": (f"no magicrc under {pdk_root} for the technology the "
                           f"layout declares ({tech or 'undeclared'})")}
    hdir.mkdir(parents=True, exist_ok=True)
    tcl = hdir / f"{block}_lef.tcl"
    lef = hdir / f"{block}.lef"
    tcl.write_text(build_lef_tcl(block, str(gds), str(lef)))
    rc, out, err = _docker_exec(
        container,
        f"cd {shlex.quote(str(hdir))} && magic -dnull -noconsole "
        f"-rcfile {shlex.quote(rcfile)} {shlex.quote(tcl.name)}")
    if not lef.is_file() or lef.stat().st_size == 0:
        return {"block": block, "emitted": False, "rc": 2,
                "reason": f"magic wrote no LEF (rc={rc})",
                "tail": (out + err)[-300:]}
    halo = float(os.environ.get("A8_PIN_ACCESS_CLEARANCE_UM", "0.6"))
    carved, n_carved = carve_pin_access(lef.read_text(errors="replace"), halo)
    if n_carved:
        lef.write_text(carved)
    (hdir / f"{block}.gds").write_bytes(gds.read_bytes())
    (hdir / f"{block}.v").write_text(interface_verilog(block, rails, signals))
    (hdir / f"{block}.lib").write_text(interface_liberty(block, rails, signals))
    return {"block": block, "emitted": True, "rc": 0,
            "lef_bytes": lef.stat().st_size,
            "obs_rects_carved_for_pin_access": n_carved,
            "pin_access_clearance_um": halo,
            "pins": len(rails) + len(signals),
            "rails": rails, "signals": signals,
            "magicrc": rcfile}


def declared_blocks(project: Path) -> List[str]:
    """The declared block NAMES, through the shared loader.

    Rolling its own reader here cost a full run: a block-list entry is a dict
    (name + spec + evidence), not a string, and `str(entry)` became a 2 KB
    path that the filesystem refused with "File name too long" — a refusal
    that reads like a design problem and is a parser problem.
    """
    from _analog_a_check_common import load_block_list
    return load_block_list(project) or []


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project")
    ap.add_argument("--block", action="append")
    ap.add_argument("--container", default="vibeic-eda")
    ap.add_argument("--pdk-root", default="/foss/pdks")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    project = Path(a.project)
    blocks = a.block or declared_blocks(project)
    if not blocks:
        print("A8_EMIT: no declared analog block — nothing to package")
        return 0
    results = [emit_block(project, b, a.container, a.pdk_root) for b in blocks]
    worst = max(r["rc"] for r in results)
    for r in results:
        print("A8_EMIT %s: %s" % (
            r["block"],
            ("lef %d B, %d pin(s)" % (r["lef_bytes"], r["pins"]))
            if r["emitted"] else "REFUSED — " + r["reason"]))
    if a.json:
        Path(a.json).write_text(json.dumps(
            {"blocks": results, "rc": worst}, indent=2) + "\n")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
