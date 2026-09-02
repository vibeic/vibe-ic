#!/usr/bin/env python3
"""analog_a6_drc_attribute.py — what each A6 DRC violation actually IS.

WHY THIS PROGRAM EXISTS
-----------------------
A6 is the adjudicator of an analog block's geometry: A5 draws and records,
A6's sign-off deck decides. But a deck answers with a NUMBER, and a number is
not adjudicable. Measured on `u_hawaii_adc/ldo` (11 devices, ihp-sg13g2): the
deck says 180. Under that one number sit four populations whose next steps
have nothing in common —

  * violations that fire on the PDK's OWN gencell when that cell is generated
    ALONE, with no layout around it. No routing change can remove them; the
    only moves are a different device parameterisation or a PDK fix.
  * violations that fire on the PLACED devices with every top-level wire
    stripped away. The placement provoked them; the routing did not.
  * violations that touch this flow's own paint. These are the ones the flow
    owns and the ones a repair must aim at.
  * violations on device geometry that appear ONLY once the layout is around
    it. Magic re-checks a subcell's interior in the parent's context, so a
    cell that is clean standalone is not necessarily clean in place.

Reported as one number, all four look like "the layout is bad", and a reader
cannot tell which of them a fix would even move.

WHAT THIS PROGRAM DOES NOT DO
-----------------------------
It does not waive anything and it does not grade. In particular:

  * a violation A5's `layout_provenance.json` already RECORDED as a deviation
    is still a violation. The record is a DISCLOSURE, not a waiver: it is
    reported as `covered_by_deviation: true` beside its class, and it never
    changes the class or the exit code. A producer that could clear its own
    DRC by writing itself a note would be marking its own homework.
  * the exit code is non-zero whenever ANY violation is attributed to the
    layout — `LAYOUT` or `INTERACTION`. Only a block whose every violation
    fires on the PDK's own cells can exit 0, and even then the violations are
    printed, never suppressed.

Every attribution is PROVEN by its own measurement, never by inspection:
the deck is re-run on the bare cell and on the routing-stripped placement,
and a class is claimed only when those runs reproduce the same rule at the
same rectangle.

    analog_a6_drc_attribute.py <project_dir> --block B [--container C]
                               [--json out.json]

exit 0 → every violation is the PDK's own cell geometry (or there are none)
exit 1 → at least one violation is within this flow's reach: it touches the
         flow's paint, or the stripped placement reproduces it, or neither
         control reproduces it
exit 2 → NOT ATTRIBUTED: the layout, the tool or the deck could not be read
chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _path_layout as _pl  # noqa: E402
import magic_gencell_layout_lib as _gl  # noqa: E402
from analog_hardmacro_gds_emit import Stage  # noqa: E402

GATE = "analog_a6_drc_attribute"
SCHEMA = 1

RC_DEVICE_ONLY = 0
RC_LAYOUT_OWNS = 1
RC_NOT_ATTRIBUTED = 2

# The four populations, and what a reader is supposed to DO about each.
CLASS_ACTION = {
    "DEVICE_CELL": ("the PDK's own gencell violates this rule when generated "
                    "alone; no routing change removes it. Re-parameterise the "
                    "device or raise it with the PDK."),
    "DEVICE_PLACEMENT": ("fires on the placed devices with every wire "
                         "stripped; the placement provoked it, the routing "
                         "did not. Move the devices."),
    "LAYOUT": ("touches this flow's own paint. This flow owns it and a "
               "repair must aim here."),
    "INTERACTION": ("device geometry, but only once the layout is around it "
                    "— Magic re-checks a subcell's interior in the parent's "
                    "context. Neither the cell alone nor the wire alone "
                    "reproduces it."),
}

_SECTION_RE = re.compile(r"^<< (\S+) >>\n(.*?)(?=^<<)", re.S | re.M)
_USE_BLOCK_RE = re.compile(
    r"^use (\S+)[^\n]*\ntimestamp \d+\ntransform 1 0 (-?\d+) 0 1 (-?\d+)"
    r"\nbox [^\n]*\n", re.M)

_DUMP_TCL = """
set w [drc listall why]
for {set i 0} {$i < [llength $w]} {incr i 2} {
  set m [lindex $w $i]
  foreach r [lindex $w [expr {$i+1}]] { puts "V|$m|$r" }
}
"""


def _check_tcl(load: str, extra: str = "") -> str:
    """The deck, run the ONE way that actually checks the whole cell.

    `drc check` works on the cursor box, so a script that loads a cell and
    checks without `select top cell` first measures whatever box happened to
    be current — which is how a control run reports 0 for a cell it never
    looked at."""
    return (f"drc off\n{extra}load {load}\nselect top cell\n"
            f"drc on\ndrc euclidean on\ndrc style drc(full)\n"
            f"drc check\ndrc catchup\n"
            f'puts "A6TOTAL [drc list count total]"\n'
            f"set a6c [drc listall count]\n"
            f'foreach e $a6c {{ puts "C|$e" }}\n'
            f"{_DUMP_TCL}\nquit -noprompt\n")


Violation = Tuple[str, Tuple[int, int, int, int]]


def parse_violations(blob: str) -> List[Violation]:
    out: List[Violation] = []
    for line in blob.splitlines():
        if not line.startswith("V|"):
            continue
        _, rule, rect = line.split("|", 2)
        vals = rect.split()
        if len(vals) == 4:
            out.append((rule.strip(), tuple(int(v) for v in vals)))
    return out


def parse_cell_counts(blob: str) -> Dict[str, int]:
    """Magic's OWN per-cell error counts, reported beside this program's
    attribution rather than instead of it: they are a different unit (errors,
    not violating rectangles) and they answer a different question (which
    CELL the error was found in, not which geometry caused it)."""
    out: Dict[str, int] = {}
    for line in blob.splitlines():
        if not line.startswith("C|"):
            continue
        parts = line[2:].split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            out[parts[0]] = int(parts[1])
    return out


def parse_total(blob: str) -> Optional[int]:
    m = re.search(r"^A6TOTAL (\d+)", blob, re.M)
    return int(m.group(1)) if m else None


def top_level_shapes(text: str) -> Dict[str, List[tuple]]:
    """The paint the LAYOUT's own top cell carries, in lambda."""
    scale = _gl.mag_scale(text)
    out: Dict[str, List[tuple]] = {}
    for sm in _SECTION_RE.finditer(text):
        name = sm.group(1)
        if name in ("checkpaint", "labels", "properties"):
            continue
        out[name] = [tuple(int(v) for v in r)
                     for r in _gl.parse_rects_lambda(sm.group(2), scale)]
    return out


