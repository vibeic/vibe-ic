#!/usr/bin/env python3
"""l12_tb_coverage_check.py — v0.52 plugin gate

Verifies that EVERY behavioural sequence enumerated in
`generated_docs/L12_BEHAVIORAL_SEQUENCES.json` has a matching testbench file
under `sim/tb/`.

Coverage rule for each sequence with id `<SEQ_NAME>`:
  (a) a testbench file named `tb_<seq_lower>.v` exists under `sim/tb/`
      (for example, sequence `TEST_MODE_ENTRY` → `tb_test_mode_entry.v` or
      the shorter conventional `tb_testmode.v` — we check a small set of
      normalised variants), OR
  (b) the literal `<SEQ_NAME>` appears as a substring in some tb file
      (simple grep of the content, case-insensitive).

Closing the L12 gap this program addresses:
Historically the v0.52 coverage report claimed "≥95% estimated" while
three out of four L12 behavioural sequences had no dedicated testbench
(only happy-path integration coverage). This gate enforces per-sequence
TB existence so the estimated-vs-machine-measured gap is forced closed
at the programmable-plugin layer.

Usage:
    python3 l12_tb_coverage_check.py <project_dir>
        [--l12 <path>]     (default: <project_dir>/generated_docs/L12_BEHAVIORAL_SEQUENCES.json)
        [--tb-dir <path>]  (default: <project_dir>/sim/tb)
        [--json <out>]     (default: <project_dir>/reports/gates/l12_tb_coverage.json)
        [--strict]

Exit codes:
    0 — every L12 sequence has TB coverage
    1 — one or more sequences have no matching TB
    2 — path / input error
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def load_l12(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    sequences = data.get("sequences", [])
    if not isinstance(sequences, list):
        raise ValueError("L12 .sequences must be a list")
    return sequences


def load_strip_suffixes(class_template_path: Path | None) -> list[str]:
    """Load `sequence_naming.strip_suffixes` from a class template YAML.

    Returns an empty list (= pure underscore-stripping only) when no
    template is given or it doesn't declare strip suffixes. This keeps
    the gate fully generic for ICs that don't ship a template.

    Tiny, dependency-free YAML reader: this codebase keeps programs
    stdlib-only. We parse the minimal subset we need (a top-level
    `sequence_naming:` block with a `strip_suffixes:` list of strings).
    """
    if not class_template_path or not class_template_path.exists():
        return []
    in_block = False
    in_list = False
    suffixes: list[str] = []
    for raw in class_template_path.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Top-level keys start in column 0
        if not raw.startswith(" "):
            in_block = (line.strip().rstrip(":") == "sequence_naming")
            in_list = False
            continue
        if not in_block:
            continue
        # Inside sequence_naming block
        stripped_line = line.strip()
        if stripped_line.startswith("strip_suffixes"):
            in_list = stripped_line.endswith(":")
            continue
        if in_list and stripped_line.startswith("-"):
            val = stripped_line[1:].strip()
            # Strip optional surrounding quotes + inline comment
            val = re.sub(r"\s+#.*$", "", val).strip()
            if val.startswith(("'", '"')) and val.endswith(("'", '"')):
                val = val[1:-1]
            if val:
                suffixes.append(val.lower())
    return suffixes


def normalise_candidates(seq_id: str, strip_suffixes: list[str] | None = None) -> list[str]:
    """Return the set of testbench filename candidates for a given seq_id.

    Always tries:
      - `tb_<snake>.v`           (the literal id, lower-cased)
      - `tb_<flat>.v`            (id with underscores removed)

    Plus, if `strip_suffixes` is provided (loaded from the IC class
    template), tries the same two forms with each matching trailing
    suffix removed:
      - `tb_<snake_minus_suffix>.v`
      - `tb_<flat_minus_suffix>.v`

    Example with strip_suffixes=['entry', 'unlock', '700ms']:
      'TEST_MODE_ENTRY' → ['tb_test_mode.v', 'tb_test_mode_entry.v',
                           'tb_testmode.v', 'tb_testmodeentry.v']
    """
    low = seq_id.lower()
    snake = low
    flat = low.replace("_", "")
    cands: set[str] = {f"tb_{snake}.v", f"tb_{flat}.v"}

    for suf in (strip_suffixes or []):
        # Each suffix is treated as a regex; we anchor to end-of-string
        # and require an underscore separator so we never strip a
        # legitimate prefix-of-token.
        try:
            stripped = re.sub(rf"_{suf}$", "", low)
        except re.error:
            continue
        if stripped != low:
            cands.add(f"tb_{stripped}.v")
            cands.add(f"tb_{stripped.replace('_', '')}.v")

    return sorted(cands)


def find_tb_file(tb_dir: Path, candidates: list[str]) -> Path | None:
    for c in candidates:
        p = tb_dir / c
        if p.exists():
            return p
    return None


def find_seq_id_in_tbs(tb_dir: Path, seq_id: str) -> list[str]:
    """Return list of tb file names that literally contain seq_id (case-insensitive)."""
    needle = seq_id.lower()
    matches = []
    for p in sorted(tb_dir.glob("tb_*.v")):
        try:
            content = p.read_text(errors="replace").lower()
        except Exception:
            continue
        if needle in content:
            matches.append(p.name)
    return matches


def check(project_dir: Path,
          l12_path: Path,
          tb_dir: Path,
          json_out: Path,
          strict: bool,
          class_template_path: Path | None = None) -> int:
    if not l12_path.exists():
        print(f"[ERROR] L12 file not found: {l12_path}", file=sys.stderr)
        return 2
    if not tb_dir.exists():
        print(f"[ERROR] TB dir not found: {tb_dir}", file=sys.stderr)
        return 2

    sequences = load_l12(l12_path)
    strip_suffixes = load_strip_suffixes(class_template_path)

    report: dict = {
        "gate": "l12_tb_coverage",
        "l12_file": str(l12_path),
        "tb_dir": str(tb_dir),
        "class_template": str(class_template_path) if class_template_path else None,
        "strip_suffixes_used": strip_suffixes,
        "total_sequences": len(sequences),
        "covered_sequences": 0,
        "uncovered_sequences": 0,
        "sequences": []
    }

    exit_code = 0

    for seq in sequences:
        seq_id = seq.get("id") or seq.get("name") or "UNKNOWN"
        candidates = normalise_candidates(seq_id, strip_suffixes)
        match_file = find_tb_file(tb_dir, candidates)
        grep_matches = find_seq_id_in_tbs(tb_dir, seq_id)

        if match_file is not None:
            method = f"filename match: {match_file.name}"
            covered = True
        elif grep_matches:
            method = f"content match in: {', '.join(grep_matches)}"
            covered = True
        else:
            method = f"NOT FOUND (tried {candidates})"
            covered = False

        report["sequences"].append({
            "id": seq_id,
            "covered": covered,
            "method": method,
            "candidates_tried": candidates,
            "content_matches": grep_matches
        })
        if covered:
            report["covered_sequences"] += 1
        else:
            report["uncovered_sequences"] += 1
            exit_code = 1

    report["pass"] = (exit_code == 0)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2))

    # human-readable output to stdout
    print(f"L12 TB coverage gate: {report['covered_sequences']}/{report['total_sequences']} sequences covered")
    for s in report["sequences"]:
        mark = "[OK]  " if s["covered"] else "[MISS]"
        print(f"  {mark} {s['id']}: {s['method']}")
    print(f"Report written to: {json_out}")
    if strict and exit_code != 0:
        return 1
    # In non-strict mode, still return 1 if any uncovered (callers decide)
    return exit_code


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Verify L12 behavioural sequences each have TB coverage.")
    ap.add_argument("project_dir", help="Root of the IC project")
    ap.add_argument("--l12", default=None,
                    help="Path to L12_BEHAVIORAL_SEQUENCES.json")
    ap.add_argument("--tb-dir", default=None, help="Path to testbench directory")
    ap.add_argument("--json", default=None, help="Output JSON path")
    ap.add_argument("--ic-class", default=None,
                    help="Path to the IC class template YAML (e.g. "
                         "plugins/vibe-ic/agents/class_kb/templates/"
                         "cable-side-id-ic.yaml). When provided, the gate "
                         "reads `sequence_naming.strip_suffixes` from it to "
                         "form abbreviated tb candidate names. Without this, "
                         "only the literal id (snake + flat) is tried.")
    ap.add_argument("--strict", action="store_true",
                    help="Exit non-zero on any uncovered sequence (default: same)")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    l12 = Path(args.l12) if args.l12 else _pl.generated_docs_dir(project) / "L12_BEHAVIORAL_SEQUENCES.json"
    # vibe-ic#599: this had NO fallback — `sim_dir(project)/"tb"` or an error.
    # The flow writes `sim_full_stack/`, so the gate reported "TB dir not found"
    # on a project holding a real testbench and four L10 test cases, and step 4
    # was credited with no coverage measurement at all.
    tb_dir = (Path(args.tb_dir) if args.tb_dir
              else (_pl.resolve_tb_dir(project) or _pl.sim_dir(project) / "tb"))
    json_out = Path(args.json) if args.json else _pl.report_path(project, "gates/l12_tb_coverage.json")
    ic_class = Path(args.ic_class) if args.ic_class else None

    return check(project, l12, tb_dir, json_out, args.strict,
                 class_template_path=ic_class)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
