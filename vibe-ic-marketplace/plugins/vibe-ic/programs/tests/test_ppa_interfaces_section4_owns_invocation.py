#!/usr/bin/env python3
"""Section 4 of `docs/PPA_INTERFACES.md` must give tool INVOCATION an owner.

THE DEFECT THIS FILE WAS WRITTEN AGAINST
========================================
The section-4 module map assigned tool PARSING to `_ppa/backends/*` and
assigned tool INVOCATION to nobody. The jppa-runner lane measured what that
costs: of the 8,745 PPA lines inside the 41,136-line
`programs/phase3_one_shot_runner.py`, 6,111 -- 70% -- anchor on functions that
start a container (`_docker_exec`, `_container_mounts`, `_to_container_path`,
`_tool_version`, ...). None of them can be extracted, because the contract
names no module for them to move to.

A silent map is not a neutral map. It reads, in practice, as "leave it in the
runner", which is a decision nobody made and nobody can cite. Section 4 has to
give an ANSWER -- either a module that owns invocation, or the explicit
sentence that invocation stays in the runner. This file fails on SILENCE.

WHAT IT DOES NOT DO
===================
It does not require the functions to have MOVED, and it does not name
`exec.py`. It looks for an OWNER of the invocation question by vocabulary, so
that the day somebody answers the question a different way -- a different
module name, or "invocation stays in the runner, deliberately" written into
the section -- this test keeps passing on the new answer and still fails on
no answer at all.

THE NEGATIVE CONTROL IS THE LOAD-BEARING PART. `_PRE_FIX_SECTION_4` below is
the verbatim map as it shipped at `bb90724dc`, and
`test_the_checker_rejects_the_map_as_it_shipped` runs the same checker over it
and requires SILENT. A test that cannot fail against the pre-fix text proves
nothing about the fix.

Chip-AGNOSTIC: flow vocabulary only -- no IC, vendor, SKU, node or codename.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_DOC = (Path(__file__).resolve().parents[2] / "docs" / "PPA_INTERFACES.md")

#: Words that name the act of RUNNING a tool, as opposed to reading what it
#: wrote. Matched as whole tokens against a module-map entry or the prose of
#: the section.
_INVOCATION_WORDS = ("invocation", "invoke", "invokes", "invoking",
                     "run", "runs", "running", "exec", "execute", "executes")

#: Words that name the container/tool the invocation drives. An entry has to
#: carry BOTH families, so a line about "running the search" is not mistaken
#: for a line about running a tool.
_TOOL_WORDS = ("container", "tool", "command", "docker", "subprocess")


def section(text: str, heading_prefix: str) -> str:
    """The body of one `## <n>. ...` section, heading line included.

    Refuses rather than returning "" when the heading is absent: an empty
    string satisfies every `not in` assertion below, so a checker that
    silently returns one is a gate that cannot fail.
    """
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(heading_prefix):
            start = i
            break
    if start is None:
        raise AssertionError(
            "[CANNOT CHECK] no section starting %r in the document -- the "
            "checker read nothing, which is NOT a clean result"
            % heading_prefix)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


def module_map(section_text: str) -> list:
    """The fenced module map inside a section, as a list of entry blocks.

    An entry starts at a line beginning with `_ppa/` and absorbs the indented
    continuation lines beneath it, so a two-line entry is one entry.
    """
    m = re.search(r"```\n(.*?)\n```", section_text, re.S)
    if not m:
        raise AssertionError(
            "[CANNOT CHECK] section 4 carries no fenced module map")
    entries, cur = [], None
    for ln in m.group(1).split("\n"):
        if ln.startswith("_ppa/"):
            if cur is not None:
                entries.append(cur)
            cur = ln
        elif cur is not None and ln.strip():
            cur += " " + ln.strip()
    if cur is not None:
        entries.append(cur)
    return entries


def _has_tokens(text: str, words) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(w), low)
               for w in words)


def invocation_owner(section_text: str):
    """The section's ANSWER to "who runs the tool", or None for SILENCE.

    Two shapes count as an answer:
      * a module-map entry whose description names both running and a tool;
      * a sentence in the section prose that says outright that invocation
        stays where it is (the "it should be an answer and not a silence"
        alternative the lane explicitly allowed).
    """
    for entry in module_map(section_text):
        name, _, desc = entry.partition(" ")
        if _has_tokens(desc, _INVOCATION_WORDS) and _has_tokens(
                desc, _TOOL_WORDS):
            return name
    for para in re.split(r"\n\s*\n", section_text):
        low = para.lower()
        if ("stays in the runner" in low or "remains in the runner" in low) \
                and _has_tokens(para, _INVOCATION_WORDS):
            return "runner (declared)"
    return None


#: The section-4 module map EXACTLY as it shipped at `bb90724dc`, kept so the
#: checker above is proven to fail on it. Do not "fix" this fixture.
_PRE_FIX_SECTION_4 = """## 4. Module map — one question per module

