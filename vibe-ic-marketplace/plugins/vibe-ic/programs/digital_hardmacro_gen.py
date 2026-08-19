#!/usr/bin/env python3
"""digital_hardmacro_gen.py — the PRODUCER for flow step 37.5ip.

Assembles the four-view IP delivery kit the cell/IP path terminates in:

    phase3/stage4/hardmacro/<design>.gds   staged from step 37's sign-off GDS
    phase3/stage4/hardmacro/<design>.lef   written by MAGIC, from that GDS
    phase3/stage4/hardmacro/<design>.lib   interface Liberty, from the DEF PINS
    phase3/stage4/hardmacro/<design>.v     blackbox view, from the DEF PINS

WHY THIS PRODUCER EXISTS AT ALL
===============================
MEASURED on this tree before this program: a completed digital sign-off run
(`phase3/stage4/gds/<top>.gds` present, DRC/LVS/STA closed) contains NO `.lef`
ANYWHERE — `find <project> -name '*.lef'` returns nothing. The flow could
place an ANALOG hard macro (A8 emits a LEF, step 15 reads one) and nothing it
produced digitally could be placed by anybody.

UPSTREAM AGREES THIS IS THE IP TERMINAL, AND SAYS SO BY DELETION.
`librelane/flows/chip.py` is `class Chip(Classic)` plus a substitution table
that contains, with its comment intact:

    "Magic.WriteLEF": None,   # "This is not a macro, there's no need to
                              #  write a LEF"

The CHIP flow switches the LEF write OFF, so the LEF write is exactly what
makes the Classic flow an IP-DELIVERY flow.

THE ALGORITHM, IN WORDS, BEFORE IT IS CODED
===========================================
Upstream's `pad.tcl` states its placement algorithm as a numbered comment
before coding it, and three of its eight steps are REFUSALS. Same shape here:

  1. Resolve the design name from the DEF's own `DESIGN <name> ;`.
     No DEF, or no DESIGN statement -> REFUSE (the kit has no identity).
  2. Locate step 37's sign-off GDS. Absent, or carrying no geometry record
     -> REFUSE (there is no layout to deliver, and a hollow one is worse
     than none).
  3. The GDS top cell must be the design name. It is not -> REFUSE (the
     abstract views would name a cell the layout does not contain).
  4. Read the interface from the DEF `PINS` section — the SAME input
     `Magic.WriteLEF` takes (`inputs = [GDS, DEF]`). No PINS, or a PINS
     section with no entries -> REFUSE (a macro with no interface cannot be
     connected to anything, and inventing one is fabrication).
  5. Stage the GDS into the kit. An existing kit file is never overwritten.
  6. Write the LEF BY CALLING MAGIC, through the PDK's own `.magicrc`,
     mirroring `librelane/scripts/magic/lef.tcl`: `gds read`, `load <top>`,
     `lef write -hide` (the abstract form, which is upstream's default).
     Magic unreachable, or the PDK has no magicrc -> SKIP with a stated
     reason and rc 2. DO NOT WRITE A LEF WRITER.
  7. Emit the Liberty and Verilog views from the pin list of step 4.
  8. Write the JSON record, whatever happened.

WHAT THIS PRODUCER DELIBERATELY DOES NOT DO
===========================================
  * IT DOES NOT CHARACTERISE TIMING. The Liberty it writes is an INTERFACE
    view: cell, pg_pins, pins, directions, and NO timing arc. Step 37.5ip
    declares no characterisation step, and inventing a delay number would be
    the worst possible lie in this kit — integration STA would close on it.
    The Liberty says so in its own header, and `digital_hardmacro_check`
    reports the kit in its `PASS_TIMING_UNCHARACTERISED` tier.
  * IT DOES NOT SET THE ABSTRACTION POLICY BY GUESSING. `-hide` is written
    because upstream's own script writes it by default; `--full-lef` and
    `--pinonly` expose the other two knobs (`MAGIC_WRITE_FULL_LEF`,
    `MAGIC_WRITE_LEF_PINONLY`) and the choice is RECORDED in the JSON.
  * IT DOES NOT VERIFY ITS OWN OUTPUT. The generator and the checker are
    separate and the CHECKER is what fails — that is upstream's shape and it
    is also this flow's rule: `flow_compliance_check` is the acceptance
    auditor, and an auditor that runs the producer certifies its own output.
    This program is declared in the step's `programs:` and is invoked by the
    RUNNER, never from the step's gate.

BETTER THAN UPSTREAM IN ONE STATED WAY
======================================
LibreLane's `pad.tcl` refuses by `exit 1` with a printed message and leaves no
machine-readable record. Every outcome here — PRODUCED, REFUSED, SKIPPED, and
the reason — is written to the `--json` report before this program returns, so
a refusal is a datum a later step can read and not a line somebody has to find
in a log.

Usage:
    python3 digital_hardmacro_gen.py <project_dir> [--json <out>]
                                     [--pdk-root <dir>] [--container <name>]
                                     [--full-lef] [--pinonly]

Exit codes:
    0 = the kit was produced, or was already present and complete.
    1 = a precondition of the KIT was violated: no DEF / no DESIGN name / no
        sign-off GDS / a GDS with no geometry / a top-cell name that is not
        the design / no interface in the DEF. Refusals, each named.
    2 = a CAPABILITY is absent (no Magic reachable, no magicrc for the PDK) or
        an argument / fatal IO error. A disclosed gap, never a silent success.

chip-AGNOSTIC: no chip, vendor, SKU or process-node literal.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _path_layout as _pl
from _atomic_artefact import write_text as atomic_write_text

# SHARED READERS, imported rather than re-typed — the same rule the gate
# follows. `parse_def_pins` is the canonical DEF PINS reader in this tree and
# already preserves the DEF's own port ORDER, which is the order a netlist
# writer emits; a second reader here would drift from it.
try:
    from lvs_def_port_seed import parse_def_pins, _extract_pins_block
except ImportError:  # pragma: no cover - programs/ is always on sys.path
    parse_def_pins = None      # type: ignore[assignment]
    _extract_pins_block = None  # type: ignore[assignment]
try:
    from analog_a5_layout_check import _gds_geometry_count
except ImportError:  # pragma: no cover
    _gds_geometry_count = None  # type: ignore[assignment]
try:
    from digital_hardmacro_check import gds_top_cells, base_name
except ImportError:  # pragma: no cover
    gds_top_cells = None       # type: ignore[assignment]
    base_name = None           # type: ignore[assignment]
try:
    from magic_port_extract_emit import build_shell_preamble
except ImportError:  # pragma: no cover
    build_shell_preamble = None  # type: ignore[assignment]

PROGRAM = "digital_hardmacro_gen"
VERSION = "1.0.0"

RC_OK, RC_REFUSED, RC_NO_CAPABILITY = 0, 1, 2

_DEF_DESIGN_RE = re.compile(r"(?m)^\s*DESIGN\s+(\S+)\s*;")
_DEF_PIN_START_RE = re.compile(r"-\s+(\S+)")
_DEF_USE_RE = re.compile(r"\+\s*USE\s+(\w+)", re.IGNORECASE)
_PG_USES = {"POWER", "GROUND"}
#: Candidate DEFs, most-final first. The routed DEF is what the sign-off GDS
#: was streamed from, so its PINS are the interface the layout actually has.
_DEF_CANDIDATES = (
    "phase3/stage3/pnr/routed.def",
    "phase3/stage3/pnr/filled.def",
    "phase3/stage4/gds/routed.def",
)


def _require(obj, what: str):
    if obj is None:
        raise RuntimeError(f"{what} unavailable; {PROGRAM} cannot run")
    return obj


@dataclass
class Record:
    program: str = PROGRAM
    version: str = VERSION
    status: str = "PRODUCED"
    design: str = ""
    reason: str = ""
    produced: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    lef_policy: dict = field(default_factory=dict)
    interface: dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# ── inputs ────────────────────────────────────────────────────────────────

def find_def(project: Path) -> Optional[Path]:
    for rel in _DEF_CANDIDATES:
        p = project / rel
        if p.is_file():
            return p
    hits = sorted((project / "phase3").rglob("*.def")) \
        if (project / "phase3").is_dir() else []
    return hits[-1] if hits else None


def find_signoff_gds(project: Path) -> Optional[Path]:
    gds_dir = _pl.gds_dir(project)
    if not gds_dir.is_dir():
        return None
    hits = sorted(gds_dir.glob("*.gds"))
    return hits[0] if hits else None


@dataclass
class Pin:
    name: str
    direction: str
    is_pg: bool
    #: The DEF's own `USE` token, upper-cased ("POWER" / "GROUND" / "SIGNAL"
    #: / ""). CARRIED AND NOT COLLAPSED INTO `is_pg`, and the reason was
    #: MEASURED on a real kit: the Liberty's `pg_type` was derived from the
    #: DEF *DIRECTION*, which is INPUT/OUTPUT/INOUT and can never hold the
    #: token "GROUND", so EVERY supply pin came out `primary_power` — two
    #: rails declared as one, which is the supply-domain merge this step's
    #: gate exists to refuse. Whether a rail is power or ground lives in
    #: `USE`, so `USE` is what must reach the emitter.
    use: str = ""


def read_interface(def_text: str) -> List[Pin]:
    """The macro's interface, from the DEF's own PINS section.

    `parse_def_pins` supplies name + direction (shared reader, DEF order
    preserved). `USE` is not on its `DefPin`, so the POWER/GROUND
    classification is read here over the SAME entry split that reader uses —
    `_extract_pins_block` — rather than by a second, differently-shaped scan
    that could disagree with it about what an entry is.
    """
    pins = _require(parse_def_pins, "parse_def_pins")(def_text)
    use_by_name: Dict[str, str] = {}
    block = _require(_extract_pins_block, "_extract_pins_block")(def_text)
    for entry in (block or "").split(";"):
        m = _DEF_PIN_START_RE.search(entry)
        if not m:
            continue
        um = _DEF_USE_RE.search(entry)
        use_by_name[m.group(1)] = (um.group(1).upper() if um else "")
    return [Pin(name=p.name, direction=(p.direction or "INOUT"),
                is_pg=use_by_name.get(p.name, "") in _PG_USES,
                use=use_by_name.get(p.name, ""))
            for p in pins]


def group_buses(pins: List[Pin]) -> List[Tuple[str, str, Optional[Tuple[int, int]]]]:
    """`[(base, direction, (msb, lsb) | None)]`, in DEF order.

    A DEF spells a bus as one entry per BIT (`dout[0]`, `dout[1]`); a Verilog
    port and a Liberty `bus` group are declared once with a range. The range
    is derived from the bits the DEF actually carries — never assumed to start
    at zero and never widened past what is there.
    """
    order: List[str] = []
    bits: Dict[str, List[int]] = {}
    dirs: Dict[str, str] = {}
    bit_re = re.compile(r"^(.*?)[\[<](\d+)[\]>]$")
    for p in pins:
        m = bit_re.match(p.name)
        base = m.group(1) if m else p.name
        if base not in bits:
            order.append(base)
            bits[base] = []
            dirs[base] = p.direction
        if m:
            bits[base].append(int(m.group(2)))
    out = []
    for base in order:
        idx = sorted(bits[base])
        out.append((base, dirs[base], (max(idx), min(idx)) if idx else None))
    return out


# ── emitters (LEF is NOT among them — Magic writes that) ──────────────────

_V_DIR = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}


def emit_verilog(design: str, pins: List[Pin]) -> str:
    """A blackbox simulation view.

    SUPPLY PORTS ARE OMITTED, deliberately and in line with what
    `digital_hardmacro_check` documents as the one narrow exception: a Verilog
    view of a hard macro carries the LOGICAL interface; supplies are physical
    and live in the LEF (`USE POWER`/`USE GROUND`) and the Liberty (`pg_pin`).
    """
    sig = [p for p in pins if not p.is_pg]
    ports = []
    for base, direction, rng in group_buses(sig):
        kw = _V_DIR.get(direction.upper(), "inout")
        width = f" [{rng[0]}:{rng[1]}]" if rng else ""
        ports.append(f"    {kw} wire{width} {base}")
    body = ",\n".join(ports)
    pg = ", ".join(p.name for p in pins if p.is_pg) or "none declared"
    return (f"// {design} — blackbox simulation view of a delivered hard macro.\n"
            f"// Emitted by {PROGRAM} from the DEF PINS section; the logical\n"
            f"// interface only. Supply pins ({pg}) are physical and are\n"
            f"// declared in the LEF and the Liberty, not here.\n"
            f"(* blackbox *)\n"
            f"module {design} (\n{body}\n);\n"
            f"endmodule\n")


_LIB_DIR = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}


def emit_liberty(design: str, pins: List[Pin]) -> str:
    """An INTERFACE Liberty — cell, pg_pins, pins, directions, NO timing.

    THE OMISSION IS THE POINT AND IT IS DECLARED IN THE FILE. A fabricated
    delay would be the most damaging value in this whole kit: integration STA
    would close on it and report timing met against a number nobody measured.
    `digital_hardmacro_check` reads the absence and reports the kit in its
    `PASS_TIMING_UNCHARACTERISED` tier, so the caveat travels with the verdict.
    """
    lines = [
        f"/* {design} — INTERFACE Liberty view of a delivered hard macro.",
        f" * Emitted by {PROGRAM} from the DEF PINS section.",
        " *",
        " * NO TIMING ARC IS DECLARED, AND THAT IS DELIBERATE. This view",
        " * states the interface only; no characterisation has been run, so",
        " * no delay, transition or leakage number is asserted. Integration",
        " * STA over this cell is NOT closed timing — it is timing against an",
        " * uncharacterised macro, and the gate for this step reports it as",
        " * such. Replace this file with a characterised Liberty before",
        " * anybody closes a chip on it.",
        " */",
        f"library ({design}) {{",
        '  delay_model : table_lookup ;',
        f"  cell ({design}) {{",
    ]
    for p in pins:
        if p.is_pg:
            # FROM `USE`, NEVER FROM `DIRECTION`. A DEF DIRECTION is
            # INPUT/OUTPUT/INOUT; it cannot spell "GROUND", so a pg_type
            # derived from it is `primary_power` for every supply pin there
            # is. Measured on a real kit: a DEF declaring `VDD + USE POWER`
            # and `VSS + USE GROUND` produced a Liberty declaring BOTH as
            # `primary_power` — the two rails merged into one domain, in the
            # view integration STA reads, written by this flow.
            kind = ("primary_ground" if p.use.upper() == "GROUND"
                    else "primary_power")
            lines.append(f"    pg_pin ({p.name}) {{ pg_type : {kind} ; }}")
    for base, direction, rng in group_buses([p for p in pins if not p.is_pg]):
        d = _LIB_DIR.get(direction.upper(), "inout")
        if rng:
            lines.append(f"    bus ({base}) {{ direction : {d} ; "
                         f"bus_type : bus_{base} ; }}")
        else:
            lines.append(f"    pin ({base}) {{ direction : {d} ; }}")
    lines += ["  }", "}", ""]
    return "\n".join(lines)


# ── the LEF: Magic, through the PDK's own magicrc ─────────────────────────

def build_lef_tcl(top: str, gds: str, def_file: str, out_lef: str,
                  full_lef: bool, pinonly: bool) -> str:
    """The Magic TCL, following `librelane/scripts/magic/lef.tcl`.

    THE `def read` IS LOAD-BEARING AND IT WAS MEASURED. Upstream's script has
    two routes and `MAGIC_LEF_WRITE_USE_GDS` picks between them; its DEFAULT
    is FALSE — read the views and `read_def`, NOT the GDS alone. The first
    draft of this producer took the GDS-only route and the result, on a real
    signed-off run, was this:

        MACRO spm
          CLASS BLOCK ;
          SIZE 285.000 BY 285.000 ;
          OBS  …
        END spm

    A LEF WITH ZERO PINS. Magic reported `Unknown layer/datatype in boundary,
    layer=901 type=0` while reading it: the port labels are on layers this
    PDK's Magic technology does not map, so no label became a port and the
    abstract came out with an outline, obstructions, and nothing to connect
    to. `gds labels yes` + `port makeall` did not change it — still 0 pins.
    Adding `def read <routed.def>` produced 41 PINs, exactly the DEF's
    `PINS 41 ;` count, each with DIRECTION, USE and a PORT layer. No tech LEF
    is required; the technology from the PDK's own magicrc suffices.

    So: the GDS supplies the GEOMETRY, the DEF supplies the PORTS, and the
    abstraction knobs are upstream's own — `-hide` unless
    `MAGIC_WRITE_FULL_LEF`, plus `-pinonly` when `MAGIC_WRITE_LEF_PINONLY`.
    """
    opts = []
    if not full_lef:
        opts.append("-hide")       # upstream's default: the ABSTRACT view
    if pinonly:
        opts.append("-pinonly")
    tail = (" " + " ".join(opts)) if opts else ""
    return (f"# Emitted by {PROGRAM}; sequence follows librelane\n"
            f"# scripts/magic/lef.tcl. Geometry from the GDS, PORTS from the\n"
            f"# DEF — the GDS-only route yields an abstract with no pin at all.\n"
            f"drc off\n"
            f"gds read {gds}\n"
            f"load {top}\n"
            f"def read {def_file}\n"
            f"load {top}\n"
            f"select top cell\n"
            f"lef write {out_lef}{tail}\n"
            f"puts stdout \"DIGITAL_LEF_WRITE_DONE {top}\"\n")


def _magicrc_for(pdk_root: str) -> Optional[str]:
    """The PDK's OWN magicrc, located rather than reconstructed.

    The tool never re-derives PDK rules — upstream's rule 4. When no magicrc
    is found the capability is ABSENT and this program skips with that stated
    reason; it does not fall back to a default technology.
    """
    root = Path(pdk_root) if pdk_root else None
    if not root or not root.is_dir():
        return None
    hits = sorted(root.glob("*/libs.tech/magic/*.magicrc"))
    return str(hits[0]) if hits else None


_LEF_HAS_PIN_RE = re.compile(r"(?m)^\s*PIN\s+\S+")


def write_lef_with_magic(top: str, gds: Path, def_file: Path, out_lef: Path,
                         pdk_root: str, full_lef: bool, pinonly: bool,
                         timeout_s: int = 900) -> Tuple[bool, str]:
    """(ok, reason). Never raises; a missing capability is a stated reason."""
    if shutil.which("magic") is None:
        return False, "magic is not on PATH in this environment"
    magicrc = _magicrc_for(pdk_root)
    if magicrc is None:
        return False, (f"no `*/libs.tech/magic/*.magicrc` under PDK_ROOT "
                       f"{pdk_root!r}; the PDK's own technology file is the "
                       f"only one this program will use")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        staged = work / f"{top}.gds"
        shutil.copy(gds, staged)
        staged_def = work / f"{top}.def"
        shutil.copy(def_file, staged_def)
        script = work / "lef.tcl"
        script.write_text(build_lef_tcl(top, str(staged), str(staged_def),
                                        str(work / f"{top}.lef"),
                                        full_lef, pinonly))
        env = dict(os.environ)
        env["PDK_ROOT"] = pdk_root
        cmd = ["magic", "-noconsole", "-dnull", "-rcfile", magicrc,
               str(script)]
        try:
            cp = subprocess.run(cmd, cwd=work, capture_output=True, text=True,
                                errors="replace", timeout=timeout_s)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"magic did not complete: {exc}"
        produced = work / f"{top}.lef"
        if not produced.is_file() or produced.stat().st_size == 0:
            tail = (cp.stderr or cp.stdout or "").strip().splitlines()[-3:]
            return False, (f"magic exited {cp.returncode} and wrote no LEF; "
                           f"last output: {' | '.join(tail) or '(none)'}")
        # A PIN-LESS ABSTRACT IS WORSE THAN NO ABSTRACT — it is an outline and
        # a set of obstructions with nothing to connect to, and it LOOKS like
        # a delivered view. Same posture as the sibling producer
        # `analog_hardmacro_gds_emit` takes on a hollow GDS: it is not left on
        # disk. The gate would refuse it anyway; shipping it and letting the
        # gate find it would mean the flow published a broken artefact.
        if not _LEF_HAS_PIN_RE.search(produced.read_text(errors="replace")):
            return False, (
                "magic wrote a LEF with NO `PIN` block — an outline and "
                "obstructions with nothing to connect to. The macro's ports "
                "did not reach Magic, so the abstract is not deliverable and "
                "has not been staged.")
        out_lef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(produced, out_lef)
        return True, ""


# ── the run ───────────────────────────────────────────────────────────────

def run(project: Path, pdk_root: str, full_lef: bool, pinonly: bool
        ) -> Tuple[int, Record]:
    rec = Record()
    rec.lef_policy = {"writer": "magic:lef write",
                      "abstract": not full_lef,
                      "hide": not full_lef, "pinonly": pinonly,
                      "mirrors": "librelane/scripts/magic/lef.tcl"}

    # 1. identity, from the DEF's own DESIGN statement
    def_path = find_def(project)
    if def_path is None:
        rec.status, rec.reason = "REFUSED", "no DEF under phase3/"
        rec.notes.append(
            "The interface and the design name both come from the DEF. With "
            "no DEF there is no interface to publish and no name to publish "
            "it under; inventing either would be fabrication.")
        return RC_REFUSED, rec
    def_text = def_path.read_text(errors="replace")
    dm = _DEF_DESIGN_RE.search(def_text)
    if not dm:
        rec.status, rec.reason = "REFUSED", f"no `DESIGN <name> ;` in {def_path.name}"
        return RC_REFUSED, rec
    design = dm.group(1)
    rec.design = design

    # 2. the layout
    gds = find_signoff_gds(project)
    if gds is None:
        rec.status, rec.reason = "REFUSED", "no sign-off GDS under phase3/stage4/gds/"
        rec.notes.append("Step 37.5ip's declared input is step 37's GDS.")
        return RC_REFUSED, rec
    geom = _require(_gds_geometry_count, "_gds_geometry_count")(gds.read_bytes())
    if geom <= 0:
        rec.status, rec.reason = "REFUSED", (
            f"{gds.name} carries no geometry record — not a layout")
        return RC_REFUSED, rec

    # 3. the layout must contain the cell the abstracts will name
    tops = _require(gds_top_cells, "gds_top_cells")(gds.read_bytes())
    if design not in tops:
        rec.status, rec.reason = "REFUSED", (
            f"the DEF names design {design!r} and the GDS top cell(s) are "
            f"{tops!r}; the abstract views would name a cell the layout does "
            f"not contain")
        return RC_REFUSED, rec

    # 4. the interface
    pins = read_interface(def_text)
    if not pins:
        rec.status, rec.reason = "REFUSED", (
            f"{def_path.name} declares no PINS entry — a macro with no "
            f"interface cannot be connected to anything")
        return RC_REFUSED, rec
    rec.interface = {
        "source": str(def_path),
        "pins": len(pins),
        "signal": [p.name for p in pins if not p.is_pg],
        "power_ground": [p.name for p in pins if p.is_pg],
    }

    hm = _pl.phase3_stage4_dir(project) / "hardmacro"
    hm.mkdir(parents=True, exist_ok=True)

    def stage(path: Path, write) -> None:
        """Never overwrite: re-running the flow must not silently replace a
        sign-off artefact."""
        if path.exists() and path.stat().st_size > 0:
            rec.skipped.append(f"{path.name} (already present)")
            return
        write(path)
        rec.produced.append(path.name)

    # 5-7
    stage(hm / f"{design}.gds", lambda p: shutil.copy(gds, p))
    stage(hm / f"{design}.v",
          lambda p: atomic_write_text(p, emit_verilog(design, pins)))
    stage(hm / f"{design}.lib",
          lambda p: atomic_write_text(p, emit_liberty(design, pins)))

    lef_path = hm / f"{design}.lef"
    if lef_path.exists() and lef_path.stat().st_size > 0:
        rec.skipped.append(f"{lef_path.name} (already present)")
        return RC_OK, rec
    ok, why = write_lef_with_magic(design, gds, def_path, lef_path, pdk_root,
                                   full_lef, pinonly)
    if not ok:
        rec.status, rec.reason = "SKIPPED_NO_CAPABILITY", why
        rec.notes.append(
            "The LEF is written by Magic and by nothing else — this program "
            "contains no LEF writer, on purpose. The kit is therefore "
            "INCOMPLETE, and `digital_hardmacro_check` will refuse it for the "
            "missing view. That refusal is correct: a kit without the view "
            "that lets somebody place the macro is not a delivery.")
        return RC_NO_CAPABILITY, rec
    rec.produced.append(lef_path.name)
    return RC_OK, rec


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=PROGRAM, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="write the JSON record here")
    ap.add_argument("--pdk-root", default=os.environ.get("PDK_ROOT", ""),
                    help="PDK_ROOT; the PDK's own magicrc is located under it")
    ap.add_argument("--full-lef", action="store_true",
                    help="upstream MAGIC_WRITE_FULL_LEF: every internal shape "
                         "instead of an abstracted view")
    ap.add_argument("--pinonly", action="store_true",
                    help="upstream MAGIC_WRITE_LEF_PINONLY: only port-labelled "
                         "areas are pins; the rest of each net on that layer "
                         "becomes an obstruction")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return RC_NO_CAPABILITY

    try:
        rc, rec = run(args.project_dir, args.pdk_root, args.full_lef,
                      args.pinonly)
    except RuntimeError as exc:
        rc, rec = RC_NO_CAPABILITY, Record(status="ERROR", reason=str(exc))

    # THE RECORD IS WRITTEN ON EVERY PATH, INCLUDING EVERY REFUSAL. Upstream's
    # own refusals exit 1 with a printed message and no machine-readable
    # record; this is the one place this producer is deliberately better.
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(asdict(rec), indent=2,
                                          ensure_ascii=False) + "\n")

    print(f"[{rec.status}] {PROGRAM}"
          + (f" — {rec.reason}" if rec.reason else "")
          + (f"; produced {', '.join(rec.produced)}" if rec.produced else ""),
          file=sys.stderr if rc else sys.stdout)
    for n in rec.notes:
        print(f"  {n}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
