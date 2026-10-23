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
import hashlib
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
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import magic_extract_spice_emit as _mx  # noqa: E402 — ordinary A7 extraction producer
import analog_a7_post_layout_emit as _a7  # noqa: E402 — source model/TB relocation
import _analog_a8_extraction_wrapper as _aw  # noqa: E402
from _analog_a_check_common import (  # noqa: E402
    DESIGN_CONTENT_FIELD, content_disclosed, load_block_list,
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
           '  capacitive_load_unit (1, pf);',
           f'  cell ({block}) {{',
           '    is_macro_cell : true;',
           '    interface_timing : false;']
    if measurement is not None:
        value = measurement["liberty_value"]
        unit = measurement["liberty_power_unit"]
        out += [f'    leakage_power_unit : "{unit}";',
                f'    cell_leakage_power : {value:.12g};']
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
_A8_MEASUREMENT_SCHEMA = "vibe-ic/analog_a8_native_measurement/1"
_POWER_TO_UW = {
    "w": 1_000_000.0,
    "mw": 1_000.0,
    "uw": 1.0,
    "nw": 0.001,
    "pw": 0.000001,
}
_POWER_TO_W = {unit: factor * 1e-6
               for unit, factor in _POWER_TO_UW.items()}

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
_MAG_USE_RE = re.compile(r"(?im)^\s*use\s+(\S+)")
_INVALID_OP_RE = re.compile(r"(?m)^\s*;;RESIDUAL_FAIL\b")


def _runtime_image_digest(container: str) -> Tuple[Optional[str], str]:
    """Resolve the execution image identity without asking a user to author it.

    A named container is checked through the shared image identity helper.  A
    native child (``container`` empty/``host``) receives the pinned identity
    from the launch environment; the fallback is the ordinary host resolver,
    which is useful when this producer is run outside a child.  A missing or
    malformed identity refuses the measurement record rather than storing a
    free-form string.
    """
    if container not in ("", "host"):
        try:
            digest, why = _pin.container_image_digest(container)
        except Exception as exc:  # pragma: no cover - environment refusal
            return None, f"container image identity probe failed: {exc}"
        if digest and _DIGEST_RE.fullmatch(str(digest)):
            return str(digest), "container_image_digest"
        return None, why or "container image identity is absent or malformed"
    for name in ("VIBEIC_RUNTIME_IMAGE_DIGEST", "VIBEIC_IMAGE_DIGEST"):
        value = os.environ.get(name, "").strip()
        if _DIGEST_RE.fullmatch(value):
            return value, f"environment:{name}"
    try:
        value = str(_pin.resolved_image_digest()).strip()
    except Exception:
        value = ""
    if _DIGEST_RE.fullmatch(value):
        return value, "host_image_resolver"
    return None, ("native execution image digest is unavailable; the ordinary "
                  "producer will not hand-author provenance")


def _remote_sha256(container: str, path: str) -> Tuple[Optional[str], str]:
    rc, out, err = _docker_exec_raw(
        container, f"sha256sum {shlex.quote(path)} 2>/dev/null")
    for line in (out or "").splitlines():
        m = re.search(r"\b([0-9a-f]{64})\b", line, re.IGNORECASE)
        if m:
            return m.group(1).lower(), ""
    return None, (err or out or f"sha256sum failed for {path}").strip()[:240]


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


