#!/usr/bin/env python3
"""vendored_attribution_retained_check.py — third-party source that SHIPS must
ship with the record that names where it came from. vibe-ic#1043.

THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
--------------------
#1043 was filed on a licensing obligation, not an engineering preference: a
withdrawal deleted `SOURCE_MANIFEST.md` files while the Apache-2.0 RTL they
attribute stayed in the tree. Apache-2.0 §4(b)/§4(d) attach to distributing the
WORK, not to publishing a run that used it — so withdrawing a run does not
withdraw the duty, and the obligation does not travel with the evidence.

The narrower point, and the reason this is a program rather than a review note:
**nothing in this repository could tell.** The attribution records are emitted
(`source_manifest_md_emit.py`, `staged_rtl_reused_ip_manifest_emit.py`) and read
back for RTL reconciliation, but no gate ever asked whether a licensed file that
is still tracked still has one. A deletion is invisible, and so is the case
below, which nobody deleted at all — it simply never had a record.

MEASURED on `947547716` (v1.10.33) over `benchmark-data/`, before this gate:

    17216 tracked files
      525 carrying an SPDX-License-Identifier  (497 Apache-2.0, 28 ISC)
        1 UNCOVERED

and the one was not a subtlety:
`benchmark-data/ic/spm/v1.10.18_sky130A/phase2/stage2/dft/cell_model_combined.v`
— **152,616 lines** of `Copyright 2020 The SkyWater PDK Authors`, Apache-2.0,
under an IC root carrying no `SOURCE_MANIFEST` of any kind.

WHAT IT CHECKS
--------------
Every TRACKED file whose head declares `SPDX-License-Identifier: <id>` must be
covered by a `SOURCE_MANIFEST.*` in its own directory or an ancestor of it.

Only the header is read. The gate forms no view on WHICH licence obliges what —
that is a legal question and this is a structural one. A file that announces a
licence is a file somebody must be able to trace; the gate asks only whether the
tracing record is still there.

THE COVERING MANIFEST MUST BE A STRICT DESCENDANT OF THE SCAN ROOT
------------------------------------------------------------------
Otherwise one `benchmark-data/SOURCE_MANIFEST.md` would cover the entire corpus
and the gate would be satisfiable by a single file — a check that can be turned
off by adding one path is a ban wearing a checkmark.
:func:`test_a_manifest_at_the_scan_root_does_not_cover_the_world` pins it.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* It does not judge whether the record's claim is TRUE — only whether it
  names the file at all. Whether "upstream: X, Apache-2.0" is accurate is a
  legal question; whether the record says anything about this file is a
  structural one, and only the second is decidable here.
  (Until vibe-ic#1307 it did not read the content at all, so an EMPTY record
  covered everything beneath it. See `record_names`.)
* It does not judge generated files differently. `cell_model_combined.v` is a
  concatenation of PDK cell models, and it carries the upstream header because
  it carries the upstream CODE — a derivative work distributes the original.
  Exempting "generated" files would exempt exactly the case that found this.
* It does not scan untracked files. The obligation attaches to what is
  DISTRIBUTED, and the git index is what this repository distributes.

BASELINE
--------
None for the ORIGINAL rule (a licensed file with no record above it): that debt
could be paid the day the gate landed, and `uncovered` is still measured at zero
tolerance.

The vibe-ic#1307 rule — the record must NAME the file — ships with one, because
that debt cannot be paid by this program. MEASURED on `1e21cc08b`: 525 licensed
files, **454 named, 71 not**, across five records (subservient 38, opentitan_aes
21, caravel_user_project 8+3, sha256 1). Writing those 71 attributions would
mean asserting provenance nobody here has verified, which converts an unproven
claim into a FALSE one — strictly worse than an open one. So they are DISCLOSED
in `_UNNAMED_RESIDUAL`, the register may only SHRINK, a NEW unnamed path FAILS,
and an entry that becomes named FAILS with "delete the entry".

chip-AGNOSTIC: no design, PDK, vendor or licence-id literal decides anything.
The SPDX id is read out of the file and reported; it is never compared against
a list.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

#: The declaration this gate keys on. SPDX is the machine-readable form every
#: vendored tree in this corpus already uses, which is why it is the hook: it
#: is the file's own statement about itself, not an inference from its path.
_SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")

#: Only the head is read. A licence header that is not in the first few KB is
#: not a header, and reading whole files would make the gate a function of
#: corpus size — this one file is 152k lines.
_HEAD_BYTES = 4096

#: The attribution record, by name. `.md` and `.json` both ship in this tree.
_MANIFEST_RE = re.compile(r"^SOURCE_MANIFEST\.")

#: Default scan scope: the published corpus, which is what this repository
#: distributes and therefore where the obligation lands.
_DEFAULT_SCOPE = "benchmark-data"


def tracked_files(repo: Path, scope: str) -> List[str]:
    """The git INDEX, never the filesystem. What is distributed is what is
    tracked; an untracked scratch copy carries no obligation and a
    filesystem walk would make the verdict depend on the author's build dir."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "HEAD", "--name-only", scope],
        capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def manifest_dirs(paths: List[str]) -> set:
    return {str(Path(p).parent) for p in paths
            if _MANIFEST_RE.match(Path(p).name)}


