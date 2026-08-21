#!/usr/bin/env python3
"""Wave 77 — auto-generate vibe-ic/programs/INDEX.md.

Scans every *.py under programs/, extracts module docstring + the
optional `_APPLICABLE_CLASSES` tuple, and renders a deterministic
INDEX.md sorted alphabetically and grouped by ic_class.

The generator is the SOURCE OF TRUTH; INDEX.md is a derived artefact.
A CI freshness test (`tests/test_programs_index_freshness.py`) re-runs
this script and diffs against the committed INDEX.md — any drift
fails CI.

Run:
    python3 tools/gen_programs_index.py
"""
from __future__ import annotations
import argparse
import ast
import re
import sys
import warnings
from pathlib import Path
from typing import Optional

# Some legacy program docstrings carry literal backticks-with-backslash
# sequences that trigger SyntaxWarning under Python 3.12 ast.parse(),
# but they aren't real syntax errors. Silence cosmetic noise.
warnings.filterwarnings("ignore", category=SyntaxWarning)

ROOT = Path(__file__).resolve().parent.parent
PROGRAMS = (
    ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
)
INDEX = PROGRAMS / "INDEX.md"

# All canonical ic_class values from ic_class_profile.py.
KNOWN_CLASSES = (
    "aid_class_half_duplex",
    "digital_cmd_driven",
    "mixed_signal_otp",
    "pure_analog",
    "bare_fpga",
    "unknown",
    "any",  # umbrella when a program has no explicit gating
)


# ─── extraction ─────────────────────────────────────────────────────
def _docstring(tree: ast.Module) -> str:
    return (ast.get_docstring(tree) or "").strip()


def _applicable_classes(tree: ast.Module) -> Optional[tuple]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_APPLICABLE_CLASSES"
        ):
            try:
                v = ast.literal_eval(node.value)
                if isinstance(v, (tuple, list)):
                    return tuple(v)
            except Exception:
                return None
    return None


def _wave_label(text: str) -> str:
    """Best-effort: pull a 'Wave NN' / 'v0.X' label from the docstring."""
    # Earliest "Wave NN" wins.
    m = re.search(r"Wave\s+(\d+)", text)
    if m:
        return f"Wave {m.group(1)}"
    m = re.search(r"v(0\.\d+(?:\.\d+)?)", text)
    if m:
        return f"v{m.group(1)}"
    return ""


#: Provenance markers this repo leads docstrings with: a version, a wave, a
#: backlog id, an analog-phase id (`A6 deterministic gate`). Deliberately
#: anchored and length-bounded — a real description that merely BEGINS with a
#: version ("v2 of the width resolver, now separator-insensitive") is long
#: enough to fall outside and is left alone.
_BARE_TAG_RE = re.compile(
    r"^(?:v?\d[\w.]*|Wave\s*\d+[\w\s./-]*|BACKLOG[\w\s./-]*|[A-Z]\d+\s[\w\s./-]*)"
    r"[.]?$")


def _is_a_bare_tag(text: str) -> bool:
    return len(text) < 30 and bool(_BARE_TAG_RE.match(text.strip()))


def _next_prose_line(docstring: str):
    """The first line after the summary that carries actual prose.

    Skips blanks and underline rules (`====`, `----`), which are section
    decoration rather than content.
    """
    for line in docstring.strip().splitlines()[1:]:
        s = line.strip()
        if len(s) > 25 and not set(s) <= set("=-~ "):
            return s
    return None


