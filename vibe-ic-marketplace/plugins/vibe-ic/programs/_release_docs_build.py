#!/usr/bin/env python3
"""_release_docs_build.py — the machinery both release-document producers use.

WHY THIS MODULE EXISTS
======================
``_release_docs_contract`` declares WHAT a document set is: which documents,
which sections, which column headers, which markers. This module is the other
half of the same contract — HOW a quantitative fact becomes a row, how a
document becomes Markdown, and how a fact is read out of the design INPUT.

They were separated because they change for different reasons. A section is
added by a documentation decision; a reader gains a key spelling because the
corpus ships one. Keeping them in one file would make every corpus fix look
like a contract edit in a diff.

WHY IT IS SHARED AND NOT COPIED
===============================
Step 37.5ip's producer landed first and this code was inside it. When step
37.5ic's producer was written the choice was to copy it or to lift it, and the
copy was refused for the reason this whole feature exists:

    A hand-maintained copy of an automatically-changing fact is stale by
    construction.

Two ``Field.row()`` implementations are two definitions of the ``Derived from``
column, and ``release_docs_check`` enforces exactly one of them. The arm whose
copy drifted would fail its own gate for a reason nobody could see in either
file. Landed on this tree the week this was written, all the same defect:
v1.13.19, v1.13.36, v1.13.39 — and in v1.13.39 the hand-written copy was the
WRONG one.

THE RULE THIS MODULE MAKES STRUCTURAL
=====================================
    Every quantitative field is DERIVED from a named artefact and carries that
    artefact's path, or it is explicitly NOT_MEASURED with a reason.

``Field`` has exactly two constructors — ``measured`` and ``unmeasured`` — and
``Field.measured`` is a PROPERTY derived from the value rather than a flag
carried beside it, so no caller can mark a NOT_MEASURED row as measured. There
is no third state and no way to build one.

§4.05: every reader here takes the design INPUT (``input/project.json``,
``phase1/generated_docs/L*.json``) or a path the caller resolved from the run's
own evidence. Nothing here reaches the oracle, the harness, or the golden.

NDA: nothing here names a commercial foundry, process node, SKU, chip codename
or qualification programme, and nothing may be added that does.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from _release_docs_contract import (
    DERIVED_COLUMN,
    NOT_MEASURED,
    REASON_PREFIX,
)

#: Where this flow already records which design and which PDK a run is for.
#: The same keys `pdk_consistency_check` and `tapeout_docs_gen` read, so a
#: document cannot name a different design from the rest of the run.
PROJECT_JSON = "input/project.json"
DESIGN_KEYS = ("design", "design_name", "top", "top_module")
PDK_KEYS = ("pdk", "target_pdk", "pdk_target")


# ── the field model ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Field:
    """One quantitative row: a value with its artefact, or a hole with a reason.

    There is no third state, and that is the entire point. ``measured`` is
    DERIVED from ``value`` rather than carried alongside it, so no caller can
    mark a NOT_MEASURED row as measured — the two can never disagree.
    """
    label: str
    value: str
    #: A project-relative artefact path when measured; the reason text when not.
    source: str

    @property
    def measured(self) -> bool:
        return self.value != NOT_MEASURED

    def row(self) -> str:
        third = (f"`{self.source}`" if self.measured
                 else f"{REASON_PREFIX} {self.source}")
        return f"| {self.label} | {self.value} | {third} |"


def measured(label: str, value: Any, source_path: str) -> Field:
    """A field READ from an artefact, carrying that artefact's path."""
    return Field(label, render(value), source_path)


def unmeasured(label: str, reason: str) -> Field:
    """A field no artefact in this run supplied, and WHY it did not."""
    return Field(label, NOT_MEASURED, reason)


