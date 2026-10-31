#!/usr/bin/env python3
"""
phase1_all_l_docs_present_check.py — gate (Wave 23, v0.119.55).

Wave 23 — Phase 1 (doc-extraction) coverage is non-waivable. 100% is the hard
threshold. To resolve, add patterns to <project>/extraction_patterns.json
— do NOT add waivers.

This gate catches the 28th fresh-agent attempt's root cause:
`1st_benchmark_example/phase2_v0119.54-vendor/` produced ONLY four L
docs (L2_FRS / L8_TIMING_WAVEFORM / L9_INTEGRATION_SPEC /
L11_OTP_CONTENT) and skipped 9 of 13 Phase 1 (doc-extraction) generator skills
entirely. The pre-existing LL-38/LL-39/LL-40 gates measure coverage
on whatever L docs are present, but if 9 L docs are missing, the
1091-literal denominator collapses to 13.7% and the agent can't
recover via patterns alone — the generators that consume those
patterns simply weren't run.

What this gate verifies
=======================
For every Phase 1 (doc-extraction)-attempted project, all 13 L doc filename prefixes
must appear in `<project>/generated_docs/`:

  L1_*, L2_*, L3_*, L4_*, L5_*, L6_*, L7_*,
  L8_*, L9_*, L10_*, L11_*, L12_*, L13_*

Each matched file must:
  1. Parse as valid JSON
  2. Have a non-empty top-level dict (more than 0 keys)

Behavior
========
- Silent-skip when `<project>/generated_docs/` is absent (Phase 1 (doc-extraction)
  not attempted yet).
- PASS when all 13 L doc prefixes have at least one matching file
  AND every matching file is parseable + non-empty.
- FAIL listing each missing or empty L prefix with the canonical
  expected filename hint.

NO WAIVER. The intent of Wave 23 is precisely to forbid silencing
Phase 1 (doc-extraction) coverage / completeness with waivers. If the project does
not produce all 13 L docs, the agent must run the missing Phase 1 (doc-extraction)
skills — there is no waiver path.

Chip-AGNOSTIC: matches by L<n>_ prefix only; the suffix part of the
filename can be anything (L3_PROTOCOL.json or L3_CMD_PROTOCOL.json
both match L3_).

Wave 32 (v0.119.64) — explicitly accepts:
  - `L4_REGMAP.json` AND/OR `L4_OTP_IMAGE.json` (the OTP byte map
    relocated from L11 to L4 in Wave 32; either filename satisfies
    the L4_ prefix).
  - `L11_CALIBRATION.json` AND/OR `L11_BEHAVIORAL.json` (joint
    ownership by calibration-gen + behavioral-sequences-gen). The
    legacy `L11_OTP_CONTENT.json` shape still satisfies the prefix
    but is deprecated by SKILL.md.

Usage
-----
    python3 phase1_all_l_docs_present_check.py <project_dir>

Returns 0 PASS / silent-skip, 1 FAIL, 2 input error.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import json
import sys
from pathlib import Path
import _path_layout as _pl

# Wave 36 (v0.119.68) — IC class profile lets us drop L docs that
# are not applicable to the IC class (e.g. L5/L11/L12/L13 on a pure
# UART chip).  Imported lazily so we never break a project that
# still ships only this single program.
try:
    from ic_class_profile import detect_ic_class, required_layers
except Exception:  # pragma: no cover - defensive
    detect_ic_class = None  # type: ignore[assignment]
    required_layers = None  # type: ignore[assignment]


_REQUIRED_PREFIXES: tuple[str, ...] = (
    "L1_", "L2_", "L3_", "L4_", "L5_", "L6_", "L7_",
    "L8_", "L9_", "L10_", "L11_", "L12_", "L13_",
)


def fact_graph_layer_contract(project: Path):
    """The native nonphysical publisher's complete source-derived layer contract.

    This is not an absence waiver: every input fact must remain at its owning
    layer, with complete list populations and 100% applicable required facts.
    Physical, unknown and raw-document inputs keep their existing contracts.
    """
    from _phase1_producer_identity import has_converged_fact_graph
    if not has_converged_fact_graph(project):
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from phase1_engine.schema import FactGraph, LAYER_FILE_NAMES
    from phase1_engine.render import compute_required_facts_coverage
    import flow109
    scope = flow109.active_rtl_scope(project)
    if scope is None:
        return None
    current, reference = flow109._bound_project_json(
        project, Path(scope["manifest"]["path"]), "D01_FACT_GRAPH_SCOPE_UNBOUND")
    if reference != scope["manifest"]:
        raise ValueError("D01_FACT_GRAPH_SCOPE_UNBOUND")
    current_plan = flow109.resolve_plan(current.get("features"), current.get("step_profiles"))
    source = project / "input/phase1_structured.yaml"
    if source.is_symlink() or not source.resolve().is_relative_to(project.resolve()):
        raise ValueError("D01_FACT_GRAPH_SOURCE_UNBOUND")
    graph = FactGraph.load(source)
    manifest = graph.metadata.get("flow109_manifest")
    if manifest is None:
        return None
    if not isinstance(manifest, dict):
        raise ValueError("D01_FACT_GRAPH_SELECTION_INVALID")
    plan = flow109.resolve_plan(manifest.get("features"), manifest.get("step_profiles"))
    if any(plan[key] != current_plan[key] for key in ("features", "step_profiles")):
        return None
    features = plan["features"]
    if (features["physical"] or not features["has_digital"]
            or features["has_analog"] or features["package_interface"]):
        return None
    coverage = compute_required_facts_coverage(graph)
    if not graph.facts or not coverage["total"] or coverage["pct"] != 1.0:
        raise ValueError("D01_FACT_GRAPH_REQUIRED_FACTS_INCOMPLETE: " + str(coverage))
    import re
    import phase1_expert_parse_track as track
    docs = {}
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("D01_FACT_GRAPH_DUPLICATE_OUTPUT_KEY: " + key)
            result[key] = value
        return result
    def preserves(actual, expected):
        if type(actual) is not type(expected):
            return False
        if isinstance(expected, dict):
            return all(k in actual and preserves(actual[k], v) for k, v in expected.items())
        if isinstance(expected, list):
            return len(actual) == len(expected) and all(preserves(a, b) for a, b in zip(actual, expected))
        return actual == expected
    for fact in graph.facts:
        layer, key = fact.path.split(".", 1)
        if layer not in fact.views or layer not in LAYER_FILE_NAMES:
            raise ValueError("D01_FACT_GRAPH_LAYER_UNSUPPORTED: " + fact.path)
        relative = "phase1/generated_docs/" + LAYER_FILE_NAMES[layer]
        if relative not in docs:
            path = project / relative
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(project.resolve()):
                raise ValueError("D01_FACT_GRAPH_OUTPUT_MISSING: " + relative)
            docs[relative] = json.loads(path.read_text(), object_pairs_hook=unique)
        pointer = "/" + re.sub(r"\[(\d+)\]", r"/\1", key.replace(".", "/"))
        values = track.subtree_at(docs[relative], pointer, layer)
        if not isinstance(values, list) or len(values) != 1 or not preserves(values[0], fact.value):
            raise ValueError("D01_FACT_GRAPH_FACT_NOT_PRESERVED: " + fact.path)
    return {"required_outputs": sorted(docs), "facts": len(graph.facts),
            "required_fact_coverage": coverage, "source": "input/phase1_structured.yaml"}


def _check(project: Path) -> tuple[int, list[str]]:
    if not project.is_dir():
        return 2, [f"FAIL — project dir not found: {project}"]

    try:
        native = fact_graph_layer_contract(project)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return 1, ["phase1_all_l_docs_present_check: FAIL — " + str(exc)]
    if native is not None:
        return 0, [f"phase1_all_l_docs_present_check: PASS — {len(native['required_outputs'])} native graph layers; {native['facts']} source facts preserved"]

    # Wave 30 (v0.119.62) — fail-closed semantic for missing
    # generated_docs/. The previous silent-skip path let fresh-agent
    # projects that NEVER ran Phase 1 (doc-extraction) pass this gate and progress to
    # SOF burn (35th-attempt root cause). 100% Phase 1 (doc-extraction) coverage is
    # non-negotiable; "did not even attempt Phase 1 (doc-extraction)" is the worst-
    # case form of "<100% coverage" and must FAIL, not SKIP.
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return 1, [
            "phase1_all_l_docs_present_check: FAIL — "
            "generated_docs/ absent.",
            "",
            "FAIL — Wave 30 (v0.119.62): Phase 1 (doc-extraction) was not attempted. "
            "All 13 L docs (L1-L13) must exist in generated_docs/ "
            "before any Phase 2 RTL/burn step is allowed. Run the "
            "phase1-orchestrate skill (or every Phase 1 (doc-extraction) generator "
            "skill individually). NO waiver allowed."
        ]

    files = sorted(gd.glob("*.json"))
    if not files:
        return 1, [
            "phase1_all_l_docs_present_check: FAIL — "
            "generated_docs/ has no *.json files (Phase 1 (doc-extraction) not "
            "attempted).",
            "",
            "FAIL — Wave 30 (v0.119.62): Phase 1 (doc-extraction) was not attempted. "
            "All 13 L docs (L1-L13) must exist in generated_docs/ "
            "before any Phase 2 RTL/burn step is allowed. Run the "
            "phase1-orchestrate skill (or every Phase 1 (doc-extraction) generator "
            "skill individually). NO waiver allowed."
        ]

    # Wave 36 (v0.119.68) — consult IC class profile so L docs that are NOT
    # applicable to the IC class drop to INFO rather than FAIL.
    # #157 (v1.4.x) — the ENFORCED set is now the class's
    # required_layers(profile)["mandatory"] (which incl. an applicable L24/L25
    # once a project declares `targets_signoff`), NOT a static L1-L13 tuple.
    # A layer in `skip` (incl. L24-L27 for a non-signoff / non-MEMS /
    # non-memory-module chip) demotes to INFO → no false-fail. Fail-closed
    # default: when detection is unavailable OR returns "unknown", the legacy
    # 13/13 L1-L13 contract stays intact.
    profile: dict | None = None
    mandatory_prefixes: list[str] = list(_REQUIRED_PREFIXES)
    skip_prefixes: set[str] = set()
    if detect_ic_class is not None and required_layers is not None:
        try:
            profile = detect_ic_class(project)
            spec = required_layers(profile)
            mand_layers = list(spec.get("mandatory", []))
            skip_layers = list(spec.get("skip", []))
            if mand_layers:
                # layer is e.g. "L5" — translate to prefix "L5_"
                mandatory_prefixes = [f"{layer}_" for layer in mand_layers]
            skip_prefixes = {f"{layer}_" for layer in skip_layers}
        except Exception:
            profile = None
            mandatory_prefixes = list(_REQUIRED_PREFIXES)
            skip_prefixes = set()

    # Prefixes we CONSIDER = the enforced (mandatory) set + the skip set
    # (demoted to INFO). A mandatory prefix with no file FAILs; a skip prefix
    # with no file is INFO. Any other L doc on disk (e.g. advanced L14-L23) is
    # neither enforced nor reported — unchanged behaviour.
    not_applicable_prefixes: set[str] = set(skip_prefixes)
    considered_prefixes: list[str] = list(dict.fromkeys(
        list(mandatory_prefixes) + sorted(skip_prefixes)))

    # Build prefix -> matching file list over the considered universe.
    matched: dict[str, list[Path]] = {p: [] for p in considered_prefixes}
    for f in files:
        for pref in considered_prefixes:
            if f.name.startswith(pref):
                matched[pref].append(f)
                break

    missing: list[str] = []
    empty: list[str] = []
    invalid: list[str] = []
    ok: list[str] = []
    not_applicable: list[str] = []

    for pref, paths in matched.items():
        if not paths:
            if pref in not_applicable_prefixes:
                # Wave 36 — L doc not applicable to this IC class. Skip.
                not_applicable.append(pref)
                continue
            missing.append(pref)
            continue
        # Use the first matching file for validation; if any matching
        # file is non-empty + parseable that prefix passes.
        prefix_ok = False
        for p in paths:
            try:
                data = json.loads(p.read_text())
            except Exception as e:
                invalid.append(f"{p.name}: JSON unparseable ({e})")
                continue
            if not isinstance(data, dict):
                invalid.append(f"{p.name}: top-level not a JSON object")
                continue
            if len(data) == 0:
                empty.append(f"{p.name}: top-level dict is empty")
                continue
            prefix_ok = True
            break
        if prefix_ok:
            ok.append(pref)

    out: list[str] = []
    # #157 — total_required tracks the class's MANDATORY layer count (the
    # enforced set), not a static 13. For the fail-closed default (unknown /
    # bare_fpga) this is exactly 13 (L1-L13) so the legacy contract is intact.
    total_required = len(mandatory_prefixes)
    cls_label = (profile or {}).get("ic_class", "unknown")
    out.append(
        f"phase1_all_l_docs_present_check: "
        f"{len(ok)}/{total_required} L doc prefixes present + "
        f"non-empty (ic_class={cls_label})")
    for pref in not_applicable:
        out.append(
            f"  INFO — {pref}*.json not applicable to "
            f"ic_class={cls_label} (skipped)")

    if missing or empty or invalid:
        out.append("")
        out.append(
            f"FAIL — Wave 23 (v0.119.55) / #157: all {total_required} "
            f"mandatory L docs (ic_class={cls_label}) must exist in "
            "generated_docs/ with non-empty content. NO waiver allowed.")
        if missing:
            out.append("")
            out.append(
                f"  Missing L doc prefixes ({len(missing)}/{total_required}):")
            for pref in missing:
                out.append(
                    f"    - {pref}*.json (e.g. {pref}DATASHEET.json / "
                    f"{pref}FRS.json / etc.)")
        if empty:
            out.append("")
            out.append(f"  L docs that exist but are empty ({len(empty)}):")
            for msg in empty:
                out.append(f"    - {msg}")
        if invalid:
            out.append("")
            out.append(f"  L docs that are unparseable ({len(invalid)}):")
            for msg in invalid:
                out.append(f"    - {msg}")
        out.append("")
        out.append(
            "To resolve: run every Phase 1 (doc-extraction) generator skill (datasheet-"
            "gen, frs-gen, cmd-protocol-gen, regmap-gen, adi-spec-gen, "
            "control-logic-gen, test-debug-gen, timing-waveform-gen, "
            "rtl-constants-gen / integration-spec-gen, test-cases-gen, "
            "calibration-gen / otp-content-gen, behavioral-sequences-"
            "gen, lab-calibration-gen) so all 13 L docs are emitted "
            "with non-empty content. Do NOT add a waiver — there is "
            "no waiver for this gate.")
        return 1, out

    out.insert(
        0,
        f"PASS — all {total_required}/{total_required} mandatory L "
        f"docs present + non-empty in generated_docs/ "
        f"(ic_class={cls_label}; "
        f"{len(not_applicable)} not-applicable layer(s) skipped)")
    return 0, out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: phase1_all_l_docs_present_check.py <project_dir>")
        return 2
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: phase1_all_l_docs_present_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    code, lines = _check(project)
    for ln in lines:
        print(ln)
    return code


if __name__ == "__main__":
    sys.exit(main())
