#!/usr/bin/env python3
"""ip_release_docs_gen.py — the release documents for a delivered hard IP.

ENFORCEMENT: advisory — this is a PRODUCER, and the token is honest about that.
It is declared in step 37.5ip's ``programs:`` and dispatched by
``phase3_one_shot_runner.step_ip_release_docs_gen`` on the path a real run
takes, and that dispatch NEVER fails the run: a refusal is recorded as SKIP.
The blocking verdict over what it writes is ``release_docs_check``, which step
37.5ip declares in its ``gate.all_of`` and which judges these documents on
their own evidence rather than on this program's exit code. This token names
the measured runner/flow control path, not finding severity.

WHAT THIS CLOSES
================
Measured on main at v1.13.43: step 37.5ip's ``required_outputs`` are
``*.lef *.lib *.gds *.v`` AND NOTHING ELSE. A hard IP ships today with its four
views and no integration guide — no statement of what it is, no instantiation,
no mandatory constraints, no errata, and no manifest binding the documents to
the views. The chip path at least had ``tapeout_docs_gen``. The IP path — the
one where a document is the ONLY way the next designer learns anything the four
views do not spell — had nothing at all.

An IP is DELIVERED, not fabricated. What is delivered is a kit somebody else
integrates, and every fact they need that is not in the four views reaches them
in a document or does not reach them.

THE RULE THAT MATTERS, AND IT IS NOT A NEW ONE
==============================================
``tapeout_docs_gen`` already holds this line — "Read a metric or return
NOT_MEASURED. Never a default." This program EXTENDS it rather than inventing a
second policy beside it:

    Every quantitative field is DERIVED from a named artefact and carries that
    artefact's path, or it is explicitly NOT_MEASURED with a reason.

Never a default, never hand-typed. Three separate landings on the day this was
written were this exact defect (v1.13.19, v1.13.36, v1.13.39), and in v1.13.39
the hand-written copy was the WRONG one. A datasheet with a hand-typed pin count
is stale on arrival.

The RENDERING is the enforcement surface. Every quantitative table carries a
``Derived from`` column, and ``release_docs_check`` refuses a row whose value is
present with no artefact path behind it, or whose path does not resolve in the
tree. A number nobody can walk back to an artefact does not ship.

DELIVERABILITY IS DECIDED BY THE GATE THAT ALREADY DECIDES IT
=============================================================
``tapeout_docs_gen`` refuses to write a document for a run that did not pass,
because a release document for a failing run is worse than none: it is a FILE,
and files get copied, attached and quoted long after the run they came from is
forgotten.

The same policy holds here and is NOT re-decided here. This program imports
``digital_hardmacro_check.run_audit`` — step 37.5ip's own gate of record — and
writes nothing when that audit refuses the kit. A second opinion about whether
an IP is deliverable would be a second policy, and two policies is how one of
them stops being enforced.

NOTHING TO DOCUMENT IS NEITHER A PASS NOR A REFUSAL. With no kit on disk this
program exits 2 (the flow's vacuous tier), announces it on the rc-independent
channel, and says WHERE it looked — the same reading its own source of truth
reaches as ``NO_HARDMACRO_PACKAGE``. It never writes a document set for a kit
that does not exist.

§4.05: reads ONLY the design INPUT (``input/project.json``,
``phase1/generated_docs/L*.json``) and the run's OWN generated evidence (the
delivered kit under ``phase3/stage4/hardmacro/``). Never the oracle, the
harness, or the golden.

NDA: no commercial foundry name, process node, SKU, chip codename or
qualification programme appears in anything this program emits. The PDK string
it prints is the one the project declared for itself. The release-notes section
that would otherwise carry a certification claim is titled by QUESTION —
"Third-Party Qualification Status" — and names no programme.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import _vacuous_exit as _vx
import digital_hardmacro_check as _hm
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
    sha256_of,
    table,
    tree_sha,
    unmeasured,
)
from _release_docs_build import document as _document
from _release_docs_build import list_under as _list_under
from _release_docs_build import read_json as _read_json
from _release_docs_build import register_rows as _register_rows
from _release_docs_build import rel_str as _rel_str
from _release_docs_build import yaml_str as _yaml_str
from _release_docs_contract import (
    IP_DATASHEET,
    IP_DELIVERABLES_MANIFEST,
    IP_DOCS,
    IP_INTEGRATION_GUIDE,
    MANIFEST_NAME,
    NOT_MEASURED,
    PIN_COUNT_LABEL,
    doc_dir,
)


def document(title, sections):
    """This arm's documents, stamped with THIS producer's name and version.

    A thin binding of the shared builder rather than a second implementation:
    the section titles still come from the contract and the preamble is still
    written once, in one place, for both arms.
    """
    return _document(title, sections, GENERATOR, VERSION)

GENERATOR = "ip_release_docs_gen"
VERSION = "1.0.0"

#: The directory the four delivered views live in, spelled once.
KIT_DIR = "phase3/stage4/hardmacro"


# ── reading the run's own kit ──────────────────────────────────────────────
@dataclass
class Kit:
    """One delivered hardmacro package, parsed once, by the gate's own readers.

    Every parse here is ``digital_hardmacro_check``'s, imported rather than
    re-implemented. A second LEF reader in this tree would be a second answer to
    "what pins does this kit have", and the document could then disagree with
    the gate that guards the same kit.
    """
    name: str
    views: Dict[str, Path]
    project: Path
    lef: Dict[str, object]
    lib: Dict[str, object]
    verilog: Dict[str, object]

    def rel(self, ext: str) -> str:
        """The project-relative path of one view, or "" when it is not shipped."""
        path = self.views.get(ext)
        return "" if path is None else _rel_str(self.project, path)


def _read_view(views: Dict[str, Path], ext: str) -> str:
    path = views.get(ext)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover - discovery just listed it
        return ""


def read_kit(project: Path, name: str, views: Dict[str, Path]) -> Kit:
    lef_text = _read_view(views, ".lef")
    bus = _hm.lef_bus_chars(lef_text) if lef_text else "[]<>"
    lib_text = _read_view(views, ".lib")
    v_text = _read_view(views, ".v")
    return Kit(
        name=name, views=views, project=project,
        lef=_hm.parse_lef(lef_text, name) if lef_text else {},
        lib=_hm.parse_liberty(lib_text, bus) if lib_text else {},
        verilog=_hm.parse_verilog(v_text, bus) if v_text else {},
    )


def _pin_sets(kit: Kit) -> Tuple[set, set]:
    signal = kit.lef.get("signal")
    pg = kit.lef.get("pg")
    return (signal if isinstance(signal, set) else set(),
            pg if isinstance(pg, set) else set())


def interface_fields(kit: Kit) -> List[Field]:
    """The interface, counted off the LEF the integrator will actually place.

    ``release_docs_check`` RE-DERIVES the same count from the delivered Verilog
    view and refuses a disagreement, naming both sides. That cross-check is what
    makes these numbers worth reading: they are not merely derived once, they
    are derived AGAIN by a different program from a different view.
    """
    lef_rel = kit.rel(".lef")
    if not lef_rel:
        why = (f"no .lef view for `{kit.name}` under {KIT_DIR}, so the "
               f"placeable interface has no artefact in this run")
        return [unmeasured(PIN_COUNT_LABEL, why),
                unmeasured("Signal pins", why),
                unmeasured("Supply pins", why)]
    signal, pg = _pin_sets(kit)
    return [
        measured(PIN_COUNT_LABEL, len(signal | pg), lef_rel),
        measured("Signal pins", len(signal), lef_rel),
        measured("Supply pins", len(pg), lef_rel),
    ]


def geometry_fields(kit: Kit) -> List[Field]:
    lef_rel = kit.rel(".lef")
    size = kit.lef.get("size") if lef_rel else None
    if not (isinstance(size, (tuple, list)) and len(size) == 2):
        why = ("the delivered LEF declares no MACRO SIZE, so the outline a "
               "placer must reserve is stated by no artefact in this run")
        return [unmeasured("Macro width (um)", why),
                unmeasured("Macro height (um)", why),
                unmeasured("Macro area (um^2)", why)]
    width, height = float(size[0]), float(size[1])
    return [
        measured("Macro width (um)", round(width, 3), lef_rel),
        measured("Macro height (um)", round(height, 3), lef_rel),
        measured("Macro area (um^2)", round(width * height, 3), lef_rel),
    ]


def view_fields(kit: Kit) -> List[Field]:
    """One row per delivered view, so an ABSENT view is a visible hole."""
    out: List[Field] = []
    for ext, what in ((".lef", "Abstract (LEF)"),
                      (".lib", "Timing (Liberty)"),
                      (".gds", "Layout (GDS)"),
                      (".v", "Simulation (Verilog)")):
        rel = kit.rel(ext)
        if rel:
            out.append(measured(what, Path(rel).name, rel))
        else:
            out.append(unmeasured(
                what, f"no {ext} view for `{kit.name}` under {KIT_DIR}"))
    return out


def name_fields(kit: Kit) -> List[Field]:
    """The name each view calls the macro. Macros are instantiated BY name."""
    out: List[Field] = []
    for key, label, ext in (("macro", "LEF MACRO name", ".lef"),
                            ("cell", "Liberty cell name", ".lib"),
                            ("module", "Verilog module name", ".v")):
        rel = kit.rel(ext)
        source = {".lef": kit.lef, ".lib": kit.lib, ".v": kit.verilog}[ext]
        value = source.get(key) if rel else None
        if isinstance(value, str) and value:
            out.append(measured(label, value, rel))
        elif not rel:
            out.append(unmeasured(label, f"no {ext} view in the delivered kit"))
        else:
            out.append(unmeasured(
                label, f"the delivered {ext} view declares no {key} name"))
    return out


def timing_fields(project: Path, kit: Kit) -> List[Field]:
    lib_rel = kit.rel(".lib")
    out: List[Field] = []
    if lib_rel:
        pins = kit.lib.get("signal")
        out.append(measured("Timed signal pins", len(pins), lib_rel)
                   if isinstance(pins, set)
                   else unmeasured("Timed signal pins",
                                   "the delivered Liberty declares no pin group"))
    else:
        out.append(unmeasured(
            "Timed signal pins",
            f"no .lib view for `{kit.name}` under {KIT_DIR}"))
    out.append(layer_count(project, "L8_TIMING_WAVEFORM",
                           "Declared timing windows",
                           ("timing_windows",)))
    out.append(layer_count(project, "L8_TIMING_WAVEFORM",
                           "Declared timing constants",
                           ("timing_constants",)))
    return out


def power_fields(project: Path, kit: Kit) -> List[Field]:
    lib_rel = kit.rel(".lib")
    out: List[Field] = []
    pg_type = kit.lib.get("pg_type") if lib_rel else None
    if isinstance(pg_type, dict) and pg_type:
        out.append(measured("Declared supply rails", len(pg_type), lib_rel))
    elif lib_rel:
        out.append(unmeasured(
            "Declared supply rails",
            "the delivered Liberty declares no pg_pin group, so the rails are "
            "stated by no artefact in this run"))
    else:
        out.append(unmeasured(
            "Declared supply rails",
            f"no .lib view for `{kit.name}` under {KIT_DIR}"))
    out.append(layer_count(project, "L21_POWER_INTENT", "Power domains",
                           ("power_domains",)))
    out.append(layer_count(project, "L21_POWER_INTENT", "Isolation cells",
                           ("isolation_cells",)))
    out.append(layer_count(project, "L21_POWER_INTENT", "Level shifters",
                           ("level_shifters",)))
    return out


# ── mandatory constraints ──────────────────────────────────────────────────
def constraints_for(project: Path, kit: Kit) -> List[Constraint]:
    """Every mandatory integration constraint this run's artefacts support."""
    out: List[Constraint] = []
    lef_rel = kit.rel(".lef")
    _signal, pg = _pin_sets(kit)

    if lef_rel and pg:
        pins = ", ".join(f"`{p}`" for p in sorted(pg))
        out.append(Constraint(
            "SUPPLY-CONNECT",
            f"the integrating design must connect every supply pin this macro "
            f"declares ({pins}); the abstract states no default connection for "
            f"any of them",
            lef_rel))

    size = kit.lef.get("size") if lef_rel else None
    if isinstance(size, (tuple, list)) and len(size) == 2:
        out.append(Constraint(
            "PLACEMENT-OUTLINE",
            f"the integrating floorplan must reserve the full "
            f"{float(size[0]):g} x {float(size[1]):g} um outline this macro "
            f"declares",
            lef_rel))

    lib_rel = kit.rel(".lib")
    pg_type = kit.lib.get("pg_type") if lib_rel else None
    if isinstance(pg_type, dict) and len(pg_type) > 1:
        rails = ", ".join(f"`{name}` ({kind or 'rail type unstated'})"
                          for name, kind in sorted(pg_type.items()))
        out.append(Constraint(
            "SUPPLY-DOMAIN-SEPARATION",
            f"the supply rails this macro declares are distinct and must not be "
            f"merged by the integrating design ({rails})",
            lib_rel))

    l21, l21_rel = layer(project, "L21_POWER_INTENT")
    domains = _list_under(l21, ("power_domains",))
    if domains:
        out.append(Constraint(
            "POWER-DOMAIN-INTENT",
            f"this IP declares {len(domains)} power domain(s); the integrating "
            f"design must honour the isolation and level-shifting its power "
            f"intent states",
            l21_rel))

    l19, l19_rel = layer(project, "L19_CONSTRAINTS_PDK")
    hints = _list_under(l19, ("floorplan_hints", "physical_constraints"))
    if hints:
        out.append(Constraint(
            "FLOORPLAN-CONSTRAINT",
            f"this IP declares {len(hints)} floorplan constraint(s) the "
            f"integrating design must satisfy",
            l19_rel))

    l7, l7_rel = layer(project, "L7_TEST_DEBUG")
    modes = _list_under(l7, ("test_modes", "test_scenarios"))
    if modes:
        out.append(Constraint(
            "TEST-ACCESS",
            f"this IP declares {len(modes)} test mode(s); the integrating "
            f"design must route their control and observation somewhere a "
            f"tester can reach, or the IP cannot be tested in place",
            l7_rel))

    return out


