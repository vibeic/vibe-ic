#!/usr/bin/env python3
"""spec_required_artifact_check.py — generic gate.

Scans the project's Phase-1 input docs and generated L*.json files for
imperative "Plugin MUST emit/produce/declare <path>" clauses (English and
Traditional-Chinese forms).  For each clause it asserts the declared artifact
exists in the run dir and is non-empty.

INPUT-DOC LOCATIONS (see `_input_doc_dirs`).  BOTH Phase-1 doc roots are
scanned, because the repo has two and they are not interchangeable:

  * `phase1/input_doc/`  — `_path_layout.input_doc_dir()`, documented there as
    the "Path A entry" and by `phase1_one_shot_runner._detect_input_mode` as
    the "Layout P canonical" location.  This is where the doc-extraction track
    puts the verbatim vendor-doc extracts, and it stores `.txt`.
  * `input/docs/`        — the legacy phase1_engine input root, which
    `_detect_input_mode` labels "legacy".  Mixed `.md` / `.txt` / `.rst`.

Reading only `input/docs/*.md` (the pre-fix behaviour) made the gate blind to
the canonical location entirely and, even in the legacy one, to every
non-Markdown doc — so on a Path-A run it found nothing to assert and reported
an EXECUTED pass.

Only PATH-SHAPED tokens are asserted on -- see `_is_path_shaped`.  A
backticked token after a MUST-verb is very often a SIGNAL name, not a
filesystem path, and asserting on those failed legitimate designs (see the
false-positive note on `_is_path_shaped`).  Rejected tokens are reported in
`ignored_tokens` so the narrowing is visible rather than silent.

Emits: reports/phase2/gates/spec_required_artifacts.json

Exit codes:
  0  — all declared artifacts present and non-empty (or VACUOUS-PASS)
  1  — one or more declared artifacts absent or empty
  2  — usage / I/O error

Chip-agnostic: no hard-coded design names, file names, or field names.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Clause extraction
# ---------------------------------------------------------------------------

# Markdown emphasis around the imperative. Specs BOLD the requirement word —
# that is what bold is for — so `**MUST**` and `**必須**` are the ordinary
# forms, not exotic ones.
#
# This fragment is SHARED by both patterns below on purpose. It was previously
# spelled out inline in the Chinese pattern only, and the two drifted: the
# Chinese half tolerated `**必須**` while the English half did not tolerate
# `**MUST**`. MEASURED on this program, same clause, same table, three forms:
#
#   `**必須**於 \`p/declaration.json\` 聲明`   -> clauses_found=1  FAIL
#   `**MUST** emit \`p/declaration.json\``     -> clauses_found=0  VACUOUS_PASS
#   `MUST emit \`p/declaration.json\``         -> clauses_found=1  FAIL
#
# So an English spec that bolds MUST declared a required artifact this gate
# then reported as "nothing to assert" — a silent false negative in the one
# gate whose job is to notice a required artifact is missing. Sharing the
# fragment is the fix for the DRIFT, not just for the bold case.
_MD_EMPH = r'[*_]{0,2}'

# English: "MUST emit/produce/declare `some/path.json`"
# Also covers "shall emit", "is required to emit" etc.
_EN_PATTERN = re.compile(
    rf'{_MD_EMPH}(?:MUST|shall|required\s+to){_MD_EMPH}\s+'
    rf'{_MD_EMPH}(?:emit|produce|declare|generate|write|output){_MD_EMPH}\s+'
    r'[`\'""]([^\s`\'"">]+)[`\'""]]?',
    re.IGNORECASE,
)

# Traditional-Chinese form (as used in these docs):
# "**必須**於 `plugin_output/declaration.json` 聲明" or
# "必須 emit `path`" or "必須產出 `path`"
_ZH_PATTERN = re.compile(
    rf'{_MD_EMPH}必須{_MD_EMPH}\s*(?:於\s*)?'
    r'[`\'""]([^\s`\'"">]+)[`\'""]]?\s*(?:聲明|宣告|emit|產出|寫出|輸出)?'
    r'|'
    rf'{_MD_EMPH}必須{_MD_EMPH}\s*'
    r'(?:emit|produce|declare|generate|write|output)\s+[`\'""]([^\s`\'"">]+)[`\'""]]?',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Path-shape filter
# ---------------------------------------------------------------------------

# CONFIRMED FALSE POSITIVE this filter closes.  Both regexes above match ANY
# backticked token that follows a MUST-verb, so a SIGNAL name reads as a
# filesystem path.  Prose lifted verbatim from this plugin's own knowledge
# base -- "A streaming run-length counter must emit `valid` for exactly one
# cycle ..." plus "MUST declare `rst_n`" -- made the gate return rc=1 /
# verdict FAIL with FAIL_ABSENT 'valid' and FAIL_ABSENT 'rst_n' on a run that
# DID contain every artifact its spec required.  Any legitimate valid/ready
# design whose spec names its signals in backticks was failed by this gate.
#
# A declared ARTIFACT is a file, so the token must look like one: it carries a
# directory separator, or it carries a known artifact extension.  Everything
# else is recorded in the report's `ignored_tokens` -- narrowed, never
# silently dropped, so a reviewer can see exactly what the gate declined to
# assert on and why.
_ARTIFACT_EXTENSIONS = frozenset({
    # structured data / reports
    "json", "yaml", "yml", "toml", "ini", "cfg", "csv", "tsv", "xml",
    "md", "txt", "log", "rpt", "html", "pdf",
    # HDL / EDA source and sign-off artifacts
    "v", "sv", "vh", "svh", "vhd", "vhdl", "tcl", "sdc", "sdf", "upf",
    "lef", "lib", "def", "gds", "gds2", "oas", "spef", "cdl", "cir",
    "spi", "sp", "vcd", "fst", "saif", "net", "eqn", "qsf", "sof", "bit",
    # generic build outputs
    "py", "sh", "zip", "tar", "gz",
})


def _is_path_shaped(token: str) -> bool:
    """True when `token` looks like a filesystem artifact rather than a name.

    Path-shaped == carries a directory separator, or ends in a known
    artifact extension.  `plugin_output/declaration.json` and
    `declaration.json` qualify; `valid`, `rst_n`, `p` do not.
    """
    if not token:
        return False
    if "/" in token or "\\" in token:
        return True
    head, dot, ext = token.rpartition(".")
    return bool(dot) and bool(head) and ext.lower() in _ARTIFACT_EXTENSIONS


def _extract_clauses_from_text(text: str, source: str) -> tuple[list[dict], list[dict]]:
    """Return (clauses, ignored) — ignored holds non-path-shaped tokens."""
    clauses: list[dict] = []
    ignored: list[dict] = []

    def _record(raw: str, token: str, pattern: str) -> None:
        path = token.strip("/").rstrip(")")
        if not path:
            return
        entry = {
            "clause_text": raw,
            "artifact_path": path,
            "source": source,
            "pattern": pattern,
        }
        if _is_path_shaped(path):
            clauses.append(entry)
        else:
            ignored.append({
                **entry,
                "reason": ("token is not path-shaped (no directory separator "
                           "and no known artifact extension) — reads as a "
                           "signal/identifier name, not a required artifact"),
            })

    for m in _EN_PATTERN.finditer(text):
        _record(m.group(0), m.group(1), "english_imperative")
    for m in _ZH_PATTERN.finditer(text):
        _record(m.group(0), (m.group(1) or m.group(2) or ""), "zh_tw_imperative")
    return clauses, ignored


# Text-bearing input-doc extensions.  The pre-fix glob was `*.md` ONLY; across
# the committed run corpus that is 0 of 181 files under `phase1/input_doc/`
# (all `.txt`) and 86 of 163 under `input/docs/` (.md 86, .txt 40, .rst 17,
# .pdf 15, .svg 4, .sv 1).  Binary/vector formats (.pdf/.svg) are deliberately
# NOT read here — the doc-extraction track converts them into the canonical
# `phase1/input_doc/*.txt`, which IS read.
_DOC_EXTS: tuple[str, ...] = (".md", ".txt", ".rst")


_PATH_LAYOUT = None       # cached module, or False once an import has failed


def _path_layout():
    """The repo's path API, imported once. Returns the module or None.

    Imported lazily (and tolerantly) so this gate stays runnable as a
    standalone script from an arbitrary cwd, which is how the flow sweep
    invokes it.
    """
    global _PATH_LAYOUT
    if _PATH_LAYOUT is None:
        try:
            here = str(Path(__file__).resolve().parent)
            if here not in sys.path:
                sys.path.insert(0, here)
            import _path_layout as _pl  # noqa: E402
            _PATH_LAYOUT = _pl
        except Exception:
            _PATH_LAYOUT = False
    return _PATH_LAYOUT or None


def _input_doc_dirs(run_dir: Path) -> list[Path]:
    """Both Phase-1 input-doc roots, canonical first, deduplicated.

    `phase1/input_doc/` is the repo's OWN canonical Path-A location
    (`_path_layout.input_doc_dir`, "Path A entry"; `phase1_one_shot_runner.
    _detect_input_mode`, "Layout P canonical").  `input/docs/` is the location
    the same function calls "legacy"; it is still scanned so a legacy-layout
    project keeps working.  Resolved through `_path_layout` when that module is
    importable so this gate cannot drift away from the path API again.
    """
    pl = _path_layout()
    canonical = (pl.input_doc_dir(run_dir) if pl is not None
                 else run_dir / "phase1" / "input_doc")
    out: list[Path] = []
    seen: set[str] = set()
    for d in (canonical, run_dir / "input" / "docs"):
        key = str(d)
        if key in seen or not d.is_dir():
            continue
        seen.add(key)
        out.append(d)
    return out


def _collect_clauses(run_dir: Path) -> tuple[list[dict], list[dict]]:
    """Scan BOTH Phase-1 input-doc roots (see `_input_doc_dirs`) for every
    text-bearing extension in `_DOC_EXTS`, plus phase1/generated_docs/L*.json.

    Returns (clauses, ignored_tokens).
    """
    clauses: list[dict] = []
    ignored: list[dict] = []
    seen_paths: set[str] = set()
    seen_ignored: set[str] = set()

    def _absorb(found: list[dict], dropped: list[dict]) -> None:
        for c in found:
            key = c["artifact_path"]
            if key not in seen_paths:
                seen_paths.add(key)
                clauses.append(c)
        for c in dropped:
            key = c["artifact_path"]
            if key not in seen_ignored:
                seen_ignored.add(key)
                ignored.append(c)

    # Input docs — BOTH roots, every text-bearing extension.
    for doc_dir in _input_doc_dirs(run_dir):
        docs = [p for p in sorted(doc_dir.rglob("*"))
                if p.is_file() and p.suffix.lower() in _DOC_EXTS]
        for doc in docs:
            try:
                text = doc.read_text(errors="replace")
            except OSError:
                continue
            _absorb(*_extract_clauses_from_text(
                text, str(doc.relative_to(run_dir))))

    # Generated L-doc JSON (look in text values only, avoid false positives
    # from structured fields whose keys happen to match)
    l_doc_dir = run_dir / "phase1" / "generated_docs"
    if l_doc_dir.is_dir():
        for jf in sorted(l_doc_dir.glob("L*.json")):
            try:
                text = jf.read_text(errors="replace")
                _absorb(*_extract_clauses_from_text(text, str(jf.relative_to(run_dir))))
            except Exception:
                pass

    return clauses, ignored


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------

# --- SUBSTANCE ------------------------------------------------------------- #
#
# WHY PRESENCE IS NOT ENOUGH.  This gate used to ask two questions of a
# spec-declared artifact: does the path exist, and is `st_size > 0`.  `{}` is
# two bytes on disk, three with the trailing newline an emitter would add;
# either way it clears `> 0`.  A declaration file containing `{}` satisfied a clause
# that says the plugin MUST DECLARE these choices, while declaring none of
# them — and the program that CAN tell the difference has existed the whole
# time.  `spec_declaration_emit --verify`'s own help text says so verbatim:
# "This is the SUBSTANCE check the required-artifact gate cannot make: it
# scores presence and byte count, and `{}` is 3 bytes."  It was invoked by
# nothing.  MEASURED 2026-09-06: `--verify` appears in no runner, no flow step,
# no gate and no YAML in this tree.
#
# TWO QUESTIONS, IN THIS ORDER, AND NEITHER INVENTS A REQUIREMENT:
#   1. THE SPEC'S OWN CONTRACT.  If the project's Phase-1 docs declare a field
#      table for THIS artifact, the required-ness comes from the spec — an
#      input this gate did not write — and `verify_declaration` names each
#      REQUIRED field that is missing or a placeholder.  That is where "refused
#      with the key named" comes from: the key is the spec's, not ours.
#   2. THE GENERIC EMPTY-CONTAINER TEST.  With no contract there is no key to
#      name, but `{}` / `[]` / unparseable JSON is still not a declaration of
#      anything.  This asks only what the file's own format already answers, so
#      it names no field, no design, no PDK and no tool.
#
# A PROBE THAT COULD NOT RUN IS NOT A PASS AND NOT A FAIL.  Every failure to
# ask (module absent, extraction raised, file unreadable) returns NOT_MEASURED
# and the artifact keeps the presence verdict it already had — the gate says
# what it could not read instead of supplying a default for it.
_SUBSTANCE_CONTRACT_CACHE: dict = {}


def _project_contract(run_dir: Path, artifact_path: str):
    """(contract|None, why). Cached per (run_dir, artifact) — contract
    extraction re-reads every input doc, and this gate asks once per clause."""
    key = (str(run_dir), artifact_path)
    if key in _SUBSTANCE_CONTRACT_CACHE:
        return _SUBSTANCE_CONTRACT_CACHE[key]
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import spec_declaration_emit as _sde  # noqa: PLC0415 — optional peer
        got = _sde.select_contract(run_dir, artifact_path, [])
        ans = (got[0], got[1])
    except Exception as exc:  # noqa: BLE001
        ans = (None, "NOT_MEASURED: %s" % exc)
    _SUBSTANCE_CONTRACT_CACHE[key] = ans
    return ans


def _substance_of(run_dir: Path, artifact_path: str, resolved: Path):
    """(status|None, reason, source).

    `status` is None when no substance question could be asked, in which case
    the caller keeps the presence verdict. `source` records WHICH question was
    asked so a reader can tell a real pass from an unasked one."""
    contract, why = _project_contract(run_dir, artifact_path)
    if contract is not None:
        try:
            import spec_declaration_emit as _sde  # noqa: PLC0415
            rep = _sde.verify_declaration(run_dir, contract, resolved)
        except Exception as exc:  # noqa: BLE001
            return None, "NOT_MEASURED: verify raised %s" % exc, "CONTRACT"
        if rep.get("verdict") in ("PASS", "PASS_INFORMATIONAL"):
            return "PASS", rep.get("note", ""), "CONTRACT"
        bits = []
        for name in rep.get("missing_required", []):
            bits.append("%s: REQUIRED by %s, absent from the declaration"
                        % (name, contract["source"]))
        for item in rep.get("placeholder_required", []):
            bits.append("%s: %s" % (item["field"], item["reason"]))
        reason = "%s — %s" % (rep.get("verdict"), rep.get("note", ""))
        if bits:
            reason += "; " + "; ".join(bits)
        # Carry the verify verdict through when it is more specific than
        # "did not satisfy": FAIL_ABSENT and FAIL_UNPARSEABLE are different
        # facts from "a required key is missing", and a status that flattens
        # all three is the same loss of information this whole item is about.
        _v = rep.get("verdict") or ""
        status = _v if _v.startswith("FAIL_") else "FAIL_UNSATISFIED"
        return status, reason, "CONTRACT"

    if resolved.suffix.lower() != ".json":
        return (None,
                "no declaration contract (%s) and not a JSON artifact, so "
                "its substance is not a question this gate can ask" % why,
                "NONE")
    try:
        loaded = json.loads(resolved.read_text())
    except Exception as exc:  # noqa: BLE001
        return ("FAIL_UNPARSEABLE",
                "the declared artifact is not readable JSON: %s" % exc,
                "JSON")
    if isinstance(loaded, (dict, list, str)) and len(loaded) == 0:
        return ("FAIL_VACUOUS",
                "the declared artifact parses as an EMPTY %s — it is present, "
                "it is %d byte(s), and it declares nothing"
                % (type(loaded).__name__, resolved.stat().st_size),
                "JSON")
    return "PASS", "parses as a non-empty JSON %s" % type(loaded).__name__, "JSON"


def _check_artifact(run_dir: Path, artifact_path: str) -> dict:
    """Return {artifact_path, resolved, exists, non_empty, status, ...}.

    Presence first, then SUBSTANCE (see the block above). An artifact that is
    absent or zero-length is already refused and no substance question is
    asked of it — there is nothing to read."""
    resolved = run_dir / artifact_path
    exists = resolved.exists()
    # UNCHANGED from the presence-only version, deliberately: adding an
    # `is_file()` here would relabel a DIRECTORY artifact (st_size 4096, so it
    # passed before) as FAIL_EMPTY, which is both a new refusal and a wrong
    # word for it. A directory falls through to the substance test and, having
    # no contract and no `.json` suffix, comes back NOT_MEASURED — i.e. it
    # keeps exactly the verdict it had.
    non_empty = exists and resolved.stat().st_size > 0
    out = {
        "artifact_path": artifact_path,
        "resolved": str(resolved),
        "exists": exists,
        "non_empty": non_empty,
    }
    if not exists:
        out["status"] = "FAIL_ABSENT"
        return out
    if not non_empty:
        out["status"] = "FAIL_EMPTY"
        return out
    sub_status, sub_reason, sub_source = _substance_of(
        run_dir, artifact_path, resolved)
    out["substance_source"] = sub_source
    out["substance_reason"] = sub_reason
    out["status"] = sub_status if sub_status is not None else "PASS"
    if sub_status is None:
        out["substance_status"] = "NOT_MEASURED"
    else:
        out["substance_status"] = sub_status
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _emit_preflight(results: list[dict]) -> int:
    """Print the author-facing OUTSTANDING list. ALWAYS returns 0.

    Advisory by construction: at handoff the artifacts are legitimately absent
    (nobody has authored them yet), so a non-zero exit here would block every
    correct run. The blocking assertion stays in the normal end-of-phase mode.
    """
    outstanding = [r for r in results if r["status"] != "PASS"]
    if not results:
        print("spec_required_artifact_preflight: NONE — the input docs declare "
              "no path-shaped mandatory artifact.")
        return 0
    if not outstanding:
        print("spec_required_artifact_preflight: ALL %d spec-declared artifact(s) "
              "already present." % len(results))
        return 0
    print("spec_required_artifact_preflight: %d spec-declared artifact(s) "
          "OUTSTANDING — author these as well as the RTL, or final_audit will "
          "FAIL after the full Phase-2 pipeline has run:" % len(outstanding))
    for r in outstanding:
        print("  - %s" % r["artifact_path"])
        print("      required by: %s" % r.get("source", "<unknown input doc>"))
        print("      clause     : %s" % (r.get("clause_text", "") or "").strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check spec-declared required artifacts exist and are non-empty."
    )
    parser.add_argument("run_dir", nargs="?", default=".",
                        help="Run directory (default: cwd)")
    # ------------------------------------------------------------------ #
    # PREFLIGHT (advisory) — the SAME extraction, surfaced at HANDOFF time
    # instead of only at the end-of-Phase-2 audit.
    #
    # Every input this gate reads (`phase1/input_doc/`, `input/docs/`) already
    # exists BEFORE the rtl_gen step waives to the AI author. But the gate is
    # only invoked from the flow-compliance sweep, so an author who was told
    # "write the RTL here" and nothing else discovers that the spec ALSO made
    # e.g. `plugin_output/declaration.json` mandatory only after synthesis, DFT
    # and a multi-minute LEC have run and final_audit FAILs. Measured on a real
    # sign-off run: an entire Phase-2 pipeline was spent to report one missing
    # file that takes seconds to write and was fully knowable at handoff.
    #
    # --preflight lists the artifacts still OUTSTANDING and always exits 0, so
    # it can be printed in the handoff message without ever blocking a run.
    # ------------------------------------------------------------------ #
    parser.add_argument("--preflight", action="store_true",
                        help="ADVISORY: list spec-declared artifacts still "
                             "outstanding and exit 0 (never blocks). For the "
                             "authoring handoff, before RTL is written.")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run_dir not found: {run_dir}", file=sys.stderr)
        return 2

    clauses, ignored = _collect_clauses(run_dir)

    results: list[dict] = []
    for c in clauses:
        check = _check_artifact(run_dir, c["artifact_path"])
        results.append({**c, **check})

    if args.preflight:
        return _emit_preflight(results)

    # Determine overall verdict
    fails = [r for r in results if r["status"] != "PASS"]
    if not results:
        verdict = "VACUOUS_PASS"
        note = ("No path-shaped MUST-emit clauses found in input docs — "
                "nothing to assert.")
        if ignored:
            note += (f" ({len(ignored)} non-path-shaped token(s) ignored: "
                     f"{', '.join(sorted(t['artifact_path'] for t in ignored)[:8])})")
    elif fails:
        verdict = "FAIL"
        # NAME THEM. "1 declared artifact(s) absent or empty." was the whole
        # message a reader got, and once substance is asked it is not even
        # accurate — an artifact can now fail while being present and
        # non-empty. Each line says which artifact, which of the three
        # questions refused it, and why.
        note = "%d declared artifact(s) did not satisfy the spec: %s" % (
            len(fails),
            "; ".join(
                "%s [%s]%s" % (
                    r["artifact_path"], r["status"],
                    (" " + r["substance_reason"])
                    if r.get("substance_reason") else "")
                for r in fails[:8]))
        if len(fails) > 8:
            note += " (+%d more, see the report)" % (len(fails) - 8)
    else:
        verdict = "PASS"
        note = (f"All {len(results)} declared artifact(s) present, non-empty "
                f"and substantive "
                f"({sum(1 for r in results if r.get('substance_source') == 'CONTRACT')}"
                f" checked against the spec's own field contract, "
                f"{sum(1 for r in results if r.get('substance_source') == 'JSON')}"
                f" against JSON emptiness, "
                f"{sum(1 for r in results if r.get('substance_status') == 'NOT_MEASURED')}"
                f" NOT_MEASURED).")

    report = {
        "schema_version": 1,
        "program": "spec_required_artifact_check",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "verdict": verdict,
        "note": note,
        "clauses_found": len(results),
        "failed_count": len(fails),
        "results": results,
        # WHICH input-doc roots were actually read, and how many docs each
        # yielded.  A VACUOUS_PASS is only trustworthy if you can see that the
        # gate looked in the right place; the pre-fix version reported an
        # executed pass while reading a directory the canonical layout does
        # not use.
        "input_doc_dirs_scanned": [
            str(d.relative_to(run_dir)) for d in _input_doc_dirs(run_dir)],
        "input_docs_read": sorted(
            str(p.relative_to(run_dir))
            for d in _input_doc_dirs(run_dir)
            for p in d.rglob("*")
            if p.is_file() and p.suffix.lower() in _DOC_EXTS),
        # Tokens the regexes matched but that are not path-shaped (signal
        # names such as `valid` / `rst_n`).  Reported so the narrowing is
        # auditable — the gate asserts on none of them.
        "ignored_token_count": len(ignored),
        "ignored_tokens": ignored,
    }

    # Write report
    out_dir = run_dir / "reports" / "phase2" / "gates"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "spec_required_artifacts.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print(f"spec_required_artifact_check: {verdict} — {note}")
    print(f"  Report: {out_path}")

    return 0 if verdict in ("PASS", "VACUOUS_PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