```
_ppa/canonical_json.py   serialization + sha256                       [FROZEN, done]
_ppa/timing.py           per-view timing rows from STA artefacts
_ppa/power.py            power split + activity basis provenance
_ppa/backends/{opensta,openroad,yosys,librelane,orfs}.py   tool-specific parsing only
```

A backend module parses one tool's output into canonical records and does
nothing else. No thresholds, no verdicts, no policy — those live in the domain
module, so that adding a tool never changes a rule.
"""


@pytest.fixture(scope="module")
def doc() -> str:
    assert _DOC.is_file(), "%s is missing" % _DOC
    return _DOC.read_text(encoding="utf-8")


# ======================================================================
# NON-VACUITY — the checker must be reading a real map before any verdict
# below is worth anything.
# ======================================================================
def test_the_map_is_read_and_is_not_empty(doc):
    entries = module_map(section(doc, "## 4."))
    assert len(entries) >= 12, (
        "only %d module-map entries were parsed; the checker is not reading "
        "the map it claims to check" % len(entries))


def test_a_missing_section_refuses_instead_of_passing_quietly():
    with pytest.raises(AssertionError) as exc:
        section("# a doc with no numbered sections\n", "## 4.")
    assert "CANNOT CHECK" in str(exc.value)


# ======================================================================
# POSITIVE — the shipped document answers the question.
# ======================================================================
def test_section_4_names_an_owner_for_tool_invocation(doc):
    owner = invocation_owner(section(doc, "## 4."))
    assert owner is not None, (
        "section 4 assigns tool PARSING to a module and tool INVOCATION to "
        "nobody. 6,111 of the runner's 8,745 PPA lines anchor on functions "
        "that start a container and have no module in this map to move to. "
        "Give the question an answer -- a module that owns invocation, or "
        "the explicit sentence that invocation stays in the runner.")


def test_the_invocation_owner_carries_no_policy(doc):
    """The invocation module obeys the backend rule: run it, do not judge it.

    An `exec` module that grew a threshold would put "did it run" and "is the
    number acceptable" back into one place, which is the arrangement section 4
    exists to prevent.
    """
    sec = section(doc, "## 4.")
    owner = invocation_owner(sec)
    assert owner is not None
    assert re.search(r"no thresholds,\s+no verdicts,\s+no policy", sec,
                     re.I), (
        "section 4 no longer states the no-policy rule that the invocation "
        "owner is required to follow")


# ======================================================================
# CONTROL — parsing was never the silent half, and must still be owned. If
# this ever fails together with the test above, the checker has stopped
# discriminating rather than the document having changed.
# ======================================================================
def test_section_4_still_assigns_tool_parsing(doc):
    entries = module_map(section(doc, "## 4."))
    assert any("parsing" in e.lower() for e in entries), (
        "no module-map entry owns tool parsing any more")


# ======================================================================
# NEGATIVE CONTROL — the same checker, over the map as it shipped.
# ======================================================================
def test_the_checker_rejects_the_map_as_it_shipped():
    assert invocation_owner(_PRE_FIX_SECTION_4) is None, (
        "the checker finds an invocation owner in the PRE-FIX map, so it "
        "would have passed before the fix and proves nothing")


def test_the_checker_accepts_the_stays_in_the_runner_answer():
    """The lane's words were: it should be an ANSWER and not a silence. The
    opposite answer is an answer, and this checker must accept it."""
    alt = _PRE_FIX_SECTION_4 + (
        "\nInvocation stays in the runner. It is not extracted, and that is a "
        "decision recorded here rather than an omission.\n")
    assert invocation_owner(alt) == "runner (declared)"