@dataclass
class Release:
    """Everything one document set is built from, resolved exactly once."""
    project: Path
    kit: Kit
    design: Field
    pdk: Field
    tree: Field
    constraints: List[Constraint]
    register_rich: bool
    register_rich_source: str
    conflicts: List[str]


def _kit_view_conflicts(kit: Kit) -> List[str]:
    """Disagreements between the delivered views, RECORDED not resolved.

    ``digital_hardmacro_check`` refuses these on its own evidence. Recording
    them here as well is not a second verdict: the manifest carries them so a
    reader of the DOCUMENTS can see that a disagreement existed, which a reader
    who never opens the gate's JSON otherwise cannot.
    """
    out: List[str] = []
    lef_signal, lef_pg = _pin_sets(kit)
    lef_all = lef_signal | lef_pg
    ports = kit.verilog.get("ports")
    if kit.rel(".lef") and kit.rel(".v") and isinstance(ports, set):
        # SUPPLY PINS ABSENT FROM THE VERILOG ARE NOT A CONFLICT, and the
        # exception is exactly as wide as the one `digital_hardmacro_check`
        # already states and no wider: a Verilog simulation view of a hard macro
        # conventionally carries the LOGICAL interface only. Recording that
        # convention here as a disagreement would be a SECOND policy over the
        # same evidence, and would put a "source conflict" in the manifest of
        # every correctly built kit — which is how a conflict list stops being
        # read.
        only_lef = sorted(lef_signal - ports)
        only_v = sorted(ports - lef_all)
        if only_lef or only_v:
            out.append(
                f"LEF vs Verilog signal pin set: only in `{kit.rel('.lef')}`: "
                f"{only_lef or 'none'}; only in `{kit.rel('.v')}`: "
                f"{only_v or 'none'}")
    lib_signal = kit.lib.get("signal")
    lib_pg = kit.lib.get("pg")
    if (kit.rel(".lef") and kit.rel(".lib")
            and isinstance(lib_signal, set) and isinstance(lib_pg, set)):
        lib_all = lib_signal | lib_pg
        only_lef = sorted(lef_all - lib_all)
        only_lib = sorted(lib_all - lef_all)
        if only_lef or only_lib:
            out.append(
                f"LEF vs Liberty pin set: only in `{kit.rel('.lef')}`: "
                f"{only_lef or 'none'}; only in `{kit.rel('.lib')}`: "
                f"{only_lib or 'none'}")
    return out