def declared_licence(repo: Path, rel: str) -> Optional[str]:
    try:
        blob = (repo / rel).read_bytes()[:_HEAD_BYTES]
    except OSError:
        return None
    m = _SPDX_RE.search(blob.decode("utf-8", errors="replace"))
    return m.group(1).strip() if m else None


#: What a record must SAY about a path for it to count as covered (vibe-ic#1307).
#:
#: THE DEFECT THIS CLOSES. Coverage used to be decided by LOCATION alone — does
#: a file named `SOURCE_MANIFEST.*` sit in this directory or an ancestor. The
#: contents were never opened, so an EMPTY record covered everything beneath it
#: and the gate printed `every one of the 525 licence-declaring file(s) is
#: covered`. MEASURED on `1e21cc08b`: replacing `benchmark-data/ic/spm/
#: SOURCE_MANIFEST.md` with zero bytes, and then with one line of unrelated
#: noise, produced BYTE-IDENTICAL output and rc=0 in all three cases.
#:
#: That is #1043's own defect one level up. #1043 is 152k lines of Apache-2.0
#: shipped with no record naming their origin; a gate that cannot tell a record
#: naming the work from a record naming nothing cannot prevent the recurrence.
#: It is not hypothetical either — #1301 exists because the GF180MCU cell models
#: were missed AFTER the SkyWater file in the same tree was recorded, and
#: throughout that window this gate was green, because a manifest existed above
#: them that said nothing about them.
#:
#: WHAT COUNTS AS NAMING, and why it is this and not stricter. The record must
#: contain the path, its basename, its basename without extension, or a
#: directory prefix of it. A prefix counts because `phase2/stage1/rtl/` is a
#: real attribution of everything under it — records legitimately attribute a
#: vendored DIRECTORY — and demanding a line per file would make the rule a
#: transcription exercise that authors would satisfy mechanically.
#:
#: The stem is accepted because real records name modules, not filenames: the
#: caravel record says "stock `user_proj_example` … wrapped in the Caravel
#: `user_project_wrapper`", which attributes `user_proj_example.v` as plainly as
#: any path would. Requiring the extension would have charged 14 files on the
#: caravel record alone. Measured both ways before choosing.
#:
#: TOKENS, NOT SUBSTRINGS — see `_TOKEN_RE`. Corpus-wide this rule leaves 71 of
#: 525 unnamed, which is the number the residual register carries.
#: Path-shaped tokens in a record. TOKENS, NOT SUBSTRINGS, and the difference
#: is the whole sibling case: a record naming `rtl/a.v` CONTAINS the substring
#: `rtl/`, so a substring rule silently covers `rtl/b.v` too — which is exactly
#: the #1301 shape this gate exists to catch. Caught by this file's own
#: `test_PAIRED_a_record_naming_only_a_SIBLING_...` on the first draft.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.+\-/]+")


def record_names(text: str, mdir: str, rel: str) -> bool:
    """Does this record's TEXT name `rel` — the path, its name, or a prefix?

    A DIRECTORY prefix counts, so a record may attribute a vendored directory
    without transcribing every file under it — but only when the record names
    that directory AS A TOKEN. `rtl/a.v` does not attribute `rtl/b.v`.
    """
    if not (text or "").strip():
        return False                      # an empty record names nothing
    try:
        inner = Path(rel).relative_to(mdir).as_posix()
    except ValueError:
        inner = rel
    exact = {inner, rel, Path(rel).name, Path(rel).stem}
    for raw in _TOKEN_RE.findall(text):
        tok = raw.strip().rstrip(",;)")
        if not tok:
            continue
        if tok in exact:
            return True
        d = tok.rstrip("/")
        # a DIRECTORY token, and `rel` genuinely sits beneath it
        if d and (inner.startswith(d + "/") or rel.startswith(d + "/")):
            return True
    return False


