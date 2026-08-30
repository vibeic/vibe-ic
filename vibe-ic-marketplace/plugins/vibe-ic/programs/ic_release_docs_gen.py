#!/usr/bin/env python3
"""ic_release_docs_gen.py — the PRODUCT documents for a signed-off die.

ENFORCEMENT: advisory — this is a PRODUCER and the token is honest about that.
It is declared in step 37.5ic's ``programs:`` and dispatched by
``phase3_one_shot_runner.step_ic_release_docs_gen`` on the path a real run
takes, and that dispatch NEVER fails the run: a refusal is recorded as SKIP.
The blocking verdict over what it writes is ``release_docs_check --arm ic``,
which step 37.5ic declares in its ``gate.all_of`` and which judges these
documents on their own evidence rather than on this program's exit code. This
token names the measured runner/flow control path, not finding severity.

WHAT THIS ADDS, AND WHAT IT DOES NOT REPLACE
============================================
Step 37.5ic ALREADY has a document generator. ``tapeout_docs_gen`` writes
``reports/phase3/docs/SIGNOFF_*.html`` and ``BRIEF_*.html``, and it is a
generator AND a checker: ``release_blockers()`` decides 17 sign-off properties
and writes NOTHING when any of them is dirty. It is not replaced, not moved,
and not re-decided here. It stays exactly where it is, in step 37.5ic's
blocking ``all_of``.

What it emits is SIGN-OFF EVIDENCE — what was checked, what passed, what did
not — for a reader who already knows what the part is. What it does not emit is
a PRODUCT document: nothing that states what the die is, what its interface is,
what must be connected to it, or what is known to be wrong with it. This
producer writes that set, into a different directory, for a different audience,
on a different lifecycle. The two are different artefact classes and the
existing path is already load-bearing in a blocking gate; moving it would be a
change to 37.5ic's contract dressed up as a documentation task.

THE REQUIREMENT THAT MATTERS, AND IT IS NOT "THE DOCUMENTS ARE GENERATED"
========================================================================
    THE DOCUMENTATION GATE REFUSES A REAL DEFECT, AND THE REFUSAL NAMES IT.

A generator that writes a beautiful datasheet for a design with no geometry in
its GDS is worse than no generator, because it launders an empty result into a
document somebody signs. Step 37.5ip proves its half by planting four ``//
stub`` views and showing the producer refuses to write anything, naming
``V_NO_MODULE`` / ``GDS_NO_GEOMETRY`` / ``LEF_NO_SIZE`` / ``LEF_NO_PIN``.

This is the chip arm's equivalent, over the chip arm's own artefacts, and the
gap it closes is MEASURED rather than supposed: every one of the 17 properties
``release_blockers`` decides is read from ``phase3/final/metrics.json``, which
is a set of NUMBERS ABOUT a layout and not the layout. A project whose metrics
state ``route__drc_errors: 0`` and ``timing__setup__ws: 0.42`` gets a full
sign-off report today while its GDS carries ZERO geometry records — the numbers
are clean because nothing was measured.

So deliverability here is decided by BOTH halves and neither re-decides the
other:

  * ``tapeout_docs_gen.release_blockers`` — the METRICS half, imported, the
    existing verdict of record, unchanged;
  * ``_ic_release_artefacts.audit`` — the SUBSTANCE half, over artefact BYTES,
    a population the metrics half cannot see.

A refusal from either writes NO document and names every rule that refused.

NOTHING TO DOCUMENT IS NEITHER A PASS NOR A REFUSAL
===================================================
With no artefact of any class on disk this program exits 2 (the flow's vacuous
tier) and announces it on the rc-independent channel, where ``_vacuous_exit``
already prints the sentence that matters — "this is NOT a pass over the
design". It never writes a document set for a die that does not exist.

And an EMPTY SWEEP IS NOT WHERE THE TEETH ARE. A die that shipped a GDS with no
document set beside it is refused by ``release_docs_check --arm ic``, which
derives the releases it EXPECTS from the tree rather than from the documentation
directory. That is the difference between a gate and a comment.

DERIVED, NEVER HAND-FED
=======================
Every quantitative field is DERIVED from a named artefact and carries that
artefact's path, or it is explicitly NOT_MEASURED with a reason. Never a
default, never hand-typed — the rule ``tapeout_docs_gen`` already holds ("Read a
metric or return NOT_MEASURED. Never a default."), extended rather than
re-invented, and rendered through the SAME builder the IP arm uses so the two
arms cannot disagree about what a well-formed row is.

§4.05: reads ONLY the design INPUT (``input/project.json``,
``phase1/generated_docs/L*.json``) and the run's OWN generated evidence (the
artefacts under ``phase3/`` and ``reports/phase3/``). Never the oracle, the
harness, or the golden.

NDA: no commercial foundry name, process node, SKU, chip codename or
qualification programme appears in anything this program emits. The PDK string
it prints is the one the project declared for itself. The release-notes section
that would otherwise carry a certification claim is titled by QUESTION —
"Third-Party Qualification Status" — and names no programme.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import _ic_release_artefacts as _art
import _vacuous_exit as _vx
import tapeout_docs_gen as _tap
from _atomic_artefact import write_text as atomic_write_text
from _release_docs_build import (
    Constraint,
    Field,
    constraint_body,
    identity,
    layer,
    layer_count,
    layer_text,
    measured,
    not_measured_body,
    register_rich,
    register_rows,
    sha256_of,
    table,
    tree_sha,
    unmeasured,
    yaml_str,
)
from _release_docs_build import document as _document
from _release_docs_build import list_under as _list_under
from _release_docs_contract import (
    IC_DOCS,
    MANIFEST_NAME,
    NOT_MEASURED,
    PIN_COUNT_LABEL,
    SIGNAL_PIN_LABEL,
    SUPPLY_PIN_LABEL,
    doc_dir,
)

GENERATOR = "ic_release_docs_gen"
VERSION = "1.0.0"

DATASHEET = "PRELIMINARY_DATASHEET.md"
URM = "USER_REFERENCE_MANUAL.md"
RELEASE_NOTES = "RELEASE_NOTES.md"
ERRATA = "ERRATA.md"
APP_NOTE = "AN001_TYPICAL_APPLICATION.md"

#: The metrics file the existing sign-off generator already reads. Named once
#: here so a citation in a document and the file this program opens cannot
#: drift apart.
METRICS_REL = "phase3/final/metrics.json"


def document(title: str, sections: Sequence[Tuple[str, str]]) -> str:
    """This arm's documents, stamped with THIS producer's name and version."""
    return _document(title, sections, GENERATOR, VERSION)


def _spec(filename: str):
    for spec in IC_DOCS:
        if spec.filename == filename:
            return spec
    raise KeyError(f"{filename} is not declared in the IC document contract")


# ── reading the metrics half ───────────────────────────────────────────────
def _metrics(project: Path) -> Tuple[dict, str]:
    """``(metrics, path)`` — the artefact the existing sign-off already reads.

    Read through ``tapeout_docs_gen.load_metrics``, which returns ``{}`` for an
    absent or unreadable file rather than raising. A second metrics reader in
    this tree would be a second answer to "what did this run measure".
    """
    path = project / METRICS_REL
    return _tap.load_metrics(path), METRICS_REL


def _metric_field(metrics: dict, label: str, key: str) -> Field:
    """One metrics row, or the hole where it would have been.

    ``tapeout_docs_gen.g`` is the reader — "Read a metric or return
    NOT_MEASURED. Never a default." — so this document and the sign-off report
    beside it cannot disagree about whether a metric was measured.
    """
    value = _tap.g(metrics, key)
    if value == NOT_MEASURED:
        return unmeasured(
            label, f"{METRICS_REL} carries no `{key}` in this run")
    return measured(label, value, METRICS_REL)


# ── the artefact fields ────────────────────────────────────────────────────
def _class_field(state: _art.ClassState, label: str, fact: str) -> Field:
    """One fact a substance class supplied, cited to the artefact it read.

    A class with no artefact gives the HOLE its own absence reason, and a class
    whose artefact carried nothing never reaches here — the producer has
    already refused by then. That is the whole shape: absent is a disclosed
    hole, empty is a refusal, and the two never reach the same comparison.
    """
    if not state.present:
        return unmeasured(label, state.absent_reason)
    if fact not in state.facts:
        return unmeasured(
            label,
            f"`{state.source()}` is present but states no {label.lower()}")
    return measured(label, state.facts[fact], state.source())


def interface_fields(audit: _art.ArtefactAudit) -> List[Field]:
    """The die's interface, counted off the routed DEF's own PINS section.

    ``release_docs_check`` RE-DERIVES the signal count from the gate-level
    netlist the route produced — a DIFFERENT view, read by a DIFFERENT program
    — and refuses a disagreement naming both sides. It settles the TOTAL
    against this document's own two component rows, because a gate-level
    netlist conventionally carries the logical interface only and cannot speak
    for the supplies. That cross-check is what makes these numbers worth
    reading: they are not merely derived once, they are derived AGAIN.
    """
    state = audit.by_id("def")
    return [
        _class_field(state, PIN_COUNT_LABEL, "total_pins"),
        _class_field(state, SIGNAL_PIN_LABEL, "signal_pins"),
        _class_field(state, SUPPLY_PIN_LABEL, "supply_pins"),
    ]


def physical_fields(audit: _art.ArtefactAudit) -> List[Field]:
    def_state = audit.by_id("def")
    gds_state = audit.by_id("gds")
    lef_state = audit.by_id("lef")
    return [
        _class_field(def_state, "Die width (um)", "die_width_um"),
        _class_field(def_state, "Die height (um)", "die_height_um"),
        _class_field(def_state, "Die area (um^2)", "die_area_um2"),
        _class_field(def_state, "Placed instances", "placed_instances"),
        _class_field(gds_state, "Layout geometry records", "geometry_records"),
        _class_field(lef_state, "Placed macro abstracts", "macro_count"),
    ]


def timing_fields(project: Path, audit: _art.ArtefactAudit,
                  metrics: dict) -> List[Field]:
    sta = audit.by_id("sta")
    return [
        _metric_field(metrics, "Setup worst slack (ns)", "timing__setup__ws"),
        _metric_field(metrics, "Setup total negative slack",
                      "timing__setup__tns"),
        _metric_field(metrics, "Hold worst slack (ns)", "timing__hold__ws"),
        _metric_field(metrics, "Hold total negative slack",
                      "timing__hold__tns"),
        _class_field(sta, "Sign-off slack datapoints", "slack_datapoints"),
        _class_field(sta, "Corners recorded", "corners_recorded"),
        layer_count(project, "L8_TIMING_WAVEFORM", "Declared timing windows",
                    ("timing_windows",)),
        layer_count(project, "L8_TIMING_WAVEFORM", "Declared timing constants",
                    ("timing_constants",)),
    ]


def power_fields(project: Path, audit: _art.ArtefactAudit,
                 metrics: dict) -> List[Field]:
    power = audit.by_id("power")
    return [
        _metric_field(metrics, "Total power (W, estimated)", "power__total"),
        _class_field(power, "Power datapoints", "power_datapoints"),
        layer_count(project, "L21_POWER_INTENT", "Power domains",
                    ("power_domains",)),
        layer_count(project, "L21_POWER_INTENT", "Isolation cells",
                    ("isolation_cells",)),
        layer_count(project, "L21_POWER_INTENT", "Level shifters",
                    ("level_shifters",)),
    ]


def contents_fields(audit: _art.ArtefactAudit) -> List[Field]:
    """ONE ROW PER ARTEFACT CLASS, so an ABSENT class is a visible hole.

    A release note that lists only what a run produced makes an absent DEF and
    a run with no place-and-route look identical. Every declared class gets a
    row whether it exists or not, and the classes are iterated from
    ``_ic_release_artefacts.CLASSES`` so a class can only leave this table by a
    visible edit to that table.
    """
    out: List[Field] = []
    for state in audit.classes:
        if not state.present:
            out.append(unmeasured(state.label, state.absent_reason))
            continue
        # THE FILENAME WHEN THERE IS ONE, the count when there are several. A
        # bare "1" tells a reader nothing they could look up; the name is what
        # they will search the delivery for. The same choice the IP arm's
        # `view_fields` already makes over its four views.
        value = (Path(state.paths[0]).name if len(state.paths) == 1
                 else f"{len(state.paths)} files")
        out.append(measured(state.label, value, state.source()))
    return out


def verification_fields(audit: _art.ArtefactAudit, metrics: dict) -> List[Field]:
    """What this run's own sign-off records say, quoted from those records.

    Deliberately NOT re-derived into a second verdict of this program's own.
    ``release_blockers`` has already been consulted for the deliverability
    decision; a document that states a verdict no written record carries is a
    verdict nobody can re-check.
    """
    drc = audit.by_id("drc")
    lvs = audit.by_id("lvs")
    blockers = _tap.release_blockers(metrics) if metrics else None
    out = [
        _class_field(drc, "DRC sign-off verdict", "drc_verdict"),
        _class_field(drc, "DRC reports read", "drc_reports_read"),
        _class_field(lvs, "LVS verdict", "lvs_verdict"),
    ]
    if blockers is None:
        out.append(unmeasured(
            "Sign-off properties not clean",
            f"{METRICS_REL} is absent or unreadable, so the 17 sign-off "
            f"properties were decided by no artefact of this run"))
    else:
        out.append(measured("Sign-off properties not clean", len(blockers),
                            METRICS_REL))
    return out


# ── mandatory constraints ──────────────────────────────────────────────────
def constraints_for(project: Path, audit: _art.ArtefactAudit) -> List[Constraint]:
    """Every mandatory operating constraint this run's artefacts SUPPORT.

    Emitted only where an artefact states the fact behind it. A constraint no
    artefact supports is not emitted — inventing one would be the hand-typed
    fact this producer exists to refuse, wearing a stronger word.
    """
    out: List[Constraint] = []
    def_state = audit.by_id("def")
    supplies = def_state.facts.get("supply_pin_names") or []
    if supplies:
        pins = ", ".join(f"`{p}`" for p in supplies)
        out.append(Constraint(
            "SUPPLY-CONNECT",
            f"every supply pad this die declares must be bonded and driven "
            f"({pins}); the layout states no default connection for any of "
            f"them",
            def_state.source()))

    width = def_state.facts.get("die_width_um")
    height = def_state.facts.get("die_height_um")
    if width is not None and height is not None:
        out.append(Constraint(
            "DIE-OUTLINE",
            f"the package and the handling flow must accommodate the full "
            f"{width:g} x {height:g} um die outline this layout declares",
            def_state.source()))

    lef_state = audit.by_id("lef")
    macros = lef_state.facts.get("macro_names") or []
    if macros:
        named = ", ".join(f"`{m}`" for m in macros)
        out.append(Constraint(
            "MACRO-INTEGRATION",
            f"this die integrates {len(macros)} placed macro(s) ({named}); any "
            f"re-spin must preserve the outline and pin set each abstract "
            f"declares or the placement is no longer the one signed off",
            lef_state.source()))

    l21, l21_rel = layer(project, "L21_POWER_INTENT")
    domains = _list_under(l21, ("power_domains",))
    if domains:
        out.append(Constraint(
            "POWER-DOMAIN-INTENT",
            f"this design declares {len(domains)} power domain(s); the board "
            f"and the test flow must honour the isolation and level-shifting "
            f"its power intent states",
            l21_rel))

    l7, l7_rel = layer(project, "L7_TEST_DEBUG")
    modes = _list_under(l7, ("test_modes", "test_scenarios"))
    if modes:
        out.append(Constraint(
            "TEST-ACCESS",
            f"this design declares {len(modes)} test mode(s); their control "
            f"and observation must be reachable on the assembled part, or the "
            f"part cannot be tested after packaging",
            l7_rel))

    l19, l19_rel = layer(project, "L19_CONSTRAINTS_PDK")
    hints = _list_under(l19, ("floorplan_hints", "physical_constraints"))
    if hints:
        out.append(Constraint(
            "PHYSICAL-CONSTRAINT",
            f"this design declares {len(hints)} physical constraint(s) any "
            f"re-spin of this layout must continue to satisfy",
            l19_rel))
    return out


# ── the release ────────────────────────────────────────────────────────────
@dataclass
class Release:
    """Everything one document set is built from, resolved exactly once."""
    project: Path
    name: str
    audit: _art.ArtefactAudit
    metrics: dict
    design: Field
    pdk: Field
    tree: Field
    release: Field
    constraints: List[Constraint] = dc_field(default_factory=list)
    register_rich: bool = False
    register_rich_source: str = ""
    conflicts: List[str] = dc_field(default_factory=list)

    def ident(self) -> List[Field]:
        return [self.design, self.pdk, self.release, self.tree]


def _pin_conflicts(project: Path, audit: _art.ArtefactAudit) -> List[str]:
    """DEF vs gate-level netlist, RECORDED here and REFUSED by the gate.

    ``release_docs_check`` decides this on its own evidence. Recording it here
    as well is not a second verdict: the manifest carries it so a reader of the
    DOCUMENTS can see that a disagreement existed, which a reader who never
    opens the gate's JSON otherwise cannot.
    """
    def_state = audit.by_id("def")
    stated = def_state.facts.get("signal_pins")
    if stated is None:
        return []
    netlist = _netlist_ports(project)
    if netlist is None:
        return []
    count, where = netlist
    if count == stated:
        return []
    return [f"DEF vs gate-level netlist signal port count: "
            f"`{def_state.source()}` states {stated}; `{where}` declares "
            f"{count}"]


#: Where the route leaves the gate-level netlist. A glob rather than a fixed
#: name because the emitter names it after the design, and the design name is
#: exactly the literal a chip-AGNOSTIC program may not carry.
PNR_NETLIST_GLOB = "phase3/stage3/pnr/*_pnr.v"


def _netlist_ports(project: Path) -> Optional[Tuple[int, str]]:
    """The logical port count the route's own netlist declares, re-derived.

    Uses ``digital_hardmacro_check.parse_verilog`` — the tree's existing
    Verilog port reader — rather than a second one, so this cannot disagree
    with step 37.5ip about what a port is.
    """
    import digital_hardmacro_check as _hm
    hits = sorted(project.glob(PNR_NETLIST_GLOB))
    if len(hits) != 1:
        # NOT a guess between candidates. Two netlists is two answers, and
        # picking one would make the cross-check depend on sort order.
        return None
    parsed = _hm.parse_verilog(
        hits[0].read_text(encoding="utf-8", errors="replace"), "[]<>")
    ports = parsed.get("ports")
    return ((len(ports) if isinstance(ports, set) else 0),
            _art.rel(project, hits[0]))


def build_release(project: Path, name: str,
                  audit: _art.ArtefactAudit) -> Release:
    design, pdk = identity(project)
    rich, rich_source = register_rich(project)
    metrics, _rel = _metrics(project)
    gds_state = audit.by_id("gds")
    return Release(
        project=project, name=name, audit=audit, metrics=metrics,
        design=design, pdk=pdk, tree=tree_sha(project),
        release=measured("Release", name, gds_state.source(_art.DEF_REL)),
        constraints=constraints_for(project, audit),
        register_rich=rich, register_rich_source=rich_source,
        conflicts=_pin_conflicts(project, audit),
    )


# ── the documents ──────────────────────────────────────────────────────────
def datasheet(rel: Release) -> Tuple[str, List[Field]]:
    ident = rel.ident()
    iface = interface_fields(rel.audit)
    phys = physical_fields(rel.audit)
    timing = timing_fields(rel.project, rel.audit, rel.metrics)
    power = power_fields(rel.project, rel.audit, rel.metrics)
    role = layer_text(rel.project, "L9_INTEGRATION_SPEC", "Module role",
                      ("module_role", "integration_overview"))
    summary = layer_text(rel.project, "L1_DATASHEET", "Datasheet summary",
                         ("summary", "description", "ic_name"))
    every = ident + iface + phys + timing + power + [role, summary]
    spec = _spec(DATASHEET)
    # THE MANDATORY CONSTRAINTS LIVE IN "4. Physical", AND THE CHOICE IS
    # DELIBERATE. `CONSTRAINT_BEARING["ic"]` names this document and the User
    # Reference Manual, and the manual is CONDITIONAL — a die with no register
    # map does not get one. If the constraints lived only there, every
    # non-register-rich release would carry an Application Note restating
    # constraints that appear in no bearing document, which is the exact
    # `MANDATORY_CONSTRAINT_ONLY_IN_APP_NOTE` failure. They go in the one
    # document the contract makes unconditional, collected in one block so a
    # reader finds them in one place rather than scattered by discipline.
    physical_body = (
        table(phys)
        + "\n\n### Mandatory operating constraints\n\n"
        + constraint_body(
            rel.constraints,
            "No artefact of this run supports a mandatory operating "
            "constraint. This is a statement about this run's artefacts, not "
            "a statement that the part has no constraints."))
    body = document(
        f"Preliminary Datasheet — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], table([summary, role])),
            (spec.sections[2],
             table(iface)
             + "\n\nThese counts are derived from the routed layout's own PINS "
               "section. `release_docs_check` re-derives the signal pin count "
               "from the gate-level netlist the route produced and refuses a "
               "disagreement, naming both sides; it settles the total against "
               "its own two component rows, because a gate-level netlist "
               "conventionally carries the logical interface only."),
            (spec.sections[3], physical_body),
            (spec.sections[4], table(timing)),
            (spec.sections[5], table(power)),
            (spec.sections[6], not_measured_body(every)),
        ))
    return body, every


def user_reference_manual(rel: Release) -> Tuple[str, List[Field]]:
    ident = rel.ident()
    counts = [
        layer_count(rel.project, "L4_REGMAP", "Declared registers",
                    ("registers",)),
        layer_count(rel.project, "L4_REGMAP", "Declared internal registers",
                    ("internal_registers",)),
        layer_count(rel.project, "L4_REGMAP", "Declared register groups",
                    ("register_groups",)),
    ]
    base = layer_text(rel.project, "L4_REGMAP", "Base address",
                      ("base_address",))
    sequences = [
        layer_text(rel.project, "L8_TIMING_WAVEFORM", "Clock and reset",
                   ("clock_and_reset_waveform", "general_timing_rule")),
        layer_count(rel.project, "L7_TEST_DEBUG", "Declared test modes",
                    ("test_modes", "test_scenarios")),
    ]
    every = ident + counts + [base] + sequences
    doc, rel_path = layer(rel.project, "L4_REGMAP")
    spec = _spec(URM)
    body = document(
        f"User Reference Manual — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1],
             table(counts + [base]) + "\n\n" + register_rows(doc, rel_path)),
            (spec.sections[2],
             "Register access is defined by the register map layer named "
             f"above (`{rel_path}`). No access rule is restated here that that "
             "layer does not carry: a restated rule is a second copy, and the "
             "copy is what goes stale."),
            (spec.sections[3], table(sequences)),
            (spec.sections[4], not_measured_body(every)),
        ))
    return body, every


def release_notes(rel: Release) -> Tuple[str, List[Field]]:
    ident = rel.ident()
    contents = contents_fields(rel.audit)
    verification = verification_fields(rel.audit, rel.metrics)
    every = ident + contents + verification
    limitations = [
        "- Silicon measurement: not performed. There is no characterised "
        "timing, no measured power, no temperature range and no yield datum "
        "in this release. Every number in this set is a tool estimate over "
        "this run's own artefacts.",
        "- Functional correctness is not the subject of this release. What is "
        "signed off here is manufacturability and the substance of the "
        "artefacts the sign-off was decided over.",
        "- This is a PRELIMINARY datasheet set. A production datasheet "
        "requires post-silicon characterisation evidence that does not exist "
        "at this step.",
    ]
    if rel.conflicts:
        limitations += [f"- View disagreement recorded: {c}"
                        for c in rel.conflicts]
    spec = _spec(RELEASE_NOTES)
    body = document(
        f"Release Notes — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], table(contents)),
            (spec.sections[2], table(verification)),
            (spec.sections[3], "\n".join(limitations)),
            (spec.sections[4],
             "No third-party qualification is claimed for this release. This "
             "flow performs no third-party qualification and this document "
             "names no programme."),
        ))
    return body, every


def errata(rel: Release) -> Tuple[str, List[Field]]:
    ident = rel.ident()
    spec = _spec(ERRATA)
    body = document(
        f"Errata — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1],
             "No erratum is open against this release.\n\n"
             "This document is emitted with an empty open list rather than "
             "omitted. Errata update POST-SHIPMENT, on a cadence the design "
             "release does not control; a release that ships without the "
             "document has nowhere to record the first one, and the absence "
             "of the file is indistinguishable from a release with no known "
             "issues."),
            (spec.sections[2],
             "No erratum has been closed against this release."),
            (spec.sections[3],
             "Report an erratum against the release identified in section 1, "
             "quoting the Tree SHA above. An erratum reported against a "
             "release that does not name its tree cannot be placed."),
        ))
    return body, ident


def application_note(rel: Release) -> Tuple[str, List[Field]]:
    """The optional AN. It RESTATES constraints; it never originates one.

    A mandatory constraint appearing ONLY in an Application Note is a gate
    FAILURE, not a style note — an AN is optional, is read by a subset of
    readers, and is the first document dropped from a delivery. So every
    constraint restated here is emitted from the SAME resolved list the
    datasheet is built from; the AN cannot introduce one, and
    ``release_docs_check`` refuses the set if it ever does.
    """
    ident = rel.ident()
    spec = _spec(APP_NOTE)
    body = document(
        f"AN001 — Typical Application — {rel.design.value}",
        (
            (spec.sections[0],
             "This note shows one way to apply the part identified below. It "
             "is OPTIONAL and carries no requirement of its own. Every "
             "mandatory constraint it mentions is restated from the "
             f"`{DATASHEET}`.\n\n" + table(ident)),
            (spec.sections[1],
             "Connect every pad listed in section 3 of "
             f"`{DATASHEET}`, honour every constraint in section 4 of the "
             "same document, and accommodate the die outline stated there."),
            (spec.sections[2], constraint_body(
                rel.constraints,
                "This release carries no mandatory operating constraint, so "
                "this note restates none.")),
        ))
    return body, ident


# ── the manifest ───────────────────────────────────────────────────────────
def manifest_yaml(rel: Release, written: Sequence[Tuple[str, Path]],
                  fields: Sequence[Field], sources: Sequence[str]) -> str:
    """The YAML that binds this document set to the artefacts it describes.

    ``tree_sha`` because a report that does not name the tree it measured can
    describe the wrong one in four ways and none of them raises an error.
    ``derived_fields`` / ``not_measured_fields`` because a document whose every
    number is NOT_MEASURED is not a document, and only counting them makes that
    visible. ``source_artefacts`` carries a per-file digest because a manifest
    whose digests are never re-derived binds nothing —
    ``release_docs_check`` recomputes every one of them.
    """
    derived = sum(1 for f in fields if f.measured)
    holes = len(fields) - derived
    lines: List[str] = [
        "# Written by ic_release_docs_gen. Every count below is re-derived and",
        "# re-checked by release_docs_check; do not edit it by hand.",
        "schema: vibeic.release_docs.manifest.v1",
        "arm: ic",
        f"generator: {GENERATOR}",
        f"generator_version: {yaml_str(VERSION)}",
        f"release_id: {yaml_str(f'{rel.design.value}-{rel.name}')}",
        f"design: {yaml_str(rel.design.value)}",
        f"pdk: {yaml_str(rel.pdk.value)}",
        f"tree_sha: {yaml_str(rel.tree.value)}",
        f"tree_sha_reason: "
        f"{yaml_str('' if rel.tree.measured else rel.tree.source)}",
        f"register_rich: {'true' if rel.register_rich else 'false'}",
        f"register_rich_source: {yaml_str(rel.register_rich_source)}",
        f"derived_fields: {derived}",
        f"not_measured_fields: {holes}",
        "artefact_classes:",
    ]
    for state in rel.audit.classes:
        lines.append(f"  - class: {yaml_str(state.class_id)}")
        lines.append(f"    present: {'true' if state.present else 'false'}")
        lines.append(f"    paths: [{', '.join(yaml_str(p) for p in state.paths)}]")
        if not state.present:
            lines.append(f"    absent_reason: {yaml_str(state.absent_reason)}")
    lines.append("source_artefacts:")
    for path_rel in sources:
        abs_path = rel.project / path_rel
        if abs_path.is_file():
            lines.append(f"  - path: {yaml_str(path_rel)}")
            lines.append(f"    sha256: {yaml_str(sha256_of(abs_path))}")
    lines.append("documents:")
    for filename, path in written:
        spec = _spec(filename)
        lines.append(f"  - filename: {yaml_str(filename)}")
        lines.append(f"    requirement: {yaml_str(spec.requirement)}")
        lines.append(f"    sha256: {yaml_str(sha256_of(path))}")
    lines.append("unresolved_placeholders: []")
    if rel.conflicts:
        lines.append("source_conflicts:")
        lines.extend(f"  - {yaml_str(c)}" for c in rel.conflicts)
    else:
        lines.append("source_conflicts: []")
    return "\n".join(lines) + "\n"


# ── the run ────────────────────────────────────────────────────────────────
def emit(project: Path, out_dir: Path, name: str,
         audit: _art.ArtefactAudit) -> Tuple[List[Tuple[str, Path]], int, int]:
    """Write one release's document set into its OWN directory.

    ONE DIRECTORY PER RELEASE, ALWAYS, including the single-release case. A
    tree with two sign-off streams has two datasheets, and collapsing the
    common case into the parent directory would make the two shapes different
    — a consumer would have to know how many releases a run had before it could
    find the documents, and the shape exercised on every run would not be the
    shape a two-die run takes.
    """
    rel = build_release(project, name, audit)
    built: List[Tuple[str, str, List[Field]]] = [
        (DATASHEET,) + datasheet(rel),
        (RELEASE_NOTES,) + release_notes(rel),
        (ERRATA,) + errata(rel),
    ]
    if rel.register_rich:
        built.append((URM,) + user_reference_manual(rel))
    built.append((APP_NOTE,) + application_note(rel))

    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Tuple[str, Path]] = []
    all_fields: List[Field] = []
    for filename, text, fields in built:
        path = out_dir / filename
        atomic_write_text(path, text)
        written.append((filename, path))
        all_fields.extend(fields)

    artefact_paths = {p for state in audit.classes for p in state.paths}
    sources = sorted({f.source for f in all_fields if f.measured}
                     | artefact_paths)
    atomic_write_text(out_dir / MANIFEST_NAME,
                      manifest_yaml(rel, written, all_fields, sources))
    derived = sum(1 for f in all_fields if f.measured)
    return written, derived, len(all_fields) - derived


def _refuse(audit: _art.ArtefactAudit, blockers: Sequence[str],
            releases: Sequence[str]) -> int:
    """No documents, and every reason named. Both halves report together.

    ONE REPORT, NOT TWO PASSES. A producer that stops at the first refusing
    half leaves the other half's defects unfound, so the next run repairs one
    thing and is refused again for a reason it could have been told the first
    time.
    """
    print(f"NOT RELEASABLE — no product documents written. "
          f"{len(releases)} release(s) examined.", file=sys.stderr)
    if audit.errors:
        print(f"  the artefacts this run signed off carry no substance "
              f"({len(audit.errors)} refusal(s)):", file=sys.stderr)
        for finding in audit.errors:
            print(f"    - {finding.line()}", file=sys.stderr)
    if blockers:
        print(f"  {GENERATOR} defers to tapeout_docs_gen.release_blockers, "
              f"which reports {len(blockers)} sign-off propert(ies) not "
              f"clean:", file=sys.stderr)
        for blocker in blockers:
            print(f"    - {blocker}", file=sys.stderr)
    print("\nA release document for a run that did not pass is worse than no "
          "document: it becomes a file that outlives the run it came from, "
          "and nothing in the copy says the run was refused.", file=sys.stderr)
    return _vx.RC_FAIL


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=GENERATOR, description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_dir", type=Path,
                        help="project root (holds phase3/stage4/gds/)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help=("where the documents go (default: the "
                              "project-relative path the flow declares)"))
    args = parser.parse_args(argv)

    project: Path = args.project_dir
    if not project.is_dir():
        print(f"ERROR: {project} is not a directory", file=sys.stderr)
        _vx.announce_vacuous(GENERATOR, "project_dir_absent")
        return _vx.RC_VACUOUS

    audit = _art.audit(project)
    releases = _art.releases(project)

    if not audit.any_present:
        # NOTHING TO DOCUMENT IS NOT A PASS, AND IT IS NOT A REFUSAL EITHER.
        # `announce_vacuous` prints the sentence this tier exists for — "this
        # is NOT a pass over the design" — on the rc-independent channel, so a
        # reader of the console cannot mistake rc 2 for a green.
        # THE DENOMINATOR, NAMED. An absence verdict that does not say where
        # it looked is a claim nobody can re-check, so every class is listed
        # with the reason its own locator gave.
        searched = ", ".join(state.class_id for state in audit.classes)
        print(f"[VACUOUS] {GENERATOR} — this run carries no artefact in any "
              f"of the {len(audit.classes)} chip-path classes ({searched}); "
              f"no product documents written")
        for state in audit.classes:
            print(f"  {state.class_id}: {state.absent_reason}")
        _vx.announce_vacuous(GENERATOR, "no_ic_release_artefact")
        return _vx.RC_VACUOUS

    metrics, _rel = _metrics(project)
    blockers = _tap.release_blockers(metrics) if metrics else [
        f"{METRICS_REL}: absent or unreadable, so no sign-off property was "
        f"decided by any artefact of this run"]

    if audit.errors or blockers:
        return _refuse(audit, blockers, releases)

    if not releases:
        # THE ARTEFACTS HAVE SUBSTANCE AND THERE IS NO SIGN-OFF LAYOUT TO NAME
        # A RELEASE AFTER. A run that has routed but not reached step 37 has
        # nothing to write a datasheet ABOUT, and naming the release after
        # anything else would invent an identifier.
        print(f"[VACUOUS] {GENERATOR} — no sign-off GDS under "
              f"{_art.rel(project, project / 'phase3/stage4/gds')}, so this "
              f"run names no release to document")
        _vx.announce_vacuous(GENERATOR, "no_signoff_layout")
        return _vx.RC_VACUOUS

    out_root = (args.out_dir if args.out_dir is not None
                else project / doc_dir("ic"))
    total_derived = total_holes = 0
    written_names: List[str] = []
    for name in releases:
        # RE-AUDITED PER RELEASE, not sliced from the run-wide audit above. The
        # sign-off GDS is the one PER-RELEASE class, and a manifest that listed
        # every release's layout would bind each document set to artefacts it
        # does not describe — so a second die's re-spin would redden the first
        # die's documents through a digest neither of them shares.
        written, derived, holes = emit(project, out_root / name, name,
                                       _art.audit(project, name))
        total_derived += derived
        total_holes += holes
        written_names.extend(str(p) for _, p in written)

    print(f"[PASS] {GENERATOR} — {len(releases)} release(s), "
          f"{len(written_names)} document(s), "
          f"{total_derived} derived field(s), "
          f"{total_holes} {NOT_MEASURED} field(s)")
    for name in written_names:
        print(f"  wrote {name}")
    return _vx.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
