#!/usr/bin/env python3
"""matrix_corpus_gen.py — build the 63x9 matrix's OWN corpus (vibe-ic#1028).

WHY THIS EXISTS
===============
D3/D4/D7 resolve their population through
``fixtures/matrix_d3_output_manifest.json``, whose four in-repo run roots were
`benchmark-data/ic/{sha256, spm/v1.9.96_gf180mcuD, u_hawaii_adc,
u_hawaii_adc/v1.9.86_sky130A}`. PR #1028 withdraws every one of them, so the
matrix loses the evidence base it stands on and 61 D3 cells collapse at once.

That is the same defect one layer up from the vacuous-gate class already fixed
in this PR, and it is the more serious one: a matrix whose population is
"whatever happens to be published" reads differently depending on what somebody
published that week. #1028 is the proof, not the cause.

WHAT THIS BUILDS, AND WHAT IT DELIBERATELY DOES NOT
====================================================
It emits REPRESENTATIVE cells the test suite OWNS, under
``programs/tests/fixtures/matrix_corpus/``. Representative, not real:

  * These artefacts are SYNTHESIZED, never copied from the withdrawn trees.
    Copying the published bytes back would resurrect withdrawn run output into
    the repository under a different directory name, which is precisely the
    thing #1028 exists to stop. Every file here is generated from the
    manifest's own declaration of what the path is, and says so in its body.
  * They are sufficient BECAUSE OF WHAT D3 ACTUALLY ASKS. `check_entry` ->
    `resolve` requires a declared path to yield a COMMITTED, NON-EMPTY
    artefact. The dimension measures whether the flow DECLARES and PRODUCES its
    outputs — not whether any particular chip was any good. A representative
    artefact answers that question exactly as a real one does.

WHAT CANNOT BE A FIXTURE, AND IS NOT FAKED
==========================================
`.gds` / `.def` / `.spef` are gitignored by construction (`.gitignore:83-84`;
the negation at :172-173 applies ONLY under `benchmark-data/ic/**`, not here),
and `benchmark-data/PUBLISHING.md` states raw geometry is never committed.
Those entries are recorded as DISCLOSED SKIPS with a reason rather than
smuggled in behind a new negation or replaced by a stub pretending to be a
layout. A green square that means nothing is the disease, not the cure.

USAGE
    python3 matrix_corpus_gen.py --write     # emit the corpus
    python3 matrix_corpus_gen.py --check     # verify it matches the manifest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "matrix_d3_output_manifest.json"
CORPUS = HERE / "matrix_corpus"

#: Run roots whose evidence PR #1028 withdraws, mapped to the fixture alias
#: that replaces them. The alias is deliberately NOT the published path: a
#: reader must never mistake a fixture for the cell it stands in for.
#: The four roots the manifest REGISTERED get a cell each. The three below them
#: were never registered as run roots, but entries name them as the run that
#: produced an artefact, and on `origin/main` those artefacts resolved because
#: the published trees carried them. #1028 withdraws those trees too, so they
#: are backed here as well — folded into the cell whose flow they belong to
#: rather than given a root of their own, because the manifest has no root for
#: them to be.
ALIASES = {
    "benchmark-data/ic/sha256": "digital_hash_cell",
    "benchmark-data/ic/spm/v1.9.96_gf180mcuD": "digital_full_flow_cell",
    "benchmark-data/ic/u_hawaii_adc": "analog_track_cell",
    "benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A": "analog_published_cell",
    "benchmark-data/ic/sha256/clean_run_v1427_20260715": "digital_hash_cell",
    "benchmark-data/ic/subservient": "digital_full_flow_cell",
    "benchmark-data/ic/caravel_user_project": "digital_full_flow_cell",
}

#: Roots that live on a campaign HOST, not in this repository. #527 stopped
#: consulting them on every host, so their entries were already unevidenced
#: BEFORE #1028 and are NOT this PR's to back. Listed so the split between
#: "withdrawn by #1028" and "never in the repo" is stated, not implied.
DEFAULT_ALIAS = "digital_full_flow_cell"

HOST_ONLY_ROOTS = (
    "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e",
    "AI_IC_design/4th_benchmark/cv32e40p_e2e",
    "AI_IC_design/4th_benchmark/ibex_e2e",
    "campaign_pdk/spm/_aborted_tmpplugin_run",
    "campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721",
)

#: Extensions the repository refuses to commit anywhere outside
#: `benchmark-data/ic/**`. Not a policy invented here — see the module
#: docstring for the two rules this defers to.
UNCOMMITTABLE = {".gds", ".def", ".spef", ".oas"}

BANNER = "SYNTHESIZED MATRIX FIXTURE — not a real run artefact (vibe-ic#1028)"


def _representative(rel: str, declared_bytes: int) -> str:
    """Body for one representative artefact, by the KIND its path declares."""
    ext = os.path.splitext(rel)[1].lower()
    note = (f"{BANNER}\nDeclared by matrix_d3_output_manifest.json as {rel!r} "
            f"({declared_bytes} B in the withdrawn cell). Generated by "
            f"matrix_corpus_gen.py; the content is representative of the "
            f"artefact's KIND, never a copy of the withdrawn bytes.")
    if ext == ".json":
        return json.dumps({
            "_fixture": BANNER,
            "_declared_path": rel,
            "_declared_size_bytes": declared_bytes,
            "_generated_by": "matrix_corpus_gen.py",
            "verdict": "PASS",
            "_representative_of_kind": "json report",
        }, indent=2) + "\n"
    if ext in (".md",):
        return f"# {os.path.basename(rel)}\n\n> {note}\n"
    if ext in (".v", ".sv"):
        return (f"// {note}\n"
                f"module fixture_representative (input wire clk);\n"
                f"endmodule\n")
    if ext == ".sdc":
        return f"# {note}\ncreate_clock -name clk -period 10.0 [get_ports clk]\n"
    if ext == ".sby":
        return f"# {note}\n[options]\nmode bmc\ndepth 10\n"
    if ext == ".xml":
        return (f"<!-- {note} -->\n"
                f'<testsuite name="fixture" tests="1" failures="0"></testsuite>\n')
    if ext == ".sp":
        return f"* {note}\n.title fixture representative\n.end\n"
    if ext == ".mag":
        return f"magic\ntech fixture\n# {note}\n<< end >>\n"
    if ext == ".lef":
        return f"# {note}\nVERSION 5.8 ;\nEND LIBRARY\n"
    if ext == ".lib":
        return f"/* {note} */\nlibrary(fixture_representative) {{\n}}\n"
    if ext == ".lyrdb":
        return f'<!-- {note} -->\n<report-database></report-database>\n'
    if ext == ".flag":
        return f"{note}\nLVS_MATCH\n"
    # .rpt and anything else textual
    return f"# {note}\nstatus: representative\n"


def plan():
    """[(alias, rel, declared_bytes, committable)] for every declared entry."""
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    seen, out = set(), []
    for _sid, step in man["steps"].items():
        for _key, e in (step.get("entries") or {}).items():
            if not isinstance(e, dict):
                continue
            if e.get("status") not in ("PRODUCED_BY_RUN", "PRODUCED_LIVE"):
                continue
            root = e.get("run") or e.get("base_run")
            # ONLY roots #1028 withdrew are backed here.
            #
            # An earlier revision of this generator gave every unrecognised
            # root a default cell, on the reasoning that host-root entries had
            # passed on `origin/main` via `resolve_anywhere` finding a match in
            # the published corpus. MEASURED, that was wrong in the way that
            # matters: it turned EIGHT cells green that are RED on main —
            # steps 12, 30, 32, M2, M3, M4 and two population guards. Those
            # cells are red BY POLICY. `UNEVIDENCED_CELLS` and this module's
            # own docstring say committing the real run trees is what closes
            # them; closing them with synthesized fixtures instead would be
            # precisely the "green square that means nothing" this corpus
            # exists to prevent, and it would have read as #1028 repairing
            # something it deleted.
            #
            # So a host-only root gets NOTHING here and its cell stays red.
            alias = ALIASES.get(root)
            if alias is None:
                continue
            # PRODUCED_BY_RUN records the artefact as `path`; PRODUCED_LIVE
            # names what its producer `writes`.
            rel = e.get("path") or e.get("writes")
            if not rel or (alias, rel) in seen:
                continue
            seen.add((alias, rel))
            ok = os.path.splitext(rel)[1].lower() not in UNCOMMITTABLE
            out.append((alias, rel, e.get("size_bytes", 0), ok))
    return sorted(out)


def write():
    made = skipped = 0
    per_root = {}
    for alias, rel, nbytes, committable in plan():
        per_root.setdefault(alias, {"written": [], "skipped": []})
        if not committable:
            per_root[alias]["skipped"].append(rel)
            skipped += 1
            continue
        dst = CORPUS / alias / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(_representative(rel, nbytes), encoding="utf-8")
        per_root[alias]["written"].append(rel)
        made += 1
    for alias, rec in per_root.items():
        att = CORPUS / alias / "FIXTURE_ATTESTATION.json"
        att.parent.mkdir(parents=True, exist_ok=True)
        att.write_text(json.dumps({
            "_comment": BANNER,
            "kind": "fixture",
            "dimension": "63x9 matrix (D3/D4/D7)",
            "stands_in_for": next(k for k, v in ALIASES.items() if v == alias),
            "withdrawn_by": "vibe-ic#1028",
            "generated_by": "programs/tests/fixtures/matrix_corpus_gen.py",
            "content": "synthesized, representative of artefact KIND only; "
                       "never a copy of the withdrawn bytes",
            "artefacts_written": sorted(rec["written"]),
            "disclosed_skips": [
                {"path": p,
                 "reason": "gitignored by construction outside "
                           "benchmark-data/ic/** (.gitignore:83-84, negated "
                           "only at :172-173); PUBLISHING.md states raw "
                           "geometry is never committed"}
                for p in sorted(rec["skipped"])],
        }, indent=2) + "\n", encoding="utf-8")
    return made, skipped


def check():
    missing = []
    for alias, rel, _n, committable in plan():
        if committable and not (CORPUS / alias / rel).is_file():
            missing.append(f"{alias}/{rel}")
    return missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.write:
        made, skipped = write()
        print(f"[matrix_corpus_gen] wrote {made} representative artefact(s); "
              f"{skipped} disclosed skip(s) (uncommittable geometry)")
        return 0
    if a.check:
        missing = check()
        if missing:
            print(f"[FAIL] {len(missing)} declared artefact(s) absent from the "
                  f"fixture corpus:", file=sys.stderr)
            for m in missing[:10]:
                print(f"    {m}", file=sys.stderr)
            return 1
        print("[PASS] fixture corpus covers every committable declared entry")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
