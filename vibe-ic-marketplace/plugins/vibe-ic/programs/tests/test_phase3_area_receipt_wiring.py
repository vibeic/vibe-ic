from pathlib import Path
import sys

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase3_one_shot_runner.py"
FRONTDOOR = PROGRAMS / "vibe_ic_one_shot_runner.py"
sys.path.insert(0, str(PROGRAMS))


def test_canonical_synth_call_and_both_area_consumers_use_explicit_pair():
    source = RUNNER.read_text()
    assert "area_receipt=args.area_receipt" in source
    assert "area_run_manifest=args.area_run_manifest" in source
    assert source.count("*_area_receipt_flags(area_receipt, area_run_manifest)") == 1
    assert "_area_flags: List[str] = _area_receipt_flags(" in source
    assert "--area-receipt" in source and "--area-run-manifest" in source


def test_reverse_mutation_removing_consumer_bridge_is_detected():
    source = RUNNER.read_text()
    mutated = source.replace(
        "*_area_receipt_flags(area_receipt, area_run_manifest)", "*[]", 1)
    assert mutated != source
    assert "*_area_receipt_flags(area_receipt, area_run_manifest)" not in mutated
