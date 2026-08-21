#!/usr/bin/env python3
"""extraction_input_capability_check.py — precondition gate on the EXTRACTION
INPUTS, so "the tool could not verify" is never reported as "the design is
wrong" (or, worse, as nothing at all).

THE DEFECT THIS EXISTS FOR
--------------------------
A Magic technology file can be *present and readable* yet **structurally
incapable of supporting extraction** — a stub whose layer sections are declared
but empty. Magic then cannot resolve the design's layers, `extract all` /
`ext2spice` yield nothing, and the flow reaches:

    LVS_EXTRACTION_NO_NETLIST -> status FAIL
    "Magic ext2spice produced no extracted netlist (rc=0); see ext2spice.log"

That verdict is honest about the *symptom* and silent about the *cause*. It is
reported as **FAIL**, the same terminal class as a genuine netlist mismatch, so
a run that verified NOTHING is shelved next to a run that verified something and
found it broken. The two are not the same fact:

    FAIL    — a compare RAN and the layout does not match the schematic.
    BLOCKED — no compare could run; the inputs cannot produce a netlist.
              Nothing is known about the design, in either direction.

This module answers ONE question, before Magic is launched: *can this
extraction input support extraction at all?* If it demonstrably cannot, the
flow says BLOCKED and names the file and the missing capability, instead of
burning an extraction run to arrive at an unattributed FAIL.

WHY "CANNOT VERIFY" IS ITS OWN VERDICT
--------------------------------------
A checker that can only say PASS or FAIL must lie whenever it could not look.
BLOCKED is the third answer, and it is a REFUSAL, not a pass: it never
satisfies a sign-off gate, and it never counts toward a green run. If BLOCKED
ever becomes a route to green it is a worse defect than the one it fixes.

HOW THE REQUIREMENTS ARE DERIVED (not a hardcoded section list)
--------------------------------------------------------------
The required sections are NOT an assumed "every tech file must have these".
They are derived from **the commands the flow's own extraction recipe issues**.
`required_capabilities(commands)` walks the recipe and unions the tech-file
capabilities each Magic command consumes. Consequences that fall out of the
derivation, rather than being special-cased:

  * the ext2spice recipe never streams GDS, so `cifoutput` is NOT required and
    a tech file lacking it is NOT blocked;
  * the recipe runs `drc off`, so the `drc` section is NOT required;
  * a recipe that DID call `gds write` would require `cifoutput`, automatically.

So the same module gives a different (correct) answer for a different recipe,
and a tech file is never blocked for lacking a capability nothing asked for.
The command->capability map encodes what MAGIC needs, which is a property of
the tool and its file format — chip-, design-, and PDK-agnostic.

A capability is NOT satisfied merely by its section being non-empty. Two of the
three defects that motivated this module survived exactly that reasoning:

  * `lef read` consumes the tech file's `lef` SECTION — the map from
    LEF-namespace layer names onto Magic types. Modelling the COMMAND while
    ignoring the SECTION it reads let a tech file with a populated `styles`
    section and no `lef` section report USABLE, and the run then failed with
    Magic rejecting each layer name it could not map.
  * `extract` can be present, non-empty and syntactically valid while carrying
    only resistance/capacitance rules. Devices come only from `device`
    statements, so extraction succeeds and emits a netlist with ZERO devices —
    a compare against nothing.

Hence `Capability.statements`: coverage is checked at the STATEMENT level the
command actually consumes, not at the section level that merely correlates
with it. "The section is there" is an adjacent measurement, and a check that
passes because it measured something adjacent to the question is the failure
mode this whole module was written to remove.

The design's own layers are the second, design-derived input: `design_layers`
(read from the tech LEF the run is already using) is cross-checked against the
types the tech file actually defines, so the check is grounded in what THIS
design needs rather than in any fixed layer list.

FAIL-SAFE DIRECTION (deliberately opposite to the verdict classifier)
---------------------------------------------------------------------
`lvs_verdict_tokens.classify` is fail-safe toward NOT-PASS: ambiguity becomes
INCOMPLETE, never MATCH, because a false clean ships a broken chip.

This module is fail-safe toward NOT-BLOCKED: it blocks only on POSITIVE,
unambiguous evidence (a required section absent, or present-but-empty), and an
unreadable / unparseable / unrecognised input returns `inconclusive` and lets
the flow proceed exactly as it does today. The reason is that the two modules
guard opposite failures. A false BLOCKED would take a working sign-off away —
it would convert real PASSes and real FAILs alike into "we could not look",
which destroys the very distinction this module was written to create. A
checker that cannot return clean is an alarm, not a checker.

chip-AGNOSTIC: pure Magic tech-file grammar + the flow's own recipe. No PDK,
foundry, layer, or design literal appears anywhere in this file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Capability model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Capability:
    """One thing a tech file must supply for some tool command to work.

    `sections` is an ANY-OF: the capability is satisfied when at least one of
    the named tech sections is present AND non-empty. (Magic accepts several
    spellings for some sections across format revisions; naming them all here
    keeps the check from blocking a valid file written in an older dialect.)

    `statements` is an ALL-OF *within* that section: leading keywords that must
    each appear on some content line. A section can be present and non-empty and
    still not supply the capability — an `extract` section carrying only
    resistance and capacitance rules parses perfectly and emits ZERO devices, so
    "section is non-empty" measures something ADJACENT to "the recipe's needs are
    met". Statement-level coverage is what the command actually consumes.

    `blocking` False marks a capability that is REPORTED but never terminal: the
    recipe is degraded without it, yet extraction still produces a netlist, so
    asserting incapability would risk a false BLOCKED. See the fail-safe note in
    the module docstring — findings that are not certain must not block.
    """
    name: str            # human-readable capability
    sections: Tuple[str, ...]
    needed_for: str      # the tool command / stage that consumes it
    statements: Tuple[str, ...] = ()
    blocking: bool = True


# The capability each Magic command consumes from the technology file.
#
# Keyed by the command's FIRST word, which is how Magic dispatches it. This map
# describes MAGIC's requirements — a property of the tool and its file format,
# not of any PDK or design. Commands the recipe issues that need nothing from
# the tech file (`quit`, `puts`, `select`, `crashbackups`, ...) are simply
# absent, and contribute no requirement.
_LAYER_DEFS = Capability(
    "layer/type definitions",
    ("types",),
    "reading layout (lef read / def read) — maps layer names to Magic types",
)
_PLANES = Capability(
    "plane definitions",
    ("planes",),
    "reading layout — every type must live on a declared plane",
)
_STYLES = Capability(
    "layer styles",
    ("styles",),
    "tech load — each type's style must resolve or the layer is unusable",
)
_CONNECT = Capability(
    "connectivity rules",
    ("connect",),
    "extract — deciding which types are electrically connected",
)
_EXTRACT_RULES = Capability(
    "extraction rules",
    ("extract",),
    "extract all / ext2spice — device, resistance and capacitance rules",
)
_CIFOUT = Capability(
    "CIF/GDS output rules",
    ("cifoutput",),
    "gds write / cif write — mask-layer generation",
)
_DRC_RULES = Capability(
    "DRC rules",
    ("drc",),
    "drc check — design-rule evaluation",
)
# `lef read` / `def read` resolve every LAYER name in the LEF/DEF through the
# tech file's own `lef` SECTION, which maps LEF-namespace names onto Magic
# types (`routing <type> <lefname>...`, `cut ...`, `masterslice ...`, `obs ...`).
# Without it Magic has no mapping for the names the file actually carries and
# rejects them one by one ("Don't know how to parse layer ..."), so the layout
# is never read and extraction runs on an empty cell.
#
# This is a distinct requirement from `types`/`planes`: those declare Magic's
# OWN type namespace, which can be fully populated while the LEF-name mapping is
# absent. Modelling the `lef read` COMMAND without modelling the `lef` SECTION
# it consumes is precisely the adjacent-measurement error.
_LEF_MAP = Capability(
    "LEF layer map",
    ("lef",),
    "lef read / def read — maps LEF-namespace layer names onto Magic types",
)
# `extract` can be present, non-empty and syntactically perfect while carrying
# only parasitic rules. Devices are emitted ONLY by `device` statements, so
# without one the extracted netlist has zero transistors and the LVS compare is
# vacuous — it "passes" a netlist containing nothing to compare.
_EXTRACT_DEVICES = Capability(
    "device extraction rules",
    ("extract",),
    "extract all / ext2spice lvs — emitting devices into the netlist",
    statements=("device",),
)
# `substrate` names the implicit bulk node each device's substrate terminal ties
# to. Its absence DEGRADES the netlist (bulk terminals resolve to a default)
# but devices are still emitted, so this is positive evidence of a defect
# WITHOUT being proof that extraction cannot run: reported, never terminal.
_EXTRACT_SUBSTRATE = Capability(
    "substrate declaration",
    ("extract",),
    "ext2spice lvs — the device bulk/substrate terminal",
    statements=("substrate",),
    blocking=False,
)

_MAGIC_COMMAND_CAPABILITIES: Dict[str, Tuple[Capability, ...]] = {
    # layout input
    "lef":       (_PLANES, _LAYER_DEFS, _STYLES, _LEF_MAP),
    "def":       (_PLANES, _LAYER_DEFS, _STYLES, _LEF_MAP),
    "gds":       (_PLANES, _LAYER_DEFS, _STYLES, _CIFOUT),
    "cif":       (_PLANES, _LAYER_DEFS, _STYLES, _CIFOUT),
    "load":      (_PLANES, _LAYER_DEFS, _STYLES),
    # extraction
    "extract":   (_PLANES, _LAYER_DEFS, _STYLES, _CONNECT, _EXTRACT_RULES,
                  _EXTRACT_DEVICES, _EXTRACT_SUBSTRATE),
    "ext2spice": (_LAYER_DEFS, _CONNECT, _EXTRACT_RULES,
                  _EXTRACT_DEVICES, _EXTRACT_SUBSTRATE),
    "ext2sim":   (_LAYER_DEFS, _CONNECT, _EXTRACT_RULES,
                  _EXTRACT_DEVICES, _EXTRACT_SUBSTRATE),
    # checking
    "drc":       (_DRC_RULES,),
}

# `drc off` / `drc no` DISABLE the checker — they consume no DRC rules. Only a
# DRC command that actually evaluates rules requires the `drc` section.
_DRC_DISABLING_ARGS = {"off", "no", "catchup", "status"}


def required_capabilities(commands: Iterable[str]) -> List[Capability]:
    """Derive the tech-file capabilities a recipe needs, from its COMMANDS.

    `commands` is the tool script the flow will actually run (one command per
    element, or a whole script — blank lines and `#` comments are ignored).
    Returns the de-duplicated capabilities, in first-needed order.

    This is the whole point of the module's derivation: the requirement set is
    a function of the recipe, so a recipe that does not stream GDS is never
    blocked for a missing `cifoutput`, and a recipe that DOES stream GDS is.
    """
    out: List[Capability] = []
    seen = set()
    for raw in _iter_commands(commands):
        toks = raw.split()
        if not toks:
            continue
        head = toks[0].lower()
        if head == "drc" and len(toks) > 1 and toks[1].lower() in _DRC_DISABLING_ARGS:
            continue  # `drc off` needs no rules
        for cap in _MAGIC_COMMAND_CAPABILITIES.get(head, ()):
            if cap.name not in seen:
                seen.add(cap.name)
                out.append(cap)
    return out


def _iter_commands(commands: Iterable[str]):
    """Flatten a recipe (list of commands, or a multi-line script) to commands."""
    if isinstance(commands, str):
        commands = commands.splitlines()
    for chunk in commands:
        for line in str(chunk).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            yield line


# ---------------------------------------------------------------------------
# Magic technology-file grammar
# ---------------------------------------------------------------------------
# A Magic tech file is a flat sequence of top-level sections:
#
#     <section-name>
#         <content ...>
#     end
#
# Top-level section headers and their terminating `end` sit at column 0; the
# nested blocks that appear inside `cifoutput` / `cifinput` / `extract`
# (`style <name> ... end`) are indented. We therefore key on column 0, which is
# the convention Magic's own distributed tech files follow.
_COMMENT_RE = re.compile(r"#.*$")


@dataclass
class TechSection:
    name: str
    start_line: int
    content_lines: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when the section declares nothing at all.

        Whitespace and `#` comments are not content: a section containing only
        a "TODO: fill this in" comment is empty for every purpose Magic cares
        about, and that is exactly the shape a stub tech file takes.
        """
        for line in self.content_lines:
            if _COMMENT_RE.sub("", line).strip():
                return False
        return True

    def leading_keywords(self) -> set:
        """The set of first tokens over this section's content lines.

        Magic's section bodies are keyword-led statements (`device mosfet ...`,
        `substrate ... `, `resist ...`). Statement-level coverage is checked
        against this set, so a section can be non-empty and still be shown to
        lack the specific statement a command consumes.
        """
        out: set = set()
        for raw in self.content_lines:
            line = _COMMENT_RE.sub("", raw).strip()
            if line:
                out.add(line.split()[0].lower())
        return out

    def has_statement(self, keyword: str) -> bool:
        return keyword.lower() in self.leading_keywords()


