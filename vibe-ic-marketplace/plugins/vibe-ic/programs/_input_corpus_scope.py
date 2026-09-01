#!/usr/bin/env python3
"""_input_corpus_scope.py — decide which subtrees are DESIGN INPUT and which
are collateral, so Phase-1 never ingests tool or process-kit documentation as
if it were the user's specification.

WHY THIS EXISTS
===============
Phase-1's raw-corpus ingester has a bounded ``rglob("README*")`` fallback
(``rglob_readme_fallback_v1_6_343``) that fires when a project ships no central
``doc/`` tree. It exists for a real and common layout: HDL repos that document
by feature sub-folder (``rtl/README.md``, ``sim/README.md``).

That fallback already excludes the runner's own OUTPUT (``phase1/``,
``phase2/``, ``phase3/``, ``reports/``) and the usual vendored noise
(``node_modules``, ``build``, ``.git``). Nothing excluded the runner's own
SOURCE — the plugin checkout itself. When the plugin is checked out INSIDE the
run root (a normal deployment: the run root holds ``input/`` and a
``plugin_work/`` checkout side by side), the fallback walks the plugin's own
tree and ingests the TOOL's documentation as the DESIGN's specification.

MEASURED HARM (not hypothetical)
--------------------------------
A run whose entire input was ONE 1,493-byte natural-language request ingested
**10** documents: the request plus **9 plugin READMEs**, which supplied 51,198
of 52,691 corpus bytes — **97.2 % of the input corpus was the tool describing
itself**. The resulting L1 datasheet described the tooling:

  * ``pin_table``   → a single pin named ``Verb``, lifted from a documentation
                      table of *verbs* in the ingester's own engine README;
  * ``vendor``      → a GitHub org name scraped from the plugin README;
  * ``process_node``→ a node named in the plugin README, contradicting the
                      PDK the run was actually driven with;
  * ``description`` → the plugin question-bank README's own summary sentence.

and — the load-bearing consequence — ``ic_class`` was decided from that text.
The crypto-accelerator detector requires a cipher-family token; it matched the
literal ``SHA`` occurring in the plugin README's **artifact-attestation**
section (SHA-256 hashing of build outputs, not a cipher the chip implements).
The design was classified ``crypto_accelerator``, whose registry entry declares
``rtl_gen=null``, so RTL generation was WAIVED, so there was no RTL, so the
reference testbench and synthesis both FAILed and Phase-2 halted — five steps
downstream of an ingester reading its own manual.

Coverage reported **100 %** throughout, because the coverage model measures
"was everything in the corpus extracted", not "was the corpus the design".

THE RULE
========
A subtree is TOOLING, and therefore never DESIGN INPUT, when it is
self-describing as tooling by STRUCTURE — never by name. Two markers:

  ``plugin_manifest``   the subtree root contains ``.claude-plugin/plugin.json``
                        — the manifest that *defines* a Claude-Code plugin
                        checkout. This is the canonical marker.
  ``program_flow_skill``the subtree root contains all three of ``programs/``,
                        ``flow/`` and ``skills/`` — the plugin's structural
                        triple, for a checkout vendored without its manifest.

Both are name-independent: they hold whether the checkout is called
``plugin_work``, ``vibe-ic``, ``.claude/plugins/<x>`` or anything else, and
neither fires on an HDL design repo, which has no reason to carry a Claude
plugin manifest or that exact directory triple.

A project-staged PDK is a second, already-declared non-design population.  The
flow's staged-PDK readers and gates define it as ``input/pdk*``.  Those readers
may inspect its enablement files and labelled process declaration, but the
generic design-document README fallback must not ingest the PDK's own manuals.
The boundary is the flow-owned path declaration, never a PDK/vendor name or a
guess from README text.

chip-AGNOSTIC: filesystem structure only. No design, PDK, vendor, cell or pin
literal appears in this module or in any decision it makes.

DEGRADE LOUDLY (flow-change-acceptance §6)
==========================================
Excluding input is itself an action with consequences, so it is never silent.
:func:`scope_record` returns a named, machine-readable record naming every
excluded root, the marker that identified it, and every file skipped because of
it. Callers persist it (``phase1/input_corpus_scope.json``). An empty
``excluded`` list is an explicit statement that nothing was excluded — it is
distinguishable from the check never having run, which carries
``"status": "NOT_RUN"``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

#: Marker (a): the file that DEFINES a Claude-Code plugin checkout.
PLUGIN_MANIFEST_REL = os.path.join(".claude-plugin", "plugin.json")

#: Marker (b): the plugin's structural triple, for a checkout vendored without
#: its manifest. ALL three must be present — any two of them occur innocently.
STRUCTURAL_TRIPLE: Sequence[str] = ("programs", "flow", "skills")

#: Canonical project-staged PDK boundary.  Kept byte-for-byte aligned with the
#: ``input/pdk*/**/*`` declaration in ``phase1_doc_one_shot_runner``.
STAGED_PDK_PARENT = "input"
STAGED_PDK_PREFIX = "pdk"

#: How deep below the project root to look for a tooling checkout. A plugin is
#: vendored at the top (``plugin_work/``) or one level in (``vendor/vibe-ic/``);
#: beyond that we stop rather than walk an arbitrarily large tree.
DEFAULT_MAX_DEPTH = 3

#: Never descend into these while HUNTING for tooling roots.
_PRUNE = {".git", "node_modules", "__pycache__", ".venv", "venv", "build",
          "dist", ".tox", ".mypy_cache", ".pytest_cache"}


def is_tooling_dir(d: Path) -> Optional[str]:
    """Return the marker name if ``d`` is the root of a tooling checkout, else None.

    Pure structure. Never consults the directory's NAME.
    """
    try:
        if (d / PLUGIN_MANIFEST_REL).is_file():
            return "plugin_manifest"
        if all((d / sub).is_dir() for sub in STRUCTURAL_TRIPLE):
            return "program_flow_skill"
    except OSError:
        return None
    return None


def find_tooling_roots(project: Path,
                       max_depth: int = DEFAULT_MAX_DEPTH) -> List[Dict[str, str]]:
    """Find tooling checkouts under ``project``.

    Returns a list of ``{"path": <relative posix>, "marker": <marker name>}``,
    sorted, one entry per root. Does not descend INTO a root once found — the
    whole subtree is excluded, so there is nothing further to discover there.

    ``project`` itself is deliberately NOT tested: when a user runs the flow
    from inside the plugin checkout, the plugin IS the project and excluding
    everything would be worse than the contamination.
    """
    project = Path(project)
    roots: List[Dict[str, str]] = []
    try:
        project_abs = project.resolve()
    except OSError:
        return roots

    for dirpath, dirnames, _files in os.walk(project_abs):
        here = Path(dirpath)
        try:
            rel_depth = len(here.relative_to(project_abs).parts)
        except ValueError:
            dirnames[:] = []
            continue
        if rel_depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(n for n in dirnames if n not in _PRUNE)
        for name in list(dirnames):
            cand = here / name
            marker = is_tooling_dir(cand)
            if marker:
                roots.append({
                    "path": cand.relative_to(project_abs).as_posix(),
                    "marker": marker,
                })
                # The entire subtree is out of scope — stop descending.
                dirnames.remove(name)
    roots.sort(key=lambda r: r["path"])
    return roots


def containing_root(path: Path,
                    project: Path,
                    roots: Iterable[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Return the tooling root that contains ``path``, or None.

    Comparison is on RESOLVED paths so a symlinked checkout cannot slip past.
    """
    try:
        target = Path(path).resolve()
        project_abs = Path(project).resolve()
    except OSError:
        return None
    for root in roots:
        try:
            root_abs = (project_abs / root["path"]).resolve()
        except OSError:
            continue
        if target == root_abs or root_abs in target.parents:
            return root
    return None


