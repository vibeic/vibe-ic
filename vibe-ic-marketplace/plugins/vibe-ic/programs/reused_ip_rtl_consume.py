#!/usr/bin/env python3
"""Deterministic reused-IP RTL CONSUME step.

Floor G-CATALOG-GLUE — a reused-IP / catalog-glue design that WAIVES rtl_gen
(``fallback_skill=catalog-glue-author``) left ``phase2/stage1/rtl/`` EMPTY, so a
runner-only (hands-off) run reached ``yosys synth -top chip_top`` → "Module
chip_top not found" → HALT at phase2. The backend was never reached because the
design's OWN provided implementation RTL was never staged.

This module closes that gap: when the design's INPUT itself PROVIDES the intended
build RTL, DETERMINISTICALLY stage those files into ``phase2/stage1/rtl/`` so the
existing chip_top auto-emit + instantiation-graph-root fallback
(``design_one_shot_runner``) can find a synthesizable top. The RESIDUAL glue that
genuinely needs an LLM (complex tie-offs, register-map wiring from a spec) STILL
WAIVES to ``catalog-glue-author`` — but the runner no longer HALTS with an empty
rtl/ when the design ships its own RTL.

§4.05 NO-LEAK (load-bearing):
  * Reads ONLY the design's legitimate INPUT build-source locations
    (``input/vendor_rtl/``, ``input/design_src/**/rtl/``, or a
    ``SOURCE_MANIFEST``-declared build-source dir CONFINED under ``input/``).
    NEVER reads ``output/`` (golden), a testbench, a gate-level (``gl/``)
    netlist, a reference-flow reference, or any benchmark scoring answer.
  * Stages ONLY when ``phase2/stage1/rtl/`` is EMPTY of RTL (never clobbers a
    deterministic-generator / author's RTL) AND the design actually provides its
    own build RTL. A design that ships NO build RTL gets NO staging (empty
    result) → the WAIVE-to-``catalog-glue-author`` behaviour is byte-for-byte
    unchanged, and no spurious ``reused_ip:true`` manifest is ever written.

G-SV-INGEST (separate floor) — SystemVerilog is staged, NOT silently dropped:
  the synth path's slang/sv2v pre-pass lowers ``.sv`` in-container; when that is
  unavailable a LOUD ``sv_ingest_note`` is emitted so the SV-ingest requirement
  is explicit.

chip-AGNOSTIC: pure structural file discovery + Verilog ``module`` grammar; no
chip / vendor / SKU literal anywhere.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

# Directory names whose contents are simulation / verification harnesses OR
# synthesis OUTPUT — NEVER a design's build SOURCE. §4.05 oracle guard: a file
# reached THROUGH any of these path segments is skipped.
_ORACLE_DIR_NAMES = frozenset({
    "tb", "test", "tests", "sim", "sims", "dv", "verif", "verification",
    "formal", "bench", "testbench", "testbenches", "gl", "gate", "gates",
    "netlist", "netlists", "golden", "ref", "reference", "sol", "solution",
    "solutions", "output", "outputs", "answer", "answers", "scoring",
})

# A file STEM that is a testbench / tester rather than build RTL. §4.05: never
# stage a TB as a build source.
_TB_STEM_RE = re.compile(
    r"(^tb[_.]|_tb$|_tb_|^test[_.]|_test$|_tests$|^test$|_tester$|_bench$|"
    r"_testbench$)", re.IGNORECASE)

# A SystemVerilog / Verilog ``module <name>`` declaration. Structure-only.
_RE_MODULE_DECL = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.MULTILINE)

# Build-source extensions we stage. Headers (.vh/.svh) ride along so `include`s
# resolve; they carry no module and are harmless to the synth frontend.
_RTL_EXTS = (".v", ".sv")
_HDR_EXTS = (".vh", ".svh")

_MANIFEST_NAME = "SOURCE_MANIFEST.json"


def _is_oracle_parts(parts) -> bool:
    """True if any path segment names an oracle / harness / output dir."""
    return any(str(p).lower() in _ORACLE_DIR_NAMES for p in parts)


def _is_tb_file(path: Path) -> bool:
    return bool(_TB_STEM_RE.search(path.stem))


def _manifest_declared_source_dirs(mf_path: Path, project: Path) -> List[Path]:
    """Build-source dirs a SOURCE_MANIFEST declares, CONFINED under input/.

    Honors keys ``build_rtl_dirs`` / ``rtl_source_dirs`` / ``build_source`` /
    ``build_sources`` (str or list). §4.05: a declared path is accepted ONLY
    when it resolves to a directory that stays UNDER ``project/input`` and does
    not traverse an oracle segment — a manifest can never point the consumer at
    ``output/`` / a golden tree / an absolute path outside the sandbox."""
    if not mf_path.is_file():
        return []
    try:
        mf = json.loads(mf_path.read_text(errors="replace"))
    except Exception:
        return []
    if not isinstance(mf, dict):
        return []
    raw: List[str] = []
    for key in ("build_rtl_dirs", "rtl_source_dirs",
                "build_source", "build_sources"):
        v = mf.get(key)
        if isinstance(v, str) and v.strip():
            raw.append(v.strip())
        elif isinstance(v, list):
            raw.extend(str(x).strip() for x in v if str(x).strip())
    input_root = (project / "input").resolve()
    out: List[Path] = []
    for rel in raw:
        cand = (project / rel) if not Path(rel).is_absolute() else Path(rel)
        try:
            rp = cand.resolve()
        except Exception:
            continue
        # must stay strictly under project/input and not traverse an oracle seg
        if input_root != rp and input_root not in rp.parents:
            continue
        try:
            inside = rp.relative_to(input_root)
        except Exception:
            continue
        if _is_oracle_parts(inside.parts):
            continue
        if rp.is_dir():
            out.append(cand)
    return out


def candidate_source_dirs(project: Path) -> List[Path]:
    """Legitimate INPUT build-source roots, in deterministic priority order.

    (1) ``input/vendor_rtl/``                 — pre-staged reusable IP,
    (2) every ``rtl/``-named dir under ``input/design_src/`` that does not sit
        under an oracle/harness segment  — the design's shipped implementation,
    (3) ``SOURCE_MANIFEST``-declared build-source dirs (confined under input/).

    §4.05: everything is confined UNDER ``project/input``; nothing else is ever
    a source. De-duplicated by resolved path, priority-order preserved."""
    input_root = project / "input"
    dirs: List[Path] = []

    vd = input_root / "vendor_rtl"
    if vd.is_dir():
        dirs.append(vd)

    # `input/rtl/` — the OBVIOUS place to drop existing RTL (2026-08-25).
    # Before this, a design shipping its implementation had to know to name the
    # directory `vendor_rtl/` or to bury it at `design_src/<x>/rtl/`; a plain
    # `input/rtl/` was silently NOT a source, and the runner reported "design
    # ships NO build RTL under input/" while the files sat right there.
    #
    # Measured 2026-08-25 across the four task natures that operate ON existing
    # RTL — completion, functional-modification, optimization, debug — the
    # supplied RTL was ignored for every one of them, so each ran as if it had
    # to invent the design from prose. Those natures are defined by having the
    # RTL; losing it is not a degraded run, it is the wrong task.
    #
    # Still confined under `input/` (§4.05: nothing outside input/ is ever a
    # source), and still subject to the same oracle/harness segment screen.
    rd = input_root / "rtl"
    if rd.is_dir() and not _is_oracle_parts(("rtl",)):
        dirs.append(rd)

    ds = input_root / "design_src"
    if ds.is_dir():
        for rtl in sorted(ds.rglob("rtl")):
            if not rtl.is_dir():
                continue
            try:
                rel = rtl.relative_to(input_root)
            except Exception:
                continue
            # skip an rtl/ dir nested under a tb/ sim/ gl/ … segment
            if _is_oracle_parts(rel.parts[:-1]):
                continue
            dirs.append(rtl)

    for mf_path in (project / "phase2" / "stage1" / "rtl" / _MANIFEST_NAME,
                    input_root / _MANIFEST_NAME):
        dirs.extend(_manifest_declared_source_dirs(mf_path, project))

    seen = set()
    out: List[Path] = []
    for d in dirs:
        try:
            rp = d.resolve()
        except Exception:
            continue
        if rp in seen or not d.is_dir():
            continue
        seen.add(rp)
        out.append(d)
    return out


def discover_provided_build_rtl(project: Path) -> List[Path]:
    """Every provided build-RTL file (.v/.sv/.vh/.svh) under the legitimate
    INPUT build-source roots, excluding oracle sub-paths and testbench files.

    §4.05 NO-LEAK: reads only ``candidate_source_dirs`` (all under input/); skips
    any file reached through an oracle/harness segment (``gl/``, ``tb/`` …) and
    any TB-stem file. Deterministic order; de-duplicated by resolved path."""
    files: List[Path] = []
    seen = set()
    for src_dir in candidate_source_dirs(project):
        matched: List[Path] = []
        for ext in _RTL_EXTS + _HDR_EXTS:
            matched.extend(src_dir.rglob(f"*{ext}"))
        for f in sorted(matched):
            if not f.is_file():
                continue
            try:
                rel = f.relative_to(src_dir)
            except Exception:
                continue
            if _is_oracle_parts(rel.parts[:-1]):
                continue
            if _is_tb_file(f):
                continue
            try:
                rp = f.resolve()
            except Exception:
                continue
            if rp in seen:
                continue
            seen.add(rp)
            files.append(f)
    return files


def _derive_ip_list(staged_paths: List[Path]) -> List[str]:
    """Structural ip_list = the ``module <name>`` declarations across the staged
    files (falls back to file stems). chip-AGNOSTIC."""
    modules: set = set()
    stems: set = set()
    for f in staged_paths:
        stems.add(f.stem)
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in _RE_MODULE_DECL.finditer(txt):
            modules.add(m.group(1))
    return sorted(modules) if modules else sorted(stems)


def emit_consume_manifest(project: Path, staged_paths: List[Path],
                          provenance: List[str]) -> Optional[Path]:
    """Emit / merge the keystone ``phase2/stage1/rtl/SOURCE_MANIFEST.json`` for
    the design-ships-its-own-RTL consume path.

    MERGE-preserving (mirrors ``staged_rtl_reused_ip_manifest_emit`` /
    ``ip_catalog_pull``): a hand-authored ``flattened_buses`` / ``tie_offs`` /
    ``renamed_interfaces`` / ``ip_list`` / ``generated_by`` block survives
    untouched — only the keystone keys are (re)asserted. Records
    ``build_rtl_provided:true`` + a ``staged_from_input`` provenance list."""
    if not staged_paths:
        return None
    mf_path = project / "phase2" / "stage1" / "rtl" / _MANIFEST_NAME
    mf_path.parent.mkdir(parents=True, exist_ok=True)
    if mf_path.is_file():
        try:
            mf = json.loads(mf_path.read_text())
            if not isinstance(mf, dict):
                mf = {}
        except Exception:
            mf = {}
    else:
        mf = {}
    mf["reused_ip"] = True
    mf["build_rtl_provided"] = True
    ip_list = _derive_ip_list(staged_paths)
    if ip_list and (not isinstance(mf.get("ip_list"), list)
                    or not mf.get("ip_list")):
        mf["ip_list"] = ip_list
    mf.setdefault("rtl_strategy", "design_provided_rtl_plus_ai_glue")
    mf.setdefault("generated_by", "phase2_runner_consume")
    # provenance — WHERE each staged file came from (input-relative)
    prov = mf.get("staged_from_input")
    if not isinstance(prov, list) or not prov:
        mf["staged_from_input"] = sorted(provenance)
    # EMPTY reconciliation scaffold (GAP-E2E-8 parity) — an empty scaffold
    # reconciles ZERO ports, so l9_rtl_pin_consistency_check's verdict is
    # byte-for-byte unchanged until a real pairing is authored.
    mf.setdefault("renamed_interfaces", [])
    mf.setdefault("flattened_buses", [])
    mf.setdefault(
        "_reconciliation_scaffold_note",
        "EMPTY scaffold. If the provided RTL's interface differs from the L9 "
        "doc abstraction, author renamed_interfaces / flattened_buses entries "
        "per catalog-glue-author/SKILL.md; an empty scaffold reconciles nothing "
        "so l9_rtl_pin_consistency_check still reports the exact ports to pair.")
    mf_path.write_text(json.dumps(mf, indent=2))
    return mf_path


def _unresolved_module_refs(files: List[Path]) -> List[str]:
    """Modules INSTANTIATED by ``files`` that ``files`` do not DEFINE.

    Empty means the set is closed — it is a design, and staging anything
    around it would be clobbering someone's work. Non-empty means the set
    names something it does not contain, which is what a glue wrapper is.

    Fail-safe: any problem reading or analysing returns ``[]``, i.e. the
    historical directory-level skip. A defect in this analysis must never be
    able to stage over an author's tree.
    """
    try:
        import staged_rtl_closure_preflight as _pf
    except Exception:  # noqa: BLE001
        return []
    try:
        report = _pf.audit([str(f) for f in files])
    except Exception:  # noqa: BLE001
        return []
    if report.get("verdict") == "ERROR":
        return []
    return sorted({str(f.get("module_ref")) for f in report.get("findings", [])
                   if f.get("module_ref")})


def consume_reused_ip_rtl(project: Path) -> Dict:
    """DETERMINISTIC reused-IP CONSUME: stage the design's provided build RTL
    into ``phase2/stage1/rtl/`` so synth can find a top.

    Returns a summary dict::

        {"reused_ip": bool, "staged": [names], "sv_files": [names],
         "vh_files": [names], "sv2v_available": bool, "sv_ingest_note": str|None,
         "manifest_emitted": rel-path|None, "reason": str}

    Fires ONLY when ``phase2/stage1/rtl/`` is EMPTY of RTL (never clobbers a
    generator/author) AND the design provides its own build RTL under input/.
    A design that ships NO build RTL returns ``reused_ip=False`` with an empty
    ``staged`` — the WAIVE-to-catalog-glue-author path is unchanged."""
    result: Dict = {
        "reused_ip": False, "staged": [], "sv_files": [], "vh_files": [],
        "sv2v_available": False, "sv_ingest_note": None,
        "manifest_emitted": None, "reason": "",
    }
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    # Never clobber generator/author RTL: only stage into an rtl/ with no RTL.
    existing: List[Path] = []
    if rtl_dir.is_dir():
        for p in rtl_dir.rglob("*"):
            if (p.is_file() and p.suffix in _RTL_EXTS
                    and p.name != _MANIFEST_NAME):
                existing.append(p)
    if existing:
        # A DIRECTORY-LEVEL SKIP CANNOT ANSWER A CLOSURE-LEVEL QUESTION.
        #
        # "rtl/ is non-empty" was read as "a generator or author owns the
        # design", and for a generator that is true. For CATALOG-GLUE it is
        # the opposite: `step_rtl_gen` WAIVES with `fallback_skill=
        # catalog-glue-author`, whose whole job is to author a WRAPPER around
        # reused IP — and the IP it wraps is staged by THIS step, next. An
        # author who obeys that waive literally writes one file here, and the
        # act of obeying it disarms the staging the wrapper depends on: the
        # vendor closure is never staged and synth fails on a module nobody
        # can find. The two halves of the flow already disagreed —
        # `_autoemit_chip_top_wrapper` defers at the WRAPPER level ("caller
        # already provided one") while this deferred at the DIRECTORY level —
        # and only the directory-level one was load-bearing.
        #
        # The right question is not "is rtl/ empty" but "does rtl/ hold a
        # DESIGN": a set of files whose instantiations all resolve inside it.
        # A glue wrapper does not; it is a file that names what is missing.
        # chip-AGNOSTIC — pure SV instantiation closure, no IP or vendor name.
        #
        # Existing files are still never clobbered: the staging loop below is
        # first-wins on a name collision, so an author's wrapper survives
        # verbatim and only the modules it REFERENCES arrive around it.
        unresolved = _unresolved_module_refs(existing)
        if not unresolved:
            result["reason"] = (
                f"phase2/stage1/rtl/ already holds {len(existing)} RTL file(s) "
                f"— a deterministic generator / author owns it; CONSUME "
                f"skipped")
            return result
        result["pre_existing_rtl"] = sorted(f.name for f in existing)
        result["unresolved_module_refs"] = unresolved
        result["consume_reason_override"] = (
            f"phase2/stage1/rtl/ holds {len(existing)} file(s) but is NOT "
            f"closed: {len(unresolved)} instantiated module(s) are defined "
            f"nowhere in it ({', '.join(unresolved[:8])}). That is a GLUE "
            f"wrapper, not a design — staging the reused IP it instantiates, "
            f"first-wins so nothing already present is overwritten.")

    provided = discover_provided_build_rtl(project)
    if not provided:
        result["reason"] = (
            "design ships NO build RTL under input/ "
            "(vendor_rtl / design_src/**/rtl / manifest-declared) — nothing to "
            "consume; WAIVE to catalog-glue-author unchanged")
        return result

    rtl_dir.mkdir(parents=True, exist_ok=True)
    staged: List[str] = []
    staged_paths: List[Path] = []
    provenance: List[str] = []
    sv_files: List[str] = []
    vh_files: List[str] = []
    collisions: Dict[str, List[str]] = {}
    claimed: Dict[str, Path] = {}
    for src in provided:
        dst = rtl_dir / src.name
        if dst.exists():
            # Staging is FLAT, so `a/m.sv` and `b/m.sv` compete for one name and
            # the second one is discarded. That is a real loss of source — the
            # discarded file's modules simply are not in the build — and it used
            # to happen with no record anywhere. The flattening itself is not
            # changed here (the staged FILENAMES are a contract several
            # downstream steps read); what changes is that the loss is NAMED.
            try:
                _first = str(claimed[src.name].relative_to(project))
            except (KeyError, ValueError):
                _first = src.name
            try:
                _lost = str(src.relative_to(project))
            except ValueError:
                _lost = str(src)
            collisions.setdefault(src.name, [_first]).append(_lost)
            continue  # deterministic first-wins on a name collision
        try:
            shutil.copy2(src, dst)
        except OSError:
            continue
        claimed[src.name] = src
        staged.append(dst.name)
        staged_paths.append(dst)
        try:
            provenance.append(str(src.relative_to(project)))
        except Exception:
            provenance.append(src.name)
        if src.suffix == ".sv":
            sv_files.append(dst.name)
        elif src.suffix in _HDR_EXTS:
            vh_files.append(dst.name)

    if not staged:
        result["reason"] = (
            "provided build RTL discovered but nothing new staged "
            "(all names already present)")
        return result

    result["reused_ip"] = True
    result["staged"] = sorted(staged)
    result["sv_files"] = sorted(sv_files)
    result["vh_files"] = sorted(vh_files)
    if collisions:
        result["staged_name_collisions"] = {
            k: sorted(set(v)) for k, v in sorted(collisions.items())}

    # G-SV-INGEST honesty — never silently drop raw SystemVerilog.
    if sv_files:
        has_sv2v = shutil.which("sv2v") is not None
        result["sv2v_available"] = has_sv2v
        result["sv_ingest_note"] = (
            f"SV-ingest: {len(sv_files)} SystemVerilog file(s) staged "
            f"({', '.join(sorted(sv_files))}). The synth path's slang/sv2v "
            f"pre-pass (vibeic-eda container) lowers them to Verilog; if that "
            f"pre-pass is unavailable, install sv2v — raw SV was NOT silently "
            f"dropped." + ("" if has_sv2v else " [host sv2v: NOT on PATH]"))

    try:
        mf = emit_consume_manifest(project, staged_paths, provenance)
        if mf is not None:
            result["manifest_emitted"] = str(mf.relative_to(project))
    except Exception:
        pass

    result["reason"] = (
        f"staged {len(staged)} design-provided build-RTL file(s) into "
        f"phase2/stage1/rtl/ (deterministic; residual glue still WAIVES to "
        f"catalog-glue-author)"
        + (" — " + result["consume_reason_override"]
           if result.get("consume_reason_override") else ""))
    return result


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Deterministic reused-IP RTL consume — stage a design's "
                    "provided build RTL into phase2/stage1/rtl/ (G-CATALOG-GLUE)")
    ap.add_argument("project", help="Project root")
    ns = ap.parse_args(argv)
    res = consume_reused_ip_rtl(Path(ns.project).resolve())
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