def build_release(project: Path, kit: Kit) -> Release:
    design, pdk = identity(project)
    rich, rich_source = register_rich(project)
    return Release(
        project=project, kit=kit, design=design, pdk=pdk,
        tree=tree_sha(project),
        constraints=constraints_for(project, kit),
        register_rich=rich, register_rich_source=rich_source,
        conflicts=_kit_view_conflicts(kit),
    )


def _ident_fields(rel: Release) -> List[Field]:
    return [rel.design, rel.pdk, rel.tree]


def datasheet(rel: Release) -> Tuple[str, List[Field]]:
    ident = _ident_fields(rel)
    iface = interface_fields(rel.kit)
    views = view_fields(rel.kit)
    names = name_fields(rel.kit)
    geom = geometry_fields(rel.kit)
    timing = timing_fields(rel.project, rel.kit)
    power = power_fields(rel.project, rel.kit)
    role = layer_text(rel.project, "L9_INTEGRATION_SPEC", "Module role",
                      ("module_role", "integration_overview"))
    summary = layer_text(rel.project, "L1_DATASHEET", "Datasheet summary",
                         ("summary", "description", "ic_name"))
    every = ident + iface + views + names + geom + timing + power + [role, summary]
    spec = _spec(IP_DATASHEET)
    body = document(
        f"IP Datasheet — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], table([summary, role])),
            (spec.sections[2],
             table(iface + names)
             + "\n\nThese counts are derived from the delivered abstract. "
               "`release_docs_check` re-derives the signal pin count from the "
               "delivered Verilog view and refuses a disagreement, naming both "
               "sides; it settles the total against its own two component rows, "
               "because a Verilog view of a hard macro conventionally omits the "
               "supplies."),
            (spec.sections[3], table(views + geom)),
            (spec.sections[4], table(timing)),
            (spec.sections[5], table(power)),
            (spec.sections[6], not_measured_body(every)),
        ))
    return body, every


