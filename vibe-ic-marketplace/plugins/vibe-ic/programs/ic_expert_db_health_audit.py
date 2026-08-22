#!/usr/bin/env python3
"""ic_expert_db_health_audit.py — periodic HEALTH audit of the IC Expert DB
(beyond the ship-blocking consistency gate).

`ic_expert_db_consistency_check.py` is the HARD gate (blindness / oracle / no
gate-override / structural) — it decides whether the DB may ship. This tool is
the softer, MAINTENANCE lint the Karpathy "LLM-Wiki lint" idea calls for: it
finds knowledge-base rot that is not a correctness violation but degrades the
DB's value over time. It is ADVISORY by default (exit 0, prints findings); pass
`--strict` to exit non-zero when any finding exists (e.g. a scheduled hygiene
job that should page a maintainer).

Dimensions (all chip-AGNOSTIC, all advisory):
  1. low_retrievability  — an ic_class whose NAME yields no design-family stem
     (per the retriever's own _fn), so ic_expert_db_query can only reach it by
     weak keyword overlap. Such a lesson is effectively unreachable = orphan.
  2. near_duplicate      — two lessons (across classes) whose keyword sets are
     >= --dup-threshold Jaccard-similar: merge / de-dup candidates.
  3. stale_program_ref   — a lesson mentions a `<name>.py` that no longer exists
     under programs/ (a rename/removal left the advice pointing at nothing).
  4. related_graph       — the optional related[] concept graph is unhealthy:
     a dangling target, a self-link, or an asymmetric edge (A->B but not B->A).
     No-op when no entry carries related[] (backward-compatible).

Reuses the LIVE retriever primitives (_fn/_kw imported from ic_expert_db_query)
so "reachable" here means exactly what the production retriever means — never a
hand-copied duplicate of that logic.

Usage: ic_expert_db_health_audit.py [--db PATH] [--programs-dir DIR]
                                    [--dup-threshold 0.6] [--strict] [--json OUT]
"""
from __future__ import annotations
import argparse, json, re, sys
from itertools import combinations
from pathlib import Path

import ic_expert_db_query as Q  # LIVE retriever primitives (_fn/_kw) — single source

_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = _HERE.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"
_PY_REF = re.compile(r"\b([a-z_][a-z0-9_]*\.py)\b")
# only a `<name>.py` that follows a plugin-PROGRAM naming convention is treated as
# a candidate vibe-ic program — so a lesson naming an EXTERNAL tool / build script
# (setup.py, make.py, a wrapper) is not mis-flagged as a "stale program ref".
_PROG_LIKE = re.compile(r"_(?:check|audit|run|runner|gen|lint|loop|fix|report|emit|"
                        r"synth|query|scorer|dispatch|guard|sweep)\.py$")


