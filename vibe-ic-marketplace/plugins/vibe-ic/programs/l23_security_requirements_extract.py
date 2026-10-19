"""Preserve source-declared security clauses in L23's existing typed fields.

This is an extractor, not a security verifier or a new admission gate. Heading
ancestry assigns explicit source sections to the typed record collections that
``l23_security_requirements_typed_check`` already reads. Statements, options,
limitations and negations remain verbatim. Neither successful extraction nor
the typed-record check proves that a countermeasure is implemented or secure.
Unclassified security semantics still need expert authoring; the producer
therefore reports PARTIALLY_EXTRACTED rather than complete extraction.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# The extractor is also loaded directly by file-based tooling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from l_doc_consumer_contract import input_doc_texts  # noqa: E402


_SECURITY_HEADING = re.compile(
    r"\b(?:security|side[- ]channel|fault[- ]injection|attack[- ]surface|"
    r"threat[- ]model|masking|key[- ](?:handling|management|storage|"
    r"provisioning|derivation|sideload|manager))\b", re.I)
_KEY_HEADING = re.compile(
    r"\bkey[- ](?:handling|management|storage|provisioning|derivation|"
    r"sideload|manager)\b", re.I)
_KEY_ASSET = re.compile(r"\b(?:keys?|key[- ]material|secret[- ]assets?)\b", re.I)
_SIDE_CHANNEL = re.compile(
    r"\b(?:side[- ]channel|masking|differential\s+power\s+analysis)\b", re.I)
_ATTACK = re.compile(
    r"\b(?:fault[- ]injection|attack[- ]surface|threat[- ]model|"
    r"tamper(?:ing)?)\b", re.I)


def extract_security_requirements(project: Path) -> Optional[Dict[str, Any]]:
    """Copy explicitly scoped sections, with independently locatable citations.

    Use the same document grammar as L2, without section or body caps. Only
    source headings establish security scope: incidental words in an unrelated
    pin table or operating requirement cannot become a security requirement.
    A child inherits its parent's category until a sibling or ancestor closes
    that section. No enabled/required posture is inferred from a keyword.
    """
    from phase1_doc_one_shot_runner import (
        _v1_6_334_extract_multi_shape_section_headers as headings,
        _v1_6_357_slice_section_body as section_body,
    )

    records: Dict[str, list] = {
        "key_handling": [], "attack_surface": [],
        "side_channel_mitigation": [],
    }
    for path, text in input_doc_texts(project):
        source = path.relative_to(project).as_posix()
        hits = headings(text, source_path=source, deduplicate=False)
        stack = []
        for index, hit in enumerate(hits):
            section = hit["section_id"]
            depth = (int(section[1:]) if section.startswith("h")
                     else len(section.rstrip(".").split(".")))
            while stack and stack[-1][0] >= depth:
                stack.pop()
            title = hit["title"]
            scoped = bool(_SECURITY_HEADING.search(title))
            scoped = scoped or bool(stack and stack[-1][1])
            categories = set(stack[-1][2]) if stack else set()
            if _KEY_HEADING.search(title):
                categories.add("key_handling")
            if _SIDE_CHANNEL.search(title):
                categories.add("side_channel_mitigation")
            if _ATTACK.search(title):
                categories.add("attack_surface")
            end = hits[index + 1]["match_pos"] if index + 1 < len(hits) else None
            body = section_body(text, hit["match_end"], end, max_chars=None)
            # Under an explicit security section, an asset reference is a
            # declared key-handling statement; copy the whole clause rather
            # than synthesizing a key lifecycle or a protection guarantee.
            if scoped and _KEY_ASSET.search(body):
                categories.add("key_handling")
            if scoped and _SIDE_CHANNEL.search(body):
                categories.add("side_channel_mitigation")
            if scoped and _ATTACK.search(body):
                categories.add("attack_surface")
            # Body-local mentions must not reclassify unrelated child sections.
            inherited = set(stack[-1][2]) if stack else set()
            if _KEY_HEADING.search(title):
                inherited.add("key_handling")
            if _SIDE_CHANNEL.search(title):
                inherited.add("side_channel_mitigation")
            if _ATTACK.search(title):
                inherited.add("attack_surface")
            stack.append((depth, scoped, inherited))
            if not scoped or not body:
                continue
            line = text.count("\n", 0, hit["match_pos"]) + 1
            for field in sorted(categories):
                records[field].append({
                    "name": title, "description": body,
                    "source": source, "evidence": f"{source}:{line}",
                })
    if not any(records.values()):
        return None
    return {
        **records,
        "security_requirements_present": True,
        "notes": (
            "Source-declared security sections are preserved with citations. "
            "Semantic interpretation and completeness require expert review; "
            "implementation and security effectiveness have not been verified."
        ),
    }
