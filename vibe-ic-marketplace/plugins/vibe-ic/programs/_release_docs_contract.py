#!/usr/bin/env python3
"""_release_docs_contract.py — ONE declaration of what a release document set is.

WHY A SHARED MODULE AND NOT TWO COPIES
======================================
A generator that decides which sections it writes, and a checker that decides
which sections it demands, are two definitions of the same contract. The
direction that drift goes is the one nobody sees: the generator stops writing a
section, the checker's own list is edited to match "so the gate goes green", and
the document set silently loses the section both were built to guarantee.

Landed on this tree the day this module was written, all the same defect:
v1.13.19 (a census guard whose literal lagged the flow six times), v1.13.36 (a
protected register whose byte-state was a photograph of one commit), v1.13.39
(two skills declaring a stage the flow already named — and the hand-written copy
was the WRONG one).

So the contract is declared exactly once, here, and both
``ip_release_docs_gen`` (the producer) and ``release_docs_check`` (the gate)
read it. A section can only be removed by editing this file, which is a visible
edit in a diff.

THE TWO ARMS, AND WHY THEY ARE DECLARED TOGETHER
================================================
Step 37.5ip delivers an IP: somebody else places it, times it, simulates it and
must be told how. Step 37.5ic signs off a die. They are different artefact
classes with different audiences, so they get different document sets — but the
RULES over those sets (every quantitative field is derived or NOT_MEASURED; a
mandatory constraint may not originate in an Application Note; the manifest
binds the documents to the artefacts they describe) are identical, and a rule
declared twice is a rule that will disagree with itself.

THE FIELD TABLE FORMAT IS PART OF THE CONTRACT
==============================================
``DERIVED_COLUMN`` names the third column every quantitative table carries. A
row is well-formed in exactly two ways and there is no third:

    | Pin count (total) | 42            | `phase3/stage4/hardmacro/w.lef` |
    | Max frequency     | NOT_MEASURED  | reason: no L8 timing constant   |

A value with no artefact path behind it is a hand-typed number, and a hand-typed
copy of an automatically-changing fact is stale by construction. A datasheet
with a hand-typed pin count is stale on arrival.

THE MANDATORY-CONSTRAINT MARKER IS PART OF THE CONTRACT TOO
===========================================================
``MANDATORY_RE`` matches the one spelling a mandatory integration constraint may
take. It carries an ID because "the same constraint" has to be decidable between
two documents by something other than prose similarity:

    - **MANDATORY** `CONSTRAINT-ID` — the text.

An ID that appears in an Application Note and in neither the Datasheet nor the
Integration Guide is a gate FAILURE, not a style note: an Application Note is
optional, is read by a subset of integrators, and is the first document dropped
from a delivery. A constraint that lives only there is a constraint the release
does not actually carry.

NDA: nothing here names a commercial foundry, process node, SKU, chip codename
or qualification programme, and nothing may be added that does. The
third-party-qualification section is deliberately titled by QUESTION rather than
by programme.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Tuple

#: Written into a field's value column when the artefact that would have
#: supplied it is absent or unreadable. Same token `tapeout_docs_gen` already
#: uses, deliberately: a second spelling of "we did not look" is a second
#: policy, and two policies is how one of them stops being enforced.
NOT_MEASURED = "NOT_MEASURED"

#: The header of the third column of every quantitative table.
DERIVED_COLUMN = "Derived from"

#: The prefix a NOT_MEASURED row's third cell must carry. "We did not look" is
#: only honest when it says WHY; without a reason it is indistinguishable from
#: a field somebody forgot to wire.
REASON_PREFIX = "reason:"

#: A project-relative artefact path, as it is spelled in a `Derived from` cell.
#: Backticked so a reader can tell a path from prose, and so the gate can
#: extract it without guessing where the path ends.
SOURCE_PATH_RE = re.compile(r"`([^`]+)`")

#: One mandatory integration constraint. The ID is the join key between
#: documents; the text after it is for the reader.
MANDATORY_RE = re.compile(
    r"^\s*[-*]\s+\*\*MANDATORY\*\*\s+`(?P<id>[A-Z0-9][A-Z0-9_.-]*)`\s*(?:—|--|-)\s*(?P<text>\S.*)$")

#: An H2 heading, which is the level every declared section is written at.
H2_RE = re.compile(r"^##\s+(?P<title>\S.*?)\s*$")

#: Tokens that must never survive into a shipped document. Narrow on purpose:
#: this is a placeholder census, not a prose critic, and a wide pattern here
#: would refuse legitimate text and get the rule weakened rather than the
#: document fixed.
PLACEHOLDER_TOKENS = ("TODO", "TBD", "FIXME", "XXX", "<PLACEHOLDER>")

#: The YAML manifest that binds one document set to the tree it describes.
MANIFEST_NAME = "documentation_manifest.yaml"

#: Where each arm's documents live. The sign-off HTML `tapeout_docs_gen` already
#: writes stays at `reports/phase3/docs/` and is NOT moved: it is load-bearing
#: in step 37.5ic's blocking `required_outputs`, it is sign-off EVIDENCE rather
#: than a product document, and relocating it would be a change to 37.5ic's
#: contract dressed up as a documentation task.
DOC_ROOT = "phase3/stage4/documentation"


@dataclass(frozen=True)
class DocSpec:
    """One document in one arm's set."""
    filename: str
    #: "required" — absent is a FAIL.
    #: "conditional" — absent is a FAIL only when `condition_field` is true for
    #:   this release; the generator records the decision in the manifest.
    #: "optional" — absent is never a FAIL; present must still be well-formed.
    requirement: str
    #: The H2 titles this document must carry, in this order. Order is checked
    #: because a section that has drifted to the end of a document is a section
    #: a reader stops finding.
    sections: Tuple[str, ...]
    #: For "conditional": the manifest key whose truth makes it required.
    condition_field: str = ""
    #: True for a document whose mandatory constraints must RESTATE one already
    #: carried by a required document. An Application Note may repeat a
    #: constraint; it may not be the only place one exists.
    is_application_note: bool = False


