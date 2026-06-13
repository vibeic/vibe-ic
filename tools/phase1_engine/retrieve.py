"""Retrieve — top-K nearest trained ICs via token-Jaccard over L1 facts.

Wraps tools/training/ic_similarity_index.py so the render pipeline can use
its seed-template output as one fact source (provenance = "retrieved").

If the similarity index hasn't been built yet, this module still works
returning an empty list (retrieval is opportunistic, not mandatory).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import List, Optional, Tuple

from .schema import FactGraph


_SIM_SCRIPT = Path("tools/training/ic_similarity_index.py")
_INDEX_PATH = Path("tools/training/ic_similarity_index.json")


def _load_sim_module():
    if not _SIM_SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("ic_sim", str(_SIM_SCRIPT))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod


def top_k_for_graph(graph: FactGraph, k: int = 5) -> List[Tuple[str, float]]:
    """Return [(ic_name, score), ...] top-K most similar trained ICs."""
    mod = _load_sim_module()
    if mod is None:
        return []
    # Build a query string from the graph's L1 summary facts.
    chunks: List[str] = [graph.ic_name]
    purpose = graph.by_path("L1.overview.purpose")
    if purpose and isinstance(purpose.value, str):
        chunks.append(purpose.value)
    features = graph.by_path("L1.overview.key_features")
    if features and isinstance(features.value, list):
        chunks.extend(str(x) for x in features.value)
    query = " ".join(chunks)

    if not _INDEX_PATH.exists():
        return []
    try:
        results = mod.query_index(query, k=k, index_path=_INDEX_PATH)  # type: ignore[attr-defined]
    except AttributeError:
        # Older version — look for a top-level query() function instead.
        if hasattr(mod, "query"):
            results = mod.query(query, k=k)  # type: ignore[attr-defined]
        else:
            return []
    except Exception:
        return []
    if not results:
        return []
    # Normalize to [(name, score)]
    out: List[Tuple[str, float]] = []
    for item in results:
        if isinstance(item, tuple) and len(item) >= 2:
            out.append((str(item[0]), float(item[1])))
        elif isinstance(item, dict) and "ic_name" in item:
            out.append((item["ic_name"], float(item.get("score", 0.0))))
    return out