def path_is_tooling(rel_or_abs: str,
                    roots: Iterable[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Textual variant of :func:`containing_root` for provenance STRINGS.

    L-doc evidence records a project-relative provenance path, sometimes behind
    an ingester key prefix, and the file it names may no longer exist. This
    matches on path SEGMENTS (never a substring), so a root ``plugin_work``
    matches ``a/plugin_work/README.md`` but never ``my_plugin_workbench/x.md``.
    """
    text = str(rel_or_abs).replace("\\", "/")
    # Strip a leading ingester key prefix such as `__chip_root_docs__/`.
    segments = [s for s in text.split("/") if s and s != "."]
    for root in roots:
        root_parts = [s for s in str(root["path"]).split("/") if s]
        if not root_parts:
            continue
        n = len(root_parts)
        for i in range(len(segments) - n + 1):
            if segments[i:i + n] == root_parts:
                return root
    return None


def staged_pdk_root(rel_or_abs: str) -> Optional[str]:
    """Return the containing canonical ``input/pdk*`` root, or ``None``.

    Matching is by path segments and the flow's own staged-input convention.
    A design directory such as ``rtl/pdk_notes`` is therefore untouched.
    """
    text = str(rel_or_abs).replace("\\", "/")
    segments = [s for s in text.split("/") if s and s != "."]
    if (len(segments) >= 2
            and segments[0] == STAGED_PDK_PARENT
            and segments[1].startswith(STAGED_PDK_PREFIX)):
        return "/".join(segments[:2])
    return None


def scope_record(project: Path,
                 roots: Sequence[Dict[str, str]],
                 excluded_files: Sequence[str],
                 status: str = "RAN",
                 excluded_staged_pdk_files: Sequence[str] = (),
                 ) -> Dict[str, object]:
    """Build the named, persistable record of what was excluded and why.

    ``status`` distinguishes ``RAN`` (the scope rule was applied; an empty
    ``excluded_roots`` then positively means "no tooling subtree present")
    from ``NOT_RUN`` (never applied) — "empty" and "clean" are never conflated.
    """
    staged_files = sorted(str(f) for f in excluded_staged_pdk_files)
    staged_roots = sorted({
        root for root in (staged_pdk_root(f) for f in staged_files) if root
    })
    return {
        "_schema_version": "1",
        "_comment": (
            "Subtrees excluded from the Phase-1 design-document corpus because "
            "they are TOOLING or project-staged PDK collateral. Tooling is "
            "identified by structure; staged PDK collateral by the flow's "
            "canonical input/pdk* boundary. status=RAN with empty exclusion "
            "lists positively means neither population was found."),
        "status": status,
        "project": Path(project).name,
        "rule": "programs/_input_corpus_scope.py",
        "markers": {
            "plugin_manifest": PLUGIN_MANIFEST_REL,
            "program_flow_skill": list(STRUCTURAL_TRIPLE),
            "staged_pdk_input_root": "input/pdk*",
        },
        "excluded_roots": list(roots),
        "excluded_files": sorted(str(f) for f in excluded_files),
        "excluded_file_count": len(excluded_files),
        "excluded_staged_pdk_roots": staged_roots,
        "excluded_staged_pdk_files": staged_files,
        "excluded_staged_pdk_file_count": len(staged_files),
    }
