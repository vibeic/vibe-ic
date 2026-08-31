"""Canonical benchmark entry docs must name shipped command/data targets.

The harness directory was relocated from ``benchmark-harness/`` to
``benchmark/``.  These docs are copied directly into agent commands, so a
stale example is an executable failure rather than harmless prose drift.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]

ENTRY_DOCS = sorted((PLUGIN / "benchmark").glob("*.md"))
ENTRY_DOCS += sorted((PLUGIN / "benchmark" / "examples").glob("*.md"))
ENTRY_DOCS += [
    PLUGIN / "commands" / "vibe-ic-benchmark.md",
    PLUGIN / "skills" / "open-benchmark-methodology" / "SKILL.md",
    PLUGIN / "skills" / "benchmark-enhancement-capture" / "SKILL.md",
]

DOCUMENTED_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:\$\{CLAUDE_PLUGIN_ROOT\}/|<plugin>/)?"
    r"(?P<relative>(?:benchmark(?:-harness)?|programs)/"
    r"[A-Za-z0-9_./-]+\.(?:py|json))\b"
)


def _missing_targets(text: str, plugin_root: Path):
    references = [Path(m.group("relative"))
                  for m in DOCUMENTED_TARGET.finditer(text)]
    missing = [relative for relative in references
               if not (plugin_root / relative).is_file()]
    return references, missing


def test_all_benchmark_entry_doc_targets_are_shipped():
    references = []
    missing = []
    for doc in ENTRY_DOCS:
        doc_references, doc_missing = _missing_targets(
            doc.read_text(encoding="utf-8"), PLUGIN)
        references.extend((doc.relative_to(PLUGIN), path)
                          for path in doc_references)
        missing.extend((doc.relative_to(PLUGIN), path) for path in doc_missing)

    assert len(references) >= 20, (
        "sanity check: canonical benchmark docs should expose their commands")
    assert any(path == Path("programs/benchmark_dispatch.py")
               for _, path in references), references
    assert not missing, "missing documented Python targets: " + ", ".join(
        f"{doc}: {path}" for doc, path in missing)


def test_missing_documented_target_is_detected():
    references, missing = _missing_targets(
        "python3 ${CLAUDE_PLUGIN_ROOT}/benchmark-harness/not_shipped.py --x",
        PLUGIN,
    )

    expected = Path("benchmark-harness/not_shipped.py")
    assert references == [expected]
    assert missing == [expected]