def _native_model_contract(container: str, pdk_root: str, tech: str
                           ) -> Tuple[Optional[Dict[str, str]], str]:
    """Find the PDK's sectioned ngspice model contract from its own files.

    The old R2 deck used ``.include cornerMOSlv.lib``.  IHP's file is a
    sectioned entry library and therefore requires ``.lib <file> mos_tt``;
    including it makes ngspice execute the bare ``.lib mos_tt`` section token
    and fail.  This resolver discovers the file/section pair instead of
    spelling a model number into the fixture.
    """
    root = f"{pdk_root.rstrip('/')}/{tech}/libs.tech/ngspice"
    rc, out, err = _docker_exec_raw(
        container,
        f"find {shlex.quote(root)} -type f "
        f"\\( -iname '*.lib' -o -iname '*.spice' \\) -print 2>/dev/null",
    )
    candidates = sorted({line.strip() for line in (out or "").splitlines()
                         if line.strip().startswith("/")})
    scored: List[Tuple[int, str, str]] = []
    for path in candidates:
        rc2, text, _ = _docker_exec_raw(container, f"cat {shlex.quote(path)}")
        if rc2 != 0 or not text.strip():
            continue
        sections = [m.group(1) for m in re.finditer(
            r"(?im)^\s*\.lib\s+([A-Za-z_]\w*)\s*$", text)]
        if not sections:
            continue
        basename = Path(path).name.lower()
        for section in sections:
            low = section.lower()
            score = 0
            if "corner" in basename:
                score += 4
            if "mos" in basename or "nmos" in text.lower() \
                    or "pmos" in text.lower():
                score += 4
            if low in ("mos_tt", "tt", "typ", "typical"):
                score += 5
            if low.endswith("_tt"):
                score += 2
            scored.append((score, path, section))
    if not scored:
        return None, (f"no sectioned ngspice model contract under {root}: "
                      f"{(err or out).strip()[:180]}")
    _score, model_path, section = max(
        scored, key=lambda item: (item[0], item[1], item[2]))
    digest, why = _remote_sha256(container, model_path)
    if digest is None:
        return None, f"model source hash unavailable for {model_path}: {why}"
    return {"path": model_path, "section": section,
            "sha256": digest}, ""


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
    binding, why = _declared_a3_subject_binding(project, block, bdir, topology)
    if binding is None:
        raise ValueError(f"current A3 subject required for wrapper: {why}")
    declared = list(topology.get("ports") or [])
    a3_ports = _aw.native_ports((bdir / f"{block}.sp").read_text(), block)
    if a3_ports != declared:
        raise ValueError("current A3 netlist ports do not equal topology ports")
    text, interface = _aw.build_wrapper(extracted.read_text(), block, declared)
    path = bdir / "a8_extraction_wrapper.spice"
    if path.resolve() == extracted.resolve():
        raise ValueError("wrapper cannot replace raw native extraction")
    return {"path": str(path.relative_to(project)),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            **interface, "subject_binding": binding}, text


def _measurement_deck_text(extracted: Path, ports: List[str], subckt: str,
                           model_path: str, model_section: str,
                           wrapper: Optional[Path] = None) -> str:
    """Reconstruct the original fixed-bias receipt contract, never a new run.

    Fresh ordinary measurements use the delivered A3 sources below. Keeping
    this original recipe preserves the meaning of already published receipts.
    """
    if not isinstance(model_path, str) or not model_path or not isinstance(
            model_section, str) or not re.fullmatch(r"[\w.+-]+", model_section):
        raise ValueError("measurement deck has no explicit PDK model/section")
    includes = [f".include {json.dumps(str(extracted))}"]
    if wrapper is not None:
        includes.append(f".include {json.dumps(str(wrapper))}")
    return "\n".join([
        "* A8 ordinary producer native measurement deck.",
        f".lib {json.dumps(model_path)} {model_section}", *includes,
        "VDD vdd 0 1.2", "VSS vss 0 0", "VIN vin 0 0.6",
        "RLOAD vout 0 1meg", f"XU {' '.join(ports)} {subckt}",
        ".control", "set noaskquit", "op", "let pwr = abs(i(VDD))*1.2",
        "print pwr", "quit", ".endc", ".end", ""])


def _terminal_voltage_expression(positive: str, negative: str) -> str:
    """ngspice control expressions have no named voltage vector for node 0."""
    if positive == "0" and negative == "0":
        return "0"
    if negative == "0":
        return f"v({positive})"
    if positive == "0":
        return f"(-v({negative}))"
    return f"(v({positive})-v({negative}))"