_INCLUDE_RE = re.compile(r"^\s*include\s+(?P<name>\S+)\s*$", re.I)

# Magic composes a technology from SEVERAL files: a top-level tech file that
# carries `include <name>` lines pulling in sibling files, each holding whole
# sections. Real PDKs ship this way — a tech whose `extract` section lives in
# an included file is COMPLETE, and judging the top-level file alone would
# declare a working PDK incapable. Includes are therefore followed, and an
# include we cannot resolve makes the answer INCONCLUSIVE rather than BLOCKED
# (the capability we think is missing may be sitting in the file we could not
# read).
_MAX_INCLUDE_DEPTH = 8


def parse_tech_sections(text: str,
                        resolver: Optional[Any] = None,
                        _depth: int = 0,
                        _unresolved: Optional[List[str]] = None,
                        ) -> Dict[str, TechSection]:
    """Parse a Magic tech file into its top-level sections, following includes.

    Generic: the section NAMES are whatever the files declare — nothing is
    assumed about which sections should exist. Duplicate sections merge (Magic
    reads them cumulatively).

    `resolver(name) -> text | None` supplies the body of an `include <name>`.
    Names that do not resolve are appended to `_unresolved`.
    """
    sections: Dict[str, TechSection] = {}
    current: Optional[TechSection] = None

    def _merge(sub_sections: Dict[str, TechSection]) -> None:
        for k, v in sub_sections.items():
            if k in sections:
                sections[k].content_lines.extend(v.content_lines)
            else:
                sections[k] = v

    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            if current is not None:
                current.content_lines.append(raw)
            continue
        at_col0 = raw[:1] not in (" ", "\t")
        # `include` is recognised at ANY indentation and BOTH between sections
        # and inside one. Magic's include is a TEXTUAL splice, so it is valid
        # wherever a line is valid; keying it to column 0 between sections made
        # an indented include parse as a bogus section named "include" (and one
        # inside a section vanish into that section's body), silently dropping
        # every capability the included file supplies. Since Magic composes
        # technologies this way, mis-parsing it is a false-BLOCKED generator.
        inc = _INCLUDE_RE.match(raw)
        if inc:
            name = inc.group("name")
            sub = resolver(name) if resolver is not None else None
            if sub is None:
                if _unresolved is not None:
                    _unresolved.append(name)
            elif _depth < _MAX_INCLUDE_DEPTH:
                if current is None:
                    # Between sections: the file supplies whole sections.
                    _merge(parse_tech_sections(
                        sub, resolver, _depth + 1, _unresolved))
                else:
                    # Inside a section: the file supplies that section's BODY
                    # (this is how a long `extract`/`drc` body gets split out).
                    # Textual splice — exactly Magic's own semantics.
                    current.content_lines.extend(sub.splitlines())
            continue
        if current is None:
            if at_col0 and stripped.lower() != "end":
                name = stripped.split()[0].lower()
                current = sections.get(name) or TechSection(name, lineno)
                sections[name] = current
            continue
        if at_col0 and stripped.lower() == "end":
            current = None
            continue
        current.content_lines.append(raw)
    return sections


