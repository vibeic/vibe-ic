#!/usr/bin/env python3
"""ic_expert_db_consistency_check.py — gate: the IC Expert DB stays an ADVISORY
knowledge layer that is CONSISTENT with (never contradicts) the deterministic
gate/program layer, and is blindness-clean.

The IC Expert DB feeds the general Vibe-IC authoring path with design-craft
knowledge. It must NOT:
  1. contain a benchmark/design IDENTIFIER (blindness — no `cvdp_*`, `Prob\\d+`,
     `circuit\\d+` design→solution association leaking into the author digest);
  2. assert an oracle-VALUE bound to a named design (e.g. "design X expects 0xF2");
  3. claim to BE / OVERRIDE a deterministic gate (a lesson is ADVICE, not a hard
     rule the flow enforces — it must never say "the gate must accept", "disable
     the check", "skip lint", "ignore the conformance gate", etc.);
  4. instruct sourcing a name/value from a hidden-scorer artifact (§4.05
     ORACLE-SOURCE ban, issue #139 adjudication 2026-07-14): the scorer-side
     `.env` (its TOPLEVEL / VERILOG_SOURCES variables), "harness metadata", or
     the golden `output.*` are the oracle — a lesson keyed on them is only
     actionable via a forbidden oracle read, so it can never be honest general
     experience. Lessons MAY still describe how a hidden checker BINDS/samples
     the design (craft about the observable contract); they may not name the
     oracle files/variables as an INPUT to the authoring decision.

MIS-FILING (#2164). An entry MAY declare `craft_subjects` — the subject tokens
its craft is about — and a lesson naming none of them is refused BY NAME. A
lesson filed in the wrong entry inherits that entry's whole audience, because
class-first retrieval selects by ENTRY; three such lessons were found and moved.
The guard is EXACT rather than lexical on purpose, and the report carries
`entries_with_declared_craft` and `lessons_craft_checked` so its coverage is a
number a reader sees rather than one the verdict implies.

SCANNED SURFACES (#2143). The four families above are applied to `entries[]`
lessons AND to every text field of `registered_class_profiles.*`. The second
surface is not decoration: a class profile's `integration_contract` prose is
written verbatim into the `contract.md` that `ic_expert_backup_pack` hands the
IC Expert Agent, so it is the same §4.05 channel a lesson is, reached by a
different field — and it was unscanned from the day the field was added (#2094)
until this gate covered it. The report carries `profile_text_fields`, the count
of profile strings actually read; a map that is present but yields zero, or a
PROFILED class whose text the walk never reached, is a FINDING, because a scan
that reads nothing and a subject that is clean look identical from the verdict.

Structural invariants also checked: the DB parses, every entry has ic_class +
non-empty lessons, and lesson_count matches. The OPTIONAL `related[]` cross-link
field (sibling ic_class names sharing a core craft — the lightweight concept
graph) must, when present, be a list of strings that each name an EXISTING
ic_class, with no self-reference and no duplicates (a dangling link would point
the author at knowledge that isn't there).

Run CLEAN on the shipped DB before merge (exit 0). chip-AGNOSTIC.

Usage: ic_expert_db_consistency_check.py [--db <path>] [--json OUT]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

from ic_expert_db_query import lesson_groups

_DEFAULT_DB = (Path(__file__).resolve().parent.parent
               / "agents" / "ic_expert_db" / "ic_expert_db.json")

# blindness: design identifiers that must never appear in an advisory lesson
_ID_RES = [
    re.compile(r"\bcvdp_[A-Za-z0-9_]+\b"),
    re.compile(r"\bProb\d{2,}\w*\b", re.I),
    re.compile(r"\bcircuit\d+\b", re.I),
]
# oracle-value-bound-to-a-named-design leak (a bare general constant is fine)
_ORACLE_RE = re.compile(
    r"\b(?:design|problem|benchmark|testbench|harness)\b[^.\n]{0,40}"
    r"\b(?:expects?|must\s+(?:output|equal|be)|golden)\b[^.\n]{0,20}\b0x[0-9A-Fa-f]+",
    re.I)
# a lesson trying to OVERRIDE the deterministic layer (advisory boundary)
_OVERRIDE_RE = re.compile(
    r"\b(?:disable|skip|bypass|ignore|suppress|waive|turn\s+off|override)\b"
    r"[^.\n]{0,30}\b(?:gate|lint|check|conformance|hygiene|synth|assertion|verific)",
    re.I)
# §4.05 ORACLE-SOURCE ban (issue #139 adjudication, 2026-07-14): a lesson may
# never key an authoring decision on a hidden-scorer artifact. History: a
# captured lesson literally advised "reconcile the top-module name to the
# harness TOPLEVEL/VERILOG_SOURCES from .env" — an instruction to read the
# oracle, waved through because no regex covered it. These tokens are the
# scorer-side file/variable names; none has a legitimate reason to appear in
# spec-alone design advice (the legal input-side counterpart is named
# `input.context` / "the prompt/task", which these patterns do not match).
_ORACLE_SOURCE_RES = [
    re.compile(r"\.env\b"),
    re.compile(r"\bVERILOG_SOURCES\b"),
    re.compile(r"\bharness\s+(?:metadata|TOPLEVEL)\b", re.I),
    re.compile(r"\boutput\.(?:context|response)\b", re.I),
]


def _scan_text(text: str, label: str) -> list:
    """The four scan families, in ONE implementation, applied to one string.

    #2143. Before this, the families lived inline inside the `entries[]` loop
    and nothing else in the DB was ever scanned. A second call site that
    re-typed the regex list would drift from this one silently — the two would
    disagree the first time a family is tightened and nobody would see it — so
    the second surface (`registered_class_profiles`, below) calls THIS, and the
    entry loop's own finding strings are produced here unchanged."""
    out = []
    for rx in _ID_RES:
        m = rx.search(text)
        if m:
            out.append(f"[{label}] BLINDNESS: design-id '{m.group(0)}' in lesson")
    if _ORACLE_RE.search(text):
        out.append(f"[{label}] ORACLE-LEAK: named-design→value in lesson")
    if _OVERRIDE_RE.search(text):
        out.append(f"[{label}] OVERRIDE: lesson tries to disable/override a gate "
                   f"(advisory boundary)")
    for rx in _ORACLE_SOURCE_RES:
        m = rx.search(text)
        if m:
            out.append(f"[{label}] ORACLE-SOURCE: lesson keys on the hidden-scorer "
                       f"artifact '{m.group(0)}' (§4.05 ban — advice must be "
                       f"actionable from the spec/input alone)")
            break
    return out