def render(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def table(fields: Sequence[Field]) -> str:
    """A quantitative table. The third column is the contract, not decoration."""
    head = f"| Field | Value | {DERIVED_COLUMN} |\n| --- | --- | --- |"
    return "\n".join([head] + [f.row() for f in fields])


# ── reading the design input ───────────────────────────────────────────────
def read_json(path: Path) -> Optional[dict]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def identity(project: Path) -> Tuple[Field, Field]:
    """(design, pdk) read off the project, or NOT_MEASURED. Never a default.

    A guessed design name is the same failure as a guessed number: it makes a
    document that names the wrong part, and nothing in the file says it was a
    guess.
    """
    doc = read_json(project / PROJECT_JSON) or {}

    def pick(label: str, keys: Sequence[str]) -> Field:
        for key in keys:
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                return measured(label, value.strip(), PROJECT_JSON)
        return unmeasured(
            label, f"{PROJECT_JSON} declares none of: {', '.join(keys)}")

    return pick("Design", DESIGN_KEYS), pick("Target PDK", PDK_KEYS)


def layer(project: Path, stem: str) -> Tuple[Optional[dict], str]:
    """One Phase-1 L document and its project-relative path.

    The path travels with the content because a fact quoted without the artefact
    it came from is a fact nobody can re-check.
    """
    rel = f"phase1/generated_docs/{stem}.json"
    return read_json(project / rel), rel


def scopes(doc: Optional[dict]) -> List[dict]:
    """The places an L document puts its content, both shapes.

    The extracted layers carry their fields at the top level and the
    skeleton-emitted ones nest them under ``fields``. Reading both is not
    tolerance of an inconsistency — it is reading the corpus that exists rather
    than the one a single writer assumed.
    """
    if not isinstance(doc, dict):
        return []
    nested = doc.get("fields")
    return [doc, nested] if isinstance(nested, dict) else [doc]


def layer_text(project: Path, stem: str, label: str,
               keys: Sequence[str]) -> Field:
    """One scalar out of an L document, with that document's path."""
    doc, rel = layer(project, stem)
    if doc is None:
        return unmeasured(label, f"{rel} is absent or unreadable in this run")
    for key in keys:
        for scope in scopes(doc):
            value = scope.get(key)
            rendered = flatten(value)
            if rendered:
                return measured(label, one_line(rendered), rel)
    return unmeasured(label, f"{rel} declares none of: {', '.join(keys)}")


def layer_count(project: Path, stem: str, label: str,
                keys: Sequence[str]) -> Field:
    """The LENGTH of a list an L document carries, with that document's path."""
    doc, rel = layer(project, stem)
    if doc is None:
        return unmeasured(label, f"{rel} is absent or unreadable in this run")
    for key in keys:
        for scope in scopes(doc):
            value = scope.get(key)
            if isinstance(value, list):
                return measured(label, len(value), rel)
    return unmeasured(label, f"{rel} declares none of: {', '.join(keys)}")


def list_under(doc: Optional[dict], keys: Sequence[str]) -> list:
    for key in keys:
        for scope in scopes(doc):
            value = scope.get(key)
            if isinstance(value, list) and value:
                return value
    return []


def flatten(value: Any) -> str:
    """One line of prose out of whatever shape an L document put it in.

    The corpus carries all three shapes for the same kind of fact — a string, a
    mapping of named sub-facts, a list of them — and a reader that understands
    only the string form reports NOT_MEASURED over a document that plainly
    states the answer. That is the WORSE direction of the two: a false hole is
    read as "the flow does not produce this", and the field gets deleted.
    """
    if isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value if value.strip() else ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {flatten(v)}" for k, v in value.items()
                         if flatten(v))
    if isinstance(value, list):
        return "; ".join(part for part in (flatten(v) for v in value) if part)
    return ""


_WS_RE = re.compile(r"\s+")


def one_line(text: str, limit: int = 400) -> str:
    """Collapse a layer's prose onto one Markdown table row.

    A newline inside a table cell ends the table, and a table that ends early
    takes every row after it out of the document a reader (and this gate) sees.
    The `|` is escaped for the same reason.
    """
    flat = _WS_RE.sub(" ", text).strip().replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def register_rich(project: Path) -> Tuple[bool, str]:
    """Whether this release needs a register document, and WHAT decided it.

    DERIVED, like every other fact here. "Conditional" is where a document set
    quietly loses a required document: somebody decides the condition by eye and
    the decision is recorded nowhere. This returns the artefact that decided it
    so the manifest can carry the path.
    """
    doc, rel = layer(project, "L4_REGMAP")
    if doc is None:
        return False, f"{rel} is absent or unreadable in this run"
    for key in ("registers", "internal_registers", "register_groups"):
        value = doc.get(key)
        if isinstance(value, list) and value:
            return True, rel
    return False, rel