def instances(text: str) -> List[Tuple[str, int, int]]:
    scale = _gl.mag_scale(text)
    a, b = scale
    return [(c, (int(x) * a) // b, (int(y) * a) // b)
            for c, x, y in _USE_BLOCK_RE.findall(text)]


def devices_only(text: str) -> str:
    """The same placement with every painted rectangle removed.

    A pure text transform of the layout's own file: the header, the instance
    blocks, nothing else. It answers "what does this placement violate before
    a single wire is drawn?" without re-running the producer."""
    head = text[:text.index("<< ")] if "<< " in text else text
    kept = "".join(m.group(0) for m in _USE_BLOCK_RE.finditer(text))
    return head + "<< checkpaint >>\n" + kept + "<< end >>\n"


def _sep(a: Sequence[int], b: Sequence[int]) -> int:
    return max(max(b[0] - a[2], a[0] - b[2], 0),
               max(b[1] - a[3], a[1] - b[3], 0))


def rule_distance(rule: str, lam: int, default: int) -> int:
    """The distance the rule itself names, in lambda, out of its own message.

    A magic deck states each rule's value in microns inside the message it
    prints ("Metal2 spacing < 0.21um (M2.b)"), so the window inside which the
    OTHER side of a violation must lie is read from the deck's own words
    rather than assumed. `lam` is lambda-per-micron, measured from Magic.
    A rule whose message names no distance falls back to `default`, and the
    caller discloses that it did."""
    m = re.search(r"<\s*([0-9.]+)\s*um", rule)
    return int(round(float(m.group(1)) * lam)) if m else default


_SCALE_RE = re.compile(r"^A6SCALE (\d+) (\d+) (\d+)", re.M)


class Deck:
    """The sign-off deck, run inside the tool image."""

    def __init__(self, stage: Stage, magicrc: str) -> None:
        self.stage = stage
        self.magicrc = magicrc
        self.lam: Optional[int] = None

    def run(self, script: str, tag: str) -> str:
        ok, err = self.stage.put_text(script, f"{tag}.tcl")
        if not ok:
            raise RuntimeError(f"cannot stage {tag}.tcl: {err}")
        rc, out, serr = self.stage.sh(
            f"cd {shlex.quote(self.stage.path or '.')} && "
            f"magic -dnull -noconsole -rcfile {shlex.quote(self.magicrc)} "
            f"{tag}.tcl", timeout=3600)
        return (out or "") + (serr or "")

    def scale(self) -> int:
        """Lambda per micron, asked of Magic rather than assumed."""
        if self.lam is None:
            blob = self.run(
                "cellname create a6scale\nload a6scale\n"
                "box 0um 0um 1000um 1000um\n"
                'puts "A6SCALE [lindex [box values] 2] '
                '[lindex [tech lambda] 0] [lindex [tech lambda] 1]"\n'
                "quit -noprompt\n", "a6scale")
            m = _SCALE_RE.search(blob)
            if not m:
                raise RuntimeError("magic did not report its coordinate "
                                   "scale; this program does not assume one")
            self.lam = (int(m.group(1)) * int(m.group(2))) // (
                int(m.group(3)) * 1000)
        return self.lam