def _delivered_measurement_deck(project: Path, block: str, extracted: Path,
                                ports: List[str], subckt: str,
                                topology: Dict, wrapper: Optional[Path] = None
                                ) -> Tuple[str, Dict]:
    """Replace the DUT in its delivered stimulus; run only native OP power.

    The A3 model bindings and external circuit cards remain the source of the
    conditions. This steady-state deck specializes power-on PWL supply rails
    to their explicit DC bias, or their own final plateau when no DC value is
    stated. The original waveform remains bound through source metadata and
    the testbench hash; the DUT, parasitics and external loads are unchanged.
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
    rail_ports = {str(value).casefold() for value in (topology.get("rails") or {}).values()}
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
    current = " + ".join(f"abs(i({row['source']}))" for row in supplies)
    power = " + ".join(f"abs(i({row['source']})*{_terminal_voltage_expression(row['positive'], row['negative'])})"
                       for row in supplies)
    includes = [f".include {json.dumps(str(extracted))}"]
    if wrapper is not None:
        includes.append(f".include {json.dumps(str(wrapper))}")
    text = "\n".join(["* A8 native OP from delivered A3 stimulus and model bindings.",
                        *bindings, *includes, *cards, *precision_cards, *method_cards,
                        f"XU {' '.join(nodes)} {subckt}", ".control", "set noaskquit", "set num_threads=1", "op",
                        f"let idd = {current}", f"let pwr = {power}",
                        "print idd pwr", "quit", ".endc", ".end", ""])
    return text, {"source_testbench": str(tb.relative_to(project)), "source_testbench_sha256": _sha256(tb),
                  "source_design_netlist": str(a3.relative_to(project)), "source_design_netlist_sha256": _sha256(a3),
                  "model_binding_lines": bindings, "power_sources": supplies,
                  "native_op_precision": precision,
                  "native_op_solver": solver,
                  "native_measurement": "native OP sum(abs(I(source)*V(source terminals)))"}


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


def _bound_models(container: str, lines: List[str], directory: Path) -> List[Dict]:
    records = []
    for line in lines:
        fields = shlex.split(line)
        if len(fields) < 2:
            raise ValueError("A8 delivered model binding is incomplete")
        path = Path(fields[1])
        if not path.is_absolute():
            path = (directory / path).resolve()
        digest = _sha256(path) if path.is_file() else _remote_sha256(container, str(path))[0]
        if digest is None:
            raise ValueError(f"A8 delivered model source cannot be read: {path}")
        records.append({"path": str(path), "section": fields[2] if len(fields) > 2 else None,
                        "sha256": digest})
    return records


def _native_measurement_produce(project: Path, block: str, container: str,
                                pdk_root: str, gds: Path,
                                topology: Dict[str, object], *, ngspice_bin: Optional[str] = None
                                ) -> Tuple[Optional[Dict[str, object]], str]:
    """Ordinary A8 producer path: extract the A5 view, then measure power.

    This is intentionally owned by the A8 producer.  A caller does not create
    ``a8_measurement.json`` by hand; the producer writes it only after Magic
    and ngspice return a source-bound result.
    """
    bdir = project / "phase3" / "analog" / block
    layout = bdir / "layout.mag"
    if not layout.is_file():
        return None, f"no A5 layout.mag at {layout}"
    tech = layout_tech(bdir)
    if not tech:
        return None, "A5 layout declares no Magic technology"
    rcfile = magicrc_for(pdk_root, container, tech)
    if rcfile is None:
        return None, f"no Magic rcfile for A5 technology {tech!r}"
    explicit_binary = ngspice_bin is not None
    if explicit_binary:
        if not Path(ngspice_bin).is_absolute():
            return None, "explicit ngspice binary must be an absolute execution-side path"
        rc, _out, why = _docker_exec_raw(container, f"test -x {shlex.quote(ngspice_bin)}")
        if rc != 0:
            return None, f"explicit ngspice binary is not executable: {ngspice_bin}"
    else:
        ngspice_bin, why = _native_ngspice_binary(container)
    if ngspice_bin is None:
        return None, why
    binary_hash, why = _remote_sha256(container, ngspice_bin)
    if binary_hash is None:
        return None, "selected ngspice binary cannot be hashed: " + why
    native_binary = {"path": ngspice_bin, "sha256": binary_hash,
                     "selection": "explicit" if explicit_binary else "discovered"}
    image_digest, image_why = _runtime_image_digest(container)
    if image_digest is None:
        return None, image_why

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
        tcl = _mx.build_extraction_tcl(
            block, f"{block}_extracted.spice",
            _mx.MagicResimExtractOptions())
        (stage / "a8_extract.tcl").write_text(tcl)
        magic_cmd = (
            f"cd {shlex.quote(str(stage))} && magic -dnull -noconsole "
            f"-rcfile {shlex.quote(rcfile)} a8_extract.tcl")
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
        model_path, model_section = models[0]["path"], models[0]["section"]
        deck.write_text(deck_text)
        # Freeze the files actually consumed. Refuse any mutation during the
        # native call, rather than stamping its result with post-call inputs.
        consumed = [extracted, layout, gds, deck, bdir / f"{block}.sp", bdir / f"tb_{block}.sp"]
        consumed += [Path(model["path"]) for model in models if Path(model["path"]).is_file()]
        if wrapper_path is not None:
            consumed.append(wrapper_path)
        frozen = {p: _sha256(p) for p in consumed}
        ngspice_rc, ng_out, ng_err = _docker_exec(
            container,
            f"cd {shlex.quote(str(bdir))} && "
            f"OMP_WAIT_POLICY=PASSIVE GOMP_SPINCOUNT=0 {shlex.quote(ngspice_bin)} -b -o "
            f"{shlex.quote(str(ng_log))} {shlex.quote(str(deck))}",
            marker="a8_native_measurement.sp")
        if any(_sha256(p) != digest for p, digest in frozen.items()):
            return None, "native measurement input group changed during ngspice"
        if _remote_sha256(container, ngspice_bin)[0] != binary_hash:
            return None, "selected ngspice binary changed during native measurement"
        if _bound_models(container, source_contract["model_binding_lines"], bdir) != models:
            return None, "native measurement model sources changed during ngspice"
        if wrapper_contract is not None:
            try:
                current_contract, _ = _extraction_wrapper_contract(
                    project, block, extracted, topology)
            except ValueError as exc:
                return None, f"current A3/wrapper subject changed during ngspice: {exc}"
            if current_contract != wrapper_contract:
                return None, "current A3/wrapper subject changed during ngspice"
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
        if not math.isfinite(power_w) or power_w <= 0:
            return None, f"native pwr result is not finite and positive: {power_w!r}"

        rec: Dict[str, object] = {
            "schema": _A8_MEASUREMENT_SCHEMA,
            "block": block,
            "status": "MEASURED",
            "provenance": "real_ngspice",
            "metric": "cell_leakage_power",
            "value": power_w,
            "unit": "W",
            **source_contract,
            "measurement_basis": "delivered_a3_testbench_op",
            "model_bindings": models,
            "native_binary": native_binary,
            "measured_current_a": measured_current,
            "source_layout": str(layout.relative_to(project)),
            "source_layout_sha256": _sha256(layout),
            "source_gds": str(gds.relative_to(project)),
            "source_gds_sha256": _sha256(gds),
            "source_netlist": str(extracted.relative_to(project)),
            "source_netlist_sha256": _sha256(extracted),
            "native_log": str(ng_log.relative_to(project)),
            "native_log_sha256": _sha256(ng_log),
            "native_extraction_log": str(extract_log.relative_to(project)),
            "native_extraction_log_sha256": _sha256(extract_log),
            "simulator": "ngspice native post-layout .op",
            "model_source": model_path,
            "model_source_sha256": models[0]["sha256"],
            "model_section": model_section,
            "image_digest": image_digest,
            "declared_ports": list(topology.get("ports") or []),
            "measurement_deck": str(deck.relative_to(project)),
            "measurement_deck_sha256": frozen[deck],
        }
        if wrapper_contract is not None:
            rec["extraction_wrapper"] = wrapper_contract
            rec["measurement_deck"] = str(deck.relative_to(project))
            rec["measurement_deck_sha256"] = frozen[deck]
            rec["subject_binding"] = wrapper_contract["subject_binding"]
            rec[DESIGN_CONTENT_FIELD] = rec["subject_binding"][DESIGN_CONTENT_FIELD]
        write_json(bdir / _A8_MEASUREMENT, rec)
        return rec, ""
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return None, f"ordinary native measurement producer failed: {exc}"
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _declared_a3_subject_binding(project: Path, block: str, bdir: Path,
                                 topology: Dict[str, object]
                                 ) -> Tuple[Optional[Dict[str, object]], str]:
    """Read, never infer, the existing A3 subject declaration.

    A8 binds its native measurement only when the block is declared and A3's
    producer sidecar names the same netlist, topology, and spec bytes.  The R3
    open fixture lacks this sidecar and stays design-content undisclosed.
    """
    declared = load_block_list(project)
    if not declared or block not in declared:
        return None, ""
    sidecar = bdir / "netlist_provenance.json"
    if not sidecar.is_file():
        return None, "declared block has no A3 netlist_provenance.json"
    try:
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"A3 netlist_provenance.json is unreadable: {exc}"
    if not isinstance(doc, dict) or doc.get("block") != block:
        return None, "A3 netlist provenance names a different block"
    prov = doc.get("_provenance")
    if not isinstance(prov, dict):
        return None, "A3 netlist provenance has no _provenance object"
    content = prov.get(DESIGN_CONTENT_FIELD)
    if not content_disclosed(content):
        return None, "A3 netlist provenance has no disclosed design_content"

    topology_path = bdir / "topology.json"
    spec_path = bdir / "spec.json"
    netlist_path = bdir / f"{block}.sp"
    rendered = prov.get("rendered_from")
    if not isinstance(rendered, dict):
        return None, "A3 netlist provenance has no rendered_from inputs"
    topology_claim = rendered.get("topology_json")
    spec_claim = rendered.get("spec_json")
    if not isinstance(topology_claim, dict) or not isinstance(spec_claim, dict):
        return None, "A3 netlist provenance has no topology/spec source claims"
    for path, claim, expected in (
        (topology_path, topology_claim, topology_path),
        (spec_path, spec_claim, spec_path),
    ):
        if claim.get("path") != str(expected.relative_to(project)):
            return None, f"A3 source claim does not name {expected.name}"
        if not path.is_file() or _sha256(path) != str(
                claim.get("sha256") or "").lower():
            return None, f"A3 source claim is stale for {expected.name}"
    if not netlist_path.is_file():
        return None, "A3 declared netlist is absent"
    artifact_hash = str(prov.get("artifact_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_hash) \
            or _sha256(netlist_path) != artifact_hash:
        return None, "A3 declared netlist hash is stale or missing"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"A3 spec is unreadable: {exc}"
    if not isinstance(spec, dict) or spec.get("block") != block:
        return None, "A3 spec does not name the declared block"
    ports = topology.get("ports") if isinstance(topology, dict) else None
    interface = spec.get("interface")
    interface = interface if isinstance(interface, dict) else None
    pins = interface.get("pins") if interface is not None else None
    spec_ports = [p.get("name") for p in (pins or []) if isinstance(p, dict)]
    if not isinstance(ports, list) or not isinstance(pins, list) \
            or spec_ports != ports:
        return None, "A3 spec interface pins do not equal topology ports"
    block_list = next((project / root / "analog_block_list.json"
                       for root in ("phase3/analog", "phase1/analog")
                       if (project / root / "analog_block_list.json").is_file()), None)
    if block_list is None:
        return None, "declared analog block list disappeared"
    binding: Dict[str, object] = {
        "producer": "analog_a8_hardmacro_emit",
        "source": "a3_netlist_provenance",
        "block": block,
        DESIGN_CONTENT_FIELD: content,
        "netlist_provenance": str(sidecar.relative_to(project)),
        "netlist_provenance_sha256": _sha256(sidecar),
        "a3_netlist": str(netlist_path.relative_to(project)),
        "a3_netlist_sha256": artifact_hash,
        "topology": str(topology_path.relative_to(project)),
        "topology_sha256": _sha256(topology_path),
        "spec": str(spec_path.relative_to(project)),
        "spec_sha256": _sha256(spec_path),
        "declared_block_list": str(block_list.relative_to(project)),
        "declared_block_list_sha256": _sha256(block_list),
    }
    return binding, ""


def _attach_declared_subject_binding(project: Path, block: str,
                                     topology: Dict[str, object],
                                     measurement: Dict[str, object]
                                     ) -> Tuple[Optional[Dict[str, object]], str]:
    """Republish a validated A3 subject claim in the ordinary A8 record."""
    bdir = project / "phase3" / "analog" / block
    binding, why = _declared_a3_subject_binding(project, block, bdir, topology)
    if binding is None:
        # Missing/stale A3 input leaves the measured record unbound; the
        # downstream content consumer then preserves its explicit refusal.
        return measurement, why
    path = bdir / _A8_MEASUREMENT
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot update {_A8_MEASUREMENT} subject binding: {exc}"
    old_binding = doc.get("subject_binding")
    if old_binding is not None and old_binding != binding:
        return None, "existing A8 subject binding disagrees with current A3 subject"
    if doc.get(DESIGN_CONTENT_FIELD) not in (None, binding[DESIGN_CONTENT_FIELD]):
        return None, "existing A8 design_content disagrees with current A3 subject"
    if old_binding != binding or doc.get(DESIGN_CONTENT_FIELD) != binding[DESIGN_CONTENT_FIELD]:
        doc[DESIGN_CONTENT_FIELD] = binding[DESIGN_CONTENT_FIELD]
        doc["subject_binding"] = binding
        write_json(path, doc)
        refreshed, refresh_why = load_native_measurement(
            project, block, bdir / f"{block}.gds", topology)
        if refreshed is None:
            return None, f"subject-bound A8 record was not admissible: {refresh_why}"
        return refreshed, ""
    return measurement, ""


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
    """Admit only a typed, native ngspice measurement bound to this input.

    ``cell_leakage_power`` is the only A8 scalar this producer currently
    supports for a pure analog macro.  Timing arcs are deliberately absent:
    a settling result is not a synchronous cell delay.  Every source file is
    resolved inside the project and its digest is recomputed at emission time;
    a stale or hand-written record therefore refuses instead of becoming a
    plausible Liberty value.
    """
    bdir = project / "phase3" / "analog" / block
    path = bdir / _A8_MEASUREMENT
    if not path.is_file():
        return None, (f"no {_A8_MEASUREMENT}: a native ngspice measurement is "
                      "required for the Liberty leakage contract")
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{_A8_MEASUREMENT} is unreadable JSON: {exc}"
    if not isinstance(rec, dict):
        return None, f"{_A8_MEASUREMENT} must contain an object"
    if rec.get("schema") != _A8_MEASUREMENT_SCHEMA:
        return None, (f"{_A8_MEASUREMENT} schema is not "
                      f"{_A8_MEASUREMENT_SCHEMA!r}")
    if rec.get("block") != block:
        return None, (f"{_A8_MEASUREMENT} names block {rec.get('block')!r}, "
                      f"not {block!r}")
    if rec.get("status") != "MEASURED":
        return None, (f"{_A8_MEASUREMENT} status is {rec.get('status')!r}; "
                      "only MEASURED native evidence is admissible")
    if rec.get("provenance") != "real_ngspice":
        return None, (f"{_A8_MEASUREMENT} provenance is "
                      f"{rec.get('provenance')!r}, not real_ngspice")
    if rec.get("metric") != "cell_leakage_power":
        return None, (f"unsupported A8 measurement metric {rec.get('metric')!r}; "
                      "no timing arc or unmeasured power field is invented")
    source_based = rec.get("measurement_basis") == "delivered_a3_testbench_op"
    if rec.get("measurement_basis") is not None and not source_based:
        return None, "unsupported native measurement basis"
    try:
        value = float(rec["value"])
    except (KeyError, TypeError, ValueError):
        return None, f"{_A8_MEASUREMENT} has no numeric measured value"
    unit = str(rec.get("unit") or "").strip().lower()
    if unit not in _POWER_TO_UW:
        return None, f"unsupported measured power unit {rec.get('unit')!r}"
    if not (value > 0.0) or not math.isfinite(value):
        return None, (f"measured cell_leakage_power must be finite and > 0; "
                      f"got {rec.get('value')!r} {rec.get('unit')!r}")

    required = (
        ("source_layout", bdir / "layout.mag"),
        ("source_gds", gds),
        ("source_netlist", None),
        ("native_log", None),
    )
    measurement_path = path
    source_netlist_path: Optional[Path] = None
    native_log_path: Optional[Path] = None
    for field, expected in required:
        hit, why = _project_file(project, rec.get(field), field=field)
        if hit is None:
            return None, why
        if field == "source_layout" and hit != expected.resolve():
            return None, (f"{field} points to {hit.relative_to(project)!s}; "
                          f"expected {expected.relative_to(project)!s}")
        if field == "source_gds" and hit != expected.resolve():
            return None, (f"{field} points to {hit.relative_to(project)!s}; "
                          f"expected {expected.relative_to(project)!s}")
        digest_field = f"{field}_sha256"
        stated = rec.get(digest_field)
        actual = _sha256(hit)
        if not isinstance(stated, str) or stated.lower() != actual:
            return None, (f"{digest_field} is stale/missing for "
                          f"{hit.relative_to(project)}")
        if field == "source_netlist":
            source_netlist_path = hit
        elif field == "native_log":
            native_log_path = hit

    # A3's design netlist is not post-layout evidence.  Reusing it under a
    # different field name would let a Liberty value describe a circuit that
    # the measured layout never produced, so the producer refuses that
    # identity rather than accepting a plausible but wrong source.
    if source_netlist_path == (bdir / f"{block}.sp").resolve():
        return None, ("source_netlist names the A3 input netlist; a native "
                      "post-layout extracted netlist is required")
    try:
        extracted_text = source_netlist_path.read_text(errors="replace") \
            if source_netlist_path is not None else ""
    except OSError as exc:
        return None, f"source_netlist is unreadable: {exc}"
    try:
        extracted_ports = _aw.native_ports(extracted_text, block)
        wrapper = rec.get("extraction_wrapper")
        if "extraction_wrapper" in rec:
            expected, text = _extraction_wrapper_contract(
                project, block, source_netlist_path, topology)
            if wrapper != expected:
                return None, "extraction_wrapper mapping/current A3 subject is stale"
            wrapper_path, why = _project_file(
                project, expected["path"], field="extraction_wrapper")
            if wrapper_path is None:
                return None, why
            if (wrapper_path.read_bytes() != text.encode() or
                    _sha256(wrapper_path) != expected["sha256"]):
                return None, "extraction_wrapper bytes/hash do not match positional map"
            if (rec.get("subject_binding") != expected["subject_binding"] or
                    rec.get(DESIGN_CONTENT_FIELD) != expected["subject_binding"][DESIGN_CONTENT_FIELD]):
                return None, "wrapped measurement lacks current A3 subject binding"
            deck, why = _project_file(project, rec.get("measurement_deck"), field="measurement_deck")
            if deck is None:
                return None, why
            if deck != (bdir / "a8_native_measurement.sp").resolve():
                return None, "measurement_deck is not the ordinary A8 deck"
            wanted = (_delivered_measurement_deck(
                project, block, source_netlist_path, list(topology.get("ports") or []),
                expected["wrapper_subckt"], topology, wrapper_path)[0] if source_based else
                _measurement_deck_text(source_netlist_path, list(topology.get("ports") or []),
                    expected["wrapper_subckt"], rec.get("model_source"), rec.get("model_section"), wrapper_path))
            if (deck.read_bytes() != wanted.encode() or
                    _sha256(deck) != rec.get("measurement_deck_sha256")):
                return None, "measurement_deck bypasses raw/wrapper group or is stale"
            if _sha256(source_netlist_path) != rec["source_netlist_sha256"]:
                return None, "raw native extraction changed while reading wrapper group"
        elif extracted_ports != list(topology.get("ports") or []):
            return None, (f"source_netlist .subckt {block!r} ports "
                          f"{extracted_ports!r} do not match topology ports; "
                          "expanded extraction requires a bound wrapper")
        elif ("measurement_deck" in rec or "measurement_deck_sha256" in rec) and not source_based:
            return None, "measurement deck without extraction_wrapper group"
        if source_based:
            wrapper_path = project / wrapper["path"] if isinstance(wrapper, dict) else None
            wanted, source_contract = _delivered_measurement_deck(
                project, block, source_netlist_path, list(topology.get("ports") or []),
                wrapper["wrapper_subckt"] if isinstance(wrapper, dict) else block, topology, wrapper_path)
            if any(rec.get(key) != value for key, value in source_contract.items()):
                return None, "delivered A3 testbench/model/power source binding is stale"
            deck, why = _project_file(project, rec.get("measurement_deck"), field="measurement_deck")
            if deck is None or deck != (bdir / "a8_native_measurement.sp").resolve():
                return None, why or "measurement_deck is not the ordinary A8 deck"
            if deck.read_text() != wanted or _sha256(deck) != rec.get("measurement_deck_sha256"):
                return None, "measurement_deck does not preserve the delivered DUT testbench"
            models = rec.get("model_bindings")
            lines = source_contract["model_binding_lines"]
            if not isinstance(models, list) or len(models) != len(lines):
                return None, "native measurement does not bind all delivered model libraries"
            for line, model in zip(lines, models):
                fields = shlex.split(line)
                path = Path(fields[1])
                if not path.is_absolute():
                    path = (bdir / path).resolve()
                if (not isinstance(model, dict) or model.get("path") != str(path)
                        or model.get("section") != (fields[2] if len(fields) > 2 else None)
                        or not re.fullmatch(r"[0-9a-f]{64}", str(model.get("sha256", "")))
                        or (path.is_file() and _sha256(path) != model["sha256"])):
                    return None, "native measurement model closure binding is stale or incomplete"
    except (OSError, ValueError, TypeError) as exc:
        return None, f"native extraction/wrapper group refused: {exc}"

    # The digest proves which log was consumed; this small semantic check
    # proves it is an ngspice measurement log rather than an arbitrary
    # non-empty text file.  The native contract emits a control-language
    # `pwr = ...` vector result from the solved source current.  Older
    # receipts with a direct measured `idd = ...` remain admissible and are
    # checked below as the same scalar contract.
    try:
        log_text = native_log_path.read_text(errors="replace") \
            if native_log_path is not None else ""
    except OSError as exc:
        return None, f"native_log is unreadable: {exc}"
    pwr_match = re.search(r"(?im)^\s*pwr\s*=\s*([-+0-9.eE]+)", log_text)
    idd_match = re.search(r"(?im)^\s*idd\s*=\s*([-+0-9.eE]+)", log_text)
    if _INVALID_OP_RE.search(log_text):
        return None, "native power receipt reports an invalid operating point (RESIDUAL_FAIL)"
    if pwr_match is None and idd_match is None:
        return None, ("native_log has no ngspice pwr/idd result; a typed "
                      "value without its measured terminal-power receipt is "
                      "not admissible")
    native_power_w: Optional[float] = None
    if pwr_match is not None:
        native_power_w = float(pwr_match.group(1))
    if source_based and pwr_match is None:
        return None, "source-preserving native measurement lacks terminal-power pwr"
    if source_based:
        import analog_real_corner_sweep as _ars
        if any(_ars._scan_analysis_failures(log_text)):
            return None, "native source-preserving power log contains a simulator failure"
    if idd_match is not None and not source_based:
        idd_power_w = abs(float(idd_match.group(1))) * 1.2
        if native_power_w is not None and not math.isclose(
                native_power_w, idd_power_w, rel_tol=1e-6, abs_tol=1e-18):
            return None, ("native pwr and I(VDD) receipts disagree")
        native_power_w = idd_power_w
    record_power_w = value * _POWER_TO_W[unit]
    if native_power_w is None or not math.isclose(
            record_power_w, native_power_w, rel_tol=1e-6, abs_tol=1e-18):
        return None, ("measured value does not match native pwr/ I(VDD) "
                      "receipt")

    if str(rec.get("simulator") or "").lower().find("ngspice") < 0:
        return None, "native measurement does not identify ngspice"
    image = rec.get("image_digest")
    if not isinstance(image, str) or not _DIGEST_RE.fullmatch(image):
        return None, "native measurement lacks a pinned image digest"
    if rec.get("model_source") is not None:
        model_hash = rec.get("model_source_sha256")
        if not isinstance(model_hash, str) \
                or not re.fullmatch(r"[0-9a-f]{64}", model_hash,
                                    re.IGNORECASE):
            return None, "native measurement lacks a typed PDK model hash"
    # The input declaration is part of the typed record.  It is not used as a
    # substitute for the files above, but it keeps the producer/consumer
    # contract explicit for a later stale-input audit.
    if rec.get("declared_ports") != list(topology.get("ports") or []):
        return None, ("native measurement declared_ports do not equal the "
                      "block's topology ports")

    out = dict(rec)
    out["liberty_value"] = value * _POWER_TO_UW[unit]
    out["liberty_power_unit"] = "1uW"
    # This is the receipt's own JSON, not the extraction wrapper that was
    # validated above.  Keep the two paths distinct: reusing ``path`` here
    # would publish the wrapper digest under ``measurement_sha256``.
    out["measurement_sha256"] = _sha256(measurement_path)
    if "native_binary" in rec:
        binary = rec["native_binary"]
        if (not isinstance(binary, dict) or not isinstance(binary.get("path"), str)
                or not Path(binary["path"]).is_absolute()
                or not re.fullmatch(r"[0-9a-f]{64}", str(binary.get("sha256", "")))):
            return None, "native binary provenance is absent or malformed"
    return out, ""


def emit_block(project: Path, block: str, container: str, pdk_root: str, *, ngspice_bin: Optional[str] = None,
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
    topology = json.loads(topo.read_text())
    measurement, measurement_reason = load_native_measurement(
        project, block, gds, topology)
    if measurement is not None and ngspice_bin is not None:
        digest = _remote_sha256(container, ngspice_bin)[0]
        prior_binary = measurement.get("native_binary") or {}
        if digest is None or prior_binary.get("path") != ngspice_bin or prior_binary.get("sha256") != digest:
            measurement, measurement_reason = None, "cached native measurement used a different selected binary"
    if measurement is None:
        produced, produce_reason = _native_measurement_produce(
            project, block, container, pdk_root, gds, topology, **({"ngspice_bin": ngspice_bin} if ngspice_bin is not None else {}))
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
    measurement, subject_reason = _attach_declared_subject_binding(
        project, block, topology, measurement)
    if measurement is None:
        return {"block": block, "emitted": False, "rc": 1,
                "reason": f"declared subject binding refused: {subject_reason}"}
    tech = layout_tech(bdir)
    rcfile = magicrc_for(pdk_root, container, tech)
    if rcfile is None:
        return {"block": block, "emitted": False, "rc": 2,
                "reason": (f"no magicrc under {pdk_root} for the technology the "
                           f"layout declares ({tech or 'undeclared'})")}
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
    # Bind all four views to the exact sign-off GDS bytes consumed here. The
    # A8 gate remains a reader; this manifest is emitted only by this producer
    # and lets A8/M1 reject a copied or subsequently mutated view.
    views = {suffix: hdir / f"{block}{suffix}"
             for suffix in (".lef", ".lib", ".gds", ".v")}
    manifest = {
        "schema": "vibe-ic/analog_a8_views/1",
        "producer": "analog_a8_hardmacro_emit",
        "block": block,
        "characterization_scope": {
            "interface": "ports_and_power_ground",
            "dc_power": "native_op_at_delivered_testbench_conditions",
            "timing_arcs": "NOT_MEASURED",
            "full_timing_characterization": False,
        },
        "source_gds": str(gds.relative_to(project)),
        "source_gds_sha256": _sha256(gds),
        "views": {suffix: {"path": str(path.relative_to(project)),
                           "sha256": _sha256(path)}
                  for suffix, path in views.items()},
        "native_measurement": {
            "path": str((bdir / _A8_MEASUREMENT).relative_to(project)),
            "sha256": measurement["measurement_sha256"],
            "metric": measurement["metric"],
            "value": measurement["value"],
            "unit": measurement["unit"],
            "provenance": measurement["provenance"],
            "source_netlist": measurement["source_netlist"],
            "source_netlist_sha256": measurement["source_netlist_sha256"],
            "native_log": measurement["native_log"],
            "native_log_sha256": measurement["native_log_sha256"],
            "simulator": measurement["simulator"],
            "image_digest": measurement["image_digest"],
        },
    }
    for key in ("extraction_wrapper", "measurement_deck", "measurement_deck_sha256", "native_binary", "native_op_solver"):
        if key in measurement:
            manifest["native_measurement"][key] = measurement[key]
    if DESIGN_CONTENT_FIELD in measurement:
        manifest["native_measurement"][DESIGN_CONTENT_FIELD] = \
            measurement[DESIGN_CONTENT_FIELD]
    if "subject_binding" in measurement:
        manifest["native_measurement"]["subject_binding"] = \
            measurement["subject_binding"]
    write_json(hdir / "a8_views_provenance.json", manifest)

    return {"block": block, "emitted": True, "rc": 0,
            "characterization_scope": manifest["characterization_scope"],
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
            "source_gds_sha256": manifest["source_gds_sha256"],
            "views_provenance": str(
                (hdir / "a8_views_provenance.json").relative_to(project))}


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
    ap.add_argument("--pdk-root", default="/foss/pdks")
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
