#!/usr/bin/env python3
"""The ONE definition of "is this waiver's `evidence` independent, or is the
run vouching for itself".

WHY THIS MODULE EXISTS
======================
#519 established that the `waivers` dialect has no `approved_at` and no human
`approver`: an evidence-gated attestation stands in for the signature. The
quartet that stands in is ``ticket`` + ``review_required: true`` +
``evidence[] non-empty`` + a substantive ``rationale``. Three of those four are
checkable as written. The fourth is not: ``evidence[] non-empty`` is a LENGTH
test, and a length test cannot tell corroboration from a self-report.

Measured over the 8 tracked attestation entries (#524):

  * 5 cite ONLY the producing run's own orchestrator report — the writer
    pointing at itself;
  * 1 uses the field for free-text fragments that are not references to
    anything (layer prefixes, a ticket id, a tool name, whole prose
    sentences);
  * 2 cite artefacts that exist independently of the run's own record.

Every one of the 8 satisfies ``evidence[] non-empty`` identically, and the
verdict a reader sees is identical in all three cases. That is the same shape
the repo keeps removing one level in: a gate whose output does not distinguish
the state it was built to distinguish.

WHERE THE SELF-REFERENCE COMES FROM — IT IS UNCONDITIONAL
=========================================================
``phase3_one_shot_runner._autogen_waivers_json`` builds the list by harvesting
every string in the step's ``extras`` and then appending, with no condition:

    evidence.append(f"reports/orchestrator/phase3_one_shot.json#steps[name=...]")

So the self-reference is on EVERY auto-generated entry, and when ``extras`` is
empty it is the WHOLE list. The same harvester explains the free-text sub-case:
``extras`` values are not all paths — an ENV_UNAVAILABLE step carries
``{"missing_tool": "<tool>"}``, a DRC step carries layer-rule fragments — and
each is appended verbatim as though it were an artefact reference. The two
sub-cases in #524 are one producer behaviour seen twice.

WHAT THIS MODULE DECIDES — AND WHAT IT DELIBERATELY DOES NOT
============================================================
It CLASSIFIES. It does not reject, does not raise, and does not decide whether
a waiver is honoured. That separation is deliberate and is the whole design:

  A self-reference is NOT worthless, and a rule that refused it outright would
  be wrong for the population the ENV_UNAVAILABLE tier exists to serve. That
  tier's claim is "the tool is not on this host". No independent artefact can
  corroborate a NON-execution — the artefact whose absence IS the waiver is the
  one being asked for. The runner's own probe record is the only witness that
  can exist. Refusing it would mean an honest, correctly disclosed,
  tool-less-host deferral could never be honoured, which breaks
  "disclosure buys deferral" for exactly the case it was built for.

  So: self-reference alone is never CORROBORATION, but it is not a defect
  either. The defect is that it was INDISTINGUISHABLE. This module makes it
  distinguishable; callers disclose what they got.

Answering #524's question directly — self-reference is acceptable ALONGSIDE
something else and is never sufficient ALONE. Not "never acceptable": the
well-formed entries in the corpus cite two real artefacts AND the run-record
index, and a rule demanding that EVERY item be independent would reject those
too, punishing the only entries that got it right.

THE CLASSIFICATION
==================
An evidence item is a REFERENCE when the text before any ``#selector`` is
path-shaped: non-empty, whitespace-free, and either containing a ``/``
separator or naming a file that exists at the project root. Whitespace is the
discriminator that keeps a prose sentence containing a slash from reading as a
path.

A reference resolves against the project and is:

  ``self_report``   inside the project's canonical orchestrator report
                    directory (``_path_layout.reports_orchestrator_dir``) — the
                    record of the run that wrote the waiver. Points at itself.
  ``independent``   names an artefact that EXISTS inside the project and is not
                    that record. This is the only kind that corroborates.
  ``dangling``      path-shaped, but nothing is there — or it escapes the
                    project (absolute path, ``..``). A citation of an artefact
                    that is not present corroborates nothing, and reads more
                    like corroboration than a self-reference does, so it is
                    named separately rather than folded in.

A non-reference is ``unresolvable``: free text, a bare token, a ticket id, a
tool name, a layer-rule fragment. It is not a pointer to anything auditable.

An attestation is CORROBORATED iff at least one item is ``independent``.

CHIP-AGNOSTIC BY CONSTRUCTION. Every test here is structural — whitespace,
a path separator, containment under a directory the shared path layout names,
and filesystem existence. No vendor, no SKU, no design name, no layer literal;
the free-text fragments that motivated this module are rejected because they
are not path-shaped, never because of what they spell.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _path_layout as _pl  # noqa: E402  (after sys.path bootstrap)
import _waiver_entries as _we  # noqa: E402  (#519's shared vocabulary)

#: An item that points at an artefact existing independently of the run's own
#: record. The only kind that corroborates.
KIND_INDEPENDENT = "independent"
#: An item that points back at the producing run's own orchestrator report.
KIND_SELF_REPORT = "self_report"
#: Path-shaped, but nothing is there (or it leaves the project).
KIND_DANGLING = "dangling"
#: Not a reference at all — free text, bare token, ticket id, tool name.
KIND_UNRESOLVABLE = "unresolvable"

#: Every kind, in report order (most to least useful as corroboration).
KINDS = (KIND_INDEPENDENT, KIND_SELF_REPORT, KIND_DANGLING, KIND_UNRESOLVABLE)


def reference_of(item: Any) -> str:
    """The reference part of an evidence item — the text before any
    ``#selector``. Empty string when the item is not a string, is blank, or is
    a bare selector with no path in front of it."""
    if not isinstance(item, str):
        return ""
    return item.split("#", 1)[0].strip()


def _is_path_shaped(ref: str, project: Path) -> bool:
    """True when ``ref`` reads as a project-relative artefact reference.

    Structural test, in this order:
      * non-empty and containing no whitespace — a prose sentence is not a
        path, even when it happens to contain a ``/``; and
      * either it carries a ``/`` separator, or it names a file that exists at
        the project root (so a bare ``drc.rpt`` beside the waiver still counts,
        while a bare ``klayout`` does not).
    """
    if not ref or any(c.isspace() for c in ref):
        return False
    if "/" in ref:
        return True
    try:
        return (project / ref).is_file()
    except OSError:
        return False


def classify_item(item: Any, project: Path) -> str:
    """The kind of ONE evidence item. One of :data:`KINDS`; never raises."""
    project = Path(project)
    ref = reference_of(item)
    if not _is_path_shaped(ref, project):
        return KIND_UNRESOLVABLE

    # Resolve WITHOUT touching the filesystem for the containment test, so an
    # absolute path or a `..` escape is judged on its text rather than on
    # whatever happens to exist outside the project.
    try:
        base = Path(project).resolve()
        target = (base / ref).resolve()
    except (OSError, ValueError, RuntimeError):
        return KIND_DANGLING

    try:
        target.relative_to(base)
    except ValueError:
        # Leaves the project: absolute path, or `..` above the root. Whatever
        # it points at cannot be audited from the project alone.
        return KIND_DANGLING

    try:
        orchestrator = _pl.reports_orchestrator_dir(base).resolve()
    except (OSError, ValueError, RuntimeError):
        orchestrator = None
    if orchestrator is not None:
        try:
            target.relative_to(orchestrator)
            return KIND_SELF_REPORT
        except ValueError:
            pass

    # The waiver document itself is not corroboration of its own claim, and it
    # is the one file guaranteed to exist next to every attestation — so
    # without this, the cheapest way to silence a disclosure would be to cite
    # the file the waiver is written in. Same self-reference, one level out.
    # The filename comes from the shared waiver vocabulary (#519) rather than
    # a literal here, so "the waiver file is called this" stays stated once.
    try:
        if target == (base / _we.WAIVERS_FILENAME).resolve():
            return KIND_SELF_REPORT
    except (OSError, ValueError, RuntimeError):
        pass

    try:
        if target.exists():
            return KIND_INDEPENDENT
    except OSError:
        pass
    return KIND_DANGLING


@dataclass
class EvidenceAssessment:
    """What one attestation's ``evidence`` list actually contains."""

    kinds: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.kinds)

    @property
    def independent(self) -> int:
        return self.counts.get(KIND_INDEPENDENT, 0)

    @property
    def self_report(self) -> int:
        return self.counts.get(KIND_SELF_REPORT, 0)

    @property
    def dangling(self) -> int:
        return self.counts.get(KIND_DANGLING, 0)

    @property
    def unresolvable(self) -> int:
        return self.counts.get(KIND_UNRESOLVABLE, 0)

    @property
    def corroborated(self) -> bool:
        """True iff at least one item is independent of the run's own record.

        "At least one", not "all": the run-record index is legitimately present
        on every auto-generated entry, and requiring every item to be
        independent would reject the entries that cite real artefacts AND the
        index — the ones that got it right."""
        return self.independent > 0

    @property
    def self_referential_only(self) -> bool:
        """The sharpest case in #524: every item is the run pointing at its own
        report. Nothing else was offered at all."""
        return self.total > 0 and self.self_report == self.total

    def as_dict(self) -> Dict[str, Any]:
        return {"total": self.total, "counts": dict(self.counts),
                "corroborated": self.corroborated,
                "self_referential_only": self.self_referential_only}

    def describe(self) -> str:
        """One line naming what the evidence list is made of, for a report a
        human reads. Says what was found, never what to conclude."""
        if self.total == 0:
            return "no evidence items"
        parts = [f"{self.counts[k]} {k}" for k in KINDS if self.counts.get(k)]
        return f"{self.total} evidence item(s): " + ", ".join(parts)


