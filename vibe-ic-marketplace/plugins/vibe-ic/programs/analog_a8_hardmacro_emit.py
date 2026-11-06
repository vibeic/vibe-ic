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
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROGRAMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_DIR))

from _atomic_artefact import write_json, write_text as atomic_write_text  # noqa: E402 - vibe-ic#1082
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import magic_extract_spice_emit as _mx  # noqa: E402 — ordinary A7 extraction producer
import analog_a7_post_layout_emit as _a7  # noqa: E402 — source model/TB relocation
import _analog_a8_extraction_wrapper as _aw  # noqa: E402
from librelane_contract import resolve_state_pdk_asset  # noqa: E402
from _analog_a_check_common import (  # noqa: E402
    load_block_list,
)


def _docker_exec_raw(container: str, cmd: str, timeout: int = 900
                     ) -> Tuple[int, str, str]:
    """A SHORT probe under a plain wall-clock bound (`ls`, `test -e`). Long
    tool runs go through `_docker_exec(..., marker=...)` below."""
    # The CONTAINER branch keeps `-l`: the EDA image puts its tools on PATH from
    # the login profile, so a non-login shell there would not find `magic`.
    #
    # The HOST branch must NOT. A login shell sources that same profile, and in
    # this image the profile PRINTS — `[INFO] Final PYTHONPATH variable: ...` —
    # straight onto the stdout this function returns for the caller to parse.
    # MEASURED through `tools/ci/run_suite_in_eda_image.sh`, the harness the
    # landing gate uses, with the probe `echo probe`:
    #     '[INFO] Final ...python\nprobe'   !=   'probe'
    # A short probe (`ls`, `test -e`, `echo`) needs no profile, and a reader of
    # its output must not have to know which banner today's image prints.
    #
    # The `-l`/no-`-l` split above is that landing's, unchanged. What moved is
    # only WHO BUILDS the container argv: `_container_exec.docker_exec_argv` is
    # the one constructor, and it carries the attach check that keeps this probe
    # from reading `magic` out of a container holding bytes nobody pinned. The
    # argv it returns is identical, `-lc` included; the host branch never
    # reaches it, because there is no container there to check.
    argv = (_ce.docker_exec_argv(container, "bash", "-lc", cmd) if container
            else ["bash", "-c", cmd])
    try:
        cp = subprocess.run(argv, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return cp.returncode, cp.stdout or "", cp.stderr or ""


def _docker_exec(container: str, cmd: str, timeout: int = 900, *,
                 marker: Optional[str] = None,
                 log_path: Optional[Path] = None) -> Tuple[int, str, str]:
    """marker=None -> `_docker_exec_raw` (short probes). marker set -> the
    shared PROGRESS-STALL WATCHDOG (`_docker_watchdog.run_docker_supervised`),
    the same delegation `design_one_shot_runner._docker_exec` makes.

    vibe-ic#2010 item 8: the `magic ... lef write` run below is a long tool
    invocation and was launched through the raw form, whose only bound is a
    wall-clock timeout — a Magic making no progress holds the step until that
    bound, and a Magic that is legitimately slow on a large layout is killed
    at it, both reported as a plain "wrote no LEF". Under the watchdog a
    still-progressing Magic runs to completion however long it takes, and a
    stalled one is reaped by identity after the grace window and says so.
    `marker` is a token already in the tool's argv (its script name here).
    """
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)
    import _docker_watchdog as _dw
    return _dw.run_docker_supervised(
        container, cmd, marker, docker_exec_raw=_docker_exec_raw,
        log_path=log_path)


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


class MagicrcRefusal(ValueError):
    """The declared PDK variant has no unambiguous native Magic startup."""


def magicrc_for(pdk_root: str, container: str, tech: Optional[str] = None
                ) -> str:
    """Locate only the layout-declared variant in the selected runtime.

    Its exact startup name wins over auxiliary files. A missing exact file
    or ambiguous alternatives is a named refusal, never a sibling fallback.
    """
    if not pdk_root:
        raise MagicrcRefusal("selected runtime declares no PDK_ROOT")
    if not tech or Path(tech).name != tech or tech in (".", ".."):
        raise MagicrcRefusal(
            f"layout declares no usable PDK variant under {pdk_root}: {tech!r}")
    magic_dir = f"{pdk_root.rstrip('/')}/{tech}/libs.tech/magic"
    expected = f"{magic_dir}/{tech}.magicrc"
    _rc, out, _err = _docker_exec(
        container, f"for magicrc_candidate in {shlex.quote(magic_dir)}/*.magicrc; do "
        '[ -f "$magicrc_candidate" ] && printf "%s\\n" "$magicrc_candidate"; done')
    candidates = sorted({line.strip() for line in (out or "").splitlines()
                         if line.strip().startswith(magic_dir + "/")})
    if expected in candidates:
        return expected
    if len(candidates) > 1:
        raise MagicrcRefusal(
            f"ambiguous magicrc for the layout-declared variant {tech}; "
            f"expected {expected}; candidates: " + ", ".join(candidates))
    raise MagicrcRefusal(
        f"no magicrc under {pdk_root} for the technology the layout declares "
        f"({tech}); expected {expected}"
        + ("; candidate: " + candidates[0] if candidates else ""))


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


def interface_liberty(block: str, rails: List[str], signals: List[str],
                      measurement: Optional[Dict[str, object]] = None) -> str:
    """Interface Liberty: PG pins, analog pins, and an optional measured
    leakage value.

    The no-measurement form is retained for callers that use this pure
    formatter in unit tests.  ``emit_block`` never publishes that form: a
    production hardmacro must carry a source-bound native measurement or
    refuse before writing the package.  Pure analog blocks do not acquire a
    fabricated synchronous timing arc; a measured leakage scalar is the
    supported non-degenerate contract.
    """
    out = [f'library ({block}_interface) {{',
           '  delay_model : table_lookup;',
           '  time_unit : "1ns";',
           '  voltage_unit : "1V";',
           '  current_unit : "1mA";',
           '  capacitive_load_unit (1, pf);']
    if measurement is not None:
        out.append(f'  leakage_power_unit : "{measurement["liberty_power_unit"]}";')
    out += [f'  cell ({block}) {{',
            '    is_macro_cell : true;',
            '    interface_timing : false;']
    if measurement is not None:
        out.append(f'    cell_leakage_power : {measurement["liberty_value"]:.12g};')
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