def register_rows(doc: Optional[dict], rel_path: str) -> str:
    """The register-group table, or a sentence saying the layer declares none."""
    groups = list_under(doc, ("register_groups",))
    if not groups:
        return f"`{rel_path}` declares no register group to tabulate here."
    rows = ["| Group | Fields |", "| --- | --- |"]
    for entry in groups:
        if not isinstance(entry, dict):
            continue
        name = one_line(str(entry.get("group", "")))
        fields = entry.get("fields")
        rendered = (", ".join(one_line(str(f)) for f in fields)
                    if isinstance(fields, list) else "")
        rows.append(f"| {name or NOT_MEASURED} | {rendered or NOT_MEASURED} |")
    return "\n".join(rows)


# ── digests and provenance ─────────────────────────────────────────────────
def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha(project: Path) -> Field:
    """The commit these documents describe, or NOT_MEASURED with the reason.

    A report that does not name the tree it measured can describe the wrong one
    in four ways and none of them raises an error. A run directory is very often
    not a work tree at all, and that is a HOLE rather than a licence to invent an
    identifier: it is stated, never defaulted.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return unmeasured("Tree SHA", f"git could not be run here: {exc}")
    sha = (proc.stdout or "").strip()
    if proc.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        return unmeasured(
            "Tree SHA",
            "the project directory is not a git work tree, so no commit "
            "identifies the source these documents were generated from")
    return measured("Tree SHA", sha, PROJECT_JSON)


def rel_str(project: Path, path: Path) -> str:
    try:
        return path.relative_to(project).as_posix()
    except ValueError:  # pragma: no cover - discovery is project-rooted
        return str(path)


# ── document assembly ──────────────────────────────────────────────────────
PREAMBLE = (
    "<!-- Generated by {gen} {ver}. Every quantitative field below is DERIVED "
    "from the artefact named beside it, or is explicitly {nm} with a reason. "
    "Never a default, never hand-typed. Do not edit by hand: an edited number "
    "is a number no artefact supports, and release_docs_check refuses it. -->")


def document(title: str, sections: Sequence[Tuple[str, str]],
             generator: str, version: str) -> str:
    """One Markdown document: a title, the preamble, then the declared sections.

    The section TITLES come from the shared contract and are passed in by the
    caller; this function never invents one, so a document can only gain or lose
    a section through an edit to ``_release_docs_contract``.
    """
    parts = [f"# {title}", "",
             PREAMBLE.format(gen=generator, ver=version, nm=NOT_MEASURED), ""]
    for heading, body in sections:
        parts.append(f"## {heading}")
        parts.append("")
        parts.append(body.rstrip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def not_measured_body(fields: Sequence[Field]) -> str:
    """The mandatory hole census for one document.

    Rendered even when empty, and saying so explicitly, because an absent
    section is indistinguishable from a document with nothing to disclose.
    """
    holes = [f for f in fields if not f.measured]
    if not holes:
        return ("Every quantitative field in this document was read from an "
                f"artefact of this run. No field is {NOT_MEASURED}.")
    lines = [f"- **{f.label}** — {REASON_PREFIX} {f.source}" for f in holes]
    return (f"{len(holes)} field(s) could not be read from any artefact of this "
            f"run. They are stated as {NOT_MEASURED} rather than filled with a "
            "plausible value:\n\n" + "\n".join(lines))


# ── mandatory constraints ──────────────────────────────────────────────────
@dataclass(frozen=True)
class Constraint:
    """A normative rule, its ID, and the artefact it came from.

    NOT a ``Field``: a constraint is normative, not a measurement, so there is no
    NOT_MEASURED form of one. A constraint no artefact in this run supports is
    simply NOT EMITTED — inventing one would be the hand-typed fact this whole
    feature exists to refuse, wearing a stronger word.

    The line it renders is the one spelling ``_release_docs_contract.
    MANDATORY_RE`` matches, and it carries the ID because "the same constraint"
    has to be decidable between two documents by something other than prose
    similarity.
    """
    cid: str
    text: str
    source: str

    def line(self) -> str:
        return (f"- **MANDATORY** `{self.cid}` — {self.text} "
                f"(derived from `{self.source}`)")


def constraint_body(constraints: Sequence[Constraint], nothing: str) -> str:
    if not constraints:
        return nothing
    return "\n".join(c.line() for c in constraints)


def yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
