"""Shared technology-LEF discovery and selection for staged PDKs.

The Phase-3 runner and every gate that judges the runner's technology stack
must resolve the same file from the same authorities.  This module deliberately
does not know any PDK, vendor, design, layer prefix, or corner name.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Tuple


class TechLefResolutionError(RuntimeError):
    """The staged tree carried technology-LEF material but no unique choice."""


@dataclass(frozen=True)
class TechLefSelection:
    path: Path
    authority: str
    candidates: Tuple[Path, ...]
    note: str = ""


def discover_staged_tech_lefs(
        pdk_dir: Path,
        roots: Optional[Iterable[Path]] = None) -> Tuple[Path, ...]:
    """Return staged technology-LEF candidates in deterministic order.

    ``*.tlef`` is an explicit technology-LEF extension and therefore needs no
    filename heuristic.  A generic ``*.lef`` remains a candidate only when its
    filename says ``tech``, matching the Phase-3 runner's long-standing rule and
    avoiding standard-cell/macro LEFs.
    """
    scan_roots = tuple(roots) if roots is not None else (pdk_dir,)
    found = set()
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix == ".tlef" or (
                    suffix == ".lef" and "tech" in path.name.lower()):
                found.add(path)
    return tuple(sorted(found, key=lambda path: str(path)))


def _declared_path(pdk_dir: Path) -> Optional[Path]:
    cfg_f = pdk_dir / "bridge" / "signoff_config.json"
    if not cfg_f.is_file():
        return None
    try:
        declared = (json.loads(cfg_f.read_text()) or {}).get("tech_lef")
    except Exception:
        declared = None
    if not declared:
        return None
    path = ((pdk_dir / str(declared)) if not os.path.isabs(str(declared))
            else Path(str(declared)))
    if not path.is_file():
        raise TechLefResolutionError(
            f"[FAIL] bridge signoff_config declares tech_lef={declared!r} "
            f"but {path} does not exist. REFUSING to fall back to an "
            f"arbitrary stack — a sign-off produced against an unintended "
            f"metal stack looks identical to a correct one.")
    return path


def _match_selected_path(
        pdk_dir: Path, candidates: Sequence[Path], selected_path: str
        ) -> Optional[Path]:
    """Map a runner-recorded path back to the staged copy.

    Runner evidence commonly names a container path while the audit reads a
    project-staged mirror.  An exact project-relative match wins; a basename
    match is accepted only when unique.  Ambiguity is never broken by sort
    order.
    """
    raw = Path(str(selected_path))
    exact = raw if raw.is_absolute() else pdk_dir / raw
    exact_text = str(exact)
    exact_matches = [candidate for candidate in candidates
                     if str(candidate) == exact_text]
    if len(exact_matches) == 1:
        return exact_matches[0]

    try:
        relative_text = str(raw.relative_to(pdk_dir))
    except (ValueError, OSError):
        relative_text = str(raw)
    relative_matches = []
    for candidate in candidates:
        try:
            candidate_rel = str(candidate.relative_to(pdk_dir))
        except ValueError:
            candidate_rel = str(candidate)
        if candidate_rel == relative_text:
            relative_matches.append(candidate)
    if len(relative_matches) == 1:
        return relative_matches[0]

    basename_matches = [candidate for candidate in candidates
                        if candidate.name == raw.name]
    return basename_matches[0] if len(basename_matches) == 1 else None


def select_staged_tech_lef(
        pdk_dir: Path,
        candidates: Sequence[Path],
        *,
        selected_path: Optional[str] = None,
        selected_path_authority: Optional[str] = None,
        top_routing_layer: Optional[Callable[[Path], Optional[str]]] = None,
        routing_layer_count: Optional[Callable[[Path], int]] = None,
        ) -> Optional[TechLefSelection]:
    """Resolve one staged technology LEF and state why it was selected.

    Authority order is bridge declaration, exact runner evidence, one staged
    candidate, sign-off-deck structural narrowing, then refusal.  The optional
    callbacks keep LEF grammar ownership with the consumer while centralising
    the selection policy.
    """
    ordered = tuple(sorted(set(candidates), key=lambda path: str(path)))
    declared = _declared_path(pdk_dir)
    if declared is not None:
        return TechLefSelection(
            path=declared,
            authority="bridge.signoff_config.tech_lef",
            candidates=ordered,
            note=("DECLARED by bridge signoff_config: "
                  f"{declared.relative_to(pdk_dir)}"),
        )

    if selected_path:
        selected = _match_selected_path(pdk_dir, ordered, selected_path)
        if selected is None:
            listing = ", ".join(str(path) for path in ordered) or "none"
            raise TechLefResolutionError(
                f"[FAIL] run evidence selects tech LEF {selected_path!r}, "
                f"but it does not map to exactly one staged candidate. "
                f"REFUSING to guess. staged candidates: {listing}")
        return TechLefSelection(
            path=selected,
            authority=(selected_path_authority or "run_evidence.tech_lef"),
            candidates=ordered,
            note=f"selected by run evidence: {selected}",
        )

    if not ordered:
        return None
    if len(ordered) == 1:
        return TechLefSelection(
            path=ordered[0],
            authority="staged_pdk.single_candidate",
            candidates=ordered,
        )

    survivors = list(ordered)
    calibre_dir = pdk_dir / "calibre"
    deck = next(iter(sorted(calibre_dir.glob("*DRC*.rule"))), None) \
        if calibre_dir.is_dir() else None
    deck_note = ""
    if (deck is not None and top_routing_layer is not None
            and routing_layer_count is not None):
        try:
            deck_text = deck.read_text(errors="ignore")
        except OSError:
            deck_text = ""
        enabled = sorted(set(
            match.group(1) for match in re.finditer(
                r"(?m)^#DEFINE\s+TOPMETAL_(\d+)\s*$", deck_text)))
        if len(enabled) == 1:
            count = int(enabled[0])
            narrowed = [candidate for candidate in ordered
                        if (top_routing_layer(candidate) or "").upper().endswith(
                            str(count))
                        and routing_layer_count(candidate) == count]
            if narrowed:
                survivors = narrowed
                deck_note = (f"narrowed from {len(ordered)} by "
                             f"{deck.name} #DEFINE TOPMETAL_{count}")

    if len(survivors) == 1:
        return TechLefSelection(
            path=survivors[0],
            authority="staged_pdk.signoff_deck_topmetal",
            candidates=ordered,
            note=deck_note,
        )

    def _top(candidate: Path) -> Optional[str]:
        return top_routing_layer(candidate) if top_routing_layer else None

    listing = "\n".join(
        f"    {candidate.relative_to(pdk_dir)}  "
        f"(top routing layer {_top(candidate)})"
        for candidate in sorted(survivors))
    cfg_f = pdk_dir / "bridge" / "signoff_config.json"
    raise TechLefResolutionError(
        f"[FAIL] the staged PDK ships {len(ordered)} tech LEF(s) and "
        f"{len(survivors)} of them remain after narrowing"
        f"{(' (' + deck_note + ')') if deck_note else ''}. The metal stack "
        f"is a DESIGN CHOICE, so this flow will not pick one for you — an "
        f"arbitrary pick yields a fully green sign-off against a stack nobody "
        f"chose, which is indistinguishable from a correct one. Declare it: "
        f"set \"tech_lef\" (a path relative to input/pdk/) in "
        f"{cfg_f.relative_to(pdk_dir.parent.parent)}.\n"
        f"  candidates:\n{listing}")