def annotate_pg_pins(lef_text: str, rails: Dict[str, str]) -> Tuple[str, int]:
    """Declare the macro's supply pins as PG pins in the LEF.

    `lef write` emits every pin the same way — `PIN <name> / PORT / …` — with
    no DIRECTION and no USE. A LEF pin with no USE is a SIGNAL pin, so a
    hard macro's supplies arrive at the digital flow as ordinary signals:
    `pdngen` does not know the macro has a power connection to make, and the
    PDN is planned as though the macro's area were free silicon.

    `rails` maps the ROLE the design declares (`vdd`/`vss`, its own
    vocabulary from the block's topology IR) to the net name that block uses,
    so a design that calls its supply `avdd` is served by its own
    declaration and no supply name is hard-coded here. A role this table
    cannot place is left alone rather than guessed at.

    Returns (text, n_pins_annotated).
    """
    role_use = {"vdd": "POWER", "vcc": "POWER", "vpwr": "POWER",
                "vss": "GROUND", "gnd": "GROUND", "vgnd": "GROUND"}
    use_of = {}
    for role, net in (rails or {}).items():
        u = role_use.get(str(role).strip().lower())
        if u and net:
            use_of[str(net)] = u
    if not use_of:
        return lef_text, 0
    out = []
    n = 0
    for line in lef_text.splitlines():
        out.append(line)
        m = re.match(r"^(\s*)PIN\s+(\S+)\s*$", line)
        if m and m.group(2) in use_of:
            pad = m.group(1) + "  "
            out.append(f"{pad}DIRECTION INOUT ;")
            out.append(f"{pad}USE {use_of[m.group(2)]} ;")
            n += 1
    return "\n".join(out) + ("\n" if lef_text.endswith("\n") else ""), n


def annotate_signal_pins(lef_text: str, signals: List[str]) -> Tuple[str, int]:
    """Declare every non-rail port PIN `DIRECTION INOUT` / `USE SIGNAL`.

    The same loss as `annotate_pg_pins`, on the other pins: a port's class and
    use do not survive the GDS the abstract is written from (Magic's GDS
    reader restores a port from its pin boundary and text, nothing more), so
    `lef write` emits the signal PINs bare. MEASURED on u_hawaii_adc/ldo
    (OpenROAD 26Q3): a bare PIN is read as `io=INPUT`, a direction this
    program is not entitled to claim for an analog port. An analog port is
    INOUT, as `interface_verilog` already declares it.

    A PIN that already states a DIRECTION or a USE is left alone. Returns
    (text, n_pins_annotated)."""
    want = {str(s) for s in (signals or [])}
    lines = lef_text.splitlines()
    out: List[str] = []
    n = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.match(r"^(\s*)PIN\s+(\S+)\s*$", line)
        if m and m.group(2) in want:
            j = i + 1
            stated = False
            while j < len(lines) and not re.match(
                    r"^\s*(PORT|END)\b", lines[j]):
                if re.match(r"^\s*(DIRECTION|USE)\b", lines[j]):
                    stated = True
                j += 1
            if not stated:
                pad = m.group(1) + "  "
                out.append(f"{pad}DIRECTION INOUT ;")
                out.append(f"{pad}USE SIGNAL ;")
                n += 1
        i += 1
    return "\n".join(out) + ("\n" if lef_text.endswith("\n") else ""), n


def lef_pin_census(lef_text: str) -> List[Dict]:
    """`[{pin, layers, use}]` — what the LEF on disk actually declares, so the
    report says what was WRITTEN, not what the topology asked for."""
    out: List[Dict] = []
    cur = None
    for raw in lef_text.splitlines():
        tok = raw.split()
        if not tok:
            continue
        if tok[0] == "PIN" and len(tok) > 1:
            cur = {"pin": tok[1], "layers": [], "use": None}
            out.append(cur)
        elif cur is not None and tok[0] == "USE" and len(tok) > 1:
            cur["use"] = tok[1].rstrip(";")
        elif cur is not None and tok[0] == "LAYER" and len(tok) > 1:
            if tok[1] not in cur["layers"]:
                cur["layers"].append(tok[1])
        elif cur is not None and tok[0] == "END" and len(tok) > 1 \
                and tok[1] == cur["pin"]:
            cur = None
        elif tok[0] == "OBS":
            cur = None
    return out


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


# ── native measurement admission ─────────────────────────────────────────

_A8_MEASUREMENT = "a8_measurement.json"
_POWER_TO_UW = {
    "w": 1_000_000.0,
    "mw": 1_000.0,
    "uw": 1.0,
    "nw": 0.001,
    "pw": 0.000001,
}
_POWER_TO_W = {unit: factor * 1e-6
               for unit, factor in _POWER_TO_UW.items()}


def _valid_leakage_power(value: float, topology: Dict) -> bool:
    """Measured zero requires a nonempty capacitor/resistor-only inventory."""
    if not math.isfinite(value) or value < 0:
        return False
    if value > 0:
        return True
    devices = topology.get("devices")
    return (isinstance(devices, list) and bool(devices)
            and all(isinstance(device, dict)
                    and device.get("role") in ("cap", "res")
                    for device in devices))

_MAG_USE_RE = re.compile(r"(?im)^\s*use\s+(\S+)")
_INVALID_OP_RE = re.compile(r"(?m)^\s*;;RESIDUAL_FAIL\b")


