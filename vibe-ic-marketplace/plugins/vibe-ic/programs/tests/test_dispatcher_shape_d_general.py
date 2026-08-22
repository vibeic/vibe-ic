"""Anti-keyword regression for the benchmark dispatcher.

Per memory 'enhancements must be general, not keyword': the Shape-D setup
path must NOT branch on any specific benchmark name. JSONL-shaped datasets
go through the general extractor (agentic_jsonl_to_shape_d.py); already-laid-
out subdir datasets get discovered via work/PROMPT.txt globbing.
"""
import re
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
DISPATCH = PROGRAMS / "benchmark_dispatch.py"


def test_dispatch_setup_has_no_bench_name_branch():
    """The cmd_setup() function must not contain `bench == "cvdp"` (or similar
    benchmark-name string comparisons). The Shape-D path must be schema-driven."""
    src = DISPATCH.read_text()
    forbidden = [
        re.compile(r'bench\s*==\s*["\']cvdp["\']'),
        re.compile(r'bench\s*==\s*["\']rtllm["\']'),
        re.compile(r'bench\s*==\s*["\']verilogeval[-_]?v2["\']'),
        re.compile(r'bench\s*==\s*["\']verilogeval[-_]?human["\']'),
        re.compile(r'bench\s*==\s*["\']pyhdl[-_]?eval["\']'),
    ]
    for pat in forbidden:
        m = pat.search(src)
        assert m is None, (
            f"Found bench-name branch {m.group()!r} in benchmark_dispatch.py — "
            f"setup logic must be schema-driven, not keyword-driven.")


def test_dispatch_routes_jsonl_datasets_through_general_extractor():
    """When the Shape-D dataset contains *.jsonl, the dispatcher must call the
    general extractor (agentic_jsonl_to_shape_d.py), not a bench-specific one."""
    src = DISPATCH.read_text()
    assert "agentic_jsonl_to_shape_d.py" in src
    # And the old bench-specific extractor reference must be gone
    assert "cvdp_jsonl_extract.py" not in src


def test_dispatch_falls_back_to_subdir_discovery_for_shape_d():
    """When --dataset doesn't contain JSONL, fall through to general subdir
    discovery — work/PROMPT.txt rglob — not a bench-specific layout."""
    src = DISPATCH.read_text()
    assert 'work/PROMPT.txt' in src