def assess(evidence: Any, project: Path) -> EvidenceAssessment:
    """Classify a whole ``evidence`` list. A non-list (or absent) evidence
    field assesses as empty rather than raising — the "is it a non-empty list"
    question belongs to the caller's schema check, and a classifier that
    crashed on a malformed field would take down the gate that merely wanted to
    describe it."""
    items = evidence if isinstance(evidence, list) else []
    kinds = [classify_item(it, project) for it in items]
    counts = {k: kinds.count(k) for k in KINDS}
    return EvidenceAssessment(kinds=kinds, counts=counts)


# The disclosure sentence a report shows for an attestation that no independent
# artefact corroborates. Written once so the compliance report and the schema
# check say the SAME thing about the same entry, rather than drifting into two
# descriptions of one finding — the drift #519 removed from the reader.
def disclosure(step_label: Any, assessment: EvidenceAssessment) -> str:
    """A human-readable disclosure for an UNCORROBORATED attestation.

    Deliberately not phrased as a refusal: the waiver may still be honoured,
    and for an ENV_UNAVAILABLE deferral the self-report is often the only
    witness that can exist. The sentence's job is to stop the report from
    reading identically whether the evidence was independent or not."""
    if assessment.self_referential_only:
        what = ("its ONLY evidence is the producing run's own orchestrator "
                "report — the run vouching for itself, which is disclosure "
                "but not corroboration")
    elif assessment.total == 0:
        what = "it carries no evidence items at all"
    else:
        what = ("no evidence item names an artefact that exists in the "
                "project independently of the run's own record — "
                + assessment.describe())
    return (f"waiver attestation for step {step_label!r}: {what}. "
            "An independent item is a project-relative reference to an "
            "artefact that is present and is not the run's own orchestrator "
            "report; free text, a ticket id, a tool name or a layer-rule "
            "fragment is not a reference. This is DISCLOSED, not refused — "
            "for a deferral whose claim is that a tool was absent, the run's "
            "own probe record may be the only witness that can exist.")