def _profile_text_fields(node, path: str):
    """Every STRING LEAF under `registered_class_profiles`, with the path that
    names it. Yields (path, text).

    Walks the whole subtree rather than an enumerated list of keys: the field
    set has already grown once (a profile carries `db_classes` and
    `integration_contract` today, and #2094 wrote the map's `_doc` beside them),
    and a hand-written key list is exactly how the next field added arrives
    unscanned. A dict KEY is a class or field name, never prose, so only values
    are scanned."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _profile_text_fields(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _profile_text_fields(v, f"{path}[{i}]")


def check(db_path: Path):
    findings = []
    try:
        db = json.loads(Path(db_path).read_text())
    except Exception as e:  # noqa: BLE001
        return {"pass": False, "findings": [f"DB does not parse: {e}"]}
    entries = db.get("entries")
    if not isinstance(entries, list) or not entries:
        return {"pass": False, "findings": ["DB has no entries[]"]}
    all_classes = {e.get("ic_class") for e in entries if e.get("ic_class")}
    total = 0
    n_declared = n_craft_checked = 0
    for e in entries:
        cls = e.get("ic_class")
        lessons = e.get("lessons")
        if not cls or not isinstance(lessons, list) or not lessons:
            findings.append(f"entry missing ic_class/lessons: {str(e)[:60]}")
            continue
        if e.get("lesson_count") != len(lessons):
            findings.append(f"[{cls}] lesson_count {e.get('lesson_count')} != {len(lessons)}")
        try:
            lesson_groups(e)
        except ValueError as exc:
            findings.append(f"[{cls}] {exc}")
        rel = e.get("related")
        if rel is not None:
            if not isinstance(rel, list) or not all(isinstance(r, str) for r in rel):
                findings.append(f"[{cls}] related must be a list[str]")
            else:
                if cls in rel:
                    findings.append(f"[{cls}] related self-references its own ic_class")
                if len(set(rel)) != len(rel):
                    findings.append(f"[{cls}] related has duplicate links")
                for r in rel:
                    if r not in all_classes:
                        findings.append(f"[{cls}] related link '{r}' names no existing ic_class (dangling)")
        # ── the lesson sits in the entry that owns it (#2164) ──────────
        # MEASURED, three times: an AXI-Lite register-read lesson inside the
        # clock-divider entry, and a learning-rate formula plus a lint-review
        # self-gate inside the decimator entry. Each was then DELIVERED to
        # every design of a profiled class, because class-first selects by
        # ENTRY and a lesson filed in the wrong entry inherits that entry's
        # whole audience.
        #
        # THE GUARD IS EXACT, NOT A HEURISTIC, AND THAT IS PAID FOR IN
        # COVERAGE. Three lexical detectors were built and measured against the
        # three known instances first: class-name stem intersection flagged 44
        # of 206 lessons; a best-other-class margin had ZERO power over two of
        # the three at any threshold that was not itself noise; a
        # self-consistency retrieval caught all three and flagged 138 of 206.
        # None of them is a gate. So an entry DECLARES its craft subjects and a
        # lesson naming none of them is refused — which judges only the entries
        # that declare, and reports how many those are rather than implying it
        # judged the rest.
        subjects = e.get("craft_subjects")
        if subjects is not None:
            if (not isinstance(subjects, list) or not subjects
                    or not all(isinstance(t, str) and t.strip()
                               for t in subjects)):
                findings.append(f"[{cls}] craft_subjects must be a non-empty "
                                f"list of non-empty strings")
                subjects = None
            else:
                n_declared += 1
        for i, les in enumerate(lessons):
            total += 1
            if subjects:
                n_craft_checked += 1
                low = les.lower()
                if not any(t.lower() in low for t in subjects):
                    findings.append(
                        f"[{cls}] MIS-FILED: lesson {i} names none of this "
                        f"entry's declared craft subjects {sorted(subjects)} "
                        f"— a lesson in the wrong entry inherits that entry's "
                        f"whole audience, because class-first selects by ENTRY")
            findings.extend(_scan_text(les, cls))

    # ── registered_class_profiles (#2143) ──────────────────────────────────
    # THE SECOND §4.05 CHANNEL. A class profile's `integration_contract` prose
    # is written into `contract.md` by `ic_expert_backup_pack.assemble` and
    # handed to the IC Expert Agent VERBATIM — the same destination as a
    # lesson, reached by a different field. Until now nothing scanned it: the
    # families above were bound to `entries[]`, so a profile requirement
    # carrying a design identifier or an oracle-sourced instruction would have
    # shipped through a gate that reported PASS.
    prof = db.get("registered_class_profiles")
    n_profile_fields = 0
    if isinstance(prof, dict):
        per_class = {}
        for path, text in _profile_text_fields(prof, "registered_class_profiles"):
            n_profile_fields += 1
            top = path.split(".")[1] if path.count(".") >= 1 else None
            if top:
                per_class[top] = per_class.get(top, 0) + 1
            findings.extend(_scan_text(text, path))
        # A ZERO IS A FINDING, NOT A PASS — but only where zero is impossible
        # to reach honestly. A DB that predates class-first has no map at all
        # and is not accused of anything; a map that IS there and yields no
        # text, or a PROFILED class none of whose text the walk reached, is the
        # silent zero this check exists to stop.
        if n_profile_fields == 0:
            findings.append(
                "[registered_class_profiles] PRESENT but 0 text fields were "
                "scanned — a profile's contract prose reaches the agent through "
                "contract.md, so scanning none of it is a broken scan, not a "
                "clean one")
        for cname, pv in prof.items():
            if isinstance(pv, dict) and per_class.get(cname, 0) == 0:
                findings.append(
                    f"[registered_class_profiles.{cname}] PROFILED but 0 text "
                    f"fields were scanned — its contract text reaches the agent "
                    f"unscanned")
    return {"pass": not findings, "classes": len(entries),
            "total_lessons": total,
            "profile_text_fields": n_profile_fields,
            # THE COVERAGE, printed rather than implied. This guard judges only
            # the entries that declare their craft; a verdict that did not say
            # how many those are would read as though it had checked them all.
            "entries_with_declared_craft": n_declared,
            "lessons_craft_checked": n_craft_checked,
            "findings": findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = check(a.db)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2))
    verdict = "PASS" if rep["pass"] else "FAIL"
    print(f"ic_expert_db_consistency: {verdict} "
          f"(classes={rep.get('classes','?')} lessons={rep.get('total_lessons','?')} "
          f"profile_text_fields={rep.get('profile_text_fields','?')} "
          f"craft_declared={rep.get('entries_with_declared_craft','?')}"
          f"/{rep.get('classes','?')} "
          f"lessons_craft_checked={rep.get('lessons_craft_checked','?')})")
    for f in rep.get("findings", []):
        print(f"  ! {f}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