def integration_guide(rel: Release) -> Tuple[str, List[Field]]:
    ident = _ident_fields(rel)
    iface = interface_fields(rel.kit)
    names = name_fields(rel.kit)
    geom = geometry_fields(rel.kit)
    power = power_fields(rel.project, rel.kit)
    clocking = [
        layer_text(rel.project, "L8_TIMING_WAVEFORM", "Clock and reset",
                   ("clock_and_reset_waveform", "general_timing_rule")),
        layer_count(rel.project, "L19_CONSTRAINTS_PDK", "Floorplan hints",
                    ("floorplan_hints", "physical_constraints")),
    ]
    test = [
        layer_count(rel.project, "L7_TEST_DEBUG", "Declared test modes",
                    ("test_modes", "test_scenarios")),
        layer_count(rel.project, "L7_TEST_DEBUG", "Declared debug observability",
                    ("debug_observability",)),
    ]
    every = ident + iface + names + geom + power + clocking + test
    module = next((f for f in names if f.label == "Verilog module name"), None)
    module_name = module.value if module and module.measured else NOT_MEASURED
    inst = (
        "Instantiate the macro by the name its simulation view declares. The "
        "three views must be instantiated under one name; step 37.5ip's own "
        "gate refuses a kit whose views disagree about it.\n\n"
        "```verilog\n"
        f"{module_name} u_{rel.kit.name} (\n"
        "    // connect every pin the abstract declares; the counts are below\n"
        ");\n"
        "```\n\n"
        + table(names)
        + "\n\nThe interface this instantiation must connect:\n\n"
        + table(iface))
    spec = _spec(IP_INTEGRATION_GUIDE)
    body = document(
        f"IP Integration Guide — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], inst),
            (spec.sections[2], constraint_body(
                rel.constraints,
                "No artefact of this run supports a mandatory integration "
                "constraint. This is a statement about this run's artefacts, "
                "not a statement that the IP has no constraints.")),
            (spec.sections[3], table(clocking)),
            (spec.sections[4], table(power)),
            (spec.sections[5], table(geom)),
            (spec.sections[6], table(test)),
            (spec.sections[7], not_measured_body(every)),
        ))
    return body, every