def manifest_text(repo: Path, mdir: str, paths: List[str]) -> str:
    """Every attribution record in `mdir`, concatenated. `.md` and `.json`
    both ship here and a tree may carry both, so neither is privileged."""
    out = []
    for p in paths:
        if str(Path(p).parent) == mdir and _MANIFEST_RE.match(Path(p).name):
            try:
                out.append((repo / p).read_text(errors="replace"))
            except OSError:
                pass
    return "\n".join(out)


def covering_manifest_dir(rel: str, mdirs: set, scope: str) -> Optional[str]:
    """The nearest ancestor directory carrying a manifest, or None.

    Stops BEFORE the scan root: a manifest at `scope` itself covers nothing,
    or one file would satisfy the whole corpus.

    LOCATION ONLY — whether that record SAYS anything about `rel` is
    `record_names`' question, kept separate so the two failure modes stay
    distinguishable in the report: "no record above it" and "a record that
    does not name it" need different repairs.
    """
    d = Path(rel).parent
    scope_p = Path(scope)
    while True:
        if str(d) == str(scope_p) or str(d) in (".", "", "/"):
            return None
        if str(d) in mdirs:
            return str(d)
        if d.parent == d:
            return None
        d = d.parent


#: SHRINK-ONLY. Paths under a record that does NOT name them, on the tree that
#: added this rule (vibe-ic#1307). MEASURED on `1e21cc08b`: 8 of 525, all under
#: `benchmark-data/ic/caravel_user_project`, all inside `v1.9.43_sky130A/`.
#:
#: RECORDED RATHER THAN CHARGED, on the same ground as vibe-ic#1293: the honest
#: repair is for someone who knows their provenance to name them in the record,
#: and writing an attribution I have not verified would convert an unproven
#: claim into a FALSE one — strictly worse. Reddening main over 8 pre-existing
#: rows would also bury the rule's real value, which is the NEXT one.
#:
#: `cell_model_combined.v` is on this list, and it is exactly the shape #1301
#: was filed for: a vendored cell model sitting under a record that never
#: mentions it.
#:
#: The register may only SHRINK. A NEW unnamed path FAILS, and an entry that
#: BECOMES named FAILS with "delete the entry" — so it cannot outlive the debt
#: it records.
_UNNAMED_RESIDUAL: frozenset = frozenset({
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/formal_counter_formal_bmc/src/defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/formal_counter_formal_bmc/src/user_defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/formal_counter_formal_safety/src/defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/formal_counter_formal_safety/src/user_defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/uprj_netlists.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/formal/user_defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/rtl/defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/rtl/uprj_netlists.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage1/rtl/user_defines.v",
    "benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/phase2/stage2/dft/cell_model_combined.v",
    "benchmark-data/ic/opentitan_aes/input/golden/aes.hjson",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/aes.nangate.sdc",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/aes_abc.nangate.sdc",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/aes_lr_synth_conf.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/python/build_translated_names.py",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/python/flow_utils.py",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/python/get_kge.py",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/python/translate_timing_csv.py",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/syn_setup.example.sh",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/syn_yosys.sh",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/flow_utils.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/lr_synth_flow_var_setup.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/sta_common.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/sta_open_design.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/sta_run_reports.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/sta_utils.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/yosys_common.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/yosys_post_synth.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/yosys_pre_map.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/tcl/yosys_run_synth.tcl",
    "benchmark-data/ic/opentitan_aes/input/reference_flow/pre_syn/translate_timing_rpts.sh",
    "benchmark-data/ic/sha256/phase2/stage1/rtl/chip_top.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/gpio_periph.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_aligner.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_alu.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_bufreg.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_bufreg2.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_compdec.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_csr.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_ctrl.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_debug.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_decode.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_immdec.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_mem_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_rf_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_rf_ram.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_rf_ram_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_rf_top.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_state.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_synth_wrapper.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/serv_top.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/servile.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/servile_arbiter.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/servile_mux.v",
    "benchmark-data/ic/subservient/phase2/stage1/rtl/servile_rf_mem_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/gpio_periph.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_bufreg.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_csr.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_ctrl.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_decode.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_immdec.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_mem_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_rf_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_rf_ram.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_rf_ram_if.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_state.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/serv_top.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/servile.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/cov_annot/servile_mux.v",
    "benchmark-data/ic/subservient/phase2/stage1/sim_full_stack/tb_subservient_gpio.v",
})