def _native_ngspice_binary(container: str) -> Tuple[Optional[str], str]:
    """Use the same capability-probed ngspice locations as A4."""
    probes = (
        "command -v ngspice",
        "test -x /foss/tools/ngspice/bin/ngspice && "
        "echo /foss/tools/ngspice/bin/ngspice",
        "ls /foss/tools/*/bin/ngspice 2>/dev/null | head -1",
    )
    for probe in probes:
        rc, out, _err = _docker_exec_raw(container, probe)
        if rc != 0:
            continue
        for line in (out or "").splitlines():
            value = line.strip()
            if value.startswith("/") and value.endswith("ngspice"):
                return value, ""
    return None, "ngspice is not reachable in the selected execution context"


def _selected_native_binary(container: str, ngspice_bin: Optional[str] = None
                            ) -> Tuple[Optional[Dict[str, str]], str]:
    """Resolve the executable ngspice selected for A8."""
    explicit = ngspice_bin is not None
    if explicit:
        if not Path(ngspice_bin).is_absolute():
            return None, "explicit ngspice binary must be an absolute execution-side path"
        rc, _out, _err = _docker_exec_raw(
            container, f"test -x {shlex.quote(ngspice_bin)}")
        if rc != 0:
            return None, f"explicit ngspice binary is not executable: {ngspice_bin}"
    else:
        ngspice_bin, why = _native_ngspice_binary(container)
        if ngspice_bin is None:
            return None, why
    return {"path": ngspice_bin,
            "selection": "explicit" if explicit else "discovered"}, ""


def _stage_layout_subtree(layout: Path, stage: Path, block: str) -> Tuple[bool, str]:
    """Copy the A5 layout bytes as the ordinary Magic top-cell identity."""
    try:
        stage.mkdir(parents=True, exist_ok=True)
        shutil.copy2(layout, stage / f"{block}.mag")
    except OSError as exc:
        return False, f"cannot stage A5 top layout: {exc}"
    pending = [layout]
    seen = set()
    for _depth in range(16):
        if not pending:
            break
        nxt: List[Path] = []
        for source in pending:
            try:
                text = source.read_text(errors="replace")
            except OSError:
                continue
            for name in _MAG_USE_RE.findall(text):
                if name in seen:
                    continue
                seen.add(name)
                child = layout.parent / f"{name}.mag"
                if not child.is_file():
                    continue
                try:
                    shutil.copy2(child, stage / child.name)
                except OSError as exc:
                    return False, f"cannot stage layout child {child.name}: {exc}"
                nxt.append(child)
        pending = nxt
    return True, f"staged top {block}.mag and {len(seen)} referenced child cell(s)"


def _extraction_wrapper_contract(project: Path, block: str, extracted: Path,
                                 topology: Dict) -> Tuple[Dict, str]:
    """Reconstruct from current raw/A3 bytes, in both producer and consumer."""
    bdir = project / "phase3" / "analog" / block
    declared = list(topology.get("ports") or [])
    a3_ports = _aw.native_ports((bdir / f"{block}.sp").read_text(), block)
    if a3_ports != declared:
        raise ValueError("current A3 netlist ports do not equal topology ports")
    text, interface = _aw.build_wrapper(extracted.read_text(), block, declared)
    path = bdir / "a8_extraction_wrapper.spice"
    if path.resolve() == extracted.resolve():
        raise ValueError("wrapper cannot replace raw native extraction")
    return {"path": str(path.relative_to(project)),
            **interface}, text


def _terminal_voltage_expression(positive: str, negative: str) -> str:
    """ngspice control expressions have no named voltage vector for node 0."""
    if positive == "0" and negative == "0":
        return "0"
    if negative == "0":
        return f"v({positive})"
    if positive == "0":
        return f"(-v({negative}))"
    return f"(v({positive})-v({negative}))"


def _l9_block_pins(project: Path, block: str, ports: List[str]) -> Dict[str, Dict]:
    path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"A8 unloaded power requires L9 pin directions: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("instances"), list):
        raise ValueError("A8 unloaded power requires L9 instance pins")
    candidates = []
    for instance in doc["instances"]:
        if not isinstance(instance, dict) or not any(
                str(instance.get(key, "")).casefold() == block.casefold()
                for key in ("block", "master", "block_type")):
            continue
        pins = {str(pin["name"]).casefold(): {
                    "direction": str(pin.get("direction", "")).casefold(),
                    "type": str(pin.get("type", "")).casefold()}
                for pin in instance.get("ports", []) if isinstance(pin, dict) and "name" in pin}
        if set(pins) != {port.casefold() for port in ports} or any(
                pin["direction"] not in ("input", "output", "inout") for pin in pins.values()):
            raise ValueError(f"A8 L9 pins/directions do not describe all {block} ports")
        candidates.append(pins)
    if not candidates or any(pins != candidates[0] for pins in candidates[1:]):
        raise ValueError(f"A8 requires consistent L9 instance pins for {block}")
    return candidates[0]


