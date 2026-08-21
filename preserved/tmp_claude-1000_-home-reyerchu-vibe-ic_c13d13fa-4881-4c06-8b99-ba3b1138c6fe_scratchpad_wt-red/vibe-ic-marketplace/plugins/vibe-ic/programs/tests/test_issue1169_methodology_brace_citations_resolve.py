"""Every brace-notation evidence citation in `benchmark-data/ic/METHODOLOGY.md`
must point at something the repo actually ships.

MEASURED 2026-08-13 on `a38902d16`. `METHODOLOGY.md` cites its per-cell evidence
in shell brace notation — `u_hawaii_adc/{RESULT,BENCHMARK_VERIFICATION_REPORT}.md`,
`u_hawaii_adc/{phase3/analog,cross_check,reports}/` — and `95787ef8` deleted three
of those targets as "superseded evidence" while leaving the citing entry, and its
`[benchmark-verified 2026-05-26]` claim, untouched:

    u_hawaii_adc/RESULT.md                        deleted
    u_hawaii_adc/BENCHMARK_VERIFICATION_REPORT.md deleted
    u_hawaii_adc/cross_check/                     deleted

Nothing caught it for a week. `evidence_citation_resolves_check` is the gate whose
entire job is "a citation points at something that no longer exists", and it was
green throughout, because it could not parse brace notation at all (#1044). So the
one class of citation this file writes ALL of its per-cell evidence in was the one
class no gate read.

That is the gap this test closes, and it is deliberately scoped to it: brace
expansion, over the published-IC methodology file, against the tree. It is not a
duplicate of `evidence_citation_resolves_check` — that gate carries a baseline of
pre-existing unresolved plain-path citations (#1168), whereas the brace class
measured CLEAN once #1169's three targets were restored: 14 expanded citations,
0 unresolved. There is therefore no debt to grandfather here, and no baseline: a
new unresolved brace citation is a regression, full stop.

The paired guard is the deletion itself — remove any one restored target and this
test fails naming that path, which is exactly what did not happen in August.
"""
from __future__ import annotations

import re
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_IC = _REPO / "benchmark-data" / "ic"
_METHODOLOGY = _IC / "METHODOLOGY.md"


def _expand_braces(token: str) -> list[str]:
    """`a/{b,c}.md` -> ['a/b.md', 'a/c.md']; recurses for nested/multiple groups."""
    match = re.search(r"\{([^{}]*)\}", token)
    if not match:
        return [token]
    out: list[str] = []
    for alternative in match.group(1).split(","):
        out.extend(
            _expand_braces(
                token[: match.start()] + alternative.strip() + token[match.end() :]
            )
        )
    return out


def _brace_citations() -> list[str]:
    """Every backticked, brace-bearing relative path in METHODOLOGY.md, expanded.

    Citations wrap across source lines, so whitespace inside a backtick span is
    collapsed before expansion. Absolute paths are out of scope: they name a
    machine, not this repo, and are a different defect class.
    """
    text = _METHODOLOGY.read_text()
    cited: list[str] = []
    for span in re.findall(r"`([^`]+)`", text, flags=re.S):
        token = " ".join(span.split())
        if "/" not in token or "{" not in token:
            continue
        for path in _expand_braces(token):
            path = path.strip().rstrip(".,")
            if path and not path.startswith("/"):
                cited.append(path)
    return sorted(set(cited))


def test_methodology_ships_a_brace_citation_to_check() -> None:
    """A pass because the file stopped citing anything would be vacuous."""
    assert _METHODOLOGY.is_file(), f"missing {_METHODOLOGY}"
    citations = _brace_citations()
    assert len(citations) >= 10, (
        "METHODOLOGY.md should carry the per-cell brace-notation evidence "
        f"citations; expanded only {len(citations)}: {citations}"
    )


def test_every_brace_citation_resolves() -> None:
    unresolved = [p for p in _brace_citations() if not (_IC / p).exists()]
    assert not unresolved, (
        "benchmark-data/ic/METHODOLOGY.md cites evidence the repo does not ship "
        "(a published claim whose evidence a reader cannot follow):\n  "
        + "\n  ".join(unresolved)
    )
