#!/usr/bin/env python3
"""_ic_release_artefacts.py — is there anything IN the chip artefacts?

WHAT THIS ANSWERS, AND WHAT IT DELIBERATELY DOES NOT
====================================================
Step 37.5ic already has a release verdict: ``tapeout_docs_gen.release_blockers``
decides 17 sign-off properties and refuses to write a document when any of them
is dirty or NOT_MEASURED. That verdict is NOT re-decided here and this module
never contradicts it.

What it cannot reach is the question this module exists for. Every one of those
17 properties is read from ONE artefact — ``phase3/final/metrics.json`` — and a
metrics file is a set of NUMBERS ABOUT a layout, not the layout. Measured
directly: a project whose ``metrics.json`` states ``route__drc_errors: 0``,
``design__lvs_error__count: 0`` and ``timing__setup__ws: 0.42`` produces a full
sign-off report and a Product Brief while its GDS carries ZERO geometry records.
The numbers are clean because nothing was measured; the document is beautiful
because the generator never opened the stream.

That is the failure mode this whole landing exists to stop:

    A generator that writes a datasheet for a design with no geometry in its
    GDS is worse than no generator, because it launders an empty result into a
    document somebody signs.

THE PREDICATE, AND WHY IT IS THE SAME ONE THE IP ARM ALREADY USES
=================================================================
Step 37.5ip's gate refuses a kit whose four views are FILES rather than views —
``V_NO_MODULE``, ``GDS_NO_GEOMETRY``, ``LEF_NO_SIZE``, ``LEF_NO_PIN``, each one
naming a view that exists, has bytes, and carries nothing of the kind it claims
to be. Four ``// stub`` views satisfy every existence check ever written and
none of those four rules.

This module asks the IDENTICAL question of the chip path's own artefacts, and
where the defect is the same the RULE NAME is the same — ``GDS_NO_GEOMETRY`` is
one defect with one name across both arms, and the geometry predicate itself is
``digital_hardmacro_check.gds_geometry_records``, imported rather than
re-implemented. A second spelling of a defect is a second policy, and two
policies is how one of them stops being enforced.

ABSENT IS NOT EMPTY, AND THE TWO MUST NEVER REACH THE SAME COMPARISON
=====================================================================
An artefact class with no file is ``NOT_MEASURED`` with a reason — never a
finding. A run that has not reached routing has no ``routed.def``, and refusing
it would make this module fire on every early run and be switched off within a
week. An artefact class with a file that carries NOTHING is an ERROR: something
wrote it, so something claimed the work was done.

When NO class has a file at all, ``any_present`` is False and the caller exits
on the flow's vacuous tier. Nothing to document is neither a pass nor a refusal.

WHAT IT DOES NOT ADJUDICATE
===========================
* Whether the corners a timing report carries are the RIGHT corners
  (``sta_corner_record_completeness_check`` owns that, and asking it twice would
  give the tree two answers). This module asks only whether the report carries a
  slack number AT ALL.
* Whether a DRC/LVS verdict is CORRECT. It asks only whether the record states
  one.
* Whether the design is releasable. ``tapeout_docs_gen.release_blockers`` owns
  that and is consulted separately by the producer.

§4.05: reads ONLY the run's own generated evidence under ``phase3/`` and
``reports/phase3/``. Never the oracle, the harness, or the golden.

NDA: no commercial foundry name, process node, SKU, chip codename or
qualification programme appears here or in anything this module reports.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import _path_layout as _pl
import digital_hardmacro_check as _hm
from lvs_def_port_seed import parse_def_pins

#: The token every consumer of this module writes into a document when a class
#: supplied nothing. Imported from the shared contract so the producer, the gate
#: and this reader cannot spell "we did not look" three different ways.
from _release_docs_contract import NOT_MEASURED

#: DEF `USE` tokens that make a pin a supply rather than a signal. The same
#: split `digital_hardmacro_gen.read_interface` already makes off the same
#: section, for the same reason: DIRECTION is INPUT/OUTPUT/INOUT and can never
#: hold the token GROUND, so USE is the only field that separates the rails.
_PG_USES = ("POWER", "GROUND")

_DEF_PIN_START_RE = re.compile(r"-\s+(\S+)")
_DEF_USE_RE = re.compile(r"\+\s*USE\s+(\S+)")
_DEF_DIEAREA_RE = re.compile(
    r"(?m)^\s*DIEAREA\b(?P<body>[^;]*);")
_DEF_POINT_RE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)")
_DEF_UNITS_RE = re.compile(r"(?m)^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;")
_DEF_COMPONENTS_RE = re.compile(r"(?m)^\s*COMPONENTS\s+(\d+)\s*;")
_DEF_PINS_HEADER_RE = re.compile(r"(?m)^\s*PINS\s+(\d+)\s*;")


# ── findings ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Finding:
    """One refusal, naming the rule, the class and the artefact it read."""
    rule: str
    severity: str
    artefact_class: str
    path: str
    message: str

    def line(self) -> str:
        return f"{self.rule} [{self.artefact_class}] `{self.path}`: {self.message}"


@dataclass
class ClassState:
    """One artefact class of the chip path, and what this run put in it."""
    class_id: str
    label: str
    #: Project-relative paths found for this class, in sorted order.
    paths: List[str] = field(default_factory=list)
    #: Why the class has no file, when it has none. Empty when it has one.
    absent_reason: str = ""
    findings: List[Finding] = field(default_factory=list)
    #: Whatever the class supplies to a document, keyed by field label.
    facts: Dict[str, Any] = field(default_factory=dict)

    @property
    def present(self) -> bool:
        return bool(self.paths)

    @property
    def refused(self) -> bool:
        return any(f.severity == "ERROR" for f in self.findings)

    def source(self, fallback: str = "") -> str:
        """The path a document cites for a fact this class supplied."""
        return self.paths[0] if self.paths else fallback


@dataclass
class ArtefactAudit:
    project: Path
    classes: List[ClassState] = field(default_factory=list)

    def by_id(self, class_id: str) -> ClassState:
        for state in self.classes:
            if state.class_id == class_id:
                return state
        raise KeyError(f"unknown IC artefact class {class_id!r}")

    @property
    def findings(self) -> List[Finding]:
        return [f for state in self.classes for f in state.findings]

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def any_present(self) -> bool:
        return any(state.present for state in self.classes)

    @property
    def refused(self) -> bool:
        return bool(self.errors)

    def present_ids(self) -> List[str]:
        return [s.class_id for s in self.classes if s.present]


# ── shared readers ─────────────────────────────────────────────────────────
def rel(project: Path, path: Path) -> str:
    try:
        return path.relative_to(project).as_posix()
    except ValueError:  # pragma: no cover - every locator is project-rooted
        return path.as_posix()


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover - the locator just listed it
        return ""


def _numbers_under_key(doc: Any, needles: Sequence[str],
                       _depth: int = 0) -> List[Tuple[str, float]]:
    """Every `(key, number)` anywhere in a JSON document whose key matches.

    A RECURSIVE SUBSTRING SEARCH RATHER THAN A KEY LIST, and the choice is the
    difference between a rule that holds and one that gets switched off. This
    tree's report writers do not agree on where a slack lives — top level,
    under `summary`, under a per-corner list — and a reader that demanded one
    spelling would report "this report carries no timing" over a report that
    plainly states it. That false hole is the WORSE direction: it reddens a
    correct run, and the rule gets deleted rather than the report fixed.

    So the question asked is the weakest one that still catches the defect: does
    a number appear ANYWHERE under a key that names the quantity? A stub report
    has none by construction; a real one has several.
    """
    if _depth > 12:  # pragma: no cover - report trees are shallow
        return []
    out: List[Tuple[str, float]] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            name = str(key).lower()
            if isinstance(value, bool):
                pass
            elif isinstance(value, (int, float)) and any(n in name
                                                         for n in needles):
                out.append((str(key), float(value)))
            out.extend(_numbers_under_key(value, needles, _depth + 1))
    elif isinstance(doc, list):
        for value in doc:
            out.extend(_numbers_under_key(value, needles, _depth + 1))
    return out


def _first_string(doc: Any, keys: Sequence[str]) -> str:
    """The first non-empty string one of `keys` holds, top level or `summary`."""
    scopes: List[dict] = []
    if isinstance(doc, dict):
        scopes.append(doc)
        nested = doc.get("summary")
        if isinstance(nested, dict):
            scopes.append(nested)
    for key in keys:
        for scope in scopes:
            value = scope.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, bool):
                return "PASS" if value else "FAIL"
    return ""


# ── class: GDS ─────────────────────────────────────────────────────────────
def _gds_class(project: Path, release: str = "") -> ClassState:
    """The sign-off layout. `phase3/stage4/gds/*.gds` — step 37.5ic's own input.

    THE ONE PER-RELEASE CLASS, and the scoping is load-bearing. A tree with two
    sign-off streams has two releases, and reading every stream for every
    release would make one hollow GDS redden the OTHER release's document set —
    a refusal that is environmental rather than content-earned, which is exactly
    what a control release exists to detect. MEASURED while writing this: with
    the class unscoped, hollowing `die_a.gds` turned `die_b` red as well.

    Every other class is one-per-run (one routed DEF, one power record) and is
    shared by every release, so a change to one legitimately reddens them all.
    """
    state = ClassState("gds", "Layout (GDS)")
    gds_dir = _pl.gds_dir(project)
    pattern = f"{release}.gds" if release else "*.gds"
    hits = sorted(gds_dir.glob(pattern)) if gds_dir.is_dir() else []
    if not hits:
        named = f"`{release}.gds`" if release else "any .gds"
        state.absent_reason = (
            f"no {named} under {rel(project, gds_dir)}, so this run states its "
            f"layout in no artefact")
        return state
    state.paths = [rel(project, p) for p in hits]
    total = 0
    for path in hits:
        records = _hm.gds_geometry_records(path)
        total += records
        if records <= 0:
            state.findings.append(Finding(
                "GDS_NO_GEOMETRY", "ERROR", "gds", rel(project, path),
                f"the sign-off GDS carries no BOUNDARY/PATH/SREF/AREF/BOX "
                f"record ({path.stat().st_size} bytes of padding, garbage or "
                f"an empty library) — not a layout. Size is not evidence of "
                f"geometry, and a datasheet written over this describes a die "
                f"with nothing on it."))
    state.facts["geometry_records"] = total
    state.facts["gds_files"] = len(hits)
    return state


# ── class: DEF ─────────────────────────────────────────────────────────────
#: The routed DEF is the artefact that states the die outline, what was placed
#: in it and what the die's own pins are. Named here once.
DEF_REL = "phase3/stage3/pnr/routed.def"


def _def_class(project: Path, release: str = "") -> ClassState:
    state = ClassState("def", "Placed and routed layout (DEF)")
    path = _pl.pnr_dir(project) / "routed.def"
    if not path.is_file():
        state.absent_reason = (
            f"{rel(project, path)} is absent, so no artefact of this run "
            f"states the die outline, what was placed in it, or its pins")
        return state
    where = rel(project, path)
    state.paths = [where]
    text = _read_text(path)

    scale = 1000.0
    units = _DEF_UNITS_RE.search(text)
    if units:
        try:
            scale = float(units.group(1)) or 1000.0
        except ValueError:  # pragma: no cover - the regex captured digits
            scale = 1000.0

    die = _DEF_DIEAREA_RE.search(text)
    points = _DEF_POINT_RE.findall(die.group("body")) if die else []
    if len(points) < 2:
        state.findings.append(Finding(
            "DEF_NO_DIEAREA", "ERROR", "def", where,
            "the routed DEF declares no DIEAREA with two corner points, so "
            "nothing in this run states the outline the die occupies. A "
            "datasheet that prints a die size derived from this is printing a "
            "number no artefact supports."))
    else:
        xs = [float(x) for x, _y in points]
        ys = [float(y) for _x, y in points]
        width = (max(xs) - min(xs)) / scale
        height = (max(ys) - min(ys)) / scale
        state.facts["die_width_um"] = round(width, 3)
        state.facts["die_height_um"] = round(height, 3)
        state.facts["die_area_um2"] = round(width * height, 3)

    components = _DEF_COMPONENTS_RE.search(text)
    if components is None:
        state.findings.append(Finding(
            "DEF_NO_COMPONENTS", "ERROR", "def", where,
            "the routed DEF carries no COMPONENTS section at all. A die with "
            "nothing placed in it is not a die, and every area, density and "
            "utilisation figure a document derives from it would be a figure "
            "over an empty outline."))
    else:
        count = int(components.group(1))
        state.facts["placed_instances"] = count
        if count <= 0:
            state.findings.append(Finding(
                "DEF_NO_COMPONENTS", "ERROR", "def", where,
                "the routed DEF declares COMPONENTS 0 — nothing was placed. "
                "The outline exists and the die is empty, which is exactly the "
                "state a document must never render as a product."))

    signal, supply = _def_pins(text)
    state.facts["signal_pins"] = len(signal)
    state.facts["supply_pins"] = len(supply)
    state.facts["total_pins"] = len(signal) + len(supply)
    state.facts["signal_pin_names"] = sorted(signal)
    state.facts["supply_pin_names"] = sorted(supply)
    if not (signal or supply):
        state.findings.append(Finding(
            "DEF_NO_PINS", "ERROR", "def", where,
            "the routed DEF declares no top-level PINS entry, so this die "
            "states no interface. Nothing can be bonded to it and no "
            "datasheet interface section over it would describe anything."))
    return state


def _def_pins(def_text: str) -> Tuple[List[str], List[str]]:
    """`(signal names, supply names)` off the DEF's own PINS section.

    The entry split is ``lvs_def_port_seed.parse_def_pins``' — the shared DEF
    reader this tree already has — so this cannot disagree with it about what a
    pin entry is. Only the POWER/GROUND classification is read here, over the
    same section, for the reason ``digital_hardmacro_gen.read_interface``
    records: ``USE`` is the only field that separates the rails.
    """
    use_by_name: Dict[str, str] = {}
    header = _DEF_PINS_HEADER_RE.search(def_text)
    if header:
        tail = def_text[header.end():]
        end = re.search(r"(?m)^\s*END\s+PINS\b", tail)
        block = tail[: end.start()] if end else tail
        for entry in block.split(";"):
            start = _DEF_PIN_START_RE.search(entry)
            if not start:
                continue
            use = _DEF_USE_RE.search(entry)
            use_by_name[start.group(1)] = use.group(1).upper() if use else ""
    signal: List[str] = []
    supply: List[str] = []
    for pin in parse_def_pins(def_text):
        (supply if use_by_name.get(pin.name, "") in _PG_USES
         else signal).append(pin.name)
    return signal, supply


# ── class: LEF ─────────────────────────────────────────────────────────────
#: Where a chip run's macro abstracts live. BOTH trees, because the digital and
#: analog paths write to different roots and a chip legitimately integrates
#: macros from either. A chip that places no macro has an EMPTY class, which is
#: NOT_MEASURED and not a finding.
_LEF_GLOBS = ("phase3/analog/hardmacro/*/*.lef",
              "phase3/stage4/hardmacro/*.lef")


def _lef_class(project: Path, release: str = "") -> ClassState:
    state = ClassState("lef", "Placed macro abstracts (LEF)")
    hits: List[Path] = []
    for pattern in _LEF_GLOBS:
        hits.extend(sorted(project.glob(pattern)))
    if not hits:
        state.absent_reason = (
            "this run places no macro abstract (searched "
            + ", ".join(_LEF_GLOBS) + "), which is a legitimate shape for a "
            "chip built entirely from standard cells")
        return state
    state.paths = [rel(project, p) for p in hits]
    macros: List[str] = []
    for path in hits:
        where = rel(project, path)
        text = _read_text(path)
        parsed = _hm.parse_lef(text, path.stem)
        macro = parsed.get("macro")
        if isinstance(macro, str) and macro:
            macros.append(macro)
        size = parsed.get("size")
        if not (isinstance(size, (tuple, list)) and len(size) == 2):
            state.findings.append(Finding(
                "LEF_NO_SIZE", "ERROR", "lef", where,
                "this macro abstract declares no MACRO SIZE, so the outline "
                "the floorplan reserved for it is stated by no artefact. A "
                "physical section that reports an area over this is reporting "
                "an area the placer never agreed to."))
        signal = parsed.get("signal")
        pg = parsed.get("pg")
        pins = (signal if isinstance(signal, set) else set()) \
            | (pg if isinstance(pg, set) else set())
        if not pins:
            state.findings.append(Finding(
                "LEF_NO_PIN", "ERROR", "lef", where,
                "this macro abstract declares no PIN — there is nothing for "
                "the integrating route to connect to. A placed macro with no "
                "pin is a keep-out region wearing a macro's name."))
    state.facts["macro_count"] = len(hits)
    state.facts["macro_names"] = sorted(macros)
    return state


# ── class: timing ──────────────────────────────────────────────────────────
STA_REL = "reports/phase3/sta/post_route_summary.json"


def _sta_class(project: Path, release: str = "") -> ClassState:
    state = ClassState("sta", "Post-route timing")
    path = project / STA_REL
    if not path.is_file():
        state.absent_reason = (
            f"{STA_REL} is absent, so no artefact of this run states a "
            f"post-route slack")
        return state
    state.paths = [STA_REL]
    doc = _read_json(path)
    if doc is None:
        state.findings.append(Finding(
            "STA_REPORT_UNREADABLE", "ERROR", "sta", STA_REL,
            "the post-route timing record does not parse as JSON. A timing "
            "claim nobody can re-read is a timing claim nobody can check."))
        return state
    slacks = _numbers_under_key(doc, ("slack", "wns", "tns"))
    if not slacks:
        state.findings.append(Finding(
            "STA_NO_SLACK", "ERROR", "sta", STA_REL,
            "the post-route timing record carries no slack number anywhere — "
            "not a worst slack, not a total negative slack, not one per "
            "corner. A timing report with no slack in it is a file, and a "
            "Timing section written over it states margin nothing measured. "
            "Whether the corners are the RIGHT corners is a different "
            "question and sta_corner_record_completeness_check owns it."))
        return state
    # THE COUNT IS THE SUBSTANCE EVIDENCE AND THE NUMBERS ARE NOT TAKEN FROM
    # HERE. `slack_datapoints` answers the only question this module asks: did
    # anything measure timing at all. The datasheet's own worst-slack rows are
    # derived from `metrics.json`, whose keys (`timing__setup__ws`,
    # `timing__hold__ws`) name the quantity EXACTLY — because the substring
    # search that makes the substance question robust is the wrong instrument
    # for a number a reader will quote. MEASURED while writing this: taking
    # `min()` over every non-"hold" slack key reported the SETUP WORST SLACK as
    # 0.0 on the clean fixture, having silently minimised over `setup_tns_ns`.
    # A robust presence test and a precise value read are two different jobs.
    state.facts["slack_datapoints"] = len(slacks)
    corners = doc.get("summary", {}).get("corners") if isinstance(doc, dict) else None
    if isinstance(corners, list) and corners:
        state.facts["corners_recorded"] = len(corners)
    return state


# ── class: power ───────────────────────────────────────────────────────────
POWER_REL = "reports/phase3/power.json"


def _power_class(project: Path, release: str = "") -> ClassState:
    state = ClassState("power", "Power estimate")
    path = project / POWER_REL
    if not path.is_file():
        state.absent_reason = (
            f"{POWER_REL} is absent, so no artefact of this run states a "
            f"power figure")
        return state
    state.paths = [POWER_REL]
    doc = _read_json(path)
    if doc is None:
        state.findings.append(Finding(
            "POWER_REPORT_UNREADABLE", "ERROR", "power", POWER_REL,
            "the power record does not parse as JSON."))
        return state
    numbers = _numbers_under_key(doc, ("power", "total", "watt"))
    if not numbers:
        state.findings.append(Finding(
            "POWER_NO_TOTAL", "ERROR", "power", POWER_REL,
            "the power record carries no power number anywhere — no total, no "
            "per-group figure. A Power section written over it prints a "
            "consumption nobody estimated."))
        return state
    state.facts["power_datapoints"] = len(numbers)
    totals = [v for k, v in numbers if "total" in k.lower()]
    if totals:
        state.facts["total_power_w"] = max(totals)
    return state


# ── class: the sign-off records ────────────────────────────────────────────
DRC_REL = "reports/phase3/drc_signoff.json"
LVS_REL = "reports/phase3/lvs_verdict.json"

#: The token a sign-off record uses to say, in its own words, that it certified
#: nothing. Read rather than inferred: `drc_report_check` writes exactly this
#: when the audit it wraps could not run.
_NOT_CHECKED = "NOT_CHECKED"


def _drc_class(project: Path, release: str = "") -> ClassState:
    state = ClassState("drc", "DRC sign-off record")
    path = project / DRC_REL
    if not path.is_file():
        state.absent_reason = (
            f"{DRC_REL} is absent, so no artefact of this run states a DRC "
            f"sign-off verdict")
        return state
    state.paths = [DRC_REL]
    doc = _read_json(path)
    if not isinstance(doc, dict):
        state.findings.append(Finding(
            "DRC_SIGNOFF_UNREADABLE", "ERROR", "drc", DRC_REL,
            "the DRC sign-off record does not parse as a JSON mapping."))
        return state
    summary = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    files_found = summary.get("files_found")
    terminal = str(summary.get("terminal_verdict") or "").strip().upper()
    checked = summary.get("checked")
    said_nothing = (
        terminal == _NOT_CHECKED
        or checked is False
        or (isinstance(files_found, int) and not isinstance(files_found, bool)
            and files_found < 1))
    verdict = _first_string(doc, ("verdict", "status", "result", "passed"))
    if said_nothing or not verdict:
        state.findings.append(Finding(
            "DRC_SIGNOFF_NOT_RUN", "ERROR", "drc", DRC_REL,
            f"the DRC sign-off record exists and certifies nothing "
            f"(files_found={files_found!r}, terminal_verdict={terminal!r}, "
            f"verdict={verdict!r}). A record that says the check did not run "
            f"is not a clean check, and a Release Notes verification section "
            f"written over it reports a sign-off that never happened."))
        return state
    state.facts["drc_verdict"] = verdict
    if isinstance(files_found, int) and not isinstance(files_found, bool):
        state.facts["drc_reports_read"] = files_found
    return state


def _lvs_class(project: Path, release: str = "") -> ClassState:
    state = ClassState("lvs", "LVS verdict record")
    path = project / LVS_REL
    if not path.is_file():
        state.absent_reason = (
            f"{LVS_REL} is absent, so no artefact of this run states an LVS "
            f"verdict")
        return state
    state.paths = [LVS_REL]
    doc = _read_json(path)
    if not isinstance(doc, dict):
        state.findings.append(Finding(
            "LVS_VERDICT_UNREADABLE", "ERROR", "lvs", LVS_REL,
            "the LVS verdict record does not parse as a JSON mapping."))
        return state
    verdict = _first_string(doc, ("status", "result", "verdict", "passed"))
    if not verdict:
        state.findings.append(Finding(
            "LVS_NO_VERDICT", "ERROR", "lvs", LVS_REL,
            "the LVS verdict record states no status, result, verdict or "
            "passed field. An empty verdict file and a clean LVS run are "
            "indistinguishable to every reader that only checks the file "
            "exists, and this is the reader that does not."))
        return state
    state.facts["lvs_verdict"] = verdict
    return state


# ── the audit ──────────────────────────────────────────────────────────────
#: Every artefact class of the chip path, in the order a document reads them.
#: Declared as a table so a class can only be added or removed by a visible
#: edit here, and so the producer and the gate iterate the SAME population.
#: Every builder takes ``(project, release)``; only the GDS builder uses the
#: second argument, and a uniform signature is what lets this table be iterated
#: without the caller knowing which classes are per-release.
CLASSES = (
    ("gds", _gds_class),
    ("def", _def_class),
    ("lef", _lef_class),
    ("sta", _sta_class),
    ("power", _power_class),
    ("drc", _drc_class),
    ("lvs", _lvs_class),
)


def audit(project: Path, release: str = "") -> ArtefactAudit:
    """Every chip-path artefact class, and whether anything is IN it.

    ``release`` scopes the classes that are PER-RELEASE (today: the sign-off
    GDS) to that release's own artefact. Passing it is what keeps one hollow
    layout from reddening a second, untouched release built from the same tree.
    Omitting it audits every release's artefacts at once, which is the right
    reading for "does this run have anything at all".
    """
    return ArtefactAudit(
        project=project,
        classes=[builder(project, release) for _id, builder in CLASSES])


def releases(project: Path) -> List[str]:
    """The releases the chip path OWES a document set, derived from the tree.

    ONE PER SIGN-OFF GDS, named by its stem. Derived rather than read off the
    documentation directory, and that is the whole point: reading the directory
    makes "the die was signed off and nobody documented it" an EMPTY SWEEP THAT
    PASSES, which is the vacuous green this landing exists to remove. Reading
    the tree makes it a refusal with a name.

    Named by the GDS stem rather than by `input/project.json`'s design field so
    a release directory can be located with no design declaration at all — a
    project.json that names nothing is a hole in the DOCUMENT, not a licence to
    lose the release.
    """
    gds_dir = _pl.gds_dir(project)
    if not gds_dir.is_dir():
        return []
    return sorted({p.stem for p in gds_dir.glob("*.gds")})


def refusal_lines(audit_result: ArtefactAudit) -> List[str]:
    """One line per refusal, for a producer that must say why it wrote nothing."""
    return [f.line() for f in audit_result.errors]


__all__ = [
    "NOT_MEASURED", "ArtefactAudit", "ClassState", "Finding", "CLASSES",
    "DEF_REL", "STA_REL", "POWER_REL", "DRC_REL", "LVS_REL",
    "audit", "rel", "releases", "refusal_lines",
]
