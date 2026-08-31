"""CVDP scorer glue validates envelopes but never solves a task."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[2] / "benchmark"
sys.path.insert(0, str(BENCHMARK))

import score_cvdp_open as scorer  # noqa: E402


def test_response_parser_preserves_exact_order_and_rejects_empty(tmp_path):
    path = tmp_path / "responses.jsonl"
    path.write_text("\n".join([
        json.dumps({"id": "a", "completion": "module a; endmodule"}),
        json.dumps({"id": "b", "completion": ""}),
    ]) + "\n")
    rows, errors = scorer._response_rows(path)
    assert [row["id"] for row in rows] == ["a"]
    assert errors == ["line 2: completion is empty"]