_TYPE_ALIAS_SPLIT_RE = re.compile(r"[,\s]+")


def defined_types(sections: Dict[str, TechSection]) -> set:
    """The set of layer/type names the tech file defines, with their aliases.

    Magic's `types` section reads `<plane> <name>,<alias>,<alias>`; every token
    after the plane is a usable spelling of that type. Purely grammatical — no
    layer name is hardcoded here.
    """
    out: set = set()
    sec = sections.get("types")
    if sec is None:
        return out
    for raw in sec.content_lines:
        line = _COMMENT_RE.sub("", raw).strip()
        if not line:
            continue
        toks = line.split(None, 1)
        if len(toks) < 2:
            continue
        for alias in _TYPE_ALIAS_SPLIT_RE.split(toks[1]):
            if alias:
                out.add(alias.strip().lower())
    return out


# `lef read` maps a LEF-namespace layer name onto a Magic type through the `lef`
# section: `<kind> <magic-type> <lefname> [<lefname> ...]`.
_LEF_SECTION_KINDS = ("routing", "cut", "masterslice", "obs", "overlap",
                      "bound", "ignore")


def defined_layer_names(sections: Dict[str, TechSection]) -> set:
    """Every spelling this technology can resolve a DESIGN layer name through.

    A design's layer names come from its LEF, and Magic resolves them through
    THREE namespaces, not one:

      * `types`   — Magic's own type names and their comma aliases;
      * `lef`     — the LEF-name -> Magic-type map (`routing m1 Metal1 MET1`),
                    which is the namespace a LEF actually speaks;
      * `aliases` — user-defined collective names.

    Checking a LEF name against `types` ALONE is the wrong name space and
    reports real, working PDKs as undefined: measured on the open-source PDKs
    available here, LEF names such as the top-metal and gate-poly layers appear
    only in the `lef` section, so a types-only comparison called 9 of one PDK's
    27 LEF names and 12 of another's 65 undefined. That was harmless only while
    the cross-check could not block; it becomes a false-BLOCKED generator the
    moment it can. Widening to all three namespaces takes both to zero.

    Purely grammatical — no layer literal is named here.
    """
    out = set(defined_types(sections))
    sec = sections.get("lef")
    if sec is not None:
        for raw in sec.content_lines:
            toks = _COMMENT_RE.sub("", raw).strip().split()
            if len(toks) >= 3 and toks[0].lower() in _LEF_SECTION_KINDS:
                for alias in toks[1:]:
                    out.add(alias.strip().lower())
    sec = sections.get("aliases")
    if sec is not None:
        for raw in sec.content_lines:
            toks = _COMMENT_RE.sub("", raw).strip().split()
            if len(toks) >= 2:
                out.add(toks[0].strip().lower())
    return out


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------
@dataclass
class CapabilityReport:
    """The verdict on ONE extraction input.

    `usable` False means: this input demonstrably cannot support the recipe.
    `inconclusive` True means: we could not tell — the caller MUST proceed as
    it would have without this check (never block on a guess).
    """
    path: str
    usable: bool
    inconclusive: bool
    missing: List[Dict[str, str]] = field(default_factory=list)
    # Capabilities the recipe consumes that are absent but NOT terminal — the
    # netlist is degraded, not impossible. Reported so a real defect is never
    # silent, never blocking so a degraded run is never called unverifiable.
    advisories: List[Dict[str, str]] = field(default_factory=list)
    empty_sections: List[str] = field(default_factory=list)
    absent_sections: List[str] = field(default_factory=list)
    sections_found: List[str] = field(default_factory=list)
    types_defined: int = 0
    design_layers_checked: int = 0
    design_layers_undefined: List[str] = field(default_factory=list)
    reason: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "usable": self.usable,
            "inconclusive": self.inconclusive,
            "missing": self.missing,
            "advisories": self.advisories,
            "empty_sections": self.empty_sections,
            "absent_sections": self.absent_sections,
            "sections_found": self.sections_found,
            "types_defined": self.types_defined,
            "design_layers_checked": self.design_layers_checked,
            "design_layers_undefined": self.design_layers_undefined,
            "reason": self.reason,
            "note": self.note,
        }

    @property
    def missing_capability_names(self) -> List[str]:
        return [m["capability"] for m in self.missing]