#: The document that states the interface, and therefore the one whose pin
#: count the gate re-derives from the delivered netlist view.
IP_DATASHEET = "IP_DATASHEET.md"
IP_INTEGRATION_GUIDE = "IP_INTEGRATION_GUIDE.md"
IP_DELIVERABLES_MANIFEST = "DELIVERABLES_MANIFEST.md"

#: The three interface rows the gate cross-checks, named here rather than in
#: either program for the same reason the sections are.
#:
#: WHICH ONE THE NETLIST CAN SETTLE, AND WHY IT IS NOT THE TOTAL. A Verilog
#: simulation view of a hard macro conventionally carries the LOGICAL interface
#: only: supplies are physical and live in the LEF (`USE POWER` / `USE GROUND`)
#: and the Liberty (`pg_pin`). `digital_hardmacro_check` states that exception
#: and accepts it, so the delivered netlist constrains the SIGNAL half exactly
#: and says nothing about the supply half. The gate therefore settles
#: `SIGNAL_PIN_LABEL` against the netlist, and settles `PIN_COUNT_LABEL` against
#: the document's own two component rows — a total that does not equal its parts
#: is a hand-edited total, and it is caught without pretending the netlist knew
#: about the supplies.
PIN_COUNT_LABEL = "Pin count (total)"
SIGNAL_PIN_LABEL = "Signal pins"
SUPPLY_PIN_LABEL = "Supply pins"