def _delivered_measurement_deck(project: Path, block: str, extracted: Path,
                                ports: List[str], subckt: str,
                                topology: Dict, wrapper: Optional[Path] = None, *,
                                models: Optional[List[Dict]] = None
                                ) -> Tuple[str, Dict]:
    """Replace the DUT in its delivered stimulus; run only native OP power.

    The A3 model bindings and external circuit cards remain the source of the
    conditions. This steady-state deck specializes power-on PWL supply rails
    to their explicit DC bias, or their own final plateau when no DC value is
    stated. L9 output pins drive the original testbench through ideal voltage
    followers, leaving the DUT outputs unloaded while retaining external bias
    and feedback. Zero-volt rail probes measure only the DUT terminal power.
    """
    bdir = project / "phase3" / "analog" / block
    a3, tb = bdir / f"{block}.sp", bdir / f"tb_{block}.sp"
    if not a3.is_file() or not tb.is_file():
        raise ValueError("A8 native OP requires the delivered A3 netlist and testbench")
    if _aw.native_ports(a3.read_text(), block) != ports:
        raise ValueError("A8 source testbench ports do not match the delivered DUT")
    bindings = _a7.model_binding_lines(a3.read_text(), bdir, bdir)
    if not bindings:
        raise ValueError("A8 delivered A3 netlist has no model bindings")
    cards, instances = [], []
    control, subcircuit = False, False
    for line in _a7._joined_lines(tb.read_text(errors="replace")):
        stripped = line.strip()
        if re.match(r"(?i)^\.control\b", stripped):
            control = True
            continue
        if re.match(r"(?i)^\.endc\b", stripped):
            control = False
            continue
        if control or not stripped or stripped.startswith(("*", ";")):
            continue
        if re.match(r"(?i)^\.subckt\b", stripped):
            subcircuit = True
        if re.match(r"(?i)^\.ends\b", stripped):
            subcircuit = False
        if not subcircuit and re.match(r"(?i)^\.(?:end|tran|ac|dc|op|noise|meas\w*|save|print|plot)\b", stripped):
            continue
        library = _a7._LIB_RE.match(line)
        if library:
            target = library.group(2).strip("'\"")
            if Path(target).name == f"{block}.sp":
                continue
            if not Path(target).is_absolute():
                target = str((bdir / target).resolve())
            line = f"{library.group(1)}{json.dumps(target)}{library.group(3)}"
        fields = stripped.split()
        if not subcircuit and fields[0].casefold().startswith("x") and len(fields) >= len(ports) + 2 \
                and fields[len(ports) + 1].casefold() == block.casefold():
            instances.append(fields)
            continue
        cards.append(line)
    if len(instances) != 1:
        raise ValueError("A8 native OP requires exactly one delivered DUT instance")
    nodes = instances[0][1:len(ports) + 1]
    pins = _l9_block_pins(project, block, ports)
    rail_ports = {str(value).casefold() for value in (topology.get("rails") or {}).values()}
    has_supply = any(pin["type"] == "power" and port in rail_ports for port, pin in pins.items())
    if not has_supply:
        if not _valid_leakage_power(0, topology):
            raise ValueError("A8 L9 pins do not identify a power rail for quiescent current")
        rail_ports = {port for port, pin in pins.items() if pin["direction"] != "output"}
    rail_nodes = {node.casefold() for port, node in zip(ports, nodes)
                  if port.casefold() in rail_ports and node != "0"}
    supplies = []
    for index, line in enumerate(cards):
        fields = line.split(None, 3)
        if len(fields) != 4 or not fields[0].casefold().startswith("v"):
            continue
        source, positive, negative, value = fields
        if not rail_nodes.intersection((positive.casefold(), negative.casefold())):
            continue
        pwl = re.fullmatch(r"(?is)\s*(?:(?:dc\s+)?(?P<dc>\S+)\s+)?pwl\s*\((?P<points>.*)\)\s*", value)
        bias = None
        selection = "delivered_source"
        if pwl:
            bias = pwl.group("dc")
            selection = "explicit_dc"
            if bias is None:
                pairs = re.split(r"[\s,]+", pwl.group("points").strip())
                if len(pairs) < 4 or len(pairs) % 2:
                    raise ValueError("A8 supply PWL has no explicit terminal DC plateau")
                bias = pairs[-1]
                selection = "pwl_terminal_plateau"
            # An OP source has one DC condition. Retaining the time waveform
            # lets native OPtran fallback select its time-zero value instead
            # of the explicit DC condition, which the residual check refuses.
            cards[index] = f"{source} {positive} {negative} dc {bias}"
        supplies.append({"source": source, "positive": positive, "negative": negative,
                         "dc_plateau": bias, "source_value": value,
                         "dc_selection": selection})
    if not supplies:
        raise ValueError("A8 delivered testbench has no voltage source driving its declared rails")
    precision_cards, precision = _native_op_precision(cards)
    method_cards, solver = _native_op_solver(cards)
    used = {token.casefold() for token in re.findall(r"[^\s(),]+", " ".join([*cards, *ports, *nodes]))}
    def fresh(prefix):
        name, suffix = prefix, 0
        while name.casefold() in used:
            suffix += 1
            name = f"{prefix}_{suffix}"
        used.add(name.casefold())
        return name

    probes, rail_probes, power_probes = [], [], []
    for index, (port, node) in enumerate(zip(ports, nodes)):
        pin = pins[port.casefold()]
        if port.casefold() in rail_ports:
            inner = fresh(f"a8_dut_{index}")
            source = fresh(f"V_A8_supply_{index}")
            probes.append(f"{source} {node} {inner} 0")
            rail_probes.append((source, inner))
            if pin["type"] == "power" or (not has_supply and pin["type"] != "ground"):
                power_probes.append(source)
            nodes[index] = inner
        elif pin["direction"] == "output":
            inner = fresh(f"a8_dut_{index}")
            source = fresh(f"E_A8_unload_{index}")
            probes.append(f"{source} {node} 0 {inner} 0 1")
            nodes[index] = inner
    if not power_probes:
        raise ValueError("A8 L9 pins do not identify a power rail for quiescent current")
    current = " + ".join(f"i({source})" for source in power_probes)
    power = " + ".join(f"i({source})*{_terminal_voltage_expression(node, '0')}"
                       for source, node in rail_probes)
    includes = [f".include {json.dumps(str(extracted))}"]
    if wrapper is not None:
        includes.append(f".include {json.dumps(str(wrapper))}")
    runtime_paths = {row["path"]: row.get("resolved_path", row["path"])
                     for row in (_validated_model_bindings(models) if models is not None else [])}
    runtime_bindings = []
    for line in bindings:
        fields = shlex.split(line)
        original = Path(fields[1])
        if not original.is_absolute():
            original = (bdir / original).resolve()
        runtime = Path(runtime_paths.get(str(original), str(original)))
        runtime_bindings.append(line if runtime == original else
                                f"{fields[0]} {json.dumps(str(runtime))}" +
                                (f" {fields[2]}" if len(fields) > 2 else ""))
    text = "\n".join(["* A8 native OP from delivered A3 stimulus and model bindings.",
                        *runtime_bindings, *includes, *cards, *precision_cards, *method_cards, *probes,
                        f"XU {' '.join(nodes)} {subckt}", ".control", "set noaskquit", "set num_threads=1", "op",
                        f"let idd = {current}", f"let pwr = {power}",
                        "print idd pwr", "quit", ".endc", ".end", ""])
    return text, {"source_testbench": str(tb.relative_to(project)),
                  "source_design_netlist": str(a3.relative_to(project)),
                  "model_binding_lines": bindings, "power_sources": supplies,
                  "native_op_precision": precision,
                  "native_op_solver": solver,
                  "native_measurement": "unloaded native OP sum(V(DUT rail)*I(DUT rail probe))"}