def _delivered_views_field(rel: Release) -> Field:
    return measured("Views delivered", len(rel.kit.views), KIT_DIR)


def _kit_verdict_field(rel: Release) -> Field:
    """The verdict step 37.5ip's own gate RECORDED, quoted from its record.

    Read out of the gate's JSON when the gate has written one, and NOT_MEASURED
    with the reason when it has not. Deliberately NOT re-derived into a second
    verdict of this program's own: the deliverability decision above already
    consults `digital_hardmacro_check`, and a document that states a verdict no
    written record carries is a verdict nobody can re-check.
    """
    rel_path = "reports/phase3/digital_hardmacro.json"
    doc = _read_json(rel.project / rel_path)
    tier = (doc or {}).get("verdict_tier") if isinstance(doc, dict) else None
    summary = (doc or {}).get("summary") if isinstance(doc, dict) else None
    if not isinstance(tier, str) or not tier:
        if isinstance(summary, dict) and isinstance(summary.get("verdict_tier"), str):
            tier = summary["verdict_tier"]
    if isinstance(tier, str) and tier:
        return measured("Delivered-kit verdict", tier, rel_path)
    return unmeasured(
        "Delivered-kit verdict",
        f"{rel_path} carries no verdict_tier in this run, so no written record "
        f"states the verdict this release was granted")