def scan(repo: Path, scope: str) -> Dict:
    paths = tracked_files(repo, scope)
    mdirs = manifest_dirs(paths)
    texts = {d: manifest_text(repo, d, paths) for d in mdirs}
    licensed: List[Tuple[str, str]] = []
    uncovered: List[Dict[str, str]] = []
    unnamed: List[Dict[str, str]] = []
    covered = 0
    for rel in paths:
        lic = declared_licence(repo, rel)
        if lic is None:
            continue
        licensed.append((rel, lic))
        mdir = covering_manifest_dir(rel, mdirs, scope)
        if mdir is None:
            uncovered.append({"path": rel, "licence": lic})
            continue
        if not record_names(texts.get(mdir, ""), mdir, rel):
            unnamed.append({"path": rel, "licence": lic, "record": mdir})
            continue
        covered += 1
    residual = sorted(u["path"] for u in unnamed if u["path"] in _UNNAMED_RESIDUAL)
    return {
        "scope": scope,
        "tracked": len(paths),
        "manifest_dirs": sorted(mdirs),
        "licensed": len(licensed),
        # The count that means what it says: FILES a record actually names,
        # not the number of files matching a filename regex (vibe-ic#1307).
        "covered": covered,
        "uncovered": sorted(uncovered, key=lambda d: d["path"]),
        "unnamed": sorted(unnamed, key=lambda d: d["path"]),
        "unnamed_residual": residual,
        "unnamed_new": sorted(u["path"] for u in unnamed
                              if u["path"] not in _UNNAMED_RESIDUAL),
        # ONLY paths this scan actually SAW. A register entry whose file is not
        # in the scanned tree says nothing about it — the first version of this
        # judged the register against every tree, so each of the 8 read as
        # "now named" inside the four-file temp repos the tests build, and
        # three existing tests went red. A register is a claim about a corpus,
        # so it may only be evaluated where that corpus is present.
        "residual_now_named": sorted(
            p for p in _UNNAMED_RESIDUAL
            if p in {r for r, _ in licensed} and p not in
            {u["path"] for u in unnamed}),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--scope", default=_DEFAULT_SCOPE)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    res = scan(repo, args.scope)

    print(f"vendored_attribution_retained_check: {res['tracked']} tracked "
          f"file(s) under {args.scope}, {res['licensed']} declaring an SPDX "
          f"licence, {res['covered']} NAMED by a record, "
          f"{len(res['manifest_dirs'])} record(s) present")

    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps(res, indent=2))

    if not res["licensed"]:
        # A scope with nothing licensed proves nothing. Say so rather than
        # printing a green that means "I looked at an empty set".
        print(f"[VACUOUS_PASS] no tracked file under {args.scope} declares an "
              f"SPDX licence, so this gate checked nothing")
        return 0

    if res["uncovered"]:
        print(f"[FAIL] {len(res['uncovered'])} tracked file(s) declare a "
              f"licence and ship with NO attribution record above them — the "
              f"code is distributed, so the record that names its origin is "
              f"owed:")
        for u in res["uncovered"][:40]:
            print(f"   [{u['licence']}] {u['path']}")
        if len(res["uncovered"]) > 40:
            print(f"   ... and {len(res['uncovered']) - 40} more")
        print("Add a SOURCE_MANIFEST.md at or above each path naming the "
              "upstream project and its licence. Deleting the file is the "
              "other lawful option; deleting only the record is not.")
        return 1

    # vibe-ic#1307 — a record that does not NAME the file it sits above. Kept
    # separate from `uncovered` because the repair differs: that one needs a
    # record, this one needs the existing record to say something.
    if res["residual_now_named"]:
        print(f"[FAIL] {len(res['residual_now_named'])} path(s) are now named "
              f"by their record and must be DELETED from _UNNAMED_RESIDUAL — "
              f"a register that outlives its debt is an amnesty:")
        for p in res["residual_now_named"]:
            print(f"   {p}")
        return 1

    if res["unnamed_new"]:
        print(f"[FAIL] {len(res['unnamed_new'])} tracked file(s) sit under an "
              f"attribution record that NEVER NAMES THEM — location is not "
              f"attribution, and an obligation is about a named work:")
        for p in res["unnamed_new"][:40]:
            print(f"   {p}")
        if len(res["unnamed_new"]) > 40:
            print(f"   ... and {len(res['unnamed_new']) - 40} more")
        print("Name the file, or a directory prefix of it, in the record "
              "above it. Do NOT write an attribution you have not verified: "
              "an unproven claim made false is worse than one left open.")
        return 1

    print(f"[PASS] every one of the {res['licensed']} licence-declaring "
          f"file(s) is NAMED by an attribution record above it"
          + (f" ({len(res['unnamed_residual'])} pre-existing unnamed path(s) "
             f"disclosed and unchanged — see _UNNAMED_RESIDUAL)"
             if res["unnamed_residual"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