def _native_op_precision(cards: List[str]) -> Tuple[List[str], Dict]:
    """Tighten OP iteration precision; never change the residual acceptance.

    The native default reltol can stop iteration before the unchanged native
    KCL check is satisfied on extracted networks. Preserve a stricter source
    tolerance, and leave unresolved source expressions for ngspice to evaluate.
    """
    stated = []
    for card in cards:
        if re.match(r"(?i)^\s*\.opt(?:ion|ions)?\b", card):
            stated.extend(re.findall(r"(?i)\breltol\s*=\s*(\{[^}]*\}|[^\s,]+)", card))
    values = [_a7.spice_number(token) for token in stated]
    if any(value is None for value in values):
        return [], {"source_reltol": stated, "reltol": None,
                    "selection": "source_expression_preserved"}
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("A8 source reltol must be finite and positive")
    reltol = min([1e-5, *values])
    return [f".options reltol={reltol:.12g}"], {
        "source_reltol": stated, "reltol": reltol,
        "selection": "stricter_of_source_and_native_op_precision",
        "residual_acceptance": "unchanged_native_check"}


def _native_op_solver(cards: List[str]) -> Tuple[List[str], Dict]:
    methods = [value for card in cards if re.match(r"(?i)^\s*\.opt(?:ion|ions)?\b", card)
               for value in re.findall(r"(?i)\bmethod\s*=\s*([^\s,]+)", card)]
    return ([] if methods else [".options method=gear"]), {
        "method": methods[-1] if methods else "gear",
        "selection": "delivered_source" if methods else "native_op_default",
        "num_threads": 1, "omp_wait_policy": "PASSIVE", "gomp_spincount": 0}


def _validated_model_bindings(value: object) -> List[Dict]:
    """Validate model path and section values before composing the deck."""
    error = "A8_MODEL_ASSET_UNRESOLVED: malformed model_bindings"
    if not isinstance(value, list) or not value:
        raise ValueError(f"{error}: expected a non-empty list")
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"{error}[{index}]: expected an object")
        for field in ("path", "resolved_path"):
            if field == "resolved_path" and field not in row:
                continue
            path = row.get(field)
            if not isinstance(path, str) or not path.strip() or "\x00" in path:
                raise ValueError(f"{error}[{index}].{field}: expected a path string")
        if "section" not in row or (row["section"] is not None and
                (not isinstance(row["section"], str) or not row["section"].strip())):
            raise ValueError(f"{error}[{index}].section: expected a string or null")
    return value


def _runtime_model_path(path: Path) -> Path:
    """Resolve an absent declared model through the actual installed PDK tree."""
    if path.is_file():
        return path
    family = next((path.parts[i - 1] for i, part in enumerate(path.parts)
                   if i > 0 and part in ("libs.tech", "libs.ref")), None)
    resolved = resolve_state_pdk_asset(path, pdk=family)
    if resolved is None:
        raise ValueError(f"A8_MODEL_ASSET_UNRESOLVED: missing or ambiguous model: {path}")
    return resolved


def _bound_models(container: str, lines: List[str], directory: Path) -> List[Dict]:
    records = []
    for line in lines:
        fields = shlex.split(line)
        if len(fields) < 2:
            raise ValueError("A8 delivered model binding is incomplete")
        path = Path(fields[1])
        if not path.is_absolute():
            path = (directory / path).resolve()
        runtime = path
        if container not in ("", "host"):
            readable = _docker_exec_raw(container, f"test -r {shlex.quote(str(path))}")[0] == 0
        else:
            if not path.is_file():
                runtime = _runtime_model_path(path)
            readable = runtime.is_file() and os.access(runtime, os.R_OK)
        if not readable:
            raise ValueError(f"A8_MODEL_ASSET_UNRESOLVED: A8 delivered model source cannot be read: {path}")
        record = {"path": str(path), "section": fields[2] if len(fields) > 2 else None}
        if runtime != path:
            record["resolved_path"] = str(runtime)
        records.append(record)
    return records


