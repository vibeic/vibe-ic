"""Recurrence guard: docs/architecture/ALL_STEPS.{md,zh-TW.md} must
cover EVERY step of the canonical flow yaml.

WHY THIS TEST EXISTS
--------------------
`flow/phase1_phase2_phase3.yaml` is the single source of truth for the flow.
The human-readable ALL_STEPS docs are hand-maintained — so they DRIFT:
twice now a step that was added to the yaml (most recently Step 18,
"Spare-cell + ECO-prep insertion (Design-for-ECO)") silently failed to appear
in ALL_STEPS, and the doc kept stale 1->33 numbering while the yaml had grown
to 1->41 (and again at the v2.3 43-step restructure). There was no guard, so the drop was only noticed by a human reading
the doc and asking "where did my step go?".

This test makes that class of drift a CI failure. It is GENERAL: it re-derives
the expected step set from the yaml every run, so adding/removing a step in the
yaml automatically tightens/loosens the requirement with ZERO per-step
maintenance here.

WHAT IT ENFORCES
----------------
Layer 1 (recurrence-killer, both EN + zh docs):
  * every integer main-track step id (1..N) present in the yaml appears as a
    numbered table row in the doc, and the doc has NO phantom integer rows
    (doc integer-id set == yaml integer-id set, bidirectional);
  * the headline "<N> sequential steps" / "<N> 個循序步驟" count matches the
    yaml's max integer id (== total_steps);
  * every non-integer track id (A1..A9, M1..M4, P0, the D-class) is mentioned.

Layer 2 (name-concept, EN doc only — zh names are translated so token overlap
does not apply): each integer step's EN doc row shares >=1 salient token with
the yaml step name, so a row that exists but describes the WRONG step is caught.

SKIP CONTRACT
-------------
The docs live at repo-root docs/architecture/, which is NOT synced into the
plugin marketplace mirror / cache. When the docs cannot be located (mirror /
cache context) the test SKIPs honestly instead of failing — exactly the
dormant-test discipline from the v0.2.36 _resolve_phase3_runner fix. It RUNS and
ENFORCES in the dev tree + repo CI, which is where the drift actually happens.
"""
import re
from pathlib import Path

import pytest

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a plugin dependency
    yaml = None

# programs/tests/<this> -> parent=tests, parent.parent=programs,
# parent.parent.parent=<plugin root> (vibe-ic), then /flow/.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_FLOW = _PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

def _verkey(p: Path) -> tuple:
    m = re.search(r"v(\d+)\.(\d+)\.(\d+)", p.name)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _discover_docs():
    """docs/architecture + the CURRENT (highest-version) ALL_STEPS docs.

    Filenames carry the flow-doc version (e.g. ALL_STEPS_v2.3.2.md); globbing
    keeps this guard working across doc-version bumps with no per-version edit.
    """
    for ancestor in [_PLUGIN_ROOT, *_PLUGIN_ROOT.parents]:
        cand = ancestor / "docs" / "architecture"
        if not cand.is_dir():
            continue
        ens = sorted((p for p in cand.glob("ALL_STEPS*.md")
                      if not p.name.endswith(".zh-TW.md")), key=_verkey)
        zhs = sorted(cand.glob("ALL_STEPS*.zh-TW.md"), key=_verkey)
        if ens and zhs:
            return cand, ens[-1].name, zhs[-1].name
    return None, "ALL_STEPS*.md", "ALL_STEPS*.zh-TW.md"


_DOCS_DIR, _EN_NAME, _ZH_NAME = _discover_docs()

# Salient-token tokenizer (Layer 2). Generic English stopwords + flow-generic
# words that carry no step identity. We keep tokens of length >= 3 so short
# acronyms (cdc, rdc, sta, sdc, dft, lec, eco, pdn, ir, em -> note 2-char ones
# handled below) survive.
_STOPWORDS = {
    "the", "and", "or", "of", "a", "an", "with", "from", "to", "for", "in",
    "check", "setup", "global", "detailed", "multi", "corner", "mode", "pre",
    "post", "static", "dynamic", "final", "insertion", "analysis", "planning",
    "plan", "output", "loop", "gate", "repair", "fixing", "early", "prototype",
    "report", "audit", "schema", "patterns", "claim", "level", "only", "fully",
    "clean", "based", "entry", "skills", "dialogue", "verification", "test",
    "step", "stage", "phase", "via", "per", "block", "tree",
}
# A few <=2 char acronyms that ARE identity-bearing; treat as keepable tokens.
_SHORT_KEEP = {"ir", "em"}


def _salient_tokens(name: str) -> set:
    name = name.replace("\U0001f501", " ")            # strip 🔁
    name = re.sub(r"\([^)]*\)", " ", name)             # drop parentheticals
    parts = re.split(r"[^A-Za-z0-9]+", name.lower())
    out = set()
    for p in parts:
        if not p:
            continue
        if p in _SHORT_KEEP:
            out.add(p)
        elif len(p) >= 3 and p not in _STOPWORDS:
            out.add(p)
    return out