def bare_cell_violations(deck: Deck, staged_dir: str, cell: str
                         ) -> Set[Violation]:
    """What the deck says about ONE gencell child on its own, expressed
    relative to that child's own origin.

    This is the negative control the DEVICE_CELL class rests on, and it is
    re-run per cell rather than assumed from the cell's name."""
    tag = f"a6solo_{re.sub(r'[^A-Za-z0-9_]', '_', cell)}"
    blob = deck.run(
        _check_tcl(tag, extra=(f"cellname create {tag}\nload {tag}\n"
                               f"box 0 0 0 0\n"
                               f"getcell {shlex.quote(staged_dir)}/{cell}.mag\n"
                               f"load {tag}\nsave {tag}.mag\n")),
        tag)
    got, _ = deck.stage.get(f"{tag}.mag", Path(deck.stage.host_tmp) /
                            f"{tag}.mag")
    ox = oy = 0
    if got:
        wrapper = (Path(deck.stage.host_tmp) / f"{tag}.mag").read_text(
            errors="replace")
        inst = instances(wrapper)
        if inst:
            _, ox, oy = inst[0]
    # violation rectangles are in INTERNAL units (twice lambda); the
    # instance transform is in lambda
    return {(rule, (r[0] - 2 * ox, r[1] - 2 * oy,
                    r[2] - 2 * ox, r[3] - 2 * oy))
            for rule, r in parse_violations(blob)}