def _native_measurement_produce(project: Path, block: str, container: str,
                                pdk_root: str, gds: Path,
                                topology: Dict[str, object], *, ngspice_bin: Optional[str] = None,
                                native_attempts=None
                                ) -> Tuple[Optional[Dict[str, object]], str]:
    """Ordinary A8 producer path: extract the A5 view, then measure power.

    This is intentionally owned by the A8 producer.  A caller does not create
    ``a8_measurement.json`` by hand; the producer writes it only after Magic
    and ngspice return a native result.
    """
    bdir = project / "phase3" / "analog" / block
    layout = bdir / "layout.mag"
    if not layout.is_file():
        return None, f"no A5 layout.mag at {layout}"
    tech = layout_tech(bdir)
    if not tech:
        return None, "A5 layout declares no Magic technology"
    rcfile = magicrc_for(pdk_root, container, tech)
    native_binary, why = _selected_native_binary(container, ngspice_bin)
    if native_binary is None:
        return None, why
    ngspice_bin = native_binary["path"]

    stage = bdir / ".a8_native_stage"
    extracted = bdir / "a8_post_layout_extracted.spice"
    extract_log = bdir / "a8_native_magic_extract.log"
    ng_log = bdir / "a8_native_ngspice.log"
    deck = bdir / "a8_native_measurement.sp"
    try:
        if stage.exists():
            shutil.rmtree(stage)
        ok, stage_why = _stage_layout_subtree(layout, stage, block)
        if not ok:
            return None, stage_why
        # Extract one physical network; hierarchy can duplicate resistor nets.
        tcl = "\n".join([
            f"load {block}",
            f"cellname rename {block} {block}__a8_hier",
            "select top cell",
            f"flatten -dotoplabels {block}",
            "",
        ]) + _mx.build_extraction_tcl(
            block, f"{block}_extracted.spice",
            _mx.MagicResimExtractOptions())
        (stage / "a8_extract.tcl").write_text(tcl)
        magic_cmd = (
            f"cd {shlex.quote(str(stage))} && magic -dnull -noconsole "
            f"-rcfile {shlex.quote(rcfile)} a8_extract.tcl")
        if native_attempts is not None:
            native_attempts.append({"tool": "magic", "operation": "post_layout_extract"})
        magic_rc, magic_out, magic_err = _docker_exec(
            container, magic_cmd, marker="a8_extract.tcl")
        extract_log.write_text((magic_out or "") + (magic_err or ""))
        stage_net = stage / f"{block}_extracted.spice"
        if magic_rc != 0 or not stage_net.is_file() \
                or stage_net.stat().st_size == 0:
            return None, (f"Magic extraction rc={magic_rc} did not write "
                          f"{stage_net.name}; see {extract_log.name}")
        try:
            extracted.write_bytes(stage_net.read_bytes())
        except OSError as exc:
            return None, f"cannot publish extracted netlist: {exc}"

        extracted_text = extracted.read_text(errors="replace")
        ports = _aw.native_ports(extracted_text, block)
        declared = list(topology.get("ports") or [])
        wrapper_contract = None
        wrapper_path = None
        subckt = block
        if ports != declared:
            wrapper_contract, wrapper_text = _extraction_wrapper_contract(
                project, block, extracted, topology)
            wrapper_path = project / wrapper_contract["path"]
            atomic_write_text(wrapper_path, wrapper_text)
            ports = declared
            subckt = wrapper_contract["wrapper_subckt"]

        deck_text, source_contract = _delivered_measurement_deck(
            project, block, extracted, ports, subckt, topology, wrapper_path)
        models = _bound_models(container, source_contract["model_binding_lines"], bdir)
        if any("resolved_path" in model for model in models):
            deck_text, source_contract = _delivered_measurement_deck(
                project, block, extracted, ports, subckt, topology, wrapper_path, models=models)
        model_path, model_section = models[0]["path"], models[0]["section"]
        deck.write_text(deck_text)
        if native_attempts is not None:
            native_attempts.append({"tool": "ngspice", "operation": "post_layout_op"})
        ngspice_rc, ng_out, ng_err = _docker_exec(
            container,
            f"cd {shlex.quote(str(bdir))} && "
            f"OMP_WAIT_POLICY=PASSIVE GOMP_SPINCOUNT=0 {shlex.quote(ngspice_bin)} -b -o "
            f"{shlex.quote(str(ng_log))} {shlex.quote(str(deck))}",
            marker="a8_native_measurement.sp")
        if not ng_log.is_file():
            ng_log.write_text((ng_out or "") + (ng_err or ""))
        log_text = ng_log.read_text(errors="replace")
        pwr = re.search(r"(?im)^\s*pwr\s*=\s*([-+0-9.eE]+)", log_text)
        idd = re.search(r"(?im)^\s*idd\s*=\s*([-+0-9.eE]+)", log_text)
        if _INVALID_OP_RE.search(log_text):
            return None, f"ngspice reported invalid operating point (RESIDUAL_FAIL); see {ng_log.name}"
        import analog_real_corner_sweep as _ars
        native_errors = _ars._scan_analysis_failures(log_text)
        if ngspice_rc != 0 or pwr is None or any(native_errors):
            return None, (f"ngspice rc={ngspice_rc} has no native idd/pwr "
                          f"result; see {ng_log.name}")
        power_w = float(pwr.group(1))
        measured_current = float(idd.group(1)) if idd is not None else None
        if not _valid_leakage_power(power_w, topology):
            return None, f"native pwr result is not finite and positive: {power_w!r}"

        rec: Dict[str, object] = {
            "block": block,
            "status": "MEASURED",
            "metric": "cell_leakage_power",
            "value": power_w,
            "unit": "W",
            **source_contract,
            "measurement_basis": "delivered_a3_testbench_op",
            "model_bindings": models,
            "native_binary": native_binary,
            "measured_current_a": measured_current,
            "source_layout": str(layout.relative_to(project)),
            "source_gds": str(gds.relative_to(project)),
            "source_netlist": str(extracted.relative_to(project)),
            "native_log": str(ng_log.relative_to(project)),
            "native_extraction_log": str(extract_log.relative_to(project)),
            "simulator": "ngspice native post-layout .op",
            "model_source": model_path,
            "model_section": model_section,
            "declared_ports": list(topology.get("ports") or []),
            "measurement_deck": str(deck.relative_to(project)),
        }
        if wrapper_contract is not None:
            rec["extraction_wrapper"] = wrapper_contract
            rec["measurement_deck"] = str(deck.relative_to(project))
        write_json(bdir / _A8_MEASUREMENT, rec)
        return rec, ""
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return None, f"ordinary native measurement producer failed: {exc}"
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _project_file(project: Path, raw: object, *, field: str
                  ) -> Tuple[Optional[Path], str]:
    if not isinstance(raw, str) or not raw.strip():
        return None, f"{field} is absent"
    p = Path(raw)
    cand = p if p.is_absolute() else project / p
    try:
        resolved = cand.resolve()
        resolved.relative_to(project.resolve())
    except (OSError, ValueError):
        return None, f"{field} is outside the project or unreadable: {raw!r}"
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        return None, f"{field} does not name a non-empty project file: {raw!r}"
    return resolved, ""