def _title(docstring: str, fallback_name: str) -> str:
    if not docstring:
        return fallback_name
    # THE SUMMARY IS THE FIRST PARAGRAPH, NOT THE FIRST LINE. Many docstrings
    # here wrap it across two or three lines before the first blank, and taking
    # only line 0 truncated them mid-phrase in the index:
    #
    #   "agent_report_sha256_attestation_check.py — verify the project's"
    #   "final report attests every canonical chip / FPGA artefact with a"
    #   "SHA256 hash."
    #        indexed as:  verify the project's
    #
    # Joining the paragraph fixes those AND subsumes the wrapped-tag case
    # ("A6 deterministic gate" + "(Per-Block Physical Verification: DRC + LVS)."),
    # so no special join rule is needed for it.
    para = []
    for line in docstring.strip().splitlines():
        if not line.strip():
            break
        para.append(line.strip())
    first = " ".join(para)
    # "module — what it does" → drop the module name, keep the description.
    #
    # SPLIT ONLY WHEN WHAT PRECEDES THE DASH IS THE MODULE NAME OR A VERSION TAG.
    # An unconditional positional split assumes every first line is
    # "<name> — <description>", and throws away the description of any line that
    # uses an em-dash as ORDINARY PUNCTUATION. Measured over all 1003 programs:
    # 816 lines do have the name in front and split correctly, 4 do not and lost
    # their titles to it —
    #
    #   "A committed pointer to a file that does not exist — anywhere."
    #        indexed as:  anywhere.
    #   "Chip-level sign-off ladder runner (B1 from spm pilot) — REAL-gate wiring"
    #        indexed as:  REAL-gate wiring
    #
    # — leaving INDEX.md, which is how a reader navigates 1003 programs, telling
    # them nothing about those entries. The version-tag case is kept splitting
    # ("v0.1.51 — phase1 output post-processor." must yield the description, not
    # the version), so the rule is "drop a NAME or a VERSION prefix, never prose".
    for sep in ("—", " - "):
        if sep not in first:
            continue
        before, after = (s.strip() for s in first.split(sep, 1))
        looks_like_name = (
            before.replace("programs/", "").removesuffix(".py").strip()
            == fallback_name)
        looks_like_version = bool(re.match(r"^v?\d[\w.]*$", before))
        if after and (looks_like_name or looks_like_version):
            first = after
        break
    if not first:
        return fallback_name

    # A TAG IS NOT A DESCRIPTION. Rows carried `v0.2.97`, `Wave 39 / D3`,
    # `BACKLOG-v11 P0.6.` — the whole of what their summary says once the module
    # name is removed, telling a reader nothing about the program.
    #
    # Fixing the GENERATOR rather than ~98 docstrings: those docstrings are not
    # wrong, they lead with a provenance tag by convention. It is the index that
    # has to present something usable.
    # …and when the whole first PARAGRAPH is only a tag — the shape where a
    # blank line separates the provenance marker from the description — the
    # substance is in the paragraph after it.
    if _is_a_bare_tag(first):
        nxt = _next_prose_line(docstring)
        if nxt:
            first = nxt
    if len(first) > 140:
        first = first[:137] + "..."
    return first


def _what_fails_on(docstring: str) -> str:
    """Pull a 'what FAILs on' / failure-mode hint from the docstring."""
    for keyword in ("FAIL", "fails when", "Fails on", "Catches", "Detects"):
        m = re.search(
            rf"({keyword}[^\n]{{0,200}})", docstring, re.IGNORECASE
        )
        if m:
            t = m.group(1).strip().rstrip(".")
            if len(t) > 200:
                t = t[:197] + "..."
            return t
    return ""


def _is_helper(path: Path) -> bool:
    name = path.name
    if name.startswith("_"):
        return True
    if name.startswith("DEPRECATED_") or name.endswith("_shim.py"):
        return True
    # Common deprecation-shim heuristic
    try:
        head = path.read_text(errors="replace")[:2000]
    except OSError:
        return False
    if "DEPRECATION SHIM" in head.upper():
        return True
    return False


