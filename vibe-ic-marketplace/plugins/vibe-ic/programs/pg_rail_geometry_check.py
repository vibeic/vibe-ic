#!/usr/bin/env python3
"""pg_rail_geometry_check — 每一條宣告的電源/地軌，在 DEF 裡都必須至少帶一段佈線幾何，否則它只是一個名字。

A power rail declared in the DEF's `SPECIALNETS` section but carrying **no
routed geometry at all** binds every pin on it to nothing. The pins look
connected — their net pointer is valid — but there is no metal on the net.

MEASURED, and this is why the check exists at all. On a real tapeout run whose
third-party hard macro takes a second supply, grepping the rail name in
`routed.def` returned exactly one line in the whole file::

    - <RAIL> ( * <PIN> ) + USE POWER ;

It ends at the `;`. There is no `+ ROUTED` clause. The rail on the next line of
the same file carries dozens of `... SHAPE STRIPE` rows. So the macro's
highest-voltage supply pin was bound to a net with zero geometry — and THREE
tools reported success:

  * ``PG_NET_OWNERSHIP_AUDIT: no_net=0`` — that audit counts pins whose net
    pointer is NULL. This pin's pointer is not NULL; it points at the empty
    rail. It measures "is the pin attached to a name", not "is the name
    attached to metal". (Named ``PG_CONNECT_AUDIT: unconnected=0`` and
    published as "N/N connected" through v1.9.62 — fixed at the source.)
  * ``[INFO PSM-0040] All shapes on net <RAIL> are connected.`` — vacuously
    true. All zero shapes are connected to each other.
  * The router itself: nothing to route means nothing to fail on.

Each tool answered its own question correctly. None of them answered *"can
current reach this pin"*, and no gate in the flow asked.

WHAT THIS GATE PROVES, EXACTLY
------------------------------
It answers ONE question: **does this rail carry at least one geometry clause?**
That is a floor, not a connectivity proof. A single 1-DBU island stub parked in
a die corner, touching no pin and no stripe, satisfies it and PASSes. This gate
therefore does NOT establish that current can reach any pin — it establishes
that the rail is not the *empty-name* degenerate case that three connectivity
tools each reported as success. Claiming more of it would repeat the very
defect it was written for: reporting a measurement of something adjacent to the
question as if it answered the question. Reach and IR-drop are separate
questions owned by separate gates.

WHAT COUNTS AS DISCLOSURE
-------------------------
A rail can be legitimately empty in one partition and delivered at integration
— that is a normal hierarchical split, not a defect. So an empty rail is a FAIL
only when nothing DISCLOSES it, and the disclosure runs through the repo's ONE
governed waiver channel, ``<project>/waivers.json``, as a normal
``waived_steps`` entry carrying ``pg_rails_integration_supplied``::

    {"waived_steps": [
      {"id": 31,
       "reason": "<>=20 chars saying which partition delivers this rail>",
       "approver": "<a human; self-approval is refused>",
       "pg_rails_integration_supplied": ["<RAIL>"]}
    ]}

That placement is deliberate. The four waiver-legitimacy gates
(``waivers_schema_check``, ``waiver_legitimacy_check``, ``waiver_growth_check``,
``waiver_staleness_check``) all read ``waived_steps``, so a disclosure written
here is subject to every one of them, and the reason/approver rules are
imported from ``waivers_schema_check`` rather than restated — one vocabulary,
not two. A private marker file of this gate's own would have been a parallel,
ungoverned waiver channel; worse, the obvious places to put it are directories
this very run writes into, which would let a runner mint its own waiver. That
is the shape ``hardmacro_supply_intent`` records as fixed bug #348 ("the
declared escape hatch had no producer"), and it is not repeated here.

chip-AGNOSTIC: parses the DEF's own SPECIALNETS grammar and compares rails to
each other within the same file. No rail name, chip name, PDK SKU or vendor
literal appears anywhere in this program — the rail above is spelled `<RAIL>`
for exactly that reason.

ENFORCEMENT: advisory — this gate is reached through the final compliance
audit (step 31's `all_of`), not invoked inline by any runner, which is also
true of its two neighbours there. `flow_gate_enforcement_audit` classifies that
wiring as AUDIT_ONLY, so declaring `blocking` here would state an intent the
wiring does not deliver and would register as a contradiction in that audit.
Promoting it is a flow-owner decision with real blast radius, not a side effect
of adding the gate.

Exit codes
----------
    0  PASS      every declared rail carries a geometry clause, or the empty
                 ones are disclosed through the governed waiver channel
    1  FAIL      a rail is declared in SPECIALNETS, carries zero geometry, and
                 nothing discloses it. Pin count is REPORTED, never required:
                 a zero-pin rail with no metal fails too, because the defect is
                 the name-without-metal, not the pin.
    2  NOT CHECKED   no routed.def, no SPECIALNETS section, or a SPECIALNETS
                 section that never terminates (a truncated DEF). Inside the
                 flow's `all_of` this is a vacuous pass, NOT a hard stop — a
                 run that did not route is left unjudged by this gate, and one
                 vacuous sub-gate marks the whole step VACUOUS_PASS.
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
try:
    # ONE waiver vocabulary. If it cannot be imported, nothing is disclosable
    # and every empty rail FAILs — fail-closed, never fail-open.
    import waivers_schema_check as _wv
except ImportError:  # pragma: no cover - standalone use
    _wv = None
try:
    from _reference_flow_boundary import ORACLE_TREE_SEGMENTS
except ImportError:  # pragma: no cover - standalone use
    ORACLE_TREE_SEGMENTS = frozenset({
        "golden", "oracle", "expected", "expected_output",
        "solution", "solutions", "answer", "answers", "ground_truth"})

GATE = "pg_rail_geometry_check"

# The waivers.json field that names rails delivered at integration.
DISCLOSURE_FIELD = "pg_rails_integration_supplied"

# A SPECIALNETS entry opens with `- <name>` at the start of a (stripped) line.
_NET_OPEN = re.compile(r"^-\s+(\S+)")
# Clause keywords that INTRODUCE a wire segment / shape. Matched as clauses
# against a tokenised, comment-stripped line — never as a substring, because a
# substring match cannot tell `+ ROUTED MET1 ...` from the same eight
# characters sitting inside a comment or a quoted property value.
_WIRE_KW = ("ROUTED", "FIXED", "COVER")
_SHAPE_KW = ("RECT", "POLYGON")
# A layer name is a bare identifier. `+ ROUTED` with no layer after it is not a
# wiring statement.
_LAYER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
# `( <inst-or-*> <pinName> )` in the entry HEAD. A DEF coordinate is also a
# parenthesised pair, so a pair of numbers is never a pin.
_PIN_GROUP = re.compile(r"\(\s*([^()\s]+)\s+([^()\s]+)\s*\)")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?\Z")


def sanitize_def_line(line: str) -> str:
    """Strip what the DEF grammar says is not code: `#` line comments, and the
    BODY of quoted strings.

    Both are load-bearing, and in the worst possible direction. `#` opens a
    comment that runs to end of line, so a commented-out geometry row read as
    raw text turns an empty rail into a passing one — a gate whose entire
    reason to exist is "declared but no metal" being talked out of it by a `#`.
    A quoted property value (`+ PROPERTY note "+ ROUTED by hand"`) does the
    same thing with no comment character at all. String bodies are blanked
    rather than deleted so column positions stay usable.
    """
    out = []
    in_str = False
    for ch in line:
        if ch == '"':
            in_str = not in_str
            out.append('"')
        elif ch == "#" and not in_str:
            break
        elif in_str:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _tokens(sane: str) -> list:
    for punct in "+();":
        sane = sane.replace(punct, f" {punct} ")
    return sane.split()


def has_geometry_clause(sane_line: str) -> bool:
    """True when this already-sanitized line carries a real geometry CLAUSE.

    `+ ROUTED|FIXED|COVER <layer>` opens a wire segment, `NEW <layer>`
    continues one, `+ RECT|POLYGON <layer>` places a shape. Each is checked as
    a clause — keyword in the right position, with a layer name after it — so
    that the keyword appearing as prose cannot be mistaken for metal.
    """
    toks = _tokens(sane_line)
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if not _LAYER.match(nxt):
            continue
        prev_is_plus = i > 0 and toks[i - 1] == "+"
        if t in _WIRE_KW and prev_is_plus:
            return True
        if t in _SHAPE_KW and prev_is_plus:
            return True
        # `NEW` continues the wiring statement and opens the line it is on.
        if t == "NEW" and i == 0:
            return True
    return False


def count_pin_connections(head: str) -> int:
    """Pin bindings live in the entry HEAD — between `- <name>` and the first
    `+` clause. Counting `( a b )` groups over the WHOLE entry instead counts
    every routing coordinate as a pin: on a real tracked DEF that turned one
    genuine binding into 333. The number is printed as fact in FAIL messages
    and written into the JSON, so it has to be the real one.
    """
    n = 0
    for a, b in _PIN_GROUP.findall(head):
        if _NUMBER.match(a) and _NUMBER.match(b):
            continue  # a coordinate pair, not a pin
        n += 1
    return n


@dataclass
class Rail:
    name: str
    line: int
    pins: int = 0
    geom_lines: int = 0
    head: str = ""
    in_head: bool = True
    raw: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.geom_lines == 0


def parse_specialnets(def_text: str) -> tuple[list, bool, bool]:
    """Return ``(rails, section_present, truncated)``.

    A special net's body runs from its `- <name>` line until the terminating
    `;`, and may span many lines — which is exactly why a single-line grep for
    a rail name cannot tell an empty rail from a routed one.

    ``truncated`` is True when the section opens and never closes. That case
    must not be parsed as data: scanning on to EOF walks straight into the
    `NETS` section and reports ordinary SIGNAL nets as power rails with zero
    geometry, i.e. it FABRICATES findings out of a damaged file. The caller
    declines to judge instead.
    """
    lines = def_text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        s = sanitize_def_line(ln).strip()
        if start is None and s.startswith("SPECIALNETS"):
            start = i
        elif start is not None and s.startswith("END SPECIALNETS"):
            end = i
            break
    if start is None:
        return [], False, False
    if end is None:
        return [], True, True

    rails: list = []
    cur: Rail | None = None
    for i in range(start + 1, end):
        sane = sanitize_def_line(lines[i])
        s = sane.strip()
        m = _NET_OPEN.match(s)
        if m:
            if cur is not None:
                rails.append(cur)
            cur = Rail(name=m.group(1), line=i + 1)
        if cur is None:
            continue
        cur.raw.append(s)
        if cur.in_head:
            seg = s
            for stop in ("+", ";"):
                if stop in seg:
                    seg = seg.split(stop, 1)[0]
                    cur.in_head = False
            cur.head += " " + seg
        if has_geometry_clause(s):
            cur.geom_lines += 1
        if s.endswith(";"):
            cur.pins = count_pin_connections(cur.head)
            rails.append(cur)
            cur = None
    if cur is not None:
        cur.pins = count_pin_connections(cur.head)
        rails.append(cur)
    return rails, True, False


def disclosures(project: Path) -> dict:
    """Rails a run HONESTLY declares as delivered at integration, read from the
    repo's ONE governed waiver channel.

    Returns ``{rail_name: {"source", "approver", "reason"}}``. An entry counts
    only when it would survive `waivers_schema_check`: a reason of real length
    that is not a placeholder, and a named approver who is neither a
    self-approver nor an unfilled scaffold slot. Those predicates are IMPORTED,
    not restated, so this gate and the schema gate cannot drift apart.

    Fail-closed at every step: a missing file, unreadable bytes, malformed
    JSON, or JSON that is legal but is not an object — `[...]`, `true`, `null`,
    `42` — all disclose nothing and are not errors. Reaching `.get()` on those
    is how this raised AttributeError and killed the run before the report was
    written, on a project that was completely clean.
    """
    out: dict = {}
    if _wv is None:
        return out
    p = project / "waivers.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return out
    if not isinstance(doc, dict):
        return out
    entries = doc.get("waived_steps")
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rails = entry.get(DISCLOSURE_FIELD)
        if not isinstance(rails, list) or not rails:
            continue
        reason = entry.get("reason")
        if (not isinstance(reason, str)
                or len(reason.strip()) < _wv.MIN_REASON_LEN
                or _wv._is_placeholder(reason)):
            continue
        approver = entry.get("approver")
        if (not isinstance(approver, str) or not approver.strip()
                or _wv._is_self_approver(approver)
                or _wv._is_placeholder_approver(approver)):
            continue
        for name in rails:
            if isinstance(name, str) and name.strip():
                out[name.strip()] = {
                    "source": "waivers.json",
                    "approver": approver.strip(),
                    "reason": reason.strip(),
                }
    return out


def _off_limits(path: Path, project: Path) -> bool:
    """A staged reference / oracle tree is never this project's own result."""
    try:
        rel = path.relative_to(project)
    except ValueError:  # pragma: no cover - defensive
        return False
    for seg in rel.parts[:-1]:
        low = seg.lower()
        if low in ORACLE_TREE_SEGMENTS or low.startswith("reference"):
            return True
    return False


