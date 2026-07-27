#!/usr/bin/env python3
"""每一條宣告的電源/地軌都必須有真實金屬幾何 — 否則它只是一個名字。

A power rail declared in the DEF's `SPECIALNETS` section but carrying **no
routed geometry** binds every pin on it to nothing. The pins look connected —
their net pointer is valid — but there is no metal to carry current.

MEASURED, and this is why the check exists at all. On a real tapeout run whose
third-party hard macro takes a second supply, `grep <RAIL> routed.def` returned
exactly one line in the whole file::

    - OTP_V ( * VPP ) + USE POWER ;

It ends at the `;`. There is no `+ ROUTED` clause. The rail on the next line of
the same file carries dozens of `MET5 ... SHAPE STRIPE` rows. So the macro's
highest-voltage supply pin was bound to a net with zero geometry — and THREE
tools reported success:

  * ``PG_CONNECT_AUDIT: total=13315 unconnected=0`` — that audit counts pins
    whose net pointer is NULL. This pin's pointer is not NULL; it points at the
    empty rail. It measures "is the pin attached to a name", not "is the name
    attached to metal".
  * ``[INFO PSM-0040] All shapes on net OTP_V are connected.`` — vacuously
    true. All zero shapes are connected to each other.
  * The router itself: nothing to route means nothing to fail on.

Each tool answered its own question correctly. None of them answered *"can
current reach this pin"*, and no gate in the flow asked.

WHAT THIS GATE DOES NOT CLAIM. A rail can be legitimately empty in one
partition and delivered at integration — that is a normal hierarchical split.
So an empty rail is only a FAIL when nothing in the run DISCLOSES it. A
disclosure is a machine-readable statement, not a code comment: see
``--integration-supplied`` and the ``pdn_integration_supplied.json`` marker.
An undisclosed empty rail is the defect; a disclosed one is an engineering
decision on the record.

chip-AGNOSTIC: parses the DEF's own SPECIALNETS grammar and compares rails to
each other within the same file. No rail name, chip name, PDK SKU or vendor
literal appears anywhere in this program.

Exit codes
----------
    0  PASS      every declared rail carries geometry (or is disclosed)
    1  FAIL      a rail is declared, used by pins, and has no geometry
    2  SKIP      no DEF, or the DEF has no SPECIALNETS section (nothing to judge)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _path_layout as _pl
except ImportError:  # standalone use
    _pl = None

GATE = "pg_rail_geometry_check"

# A SPECIALNETS entry opens with `- <name>` at the start of a (stripped) line.
_NET_OPEN = re.compile(r"^-\s+(\S+)")
# Geometry clauses inside a special net. `ROUTED`/`NEW`/`FIXED`/`COVER` all
# introduce a wire segment; SHAPE/RECT/POLYGON carry the actual metal.
_GEOM = re.compile(r"\+\s*(?:ROUTED|FIXED|COVER)\b|^\s*NEW\s+\S+|\+\s*(?:RECT|POLYGON)\b")
# `( * PINNAME )` or `( instance pin )` — the pins bound to this rail.
_PIN = re.compile(r"\(\s*\S+\s+\S+\s*\)")


@dataclass
class Rail:
    name: str
    line: int
    pins: int = 0
    geom_lines: int = 0
    raw: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.geom_lines == 0


def parse_specialnets(def_text: str) -> tuple[list, bool]:
    """Return (rails, section_present). Parses the DEF's own grammar.

    A special net's body runs from its `- <name>` line until the terminating
    `;`, and may span many lines — which is exactly why a single-line grep for
    a rail name cannot tell an empty rail from a routed one."""
    lines = def_text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if start is None and s.startswith("SPECIALNETS"):
            start = i
        elif start is not None and s.startswith("END SPECIALNETS"):
            end = i
            break
    if start is None:
        return [], False

    rails: list = []
    cur: Rail | None = None
    for i in range(start + 1, end if end is not None else len(lines)):
        raw = lines[i]
        s = raw.strip()
        m = _NET_OPEN.match(s)
        if m:
            if cur is not None:
                rails.append(cur)
            cur = Rail(name=m.group(1), line=i + 1)
        if cur is None:
            continue
        cur.raw.append(s)
        cur.pins += len(_PIN.findall(s))
        if _GEOM.search(s) or _GEOM.search(raw):
            cur.geom_lines += 1
        if s.endswith(";"):
            rails.append(cur)
            cur = None
    if cur is not None:
        rails.append(cur)
    return rails, True


def _disclosed(project: Path) -> set:
    """Rails a run HONESTLY declares as delivered at integration.

    Mirrors the disclosed-skip shape used elsewhere in the flow: a real,
    machine-readable marker written by the run, not a prose comment. Absent or
    unreadable marker discloses nothing — fail-closed."""
    out: set = set()
    for rel in ("reports/phase3/pdn_integration_supplied.json",
                "reports/pdn_integration_supplied.json",
                "phase3/stage3/pnr/pdn_integration_supplied.json"):
        p = project / rel
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        names = d.get("integration_supplied_rails") or d.get("rails") or []
        if isinstance(names, list):
            out |= {str(n) for n in names}
    return out


def _find_def(project: Path) -> Path | None:
    cands = []
    if _pl is not None:
        try:
            cands.append(_pl.pnr_dir(project) / "routed.def")
        except Exception:
            pass
    cands.append(project / "phase3" / "stage3" / "pnr" / "routed.def")
    for c in cands:
        if c.is_file():
            return c
    hits = sorted(project.rglob("routed.def"))
    return hits[0] if hits else None


def check(project: Path, extra_disclosed: set | None = None) -> dict:
    def_path = _find_def(project)
    if def_path is None:
        return {"gate": GATE, "verdict": "SKIP",
                "reason": "no routed.def under the project — nothing to judge"}
    try:
        text = def_path.read_text(errors="replace")
    except OSError as e:
        return {"gate": GATE, "verdict": "SKIP", "reason": f"unreadable DEF: {e}"}

    rails, present = parse_specialnets(text)
    if not present:
        return {"gate": GATE, "verdict": "SKIP", "def": str(def_path),
                "reason": "DEF has no SPECIALNETS section — no PG rails declared"}
    if not rails:
        return {"gate": GATE, "verdict": "SKIP", "def": str(def_path),
                "reason": "SPECIALNETS section is empty"}

    disclosed = _disclosed(project) | (extra_disclosed or set())
    routed = [r for r in rails if not r.empty]
    empty = [r for r in rails if r.empty]
    undisclosed = [r for r in empty if r.name not in disclosed]

    detail = [{"rail": r.name, "def_line": r.line, "pins": r.pins,
               "geometry_lines": r.geom_lines,
               "disclosed": r.name in disclosed} for r in rails]

    if undisclosed:
        findings = []
        for r in undisclosed:
            findings.append({
                "rail": r.name, "def_line": r.line, "pins_bound": r.pins,
                "rule": "PG_RAIL_NO_GEOMETRY",
                "detail": (
                    f"rail `{r.name}` is declared in SPECIALNETS at line "
                    f"{r.line} and {r.pins} pin connection(s) bind to it, but it "
                    f"carries ZERO routed geometry. Pins on it have a valid net "
                    f"pointer and will pass a null-pointer connectivity audit, "
                    f"and a shapes-are-connected check is vacuously true on an "
                    f"empty shape set — but no metal carries current to them. "
                    f"For comparison this DEF routes "
                    f"{len(routed)} other rail(s) with geometry."),
            })
        return {"gate": GATE, "verdict": "FAIL", "def": str(def_path),
                "rails_total": len(rails), "rails_routed": len(routed),
                "rails_empty_undisclosed": len(undisclosed),
                "findings": findings, "rails": detail}

    reason = f"all {len(rails)} declared rail(s) carry routed geometry"
    if empty:
        reason = (f"{len(routed)}/{len(rails)} rail(s) carry geometry; "
                  f"{len(empty)} empty rail(s) are DISCLOSED as delivered at "
                  f"integration: {sorted(r.name for r in empty)}")
    return {"gate": GATE, "verdict": "PASS", "def": str(def_path),
            "rails_total": len(rails), "rails_routed": len(routed),
            "rails_empty_disclosed": len(empty), "reason": reason,
            "rails": detail}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--integration-supplied", default="",
                    help="comma-separated rails known to be delivered at "
                         "integration (prefer the on-disk marker; this flag is "
                         "for a caller that already holds the contract)")
    a = ap.parse_args(argv)
    project = Path(a.project_dir).resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    extra = {s.strip() for s in a.integration_supplied.split(",") if s.strip()}
    res = check(project, extra)

    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")

    v = res["verdict"]
    stream = sys.stderr if v == "FAIL" else sys.stdout
    if v == "FAIL":
        print(f"FAIL: {len(res['findings'])} rail(s) declared with no geometry",
              file=stream)
        for f in res["findings"]:
            print(f"  [{f['rule']}] {f['detail']}", file=stream)
    else:
        print(f"{v}: {res.get('reason', res.get('reason', ''))}", file=stream)
    return {"PASS": 0, "FAIL": 1, "SKIP": 2}[v]


if __name__ == "__main__":
    sys.exit(main())