def _step_region(text: str) -> str:
    """The slice of the doc that holds the numbered 1..N step tables.

    All flow integer steps live under '## Phase 2' .. '## Phase 3' and end
    before the '## Parallel'/'## 並行' tracks heading. Scoping here excludes
    the Phase-1 Agent-path table (whose two rows are locally numbered 1 and 2,
    colliding with step ids 1-2), the D1-D5 table, and the Totals table.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"^##\s+Phase 2", l)), 0)
    end = next((i for i, l in enumerate(lines)
                if i > start and re.match(r"^##\s+(Parallel|並行)", l)), len(lines))
    return "\n".join(lines[start:end])


def _doc_integer_ids(text: str) -> set:
    """Integer ids that are the FIRST cell of a step-table row (scoped)."""
    ids = set()
    for line in _step_region(text).splitlines():
        m = re.match(r"^\|\s*(\d{1,3})\s*\|", line)
        if m:
            ids.add(int(m.group(1)))
    return ids


def _doc_row_text(text: str, step_id: int) -> str | None:
    """Return the step-table row text for a given integer step id (or None)."""
    for line in _step_region(text).splitlines():
        m = re.match(r"^\|\s*(\d{1,3})\s*\|", line)
        if m and int(m.group(1)) == step_id:
            return line.lower()
    return None


def _find_docs_dir() -> Path | None:
    return _DOCS_DIR


def _load_flow():
    if yaml is None:
        pytest.skip("pyyaml not importable in this environment")
    if not _FLOW.exists():
        pytest.skip(f"flow yaml not found at {_FLOW}")
    data = yaml.safe_load(_FLOW.read_text())
    steps = data.get("steps", [])
    int_steps = {}      # id(int) -> name
    other_ids = set()   # 'A1'..'M4'..'P0'.. + D-class
    for s in steps:
        sid = s.get("id")
        name = s.get("name", "")
        if isinstance(sid, int):
            int_steps[sid] = name
        elif sid is not None:
            other_ids.add(str(sid))
    return data, int_steps, other_ids


def _docs():
    docs_dir = _find_docs_dir()
    if docs_dir is None:
        pytest.skip(
            "ALL_STEPS docs not found (repo-root docs/architecture is not "
            "synced into the plugin mirror/cache) — guard runs in the dev "
            "tree + repo CI where the docs live."
        )
    en = (docs_dir / _EN_NAME).read_text()
    zh = (docs_dir / _ZH_NAME).read_text()
    return en, zh


# ─────────────────────────────────────────────────────────────────────────
# Layer 1 — id-set coverage (the recurrence-killer)
# ─────────────────────────────────────────────────────────────────────────

def test_en_integer_step_ids_match_flow_exactly():
    _data, int_steps, _other = _load_flow()
    en, _zh = _docs()
    expected = set(int_steps)
    actual = _doc_integer_ids(en)
    missing = sorted(expected - actual)
    phantom = sorted(actual - expected)
    assert not missing, (
        f"{_EN_NAME} is MISSING flow steps {missing} — they exist in the flow "
        f"yaml but have no numbered table row in the doc. "
        f"Examples: {[(i, int_steps[i]) for i in missing[:3]]}"
    )
    assert not phantom, (
        f"{_EN_NAME} has PHANTOM step rows {phantom} not present in the flow "
        f"yaml (id range is 1..{max(expected)})."
    )


def test_zh_integer_step_ids_match_flow_exactly():
    _data, int_steps, _other = _load_flow()
    _en, zh = _docs()
    expected = set(int_steps)
    actual = _doc_integer_ids(zh)
    missing = sorted(expected - actual)
    phantom = sorted(actual - expected)
    assert not missing, (
        f"{_ZH_NAME} is MISSING flow steps {missing} (no numbered row). "
        f"Examples: {[(i, int_steps[i]) for i in missing[:3]]}"
    )
    assert not phantom, (
        f"{_ZH_NAME} has PHANTOM step rows {phantom} not in the flow yaml."
    )


def test_headline_step_count_matches_flow():
    data, int_steps, _other = _load_flow()
    en, zh = _docs()
    total = max(int_steps)
    assert total == data.get("total_steps"), (
        f"flow yaml internal inconsistency: max integer id {total} != "
        f"total_steps {data.get('total_steps')}"
    )
    assert f"{total} sequential steps" in en, (
        f"{_EN_NAME} headline must claim '{total} sequential steps' "
        f"(matches flow total_steps={total})."
    )
    assert f"{total} 個循序步驟" in zh, (
        f"{_ZH_NAME} headline must claim '{total} 個循序步驟' "
        f"(matches flow total_steps={total})."
    )


def test_parallel_and_preflight_tracks_present():
    _data, _int, other_ids = _load_flow()
    en, zh = _docs()
    # A1..A9, M1..M4, P0 are referenced verbatim by id; the single yaml D1
    # step is expanded to D1..D5 in the doc, so require at least 'D1'.
    require = {tok for tok in other_ids if tok != "D1"} | {"D1"}
    for tok in sorted(require):
        assert tok in en, f"{_EN_NAME} does not mention track id '{tok}'"
        assert tok in zh, f"{_ZH_NAME} does not mention track id '{tok}'"


# ─────────────────────────────────────────────────────────────────────────
# Layer 2 — name-concept (EN doc only; zh names are translated)
# ─────────────────────────────────────────────────────────────────────────

def test_en_step_rows_describe_the_right_step():
    _data, int_steps, _other = _load_flow()
    en, _zh = _docs()
    mismatches = []
    for sid, name in sorted(int_steps.items()):
        row = _doc_row_text(en, sid)
        if row is None:
            continue  # covered by Layer 1
        salient = _salient_tokens(name)
        if not salient:
            continue  # name had no identity-bearing token (won't happen today)
        if not any(tok in row for tok in salient):
            mismatches.append((sid, name, sorted(salient)))
    assert not mismatches, (
        "These EN doc rows share NO salient token with the flow step name "
        "(row may describe the wrong step): "
        + "; ".join(f"step {s} '{n}' expected one of {t}" for s, n, t in mismatches)
    )