# A file that parses into fewer than this many top-level sections is not a tech
# file we recognise (wrong file, a Tcl rc, a truncated download). We report
# `inconclusive` rather than blocking on a file we did not understand.
_MIN_PLAUSIBLE_SECTIONS = 2


def check_magic_tech(text: str,
                     commands: Iterable[str],
                     path: str = "<tech>",
                     design_layers: Optional[Sequence[str]] = None,
                     resolver: Optional[Any] = None,
                     ) -> CapabilityReport:
    """Can this Magic tech file support `commands`?

    Blocks ONLY on positive evidence: a capability whose every candidate
    section is absent, or present-but-empty. Anything we cannot read or
    recognise is `inconclusive`, and the caller proceeds unchanged.

    `resolver(name) -> text | None` supplies `include <name>` bodies. A
    technology split across included files is complete when read together, so
    an include we could not resolve suppresses a would-be BLOCKED.
    """
    unresolved: List[str] = []
    sections = parse_tech_sections(text or "", resolver, 0, unresolved)
    found = sorted(sections)
    if len(sections) < _MIN_PLAUSIBLE_SECTIONS:
        return CapabilityReport(
            path=path, usable=True, inconclusive=True, sections_found=found,
            reason="",
            note=(f"not recognised as a Magic technology file "
                  f"({len(sections)} top-level section(s) parsed) — "
                  f"capability not asserted, flow proceeds unchanged"))

    needed = required_capabilities(commands)
    missing: List[Dict[str, str]] = []
    advisories: List[Dict[str, str]] = []
    empty: List[str] = []
    absent: List[str] = []
    for cap in needed:
        satisfied = False
        cap_empty: List[str] = []
        cap_absent: List[str] = []
        cap_incomplete: List[str] = []
        for name in cap.sections:
            sec = sections.get(name)
            if sec is None:
                cap_absent.append(name)
            elif sec.is_empty:
                cap_empty.append(name)
            elif cap.statements and not all(sec.has_statement(s)
                                            for s in cap.statements):
                # Present, non-empty, and STILL not supplying what the command
                # consumes. Naming the statement is the whole point: "the
                # section is there" is the adjacent measurement.
                lacking = [s for s in cap.statements if not sec.has_statement(s)]
                cap_incomplete.append(f"{name} (no `{'`/`'.join(lacking)}` "
                                      f"statement)")
            else:
                satisfied = True
                break
        if satisfied:
            continue
        if cap_incomplete:
            state = (f"section(s) {', '.join(sorted(cap_incomplete))} present "
                     f"but INCOMPLETE")
        elif cap_empty:
            state = (f"section(s) {', '.join(sorted(cap_empty))} present but "
                     f"EMPTY")
            empty.extend(cap_empty)
        else:
            state = f"section(s) {', '.join(sorted(cap_absent))} absent"
        absent.extend(cap_absent)
        entry = {
            "capability": cap.name,
            "sections": ",".join(cap.sections),
            "state": state,
            "needed_for": cap.needed_for,
        }
        (missing if cap.blocking else advisories).append(entry)

    types = defined_layer_names(sections)
    undefined: List[str] = []
    checked = 0
    layers_block = False
    if design_layers:
        wanted = [str(l).strip().lower() for l in design_layers if str(l).strip()]
        checked = len(wanted)
        undefined = sorted({l for l in wanted if l not in types})
        # INDEPENDENTLY BLOCKING. This cross-check used only to append text to
        # an already-failing reason, so a tech file that was structurally fine
        # but defined NONE of the layers this design is built on returned
        # USABLE — the cross-check could never be the thing that caught it.
        #
        # Blocking needs POSITIVE evidence, so the bar is TOTAL non-coverage:
        # not one of the design's layers is resolvable in any of the three
        # namespaces Magic uses. Partial non-coverage stays advisory, because
        # a LEF may legitimately carry layers this flow never routes on.
        layers_block = bool(checked) and len(undefined) == checked
        if layers_block:
            missing.append({
                "capability": "design layer coverage",
                "sections": "types,lef,aliases",
                "state": (f"none of the {checked} layer(s) this design uses "
                          f"resolve to a type ({', '.join(undefined[:6])}"
                          f"{'...' if len(undefined) > 6 else ''})"),
                "needed_for": ("lef read / def read — every design layer must "
                               "resolve or the layout is never read"),
            })

    if missing and unresolved:
        # The capability we believe is missing may live in an included file we
        # could not read. Never block on that — this is precisely the case
        # that would declare a complete, working PDK incapable.
        return CapabilityReport(
            path=path, usable=True, inconclusive=True,
            sections_found=found, types_defined=len(types),
            note=(f"technology includes {len(unresolved)} file(s) that could "
                  f"not be read here ({', '.join(sorted(set(unresolved))[:4])}"
                  f") — capability not asserted, flow proceeds unchanged"))

    if missing:
        caps = "; ".join(f"{m['capability']} ({m['state']}, needed for "
                         f"{m['needed_for']})" for m in missing)
        reason = (f"technology file cannot support extraction — {caps}")
        if advisories:
            reason += ("; also degraded: "
                       + "; ".join(f"{a['capability']} ({a['state']})"
                                   for a in advisories))
        return CapabilityReport(
            path=path, usable=False, inconclusive=False,
            missing=missing,
            advisories=advisories,
            empty_sections=sorted(set(empty)),
            absent_sections=sorted(set(absent)),
            sections_found=found,
            types_defined=len(types),
            design_layers_checked=checked,
            design_layers_undefined=undefined,
            reason=reason)

    note = ""
    if advisories:
        note = ("; ".join(f"{a['capability']}: {a['state']} — needed for "
                          f"{a['needed_for']}" for a in advisories)
                + " (reported, not blocking: extraction still yields a netlist)")
    if undefined and checked and len(undefined) < checked:
        # Partial coverage is EVIDENCE, not a verdict: Magic renames and
        # aliases layers, so a LEF name absent from every declared namespace is
        # routinely legitimate. Recorded for triage; never blocking.
        # APPENDED, never assigned: overwriting here would silently drop a
        # capability advisory, which is the same class of defect as the ones
        # this module exists to catch.
        partial = (f"{len(undefined)}/{checked} design layer name(s) not found "
                   f"in `types`/`lef`/`aliases` (informational — Magic aliases "
                   f"layers; not treated as a blocker)")
        note = f"{note}; {partial}" if note else partial
    return CapabilityReport(
        path=path, usable=True, inconclusive=False,
        advisories=advisories,
        sections_found=found, types_defined=len(types),
        design_layers_checked=checked, design_layers_undefined=undefined,
        note=note)


