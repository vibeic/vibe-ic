"""D71 row-local metric bindings over existing native GLS evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path




_D71_FIXTURES = Path(__file__).resolve().parent / "fixtures/flow109_d71"


def _frozen_D71_sources():
    sources = json.loads((_D71_FIXTURES / "frozen-b74-operation-sources-713.json").read_text())
    provenance = json.loads(
        (_D71_FIXTURES / "frozen-b74-operation-sources-713.provenance.json").read_text())
    return sources, provenance


















def test_frozen_b74_population_accepts_only_real_consumer_induced_AST_growth():
    recorded, provenance = _frozen_D71_sources()
    canonical = json.dumps(recorded, sort_keys=True, separators=(",", ":")).encode()
    assert len(recorded) == provenance["entry_count"] == 713
    assert hashlib.sha256(canonical).hexdigest() == provenance["canonical_json_sha256"] == (
        "c76f4ba79eacf8422687c6e1c6ca7c09db03a977ead119a2c1370f397d2f9e06")
    assert all(not Path(name).is_absolute() and name.startswith("programs/")
               for name in recorded)
    native_sources = provenance["native_producer_sources"]
    assert native_sources and set(native_sources) <= set(recorded)
    assert {name: recorded[name] for name in native_sources} == native_sources