# ─── render ─────────────────────────────────────────────────────────
def collect() -> list[dict]:
    rows: list[dict] = []
    for p in sorted(PROGRAMS.glob("*.py")):
        if _is_helper(p):
            continue
        text = p.read_text(errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        ds = _docstring(tree)
        ac = _applicable_classes(tree)
        rows.append(
            {
                "name": p.stem,
                "title": _title(ds, p.stem),
                "applicable_classes": ac,
                "wave": _wave_label(ds),
                "what_fails_on": _what_fails_on(ds),
            }
        )
    return rows


def _classes_label(ac: Optional[tuple]) -> str:
    if ac is None:
        return "any"
    return ", ".join(ac)


def _group_by_class(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {c: [] for c in KNOWN_CLASSES}
    for r in rows:
        ac = r["applicable_classes"]
        if ac is None:
            groups["any"].append(r)
        else:
            for c in ac:
                if c in groups:
                    groups[c].append(r)
                else:
                    groups.setdefault(c, []).append(r)
    return groups


def render(rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=lambda r: r["name"])
    groups = _group_by_class(rows)

    out: list[str] = []
    out.append("<!-- AUTO-GENERATED by tools/gen_programs_index.py — DO NOT EDIT BY HAND -->")
    out.append("")
    out.append("# Vibe-IC plugin programs — INDEX")
    out.append("")
    out.append(
        "Auto-generated catalog of every `*.py` under "
        "`vibe-ic-marketplace/plugins/vibe-ic/programs/` (helpers and "
        "deprecation shims excluded). The generator at "
        "`tools/gen_programs_index.py` is the source of truth; a "
        "freshness CI test diffs the regenerated INDEX against this "
        "file and FAILs on drift."
    )
    out.append("")

    # ─── Stats ─────────────────────────────────────────────────────
    out.append("## Stats")
    out.append("")
    out.append(f"- **Total programs (excluding helpers / shims):** {len(rows_sorted)}")
    explicit = sum(1 for r in rows_sorted if r["applicable_classes"] is not None)
    out.append(
        f"- **Programs with explicit `_APPLICABLE_CLASSES`:** {explicit} "
        f"(of {len(rows_sorted)})"
    )
    out.append("")
    out.append("### Per-class applicability counts")
    out.append("")
    out.append("| ic_class | gates applicable |")
    out.append("|---|---|")
    for c in KNOWN_CLASSES:
        out.append(f"| `{c}` | {len(groups.get(c, []))} |")
    out.append("")

    # ─── Alphabetical listing ───────────────────────────────────────
    out.append("## Alphabetical listing")
    out.append("")
    out.append("| Program | Applicable classes | Wave | Title |")
    out.append("|---|---|---|---|")
    for r in rows_sorted:
        out.append(
            f"| `{r['name']}` "
            f"| {_classes_label(r['applicable_classes'])} "
            f"| {r['wave'] or '—'} "
            f"| {r['title']} |"
        )
    out.append("")

    # ─── By ic_class ────────────────────────────────────────────────
    out.append("## By ic_class")
    out.append("")
    for c in KNOWN_CLASSES:
        items = sorted(groups.get(c, []), key=lambda r: r["name"])
        out.append(f"### `{c}` ({len(items)} programs)")
        out.append("")
        if not items:
            out.append("_(no programs in this group)_")
            out.append("")
            continue
        for r in items:
            line = f"- `{r['name']}` — {r['title']}"
            if r["wave"]:
                line += f"  _[{r['wave']}]_"
            out.append(line)
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if INDEX.md would change (CI mode)")
    ap.add_argument("--out", default=str(INDEX),
                    help=f"output path (default {INDEX})")
    args = ap.parse_args(argv)

    rows = collect()
    body = render(rows)
    out_path = Path(args.out)

    if args.check:
        existing = out_path.read_text() if out_path.exists() else ""
        if existing != body:
            sys.stderr.write(
                f"INDEX.md is stale at {out_path}; "
                f"re-run `python3 tools/gen_programs_index.py`\n"
            )
            return 1
        # A PASS must say how much it examined (vibe-ic#447). A silent `return
        # 0` here is byte-identical to a run that walked nothing — and this
        # tree's own `gate_discloses_denominator_check` catches exactly that,
        # which is how this line came to exist.
        if not rows:
            sys.stderr.write(
                "NOTHING_SCANNED: no programs found — this is NOT a pass; "
                "an index generated over zero programs matches an empty "
                "INDEX.md trivially.\n")
            return 2
        print(f"[PASS] programs index fresh: {len(rows)} program(s) indexed, "
              f"INDEX.md matches what the tree would generate.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body)
    print(f"wrote {out_path} ({len(rows)} programs)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