def check_magic_tech_file(tech_path: Path,
                          commands: Iterable[str],
                          design_layers: Optional[Sequence[str]] = None
                          ) -> CapabilityReport:
    """`check_magic_tech` over a path. An unreadable file is INCONCLUSIVE.

    Unreadable must never block: the tech file routinely lives inside the tool
    container while this check runs on the host, and "I could not open it" is
    not evidence that the tool cannot either.
    """
    p = Path(tech_path)
    try:
        text = p.read_text(errors="replace")
    except OSError as exc:
        return CapabilityReport(
            path=str(p), usable=True, inconclusive=True,
            note=(f"not readable here ({exc.__class__.__name__}) — capability "
                  f"not asserted, flow proceeds unchanged"))
    return check_magic_tech(text, commands, path=str(p),
                            design_layers=design_layers,
                            resolver=make_dir_resolver(p.parent))


def make_dir_resolver(base_dir):
    """An `include` resolver reading sibling files from `base_dir`.

    Magic writes `include <name>` without the `.tech` suffix, so both spellings
    are tried. Returns None for anything unreadable — the caller then treats
    capability as unknown rather than missing.
    """
    base = Path(base_dir)

    def resolve(name: str) -> Optional[str]:
        for cand in (base / name, base / f"{name}.tech"):
            try:
                if cand.is_file():
                    return cand.read_text(errors="replace")
            except OSError:
                continue
        return None
    return resolve


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------
# Magic's rc file selects the technology with `tech load <file>`. Resolve it so
# the caller can check the TECH FILE while the flow only ever names the rc.
_TECH_LOAD_RE = re.compile(
    r"^\s*tech\s+load\s+(?P<path>[^\s;#]+)", re.M | re.I)