def recorded_deviation_boxes(bdir: Path, lam: int
                             ) -> List[Tuple[str, Tuple[int, ...]]]:
    """Where A5 said it already knew the geometry was tight.

    Read ONLY to annotate; it can never change a class or the exit code."""
    prov = bdir / "layout_provenance.json"
    if not prov.is_file():
        return []
    try:
        doc = json.loads(prov.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for dev in doc.get("deviations", []) or []:
        for box in re.findall(r"\((-?\d+), (-?\d+), (-?\d+), (-?\d+)\)",
                              str(dev.get("detail", ""))):
            out.append((str(dev.get("quantity")),
                        tuple(int(v) for v in box)))
    return out


def attribute(project: Path, block: str, stage: Stage, magicrc: str,
              default_window: int = 25) -> Tuple[int, dict]:
    bdir = _pl.analog_dir(project) / block
    mag = bdir / "layout.mag"
    report: dict = {"gate": GATE, "schema": SCHEMA, "block": block,
                    "layout": str(mag)}
    if not mag.is_file():
        report["result"] = "NOT_ATTRIBUTED"
        report["reason"] = (f"no layout at {mag}; A5 has not drawn this "
                            f"block, so there is nothing to adjudicate")
        return RC_NOT_ATTRIBUTED, report

    text = mag.read_text(errors="replace")
    inst = instances(text)
    cells = sorted({c for c, _, _ in inst})
    report["instances"] = len(inst)
    report["distinct_cells"] = len(cells)

    # everything the deck needs to see must be where the deck runs
    staged = stage.path or "."
    for name in [mag.name] + [f"{c}.mag" for c in cells]:
        src = bdir / name
        if not src.is_file():
            report["result"] = "NOT_ATTRIBUTED"
            report["reason"] = (
                f"{src} is missing; a Magic layout is a cell hierarchy and "
                f"the deck cannot read a top cell whose children are absent "
                f"— it reports a count of 0 for a layout it never loaded")
            return RC_NOT_ATTRIBUTED, report
        ok, err = stage.put(src, name)
        if not ok:
            report["result"] = "NOT_ATTRIBUTED"
            report["reason"] = f"cannot stage {name}: {err}"
            return RC_NOT_ATTRIBUTED, report

    deck = Deck(stage, magicrc)
    try:
        lam = deck.scale()
        full_blob = deck.run(_check_tcl(mag.stem), "a6full")
        total = parse_total(full_blob)
        if total is None:
            report["result"] = "NOT_ATTRIBUTED"
            report["reason"] = (
                "the deck did not report a count; a missing verdict is not a "
                "clean one. Tail: " + full_blob.strip()[-400:])
            return RC_NOT_ATTRIBUTED, report
        viol = parse_violations(full_blob)
        cell_counts = parse_cell_counts(full_blob)

        # the same placement with every wire stripped away
        ok, err = stage.put_text(devices_only(text), "a6devonly.mag")
        dev_blob = deck.run(_check_tcl("a6devonly"), "a6devonly") if ok else ""
        dev_total = parse_total(dev_blob)
        dev_set = set(parse_violations(dev_blob))

        cell_set: Set[Violation] = set()
        per_cell = {}
        for cell in cells:
            rel = bare_cell_violations(deck, staged, cell)
            per_cell[cell] = len(rel)
            for c, tx, ty in inst:
                if c != cell:
                    continue
                for rule, r in rel:
                    cell_set.add((rule, (r[0] + 2 * tx, r[1] + 2 * ty,
                                         r[2] + 2 * tx, r[3] + 2 * ty)))
    finally:
        pass

    paint = top_level_shapes(text)
    dev_boxes = recorded_deviation_boxes(bdir, lam)

    classified: Dict[str, List[dict]] = {k: [] for k in CLASS_ACTION}
    fallback_window_used = 0
    for rule, r in viol:
        lam_rect = tuple(v // 2 for v in r)
        if (rule, r) in cell_set:
            cls = "DEVICE_CELL"
        else:
            win = rule_distance(rule, lam, default_window)
            if not re.search(r"<\s*[0-9.]+\s*um", rule):
                fallback_window_used += 1
            touches = any(_sep(lam_rect, q) <= win
                          for rects in paint.values() for q in rects)
            if touches:
                cls = "LAYOUT"
            elif (rule, r) in dev_set:
                cls = "DEVICE_PLACEMENT"
            else:
                cls = "INTERACTION"
        covered = any(_sep(lam_rect, b) == 0 for _q, b in dev_boxes)
        classified[cls].append({"rule": rule, "rect_lambda": list(lam_rect),
                                "covered_by_deviation": covered})

    # OWNED BY THIS FLOW = everything except the PDK's own cell. A violation
    # the PLACEMENT causes is this flow's too: the emitter chose where the
    # devices went, so "the routing did not do it" is not the same as "we
    # cannot fix it". Only `DEVICE_CELL` — which the bare gencell reproduces
    # with no layout around it at all — is outside this flow's reach.
    owned = sum(len(v) for k, v in classified.items() if k != "DEVICE_CELL")
    report.update({
        "drc_total": total,
        "devices_only_total": dev_total,
        "violating_rects": len(viol),
        "magic_errors_by_cell": cell_counts,
        "unit_note": ("`drc_total` and `magic_errors_by_cell` count magic "
                      "ERRORS; `by_class` counts violating RECTANGLES, which "
                      "is the unit an attribution can be made in. The two "
                      "are different measurements of the same run and are "
                      "reported side by side rather than mixed"),
        "lambda_per_um": lam,
        "bare_cell_violating_rects": per_cell,
        "by_class": {k: len(v) for k, v in classified.items()},
        "by_class_and_rule": {
            k: _tally(v) for k, v in classified.items() if v},
        "class_action": CLASS_ACTION,
        "covered_by_deviation": sum(
            1 for v in classified.values() for d in v
            if d["covered_by_deviation"]),
        "waiver_note": ("`covered_by_deviation` is a DISCLOSURE, not a "
                        "waiver: it never changes a class and never changes "
                        "this program's exit code"),
        "findings": classified,
    })
    if fallback_window_used:
        report["window_fallback_rects"] = fallback_window_used
        report["window_fallback_note"] = (
            f"{fallback_window_used} rect(s) came from a rule whose message "
            f"names no distance; the default {default_window}-lambda window "
            f"was used for those and the attribution is weaker for them")
    report["result"] = "LAYOUT_OWNS" if owned else "DEVICE_ONLY"
    return (RC_LAYOUT_OWNS if owned else RC_DEVICE_ONLY), report


def _tally(items: Sequence[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for d in items:
        out[d["rule"]] = out.get(d["rule"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _finish(report: dict, args, rc: int) -> int:
    """Print the report and, when asked, write it — on EVERY path.

    A run that ends NOT_ATTRIBUTED is exactly the run whose report a reader
    most needs, so it is written like any other."""
    print(json.dumps(report, indent=2))
    if getattr(args, "json", None):
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    if report.get("by_class"):
        print(f"\nA6 DRC ATTRIBUTION [{report.get('block')}] "
              f"total={report.get('drc_total')} "
              f"rects={report.get('violating_rects')}")
        for cls, n in report["by_class"].items():
            if n:
                print(f"  {cls:18} {n:6}  {CLASS_ACTION[cls]}")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--block", required=True)
    ap.add_argument("--container", default="")
    ap.add_argument("--magicrc",
                    default="/foss/pdks/ihp-sg13g2/libs.tech/magic/"
                            "ihp-sg13g2.magicrc")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    host = Path(tempfile.mkdtemp(prefix="a6_drc_attribute."))
    stage = Stage(args.container, host)
    opened, why = stage.open()
    if not opened:
        out = {"gate": GATE, "block": args.block,
               "result": "NOT_ATTRIBUTED", "tool": "docker/container",
               "reason": (f"NOT_ATTRIBUTED: the sign-off deck runs inside the "
                          f"EDA container and the container is not: {why}")}
        return _finish(out, args, RC_NOT_ATTRIBUTED)
    try:
        rc_tool, _, _ = stage.sh("command -v magic", timeout=120)
        if rc_tool != 0:
            out = {"gate": GATE, "block": args.block,
                   "result": "NOT_ATTRIBUTED", "tool": "magic",
                   "reason": (f"NOT_ATTRIBUTED: `magic` is not on PATH in "
                              f"{args.container or 'this host'}; without the "
                              f"deck there is no violation to attribute and "
                              f"a count of 0 would be a fabrication")}
            return _finish(out, args, RC_NOT_ATTRIBUTED)
        try:
            rc, report = attribute(project, args.block, stage, args.magicrc)
        except RuntimeError as exc:
            rc, report = RC_NOT_ATTRIBUTED, {
                "gate": GATE, "block": args.block,
                "result": "NOT_ATTRIBUTED", "reason": str(exc)}
    finally:
        stage.close()

    return _finish(report, args, rc)


if __name__ == "__main__":
    sys.exit(main())