def release_notes(rel: Release) -> Tuple[str, List[Field]]:
    ident = _ident_fields(rel)
    views = view_fields(rel.kit)
    status = [_delivered_views_field(rel), _kit_verdict_field(rel)]
    every = ident + views + status
    limitations = [
        "- Silicon measurement: not performed. There is no characterised "
        "timing, no measured power, no temperature range and no yield datum "
        "in this release.",
        "- Functional correctness is not the subject of this release. What is "
        "signed off here is the deliverability of the kit.",
    ]
    if rel.conflicts:
        limitations += [f"- View disagreement recorded: {c}"
                        for c in rel.conflicts]
    spec = _spec("RELEASE_NOTES.md")
    body = document(
        f"Release Notes — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], table(views)),
            (spec.sections[2], table(status)),
            (spec.sections[3], "\n".join(limitations)),
            (spec.sections[4],
             "No third-party qualification is claimed for this release. This "
             "flow performs no third-party qualification and this document "
             "names no programme."),
        ))
    return body, every


def errata(rel: Release) -> Tuple[str, List[Field]]:
    ident = _ident_fields(rel)
    spec = _spec("ERRATA.md")
    body = document(
        f"Errata — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1],
             "No erratum is open against this release.\n\n"
             "This document is emitted with an empty open list rather than "
             "omitted. Errata update POST-SHIPMENT, on a cadence the design "
             "release does not control; a release that ships without the "
             "document has nowhere to record the first one, and the absence of "
             "the file is indistinguishable from a release with no known "
             "issues."),
            (spec.sections[2], "No erratum has been closed against this "
                               "release."),
            (spec.sections[3],
             "Report an erratum against the release identified in section 1, "
             "quoting the Tree SHA above. An erratum reported against a "
             "release that does not name its tree cannot be placed."),
        ))
    return body, ident


def deliverables_manifest(rel: Release) -> Tuple[str, List[Field]]:
    ident = _ident_fields(rel)
    rows = ["| File | Bytes | sha256 |", "| --- | --- | --- |"]
    for ext in (".lef", ".lib", ".gds", ".v"):
        path = rel.kit.views.get(ext)
        if path is None:
            rows.append(f"| (no {ext} view) | {NOT_MEASURED} | {NOT_MEASURED} |")
            continue
        rows.append(f"| `{_rel_str(rel.project, path)}` | "
                    f"{path.stat().st_size} | `{sha256_of(path)}` |")
    spec = _spec(IP_DELIVERABLES_MANIFEST)
    body = document(
        f"Deliverables Manifest — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], "\n".join(rows)),
            (spec.sections[2],
             "Each digest above is the SHA-256 of the file's bytes as shipped. "
             "`release_docs_check` recomputes every one of them against the "
             "tree and refuses a disagreement: a manifest whose digests are "
             "never re-derived binds nothing."),
        ))
    return body, ident


def programming_reference(rel: Release) -> Tuple[str, List[Field]]:
    ident = _ident_fields(rel)
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
    every = ident + counts + [base]
    doc, rel_path = layer(rel.project, "L4_REGMAP")
    rows = _register_rows(doc, rel_path)
    spec = _spec("IP_PROGRAMMING_REFERENCE.md")
    body = document(
        f"IP Programming Reference — {rel.design.value}",
        (
            (spec.sections[0], table(ident)),
            (spec.sections[1], table(counts + [base]) + "\n\n" + rows),
            (spec.sections[2],
             "Register access is defined by the register map layer named "
             f"above (`{rel_path}`). No access rule is restated here that that "
             "layer does not carry: a restated rule is a second copy, and the "
             "copy is what goes stale."),
            (spec.sections[3], not_measured_body(every)),
        ))
    return body, every