def tech_path_from_magicrc_text(text: str) -> Optional[str]:
    """The tech-file path a magicrc's `tech load` names, VERBATIM, or None.

    Pure text: no filesystem access, so the caller can resolve the result in
    whichever namespace the file actually lives in (the host, or inside the
    tool container). Returns None — never a guess — when the rc names no tech
    file or names one through a Tcl variable we cannot expand.
    """
    return tech_load_directive(text)[0]


# Why the reason matters as much as the path: the runner used to receive a bare
# None for BOTH "this rc loads no technology at all" and "this rc loads one
# through a Tcl variable", and in both cases skipped the capability check
# ENTIRELY and silently. A magicrc written with a variable therefore disabled
# the whole pre-flight with no error and no artifact — the check reported
# nothing, which reads downstream as though it had looked and found nothing
# wrong. Naming the reason lets the caller emit a FINDING instead of a silence.
TECH_LOAD_OK = "ok"
TECH_LOAD_NONE = "no_tech_load_directive"
TECH_LOAD_UNEXPANDED = "tech_load_path_is_unexpanded_tcl"


def tech_load_directive(text: str) -> Tuple[Optional[str], str, str]:
    """`(path, reason, raw)` for a magicrc's `tech load`.

    `path` is None whenever the technology cannot be identified from text
    alone; `reason` says WHICH of the two unresolvable cases it is, and `raw`
    carries the verbatim unexpanded argument so a finding can quote it.
    """
    first_raw = ""
    for m in _TECH_LOAD_RE.finditer(text or ""):
        raw = m.group("path").strip().strip('"').strip("'")
        if "$" in raw or "[" in raw:
            first_raw = first_raw or raw
            continue  # unexpanded Tcl — do not guess
        return raw, TECH_LOAD_OK, raw
    if first_raw:
        return None, TECH_LOAD_UNEXPANDED, first_raw
    return None, TECH_LOAD_NONE, ""


