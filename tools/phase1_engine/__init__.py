"""Vibe-IC Phase-1 fact-graph pipeline.

Replaces the v0.51 serial L1..L9 doc-gen skills with:

    user_input  →  facts.yaml (fact graph)  →  L1..L9 JSON

Three verbs:
    ingest   — any input format (structured YAML, existing L*.json, pin paste,
               reg-map CSV, OTP hex, free text) → facts.yaml
    resolve  — detect gaps vs class template; fill from K3 defaults or
               retrieved neighbours; flag high-impact conflicts for review
    render   — facts.yaml → L1_DATASHEET.json ... L9_INTEGRATION_SPEC.json
               (pure-Python projection; no LLM writes)

See tools/phase1_engine/README.md for design rationale.
"""
from .schema import Fact, FactGraph, Provenance

__all__ = ["Fact", "FactGraph", "Provenance"]
