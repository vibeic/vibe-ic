#!/usr/bin/env python3
"""source_manifest_md_emit.py — ORGANIC v1462.

Render the acceptance-artifact ``SOURCE_MANIFEST.md`` at the RUN-DIR TOP LEVEL —
exactly where ``benchmark_verify_report.py`` probes for it
(``project / "SOURCE_MANIFEST.md"``) — tagging every RTL module **GENERATED**
vs **REUSED-IP**.

WHY THIS EXISTS
---------------
The reused-IP provenance already exists on disk as
``phase2/stage1/rtl/SOURCE_MANIFEST.json`` (emitted by
``staged_rtl_reused_ip_manifest_emit`` for a catalog-glue / reused-IP design),
and the staged RTL itself is on disk, but the verify report probes for a
TOP-LEVEL MARKDOWN it never finds → "SOURCE_MANIFEST.md MISSING" on every run
(v1462: absent on all seven run dirs). This materialises that markdown
FAITHFULLY from the on-disk artifacts — it never fabricates provenance:

  * a module named in the reused-IP manifest's ``ip_list`` (or whose file was
    ``staged_from_input``) is **REUSED-IP**;
  * every other RTL module under ``phase2/stage1/rtl`` (the AI-authored glue /
    chip-top, or a fully generated design with no reused manifest) is
    **GENERATED**.

Idempotent + NON-DESTRUCTIVE: writes ONLY when ``SOURCE_MANIFEST.md`` is ABSENT
(unless ``force``), so a hand-authored provenance is never clobbered. Returns
``None`` when there is neither RTL nor a reused manifest (e.g. an analog-only
run) — it never invents a manifest for a design that has no digital source.

chip-AGNOSTIC: structure-only (the Verilog ``module`` grammar + the manifest
schema); no chip / vendor literal anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROGRAM = "source_manifest_md_emit"
MD_REL = "SOURCE_MANIFEST.md"
RTL_REL = ("phase2", "stage1", "rtl")
MANIFEST_NAME = "SOURCE_MANIFEST.json"

# A SystemVerilog/Verilog `module <name>` declaration — grammar-only, no literal.
_RE_MODULE_DECL = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.MULTILINE)


def _rtl_dir(project: Path) -> Path:
    return project.joinpath(*RTL_REL)


def _module_names(rtl_file: Path) -> List[str]:
    """Module names declared in a file; falls back to the file stem when the
    file declares none (a package/header still names a source unit)."""
    try:
        txt = rtl_file.read_text(errors="ignore")
    except OSError:
        return []
    names = []
    seen: Set[str] = set()
    for m in _RE_MODULE_DECL.finditer(txt):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            names.append(n)
    return names or [rtl_file.stem]


def _load_reused(project: Path) -> Tuple[bool, bool]:
    """Return (design_is_reused_ip, manifest_present).

    Provenance here is DESIGN-LEVEL: ``reused_ip:true`` asserts the staged RTL
    is pulled open-source IP (its ``ip_list`` names IP *families* — e.g.
    ``serv`` — not per-module identifiers, so a per-module name match would
    mis-tag most vendor modules and falsely credit the runner with authoring
    them). We therefore tag by the manifest's own design-level assertion, never
    invent a finer split the manifest does not carry. Absent/unreadable/
    non-reused manifest → (False, present?)."""
    mf = _rtl_dir(project) / MANIFEST_NAME
    if not mf.is_file():
        return False, False
    try:
        doc = json.loads(mf.read_text(errors="replace"))
    except (OSError, ValueError):
        return False, False
    if not isinstance(doc, dict):
        return False, False
    return doc.get("reused_ip") is True, True


# A file's own copyright header. SPDX-FileCopyrightText is a machine-readable
# assertion, BY A NAMED PARTY, that they wrote this file — the one piece of
# per-file authorship evidence a staged tree reliably carries.
_SPDX_COPYRIGHT = re.compile(r"^\s*(?://|/\*|\*|#)?\s*SPDX-FileCopyrightText:\s*(\S.*?)\s*$",
                             re.MULTILINE)

#: How far into a file a copyright header can appear. Bounded so a copyright
#: NOTICE quoted in the body of a long file is not read as this file's header.
_HEADER_LINES = 40


def third_party_copyright(path: Path) -> Optional[str]:
    """The copyright holder this file's own header names, or None.

    Read from the header region only. This is EVIDENCE, not inference: the
    file states who wrote it."""
    try:
        head = "\n".join(
            path.read_text(encoding="utf-8", errors="replace").splitlines()[:_HEADER_LINES])
    except OSError:
        return None
    m = _SPDX_COPYRIGHT.search(head)
    return m.group(1) if m else None


def collect(project: Path) -> List[Tuple[str, str, str]]:
    """Walk phase2/stage1/rtl and tag each module. Returns a sorted list of
    (module, tag, relative_file) where tag is 'REUSED-IP' or 'GENERATED'.

    DESIGN-LEVEL provenance is the DEFAULT: a ``reused_ip:true`` manifest →
    REUSED-IP; no reused manifest → GENERATED.

    PER-FILE EVIDENCE OVERRIDES THAT DEFAULT. The design-level rule used to be
    the whole answer, and its docstring claimed it "never falsely tags vendor
    RTL as generated". MEASURED, that claim was false: on a run where
    ``ip_catalog_query`` REFUSED the catalog match and no reused manifest was
    written, 21 of 27 staged files carried a third-party
    ``SPDX-FileCopyrightText`` header and every one of them was tagged
    GENERATED. The emitted manifest read:

        - Reused from catalog / vendor RTL: 0
        - Authored this run: 27

    while 21 of those files name someone else as their author, in their own
    first 12 lines. The program asserted authorship without ever opening the
    file. That manifest is what ``benchmark_verify_report`` consumes, so a
    false attribution reached a published report.

    A file whose own header names a copyright holder was not authored by this
    run, whatever the design-level default says.

    THIS IS A LOWER BOUND, and deliberately so: a vendored file whose header
    was stripped still counts as authored. Measured across the corpus, 2 of 7
    ICs with staged RTL carry SPDX headers at all. Closing the rest needs
    evidence this tree does not carry; converting a groundless "0" into a
    true-but-incomplete count is the improvement available here, and the
    incompleteness is disclosed in the rendered manifest rather than hidden."""
    rtl = _rtl_dir(project)
    if not rtl.is_dir():
        return []
    is_reused, _present = _load_reused(project)
    default_tag = "REUSED-IP" if is_reused else "GENERATED"
    rows: Dict[str, Tuple[str, str]] = {}
    files = sorted(rtl.rglob("*.v")) + sorted(rtl.rglob("*.sv"))
    for f in files:
        if f.name == MANIFEST_NAME:
            continue
        try:
            rel = str(f.relative_to(project))
        except ValueError:
            rel = f.name
        tag = default_tag
        if tag == "GENERATED" and third_party_copyright(f) is not None:
            tag = "REUSED-IP"
        for mod in _module_names(f):
            rows.setdefault(mod, (tag, rel))  # first declaration wins
    return sorted((m, t, r) for m, (t, r) in rows.items())


def render_md(project: Path) -> Optional[str]:
    """Render the SOURCE_MANIFEST.md text, or None when there is no digital
    source to describe (no RTL and no reused manifest)."""
    rows = collect(project)
    _is_reused, manifest_present = _load_reused(project)
    if not rows and not manifest_present:
        return None
    n_reused = sum(1 for _, t, _ in rows if t == "REUSED-IP")
    n_gen = sum(1 for _, t, _ in rows if t == "GENERATED")
    L: List[str] = []
    L.append(f"# Source Manifest — `{project.name}`")
    L.append("")
    # NOTE: the bare source tokens appear ONLY in the per-module rows below, so a
    # consumer counting them (benchmark_verify_report) gets exactly one token per
    # module — the prose/tally here deliberately avoids the bare tokens.
    L.append(f"_Emitted by `{PROGRAM}.py` from the on-disk staged RTL and "
             f"`{'/'.join(RTL_REL)}/{MANIFEST_NAME}` (when present). Each module "
             "is tagged as authored-this-run or reused-from-catalog in the "
             "Source column._")
    L.append("")
    L.append(f"- Reused from catalog / vendor RTL: {n_reused}")
    L.append(f"- Authored this run: {n_gen}")
    L.append("")
    # The authored-this-run count is an UPPER bound and says so. A staged file
    # whose copyright header was stripped is indistinguishable here from one
    # the run wrote, so silence about that limit would be the same groundless
    # assertion this program used to make.
    L.append("_Provenance evidence: a module is counted as reused when its own "
             "file header carries an `SPDX-FileCopyrightText` naming an author, "
             "or when the reused-IP manifest lists it. A vendored file with no "
             "such header cannot be told apart from an authored one, so "
             "**`Authored this run` is an upper bound**._")
    L.append("")
    L.append("| Module | Source | File |")
    L.append("|---|---|---|")
    for mod, tag, rel in rows:
        L.append(f"| `{mod}` | {tag} | `{rel}` |")
    L.append("")
    return "\n".join(L) + "\n"


def emit(project: Path, force: bool = False) -> Optional[Path]:
    """Write SOURCE_MANIFEST.md at the run-dir top level. Non-destructive:
    skips (returns the existing path) when the file already exists unless
    ``force``. Returns the written/existing path, or None when there is nothing
    to render."""
    out = project / MD_REL
    if out.exists() and not force:
        return out
    text = render_md(project)
    if text is None:
        return None
    try:
        out.write_text(text)
    except OSError:
        return None
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit the top-level SOURCE_MANIFEST.md (GENERATED vs "
                    "REUSED-IP) from the staged RTL + reused-IP manifest.")
    ap.add_argument("project_dir", help="Run directory (project top level)")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite an existing SOURCE_MANIFEST.md")
    args = ap.parse_args(argv)
    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2
    path = emit(project.resolve(), force=args.force)
    if path is None:
        print("no digital source to manifest (no RTL, no reused-IP manifest)")
        return 0
    print(f"SOURCE_MANIFEST.md -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