def resolve_tech_from_magicrc(magicrc_path: Path) -> Optional[Path]:
    """Host-side convenience: the `.tech` a magicrc loads, or None.

    None whenever the rc does not name a resolvable tech file — the caller then
    treats capability as unknown and proceeds unchanged.
    """
    rc = Path(magicrc_path)
    try:
        text = rc.read_text(errors="replace")
    except OSError:
        return None
    raw = tech_path_from_magicrc_text(text)
    if raw is None:
        return None
    cand = Path(raw)
    if not cand.is_absolute():
        cand = rc.parent / cand
    if cand.is_file():
        return cand
    if not cand.suffix:
        withext = cand.with_suffix(".tech")
        if withext.is_file():
            return withext
    return None


_LEF_LAYER_RE = re.compile(r"^\s*LAYER\s+([A-Za-z0-9_.\-]+)", re.M | re.I)
_LEF_ROUTING_RE = re.compile(r"^\s*TYPE\s+ROUTING\s*;", re.M | re.I)


def lef_layers(lef_text: str, routing_only: bool = True) -> List[str]:
    """Layer names a LEF declares — the layers THIS design is built on.

    With `routing_only`, only layers whose TYPE is ROUTING are returned (the
    metals extraction must resolve). Purely grammatical; no layer literal.
    """
    out: List[str] = []
    blocks = re.split(r"^\s*LAYER\s+", lef_text or "", flags=re.M | re.I)[1:]
    for blk in blocks:
        name = blk.split(None, 1)[0].strip() if blk.split() else ""
        if not name:
            continue
        head = blk[:blk.lower().find("end " + name.lower())] if (
            "end " + name.lower()) in blk.lower() else blk[:2000]
        if routing_only and not _LEF_ROUTING_RE.search(head):
            continue
        if name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    """Exit 0 = usable (or inconclusive), 1 = BLOCKED, 2 = usage error."""
    ap = argparse.ArgumentParser(
        description="Check whether an extraction input can support extraction.")
    ap.add_argument("tech", help="Magic .tech file (or a .magicrc that loads one)")
    ap.add_argument("--recipe", default=None,
                    help="file holding the tool commands that will be run; "
                         "defaults to the ext2spice recipe's commands")
    ap.add_argument("--tech-lef", default=None,
                    help="tech LEF whose ROUTING layers this design uses")
    ap.add_argument("--json", default=None, help="write the report here")
    args = ap.parse_args(argv)

    p = Path(args.tech)
    if not p.is_file():
        print(f"ERROR: no such file: {p}", file=sys.stderr)
        return 2
    if p.suffix.lower() != ".tech":
        resolved = resolve_tech_from_magicrc(p)
        if resolved is not None:
            p = resolved

    if args.recipe:
        try:
            commands = Path(args.recipe).read_text(errors="replace")
        except OSError as exc:
            print(f"ERROR: cannot read recipe: {exc}", file=sys.stderr)
            return 2
    else:
        commands = DEFAULT_EXT2SPICE_COMMANDS

    layers = None
    if args.tech_lef:
        try:
            layers = lef_layers(Path(args.tech_lef).read_text(errors="replace"))
        except OSError:
            layers = None

    rep = check_magic_tech_file(p, commands, design_layers=layers)
    if args.json:
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2) + "\n")

    if not rep.usable:
        print(f"BLOCKED {rep.path}")
        print(f"  {rep.reason}")
        return 1
    if rep.inconclusive:
        print(f"INCONCLUSIVE {rep.path}: {rep.note}")
        return 0
    print(f"USABLE {rep.path} "
          f"({len(rep.sections_found)} sections, {rep.types_defined} types)")
    if rep.note:
        print(f"  note: {rep.note}")
    return 0


# The commands the flow's ext2spice recipe issues. Kept here so the CLI and the
# runner derive requirements from the SAME recipe.
DEFAULT_EXT2SPICE_COMMANDS = """\
drc off
lef read
def read
load
extract all
ext2spice lvs
ext2spice
"""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
