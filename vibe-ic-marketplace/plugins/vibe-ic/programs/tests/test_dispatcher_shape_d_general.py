"""Anti-keyword regression for the benchmark dispatcher.

Per memory 'enhancements must be general, not keyword': the Shape-D path must
NOT branch on any specific benchmark name. JSONL-shaped datasets go through
the general extractor (agentic_jsonl_to_shape_d.py); already-laid-out subdir
datasets get discovered by a general glob.

WHY THE LAST TWO TESTS NO LONGER PIN THOSE TWO STRINGS
======================================================
They used to assert that `agentic_jsonl_to_shape_d.py` and `work/PROMPT.txt`
appear in `benchmark_dispatch.py`. `e9ec0ce1c1` ("benchmark: remove
dataset-specific solve shortcuts") deleted `cmd_setup()` — the whole `--setup`
verb — and with it the ONLY Shape-D branch, which was also the only caller of
the general extractor and the only place doing the `work/PROMPT.txt` rglob.
`31385d6ffb` then carried other dropped contracts onto the new entry surface
and did not carry these.

Pasting either string back into a docstring makes both greps pass while Shape D
stays unreachable and the policy governs nothing. So the SCOPE was decided
instead and written down (`BENCHMARK_REGISTRY.json:_dispatcher_scope`): the
dispatcher implements Shape B and Shape C; Shape D is run by the benchmark's
own agent harness. These tests now hold that decision to its consequences in
BOTH directions — a Shape-D dataset must not become dispatchable while the
registry still says it is out of scope, and the declaration must not outlive
the code that makes it true.
"""
import json
import re
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
DISPATCH = PROGRAMS / "benchmark_dispatch.py"
REGISTRY = PROGRAMS.parent / "benchmark" / "BENCHMARK_REGISTRY.json"
_GENERAL_EXTRACTOR = "agentic_jsonl_to_shape_d.py"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _dispatcher_routes_shape_d() -> bool:
    """Does the dispatcher name the general Shape-D extractor at all?"""
    return _GENERAL_EXTRACTOR in DISPATCH.read_text()


def _bench_format() -> dict:
    """`_BENCH_FORMAT` read from the source, without importing the module."""
    import ast
    tree = ast.parse(DISPATCH.read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "_BENCH_FORMAT"
                        for t in node.targets)):
            return ast.literal_eval(node.value)
    raise AssertionError("_BENCH_FORMAT is gone from benchmark_dispatch.py")


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
    """A JSONL Shape-D dataset is routed through the GENERAL extractor, or it
    is not routed at all — never through a bench-named one.

    The negative half is unconditional: `cvdp_jsonl_extract.py` is the
    bench-specific extractor this file exists to keep out, and no scope
    decision licenses it back.

    The positive half is a DISJUNCTION with an exclusive-or, not a text pin:
    either the dispatcher names the general extractor (it has a Shape-D path,
    and that path is general), or the registry declares Shape D out of the
    dispatcher's scope. Both true is a contradiction — a live Shape-D path
    while the registry says there is none — and it fails here.
    """
    src = DISPATCH.read_text()
    assert "cvdp_jsonl_extract.py" not in src, (
        "a bench-named JSONL extractor is back in the dispatcher")
    for stem in ("cvdp", "rtllm", "verilogeval", "pyhdl"):
        assert f"{stem}_jsonl_extract" not in src, (
            f"bench-named extractor {stem}_jsonl_extract in the dispatcher")

    routes = _dispatcher_routes_shape_d()
    scope = _registry().get("_dispatcher_scope")
    declared_out = (isinstance(scope, dict)
                    and "D" not in (scope.get("implements_shapes") or []))
    assert routes or declared_out, (
        f"the dispatcher names no Shape-D extractor and the registry does not "
        f"declare Shape D out of scope — {_GENERAL_EXTRACTOR} is orphaned and "
        f"nothing says so; decide and record it in "
        f"BENCHMARK_REGISTRY.json:_dispatcher_scope")
    assert not (routes and declared_out), (
        f"the dispatcher routes Shape D through {_GENERAL_EXTRACTOR} while the "
        f"registry still declares Shape D out of its scope — the declaration "
        f"outlived the code; update _dispatcher_scope.implements_shapes")


def test_dispatch_falls_back_to_subdir_discovery_for_shape_d():
    """Dataset LAYOUT knowledge stays out of the dispatcher, and the shapes it
    accepts stay the shapes it implements.

    The original pin (`'work/PROMPT.txt' in src`) asserted the presence of the
    general subdir-discovery rglob. With no Shape-D verb there is no discovery
    to pin, and re-adding the string would pin a comment. What the pin was
    PROTECTING is still checkable and is checked here: a dataset laid out as
    per-problem directories must never be reached by a per-benchmark layout
    literal, and a benchmark whose registry shape the dispatcher does not
    implement must not be dispatchable.

    Fails if someone adds a Shape-D (or any unimplemented-shape) benchmark to
    `_BENCH_FORMAT` without either wiring the general path or moving the shape
    into `_dispatcher_scope.implements_shapes` — which the previous test then
    holds to the general extractor.

    A per-benchmark LAYOUT-literal scan was written here and REMOVED after
    measuring it: substring-matching every registry `layout` value against the
    dispatcher source reported three hits, and all three were artefacts of the
    instrument. `cvdp.layout.harness_subdir='score'` matches 77 unrelated
    occurrences of the word, and `module_name_strategy='always_TopModule'`
    matches `benchmark_dispatch.py:1908`, which READS that declared strategy
    from the registry and compares — the general pattern, not a leak. A check
    whose every finding is its own false positive is worse than no check.
    """
    reg = _registry()
    scope = reg.get("_dispatcher_scope")
    assert isinstance(scope, dict), (
        "BENCHMARK_REGISTRY.json no longer declares _dispatcher_scope — the "
        "set of shapes the dispatcher implements must be written down, not "
        "inferred from which verbs happen to exist")
    implemented = set(scope.get("implements_shapes") or [])
    assert implemented, "_dispatcher_scope.implements_shapes is empty"

    benchmarks = reg["benchmarks"]
    offenders = []
    for bench in _bench_format():
        entry = benchmarks.get(bench)
        assert entry is not None, (
            f"the dispatcher accepts {bench!r}, which the registry does not "
            f"describe at all")
        shapes = {s.strip() for s in str(entry.get("shape", "")).split("/")
                  if s.strip()}
        if not shapes & implemented:
            offenders.append((bench, entry.get("shape")))
    assert not offenders, (
        f"the dispatcher accepts benchmarks whose registry shape it does not "
        f"implement {offenders}; implemented={sorted(implemented)}")