IP_DOCS: Tuple[DocSpec, ...] = (
    DocSpec(
        filename=IP_DATASHEET,
        requirement="required",
        sections=(
            "1. Identification",
            "2. Functional Overview",
            "3. Interface",
            "4. Delivered Views",
            "5. Timing",
            "6. Power",
            "7. What Is Not Measured",
        ),
    ),
    DocSpec(
        filename=IP_INTEGRATION_GUIDE,
        requirement="required",
        sections=(
            "1. Identification",
            "2. Instantiation",
            "3. Mandatory Integration Constraints",
            "4. Clocking And Reset",
            "5. Power Connection",
            "6. Physical Placement",
            "7. Test And Debug Access",
            "8. What Is Not Measured",
        ),
    ),
    DocSpec(
        filename="RELEASE_NOTES.md",
        requirement="required",
        sections=(
            "1. Release Identification",
            "2. Contents Of This Release",
            "3. Verification Status",
            "4. Known Limitations",
            "5. Third-Party Qualification Status",
        ),
    ),
    DocSpec(
        # STANDALONE FROM THE START. Errata updates POST-SHIPMENT, on a cadence
        # the design release does not control; folding it into the Release Notes
        # "until a standalone document is justified" makes the split a future
        # decision nobody will be present to make. An empty template is the
        # correct content for a release with no known issue — its absence and
        # "no known issues" must not look the same.
        filename="ERRATA.md",
        requirement="required",
        sections=(
            "1. Errata Identification",
            "2. Open Errata",
            "3. Closed Errata",
            "4. How To Report An Erratum",
        ),
    ),
    DocSpec(
        filename=IP_DELIVERABLES_MANIFEST,
        requirement="required",
        sections=(
            "1. Release Identification",
            "2. Delivered Files",
            "3. Digest Method",
        ),
    ),
    DocSpec(
        filename="IP_PROGRAMMING_REFERENCE.md",
        requirement="conditional",
        condition_field="register_rich",
        sections=(
            "1. Identification",
            "2. Register Map",
            "3. Access Rules",
            "4. What Is Not Measured",
        ),
    ),
    DocSpec(
        filename="AN001_REFERENCE_INTEGRATION.md",
        requirement="optional",
        is_application_note=True,
        sections=(
            "1. Scope",
            "2. Reference Integration",
            "3. Constraints Restated From The Release Documents",
        ),
    ),
)

#: Step 37.5ic's product-document set. Declared here beside the IP arm because
#: the RULES are shared and a rule declared twice disagrees with itself. The
#: 37.5ic producer that writes these is a separate landing; until it exists the
#: flow wires only the `ip` arm, so this table is read by the gate's `--arm ic`
#: and by nothing in a real run — which is stated rather than hidden, because an
#: arm that is declared and never invoked is exactly the defect v1.13.42
#: measured six times over.
IC_DOCS: Tuple[DocSpec, ...] = (
    DocSpec(
        filename="PRELIMINARY_DATASHEET.md",
        requirement="required",
        sections=(
            "1. Identification",
            "2. Functional Overview",
            "3. Interface",
            "4. Physical",
            "5. Timing",
            "6. Power",
            "7. What Is Not Measured",
        ),
    ),
    DocSpec(
        filename="USER_REFERENCE_MANUAL.md",
        requirement="conditional",
        condition_field="register_rich",
        sections=(
            "1. Identification",
            "2. Register Map",
            "3. Access Rules",
            "4. Operating Sequences",
            "5. What Is Not Measured",
        ),
    ),
    DocSpec(
        filename="RELEASE_NOTES.md",
        requirement="required",
        sections=(
            "1. Release Identification",
            "2. Contents Of This Release",
            "3. Verification Status",
            "4. Known Limitations",
            "5. Third-Party Qualification Status",
        ),
    ),
    DocSpec(
        filename="ERRATA.md",
        requirement="required",
        sections=(
            "1. Errata Identification",
            "2. Open Errata",
            "3. Closed Errata",
            "4. How To Report An Erratum",
        ),
    ),
    DocSpec(
        filename="AN001_TYPICAL_APPLICATION.md",
        requirement="optional",
        is_application_note=True,
        sections=(
            "1. Scope",
            "2. Typical Application",
            "3. Constraints Restated From The Release Documents",
        ),
    ),
)

ARMS: Dict[str, Tuple[DocSpec, ...]] = {"ip": IP_DOCS, "ic": IC_DOCS}

#: The documents whose mandatory constraints a release actually carries. A
#: constraint an Application Note states must also appear in one of these.
CONSTRAINT_BEARING: Dict[str, Tuple[str, ...]] = {
    "ip": (IP_DATASHEET, IP_INTEGRATION_GUIDE),
    "ic": ("PRELIMINARY_DATASHEET.md", "USER_REFERENCE_MANUAL.md"),
}


def arm_docs(arm: str) -> Tuple[DocSpec, ...]:
    """The document set for one arm, or raise on an unknown arm name."""
    try:
        return ARMS[arm]
    except KeyError:  # pragma: no cover - argparse `choices` fences this
        raise KeyError(f"unknown documentation arm {arm!r}; "
                       f"known: {', '.join(sorted(ARMS))}") from None


def doc_dir(arm: str) -> str:
    """The project-relative directory one arm's documents live in."""
    arm_docs(arm)
    return f"{DOC_ROOT}/{arm}"
