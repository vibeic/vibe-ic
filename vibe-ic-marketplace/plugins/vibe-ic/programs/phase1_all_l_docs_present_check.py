#!/usr/bin/env python3
"""
phase1_all_l_docs_present_check.py — gate (Wave 23, v0.119.55).

Wave 23 — Phase 1 (doc-extraction) coverage is non-waivable. 100% is the hard
threshold. To resolve, add patterns to <project>/extraction_patterns.json
— do NOT add waivers.

This gate catches the 28th fresh-agent attempt's root cause:
`1st_benchmark_sn2025/phase2_v0119.54-vendor/` produced ONLY four L
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


def _check(project: Path) -> tuple[int, list[str]]:
    if not project.is_dir():
        return 2, [f"FAIL — project dir not found: {project}"]

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

    # Build prefix -> matching file list.
    matched: dict[str, list[Path]] = {p: [] for p in _REQUIRED_PREFIXES}
    for f in files:
        for pref in _REQUIRED_PREFIXES:
            if f.name.startswith(pref):
                matched[pref].append(f)
                break

    # Wave 36 (v0.119.68) — consult IC class profile so L docs that
    # are NOT applicable to the IC class drop to INFO rather than
    # FAIL.  Fail-closed default: when detection returns "unknown"
    # we keep the legacy 13/13 contract.
    profile: dict | None = None
    not_applicable_prefixes: set[str] = set()
    if detect_ic_class is not None and required_layers is not None:
        try:
            profile = detect_ic_class(project)
            spec = required_layers(profile)
            skip_layers = set(spec.get("skip", []))
            for layer in skip_layers:
                # layer is e.g. "L5" — translate to prefix "L5_"
                not_applicable_prefixes.add(f"{layer}_")
        except Exception:
            profile = None
            not_applicable_prefixes = set()

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
    total_required = 13 - len(not_applicable)
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
            "FAIL — Wave 23 (v0.119.55): all 13 L docs (L1-L13) must "
            "exist in generated_docs/ with non-empty content. NO waiver "
            "allowed.")
        if missing:
            out.append("")
            out.append(
                f"  Missing L doc prefixes ({len(missing)}/13):")
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