def audit(db_path: Path, programs_dir: Path = _HERE, dup_threshold: float = 0.6) -> dict:
    findings: list[str] = []
    dims: dict[str, list] = {"low_retrievability": [], "near_duplicate": [],
                             "stale_program_ref": [], "related_graph": []}
    try:
        db = json.loads(Path(db_path).read_text())
    except Exception as e:  # noqa: BLE001
        return {"pass": False, "fatal": True,
                "findings": [f"DB does not parse: {e}"], "dimensions": dims}
    entries = db.get("entries")
    if not isinstance(entries, list) or not entries:
        return {"pass": False, "fatal": True,
                "findings": ["DB has no entries[] (missing key or not a non-empty list)"],
                "dimensions": dims}

    # Index ROBUSTLY: a maintenance lint must REPORT structural rot, not die on it.
    # Malformed entries are surfaced as findings; a valid entries[] is never fatal.
    by_class: dict = {}
    lessons_by_class: dict = {}
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            findings.append(f"entry #{idx} is not an object — malformed")
            continue
        cls = e.get("ic_class")
        if not isinstance(cls, str) or not cls:
            findings.append(f"entry #{idx} has a missing/invalid ic_class — malformed")
            continue
        lessons = e.get("lessons")
        if not isinstance(lessons, list):
            findings.append(f"[{cls}] lessons is not a list — malformed")
            continue
        by_class[cls] = e
        lessons_by_class[cls] = [l for l in lessons if isinstance(l, str)]

    # 1) low retrievability — mirror what ic_expert_db_query ACTUALLY indexes: it
    #    scores a lesson via _fn(cls + " " + lesson), so a class is only truly hard
    #    to retrieve when NEITHER its name NOR its lessons carry a design-family stem.
    for cls, ls in lessons_by_class.items():
        if not Q._fn(cls + " " + " ".join(ls)):
            dims["low_retrievability"].append(cls)
            findings.append(f"[{cls}] low-retrievability: neither the ic_class name nor its "
                            f"lessons carry a design-family stem — reachable only by weak "
                            f"keyword overlap")

    lesson_rows = [(cls, les, Q._kw(les))
                   for cls, ls in lessons_by_class.items() for les in ls]

    # 2) near-duplicate lessons — ANY two lessons in the DB (Jaccard over keyword
    #    sets), including two in the same class; both are legitimate merge signals.
    for (ca, la, ka), (cb, lb, kb) in combinations(lesson_rows, 2):
        if not ka or not kb:
            continue
        jac = len(ka & kb) / len(ka | kb)
        if jac >= dup_threshold:
            dims["near_duplicate"].append({"a": ca, "b": cb, "jaccard": round(jac, 2)})
            findings.append(f"near-duplicate lessons [{ca}] ~ [{cb}] (jaccard {jac:.2f}) — "
                            f"merge candidate")

    # 3) stale program references — only names that follow a plugin-PROGRAM naming
    #    convention (see _PROG_LIKE); an external tool / build-script name is skipped.
    for cls, les, _ in lesson_rows:
        for ref in set(_PY_REF.findall(les)):
            if not _PROG_LIKE.search(ref):
                continue
            if not (programs_dir / ref).exists():
                dims["stale_program_ref"].append({"ic_class": cls, "ref": ref})
                findings.append(f"[{cls}] stale program ref '{ref}' — no such vibe-ic program "
                                f"under programs/")

    # 4) related[] concept-graph health (no-op if the field is unused)
    rel = {c: e.get("related") for c, e in by_class.items() if e.get("related") is not None}
    for cls, links in rel.items():
        if not isinstance(links, list):
            continue
        for r in links:
            if r == cls:
                dims["related_graph"].append({"ic_class": cls, "issue": "self-link"})
                findings.append(f"[{cls}] related self-link")
            elif r not in by_class:
                dims["related_graph"].append({"ic_class": cls, "issue": "dangling", "target": r})
                findings.append(f"[{cls}] related dangling target '{r}'")
            else:
                back = by_class[r].get("related") or []
                if isinstance(back, list) and cls not in back:
                    dims["related_graph"].append({"ic_class": cls, "issue": "asymmetric",
                                                  "target": r})
                    findings.append(f"[{cls}] related asymmetric: {cls}->{r} but {r} does not "
                                    f"link back")

    return {"pass": not findings, "classes": len(by_class),
            "counts": {k: len(v) for k, v in dims.items()},
            "findings": findings, "dimensions": dims}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--programs-dir", type=Path, default=_HERE)
    ap.add_argument("--dup-threshold", type=float, default=0.6)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when any finding exists (default: advisory, exit 0)")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = audit(a.db, a.programs_dir, a.dup_threshold)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    c = rep.get("counts", {})
    print(f"ic_expert_db_health: classes={rep.get('classes','?')} "
          f"low_retrievability={c.get('low_retrievability',0)} "
          f"near_duplicate={c.get('near_duplicate',0)} "
          f"stale_program_ref={c.get('stale_program_ref',0)} "
          f"related_graph={c.get('related_graph',0)}")
    for f in rep.get("findings", []):
        print(f"  ~ {f}")
    if rep.get("fatal"):
        return 1  # an unparseable / structurally-broken DB is a hard error even in advisory mode
    return (1 if (a.strict and not rep["pass"]) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