def application_note(rel: Release) -> Tuple[str, List[Field]]:
    """The optional AN. It RESTATES constraints; it never originates one.

    A mandatory constraint appearing ONLY in an Application Note is a gate
    FAILURE, not a style note — an AN is optional, is read by a subset of
    integrators, and is the first document dropped from a delivery. So every
    constraint restated here is emitted from the SAME resolved list the
    Integration Guide is built from; the AN cannot introduce one, and
    ``release_docs_check`` refuses the set if it ever does.
    """
    ident = _ident_fields(rel)
    spec = _spec("AN001_REFERENCE_INTEGRATION.md")
    body = document(
        f"AN001 — Reference Integration — {rel.design.value}",
        (
            (spec.sections[0],
             "This note shows one way to integrate the IP identified below. It "
             "is OPTIONAL and carries no requirement of its own. Every "
             "mandatory constraint it mentions is restated from the Datasheet "
             "or the Integration Guide.\n\n" + table(ident)),
            (spec.sections[1],
             "Connect every pin listed in section 3 of "
             f"`{IP_DATASHEET}`, honour every constraint in section 3 of "
             f"`{IP_INTEGRATION_GUIDE}`, and reserve the outline stated in "
             "section 4 of the datasheet."),
            (spec.sections[2], constraint_body(
                rel.constraints,
                "This release carries no mandatory integration constraint, so "
                "this note restates none.")),
        ))
    return body, ident


def _spec(filename: str):
    for spec in IP_DOCS:
        if spec.filename == filename:
            return spec
    raise KeyError(f"{filename} is not declared in the IP document contract")


# ── the manifest ───────────────────────────────────────────────────────────
def manifest_yaml(rel: Release, written: Sequence[Tuple[str, Path]],
                  fields: Sequence[Field],
                  sources: Sequence[str]) -> str:
    """The YAML that binds this document set to the artefacts it describes.

    ``tree_sha`` because a report that does not name the tree it measured can
    describe the wrong one in four ways and none of them raises an error.
    ``derived_fields`` / ``not_measured_fields`` because a document whose every
    number is NOT_MEASURED is not a document, and only counting them makes that
    visible. ``release_docs_check`` RECOUNTS both from the documents and refuses
    a disagreement — a count nobody re-derives is a count that drifts.
    """
    derived = sum(1 for f in fields if f.measured)
    holes = len(fields) - derived
    lines: List[str] = [
        "# Written by ip_release_docs_gen. Every count below is re-derived and",
        "# re-checked by release_docs_check; do not edit it by hand.",
        "schema: vibeic.release_docs.manifest.v1",
        "arm: ip",
        f"generator: {GENERATOR}",
        f"generator_version: {_yaml_str(VERSION)}",
        f"release_id: {_yaml_str(f'{rel.design.value}-{rel.kit.name}')}",
        f"design: {_yaml_str(rel.design.value)}",
        f"pdk: {_yaml_str(rel.pdk.value)}",
        f"tree_sha: {_yaml_str(rel.tree.value)}",
        f"tree_sha_reason: {_yaml_str('' if rel.tree.measured else rel.tree.source)}",
        f"register_rich: {'true' if rel.register_rich else 'false'}",
        f"register_rich_source: {_yaml_str(rel.register_rich_source)}",
        f"derived_fields: {derived}",
        f"not_measured_fields: {holes}",
        "source_artefacts:",
    ]
    for path_rel in sources:
        abs_path = rel.project / path_rel
        if abs_path.is_file():
            lines.append(f"  - path: {_yaml_str(path_rel)}")
            lines.append(f"    sha256: {_yaml_str(sha256_of(abs_path))}")
    lines.append("documents:")
    for filename, path in written:
        spec = _spec(filename)
        lines.append(f"  - filename: {_yaml_str(filename)}")
        lines.append(f"    requirement: {_yaml_str(spec.requirement)}")
        lines.append(f"    sha256: {_yaml_str(sha256_of(path))}")
    lines.append("unresolved_placeholders: []")
    if rel.conflicts:
        lines.append("source_conflicts:")
        lines.extend(f"  - {_yaml_str(c)}" for c in rel.conflicts)
    else:
        lines.append("source_conflicts: []")
    return "\n".join(lines) + "\n"