def load_native_measurement(project: Path, block: str, gds: Path,
                            topology: Dict) -> Tuple[Optional[Dict[str, object]], str]:
    """Read native OP power and its physical interface for Liberty emission."""
    bdir = project / "phase3" / "analog" / block
    path = bdir / _A8_MEASUREMENT
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"native measurement is unavailable: {exc}"
    if not isinstance(rec, dict):
        return None, "native measurement must contain an object"
    if rec.get("block") != block:
        return None, "native measurement names a different block"
    if rec.get("status") != "MEASURED":
        return None, "native power was not measured"
    if rec.get("metric") != "cell_leakage_power":
        return None, "unsupported A8 measurement metric"
    source_netlist, why = _project_file(project, rec.get("source_netlist"), field="source_netlist")
    if source_netlist is None:
        return None, why
    native_log, why = _project_file(project, rec.get("native_log"), field="native_log")
    if native_log is None:
        return None, why
    try:
        ports = _aw.native_ports(source_netlist.read_text(errors="replace"), block)
        declared = list(topology.get("ports") or [])
        if ports != declared:
            wrapper = rec.get("extraction_wrapper")
            if not isinstance(wrapper, dict):
                return None, "expanded extraction requires an interface wrapper"
            wrapper_path, why = _project_file(project, wrapper.get("path"), field="extraction_wrapper")
            if wrapper_path is None:
                return None, why
            wrapper_ports = _aw.native_ports(wrapper_path.read_text(), wrapper.get("wrapper_subckt", ""))
            if wrapper_ports != declared:
                return None, "extraction wrapper ports do not match topology ports"
        log_text = native_log.read_text(errors="replace")
    except (OSError, ValueError) as exc:
        return None, f"native extraction or log is unreadable: {exc}"
    if _INVALID_OP_RE.search(log_text):
        return None, "ngspice reported invalid operating point (RESIDUAL_FAIL)"
    import analog_real_corner_sweep as _ars
    if any(_ars._scan_analysis_failures(log_text)):
        return None, "native power log contains a simulator failure"
    pwr = re.search(r"(?im)^\s*pwr\s*=\s*([-+0-9.eE]+)", log_text)
    idd = re.search(r"(?im)^\s*idd\s*=\s*([-+0-9.eE]+)", log_text)
    source_based = rec.get("measurement_basis") == "delivered_a3_testbench_op"
    if pwr is not None:
        power_w = float(pwr.group(1))
    elif idd is not None and not source_based:
        power_w = abs(float(idd.group(1))) * 1.2
    else:
        return None, "native_log has no ngspice terminal-power result"
    if not _valid_leakage_power(power_w, topology):
        return None, "native cell_leakage_power is not finite and positive; zero requires passive inventory"
    out = dict(rec)
    out.update(value=power_w, unit="W", liberty_value=power_w * _POWER_TO_UW["w"], liberty_power_unit="1uW")
    return out, ""


def emit_block(project: Path, block: str, container: str, pdk_root: str, *, ngspice_bin: Optional[str] = None,
               native_attempts=None) -> Dict:
    """Publish attempts to an optional per-call sink even if later work raises."""
    native_attempts = native_attempts if native_attempts is not None else []
    try:
        result = _emit_block(project, block, container, pdk_root,
                             ngspice_bin=ngspice_bin, native_attempts=native_attempts)
    except MagicrcRefusal as exc:
        result = {"block": block, "emitted": False, "rc": 2, "reason": str(exc)}
    except (OSError, subprocess.SubprocessError) as exc:
        result = {"block": block, "emitted": False, "rc": 2,
                  "reason": f"native export transport unavailable: {exc}"}
    return dict(result, native_attempts=native_attempts)