def _find_def(project: Path) -> Path | None:
    """The project's OWN routed DEF, or None.

    An unrestricted `rglob("routed.def")` will happily return a staged
    `reference_flow/golden/pnr/routed.def` when the canonical path is absent,
    and then certify the run on the strength of the known-good answer. The
    fallback is therefore restricted to a file that really sits in a `pnr`
    directory and is not inside a reference / oracle tree; when there is no
    such file the honest verdict is NOT CHECKED, not a borrowed PASS.
    """
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
    hits = [h for h in sorted(project.rglob("routed.def"))
            if h.parent.name.lower() == "pnr" and not _off_limits(h, project)]
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

    rails, present, truncated = parse_specialnets(text)
    if truncated:
        return {"gate": GATE, "verdict": "SKIP", "def": str(def_path),
                "reason": ("SPECIALNETS section never terminates (no `END "
                           "SPECIALNETS`) — the DEF is truncated or malformed. "
                           "Declining to judge: scanning past it would report "
                           "signal nets as power rails with no geometry.")}
    if not present:
        return {"gate": GATE, "verdict": "SKIP", "def": str(def_path),
                "reason": "DEF has no SPECIALNETS section — no PG rails declared"}
    if not rails:
        return {"gate": GATE, "verdict": "SKIP", "def": str(def_path),
                "reason": "SPECIALNETS section is empty"}

    disc = disclosures(project)
    for name in (extra_disclosed or set()):
        disc.setdefault(name, {"source": "cli", "approver": None, "reason": None})

    routed = [r for r in rails if not r.empty]
    empty = [r for r in rails if r.empty]
    undisclosed = [r for r in empty if r.name not in disc]

    detail = [{"rail": r.name, "def_line": r.line, "pins": r.pins,
               "geometry_lines": r.geom_lines,
               "disclosed": r.name in disc,
               "disclosure": disc.get(r.name)} for r in rails]

    if undisclosed:
        findings = []
        for r in undisclosed:
            findings.append({
                "rail": r.name, "def_line": r.line, "pins_bound": r.pins,
                "rule": "PG_RAIL_NO_GEOMETRY",
                "detail": (
                    f"rail `{r.name}` is declared in SPECIALNETS at line "
                    f"{r.line} and {r.pins} pin connection(s) bind to it, but it "
                    f"carries ZERO geometry clauses. Pins on it have a valid net "
                    f"pointer and will pass a null-pointer connectivity audit, "
                    f"and a shapes-are-connected check is vacuously true on an "
                    f"empty shape set — but no metal is on the net at all. "
                    f"For comparison this DEF routes "
                    f"{len(routed)} other rail(s) with geometry. If this rail "
                    f"is delivered at integration, disclose it in waivers.json "
                    f"via `{DISCLOSURE_FIELD}` (reason + approver required)."),
            })
        return {"gate": GATE, "verdict": "FAIL", "def": str(def_path),
                "rails_total": len(rails), "rails_routed": len(routed),
                "rails_empty_undisclosed": len(undisclosed),
                "findings": findings, "rails": detail}

    reason = (f"all {len(rails)} declared rail(s) carry a geometry clause "
              f"({len(rails)}/{len(rails)} examined)")
    if empty:
        who = ", ".join(
            f"{r.name} (approved by {disc[r.name].get('approver') or 'CLI caller'})"
            for r in empty)
        reason = (f"{len(routed)}/{len(rails)} rail(s) carry geometry; "
                  f"{len(empty)} empty rail(s) are DISCLOSED as delivered at "
                  f"integration: {who}")
    return {"gate": GATE, "verdict": "PASS", "def": str(def_path),
            "rails_total": len(rails), "rails_routed": len(routed),
            "rails_empty_disclosed": len(empty), "reason": reason,
            "rails": detail}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--integration-supplied", default="",
                    help="comma-separated rails a CALLER already holds the "
                         "contract for. Recorded in the report as source=cli "
                         "so a PASS always says where its excuse came from. "
                         "The channel of record is waivers.json — see "
                         f"`{DISCLOSURE_FIELD}`.")
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
        print(f"{v}: {res.get('reason', '')}", file=stream)
    return {"PASS": 0, "FAIL": 1, "SKIP": 2}[v]


if __name__ == "__main__":
    sys.exit(main())