# ── the run ────────────────────────────────────────────────────────────────
def emit(project: Path, out_dir: Path,
         kit: Kit) -> Tuple[List[Tuple[str, Path]], int, int]:
    """Write one package's document set into its OWN directory.

    ONE DIRECTORY PER PACKAGE, ALWAYS, including the single-package case. A kit
    with two macros has two datasheets, and collapsing the common case into the
    parent directory would make the two shapes different — so a consumer would
    have to know how many packages a release had before it could find the
    documents, and the shape that is exercised on every run would not be the
    shape a two-macro release takes.
    """
    rel = build_release(project, kit)
    built: List[Tuple[str, str, List[Field]]] = []

    for filename, builder in (
            (IP_DATASHEET, datasheet),
            (IP_INTEGRATION_GUIDE, integration_guide),
            ("RELEASE_NOTES.md", release_notes),
            ("ERRATA.md", errata),
            (IP_DELIVERABLES_MANIFEST, deliverables_manifest),
    ):
        text, fields = builder(rel)
        built.append((filename, text, fields))

    if rel.register_rich:
        text, fields = programming_reference(rel)
        built.append(("IP_PROGRAMMING_REFERENCE.md", text, fields))

    text, fields = application_note(rel)
    built.append(("AN001_REFERENCE_INTEGRATION.md", text, fields))

    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Tuple[str, Path]] = []
    all_fields: List[Field] = []
    for filename, text, fields in built:
        path = out_dir / filename
        atomic_write_text(path, text)
        written.append((filename, path))
        all_fields.extend(fields)

    sources = sorted({f.source for f in all_fields if f.measured}
                     | {_rel_str(project, p) for p in kit.views.values()})
    atomic_write_text(out_dir / MANIFEST_NAME,
                      manifest_yaml(rel, written, all_fields, sources))
    derived = sum(1 for f in all_fields if f.measured)
    return written, derived, len(all_fields) - derived


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=GENERATOR, description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project_dir", type=Path,
                        help="project root (holds phase3/stage4/hardmacro/)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help=("where the documents go (default: the "
                              "project-relative path the flow declares)"))
    args = parser.parse_args(argv)

    project: Path = args.project_dir
    if not project.is_dir():
        print(f"ERROR: {project} is not a directory", file=sys.stderr)
        _vx.announce_vacuous(GENERATOR, "project_dir_absent")
        return _vx.RC_VACUOUS

    hm_dir = _hm.hardmacro_dir(project)
    packages = _hm.discover_packages(hm_dir)
    if not packages:
        # NOTHING TO DOCUMENT IS NOT A PASS, and it is not a refusal either.
        # Same reading `digital_hardmacro_check` reaches as NO_HARDMACRO_PACKAGE
        # over the same directory, so the producer and its gate cannot disagree
        # about whether this run had a kit at all.
        print(f"[VACUOUS] {GENERATOR} — examined 0 hardmacro package(s) under "
              f"{_rel_str(project, hm_dir)}; no release documents written")
        _vx.announce_vacuous(GENERATOR, "no_hardmacro_package")
        return _vx.RC_VACUOUS

    audit = _hm.run_audit(project)
    if not audit.passed:
        # THE SAME POLICY `tapeout_docs_gen` HOLDS, NOT A SECOND ONE. A release
        # document for a kit its own gate refuses is worse than no document: it
        # is a FILE, it outlives the run, and nothing in the copy says the kit
        # was refused.
        print(f"NOT DELIVERABLE — no documents written. "
              f"{len(packages)} package(s) examined; "
              f"{GENERATOR} defers to digital_hardmacro_check, which refuses "
              f"this kit:", file=sys.stderr)
        for finding in audit.findings:
            if finding.severity == "ERROR":
                print(f"  - {finding.rule}: {finding.message}", file=sys.stderr)
        return _vx.RC_FAIL

    out_root = args.out_dir if args.out_dir is not None \
        else project / doc_dir("ip")
    total_derived = total_holes = 0
    written_names: List[str] = []
    for name in sorted(packages):
        kit = read_kit(project, name, packages[name])
        written, derived, holes = emit(project, out_root / name, kit)
        total_derived += derived
        total_holes += holes
        written_names.extend(str(p) for _, p in written)

    print(f"[PASS] {GENERATOR} — {len(packages)} package(s), "
          f"{len(written_names)} document(s), "
          f"{total_derived} derived field(s), "
          f"{total_holes} {NOT_MEASURED} field(s)")
    for name in written_names:
        print(f"  wrote {name}")
    return _vx.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