def _emit_block(project: Path, block: str, container: str, pdk_root: str, *,
                ngspice_bin: Optional[str] = None, native_attempts) -> Dict:
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
    if not pdk_root:
        rc, root, _err = _docker_exec(container, 'printf "%s" "${PDK_ROOT:-}"')
        pdk_root = root.strip() if rc == 0 else ""
        if not pdk_root:
            return {"block": block, "emitted": False, "rc": 2,
                    "reason": "selected runtime declares no PDK_ROOT"}
    topology = json.loads(topo.read_text())
    measurement, measurement_reason = load_native_measurement(
        project, block, gds, topology)
    if measurement is not None and measurement.get("measurement_basis") != "delivered_a3_testbench_op":
        measurement, measurement_reason = None, "cached measurement predates unloaded DUT power recipe"
    if measurement is None:
        produced, produce_reason = _native_measurement_produce(
            project, block, container, pdk_root, gds, topology,
            native_attempts=native_attempts,
            **({"ngspice_bin": ngspice_bin} if ngspice_bin is not None else {}))
        if produced is None:
            return {"block": block, "emitted": False, "rc": 1,
                    "reason": (f"{measurement_reason}; ordinary native "
                               f"producer: {produce_reason}")}
        measurement, measurement_reason = load_native_measurement(
            project, block, gds, topology)
        if measurement is None:
            return {"block": block, "emitted": False, "rc": 1,
                    "reason": ("ordinary native producer wrote a record "
                               f"that could not be admitted: {measurement_reason}")}
    tech = layout_tech(bdir)
    rcfile = magicrc_for(pdk_root, container, tech)
    hdir.mkdir(parents=True, exist_ok=True)
    tcl = hdir / f"{block}_lef.tcl"
    lef = hdir / f"{block}.lef"
    # Docker may execute Magic as root. Pre-create its unique output as the
    # caller, then publish only a successful nonempty native result. A prior
    # delivered LEF is never truncated, reused after native failure, or chowned.
    with tempfile.TemporaryDirectory(prefix=f".{block}-native-lef-", dir=hdir) as staging:
        native_lef = Path(staging) / f"{block}.lef"
        native_lef.write_text("")
        tcl.write_text(build_lef_tcl(block, str(gds), str(native_lef)))
        native_attempts.append({"tool": "magic", "operation": "lef_export"})
        rc, out, err = _docker_exec(
            container,
            f"cd {shlex.quote(str(hdir))} && magic -dnull -noconsole "
            f"-rcfile {shlex.quote(rcfile)} {shlex.quote(tcl.name)}",
            marker=tcl.name)
        if rc != 0 or not native_lef.is_file() or native_lef.stat().st_size == 0:
            return {"block": block, "emitted": False, "rc": 2,
                    "reason": f"magic wrote no valid LEF (rc={rc})",
                    "tail": (out + err)[-300:]}
        lef_text = native_lef.read_text(errors="replace")
    # THE CARVE STAYS ON, AND HERE IS THE HYPOTHESIS THAT DIED.
    #
    # Chip-level Magic extraction reports thousands of `Illegal overlap
    # between obsmN and metalN` entries, which aborts LVS as "extracted
    # netlist untrustworthy". The obvious suspect was this carve: it deletes
    # obstruction, so the router can route where the macro really has metal.
    # MEASURED with the carve fully OFF: 3,719 entries against 3,716 with it
    # on. The carve is not the cause, and the default stays where round 12
    # put it rather than moving on a refuted story.
    #
    # What the same arm DID establish: routing no longer needs the carve.
    # `pnr` PASSes with an uncarved abstract, because the generator now paints
    # a real 2.0 x 1.5 um port pad and Magic's own `lef write` leaves that pin
    # exposed by itself (measured uncarved: pin 1.2 x 0.7 um, OBS flush on
    # three sides and 0.21 um clear on the fourth). So a caller may set the
    # clearance to 0 and keep a whole, more faithful obstruction — the two
    # arms are simply not yet separable on the sign-off DRC number, because
    # the runner streamed one of them with magic and the other with klayout.
    _rails_map = json.loads(topo.read_text()).get("rails") or {}
    _pg_text, n_pg = annotate_pg_pins(lef_text,
                                      _rails_map)
    _sig_text, n_sig = annotate_signal_pins(_pg_text,
                                            signals)
    halo = float(os.environ.get("A8_PIN_ACCESS_CLEARANCE_UM", "0.6"))
    carved, n_carved = ((_sig_text, 0) if halo <= 0
                        else carve_pin_access(_sig_text, halo))
    atomic_write_text(lef, carved)
    (hdir / f"{block}.gds").write_bytes(gds.read_bytes())
    (hdir / f"{block}.v").write_text(interface_verilog(block, rails, signals))
    (hdir / f"{block}.lib").write_text(
        interface_liberty(block, rails, signals, measurement))
    census = lef_pin_census(lef.read_text(errors="replace"))
    characterization_scope = {
        "interface": "ports_and_power_ground",
        "dc_power": "native_op_at_delivered_testbench_conditions",
        "timing_arcs": "NOT_MEASURED",
        "full_timing_characterization": False,
    }

    return {"block": block, "emitted": True, "rc": 0,
            "characterization_scope": characterization_scope,
            "lef_bytes": lef.stat().st_size,
            "obs_rects_carved_for_pin_access": n_carved,
            "pg_pins_declared": n_pg,
            "signal_pins_declared": n_sig,
            "pin_access_clearance_um": halo,
            # MEASURED on the LEF just written — never the topology's count.
            # The count this used to print ("4 pin(s)" from the topology) was
            # printed beside a LEF with ZERO pins (T94).
            "pins": len(census),
            "lef_pins": census,
            "declared_ports": len(rails) + len(signals),
            "rails": rails, "signals": signals,
            "magicrc": rcfile,
            "source_gds": str(gds.relative_to(project)),
            "native_measurement": str((bdir / _A8_MEASUREMENT).relative_to(project))}


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
    ap.add_argument("--container", default=_pin.default_container_name())
    ap.add_argument("--pdk-root", default="",
                    help="PDK root in the selected runtime (default: its PDK_ROOT)")
    ap.add_argument("--ngspice-bin", default=None, help="Absolute ngspice executable path in the selected execution environment")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    project = Path(a.project)
    blocks = a.block or declared_blocks(project)
    if not blocks:
        print("A8_EMIT: no declared analog block — nothing to package")
        return 0
    results = [emit_block(project, b, a.container, a.pdk_root,
                          **({"ngspice_bin": a.ngspice_bin} if a.ngspice_bin is not None else {})) for b in blocks]
    worst = max(r["rc"] for r in results)
    for r in results:
        print("A8_EMIT %s: %s" % (
            r["block"],
            ("lef %d B, %d pin(s) in the LEF of %s declared [%s]" % (
                r["lef_bytes"], r["pins"], r.get("declared_ports", "?"),
                ", ".join("%s:%s" % (p["pin"], "/".join(p["layers"]))
                          for p in r.get("lef_pins", []))))
            if r["emitted"] else "REFUSED — " + r["reason"]))
    if a.json:
        # Atomic (vibe-ic#1082): the declared report appears under its final
        # name only once complete — never a truncated document to a reader.
        write_json(a.json, {"blocks": results, "rc": worst})
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
