"""Drive the optional transition-role API explicitly, outside normal metadata reads.

These certificate tests retain their original native queries and assertions.
The normal structural entry point no longer runs this optional SAT analysis.
"""
import json
from pathlib import Path
from unittest.mock import patch

import formal_structural_check as fsc

_entry_check = fsc.check
_transition_mapping = fsc.reset_control_mapping


def transition_check(rtl_files, top, claims, work_dir, container=None, simdef="", klass=None):
    # Suppress the former implicit invocation when the same test bytes run
    # against BASE; both arms below call the actual native API explicitly.
    with patch.object(fsc, "reset_control_mapping", return_value={}):
        rec = _entry_check(rtl_files, top, claims, work_dir, container, simdef, klass)
    tag = "_reset_memory" if rec.get("reset_memory_construction") and all(
        p["inside"] for p in rec["reset_memory_construction"]) else ""
    optimized_path = Path(work_dir) / f"formal_structural_netlist{tag}.json"
    raw_path = Path(work_dir) / f"formal_structural_netlist{tag}_raw.json"
    optimized, raw = (json.loads(p.read_text()) for p in (optimized_path, raw_path))
    mappings = {}
    for claim in rec["claims"]:
        if claim["rule"] not in {"reset_port", "reset_sync", "reset_polarity"}:
            continue
        if claim.get("finding", "").startswith("outside the claim's supported class"):
            continue
        signal = claim.get("signal", "")
        if signal not in mappings:
            mapping = _transition_mapping(optimized, raw, top, signal,
                Path(work_dir) / f"reset_transition_0_{signal.encode().hex()}", container)
            mapping["source_binding"] = {
                "rtl_sha256": rec["rtl_sha256"], "defines": rec["elaborations"][0]["defines"],
                "optimized_netlist_sha256": fsc.file_sha256(optimized_path),
                "raw_netlist_sha256": fsc.file_sha256(raw_path),
                "scope": "same-invocation source next-state roles; not optimized-state coverage"}
            mappings[signal] = mapping
        answer = fsc.check_claim(optimized, top, claim, mappings[signal])
        claim.clear()
        claim.update(answer)
    rec["verdict"] = (fsc.PASS if rec["claims"] and all(c["verdict"] == fsc.PASS for c in rec["claims"])
                      else fsc.REFUTED if any(c["verdict"] == fsc.REFUTED for c in rec["claims"])
                      else fsc.NOT_DISCHARGED)
    return rec


def transition_main(argv):
    with patch.object(fsc, "check", transition_check):
        return fsc.main(argv)
