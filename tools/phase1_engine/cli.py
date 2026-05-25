#!/usr/bin/env python3
"""Phase-1 fact-graph CLI.

Verbs:
    ingest-docs       <generated_docs_dir> → facts.yaml (reverse-extract)
    ingest-yaml       <structured.yaml>    → facts.yaml (structured input)
    ingest-pins       <pins.csv>           → L1.pinout.* facts
    ingest-regmap-csv <regmap.csv>         → L4.registers.* facts
    ingest-otp-hex    <otp.hex>            → L4.otp.* facts (Intel HEX or raw)
    gaps              <facts.yaml>         → gaps report (stdout + json)
    render            <facts.yaml> <out_dir> → L1..L9 JSON
    run-all           <input.yaml|docs_dir> <out_dir>
                                            → ingest → gaps → render
    retrieve          <facts.yaml>         → top-K nearest trained ICs
    round-trip        <docs_dir>           → ingest then render back to
                                             a sibling dir for diff testing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .ingest import (
    from_existing_docs,
    from_structured_yaml,
    from_pin_csv,
    from_regmap_csv,
    from_otp_hex,
    merge,
)
from .schema import FactGraph, Provenance, Fact
from .gap_detect import auto_fill, detect_gaps, DEFAULT_CLASS_KB
from .render import (
    DEFAULT_HARD_GATE_THRESHOLD,
    InsufficientRequiredFactsError,
    append_warn_insufficient_block,
    enforce_required_facts_threshold,
    render_human_docs,
    render_layers,
    render_provenance_report,
    render_fact_index,
)
from .retrieve import top_k_for_graph
from .nl_ingest import (
    build_extract_prompt,
    call_anthropic_extract,
    from_extracted_facts,
)


def _cmd_ingest_docs(args: argparse.Namespace) -> int:
    graph = from_existing_docs(
        Path(args.docs_dir),
        ic_name=args.ic_name,
        class_path=args.class_path,
    )
    out = Path(args.out or "facts.yaml")
    graph.save(out)
    print(f"[ingest-docs] wrote {len(graph.facts)} facts → {out}")
    return 0


def _cmd_ingest_yaml(args: argparse.Namespace) -> int:
    graph = from_structured_yaml(Path(args.yaml_path))
    out = Path(args.out or "facts.yaml")
    graph.save(out)
    print(f"[ingest-yaml] wrote {len(graph.facts)} facts → {out}")
    return 0


def _apply_bulk(graph: FactGraph, args: argparse.Namespace, label: str) -> int:
    """Save a freshly-parsed bulk graph, optionally merging into an
    existing facts.yaml under --merge-into."""
    if args.merge_into:
        base = FactGraph.load(Path(args.merge_into))
        merge(base, graph)
        out = Path(args.out or args.merge_into)
        base.save(out)
        print(f"[{label}] merged {len(graph.facts)} facts → {out} "
              f"(total {len(base.facts)})")
    else:
        out = Path(args.out or "facts.yaml")
        graph.save(out)
        print(f"[{label}] wrote {len(graph.facts)} facts → {out}")
    return 0


def _cmd_ingest_pins(args: argparse.Namespace) -> int:
    graph = from_pin_csv(Path(args.csv_path))
    return _apply_bulk(graph, args, "ingest-pins")


def _cmd_ingest_regmap_csv(args: argparse.Namespace) -> int:
    graph = from_regmap_csv(Path(args.csv_path))
    return _apply_bulk(graph, args, "ingest-regmap-csv")


def _cmd_ingest_otp_hex(args: argparse.Namespace) -> int:
    graph = from_otp_hex(Path(args.hex_path))
    return _apply_bulk(graph, args, "ingest-otp-hex")


def _cmd_gaps(args: argparse.Namespace) -> int:
    graph = FactGraph.load(Path(args.facts))
    gaps = detect_gaps(graph)
    report = {
        "ic_name": graph.ic_name,
        "class_path": graph.class_path,
        "gap_count": len(gaps),
        "gaps": [g.as_dict() for g in gaps],
    }
    out_json = Path(args.out_json) if args.out_json else None
    if out_json:
        out_json.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if not gaps else 3


def _cmd_auto_fill(args: argparse.Namespace) -> int:
    """Apply every gap's suggested_default into the fact graph.

    Used by the training loop to automate what PM Agent dialogue does in
    interactive mode: fill required-but-missing facts with K3 / class
    reference defaults, so subsequent `render` + gates have enough content
    to pass.
    """
    graph = FactGraph.load(Path(args.facts))
    summary = auto_fill(graph)
    out = Path(args.out or args.facts)
    graph.save(out)
    print(
        f"[auto-fill] filled={summary['filled']}  "
        f"no_default={summary['no_default']}  "
        f"sentinels={summary.get('sentinels_added',0)}  "
        f"total_gaps={summary['total_gaps']}  "
        f"→ {out}"
    )
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    graph = FactGraph.load(Path(args.facts))

    # v1.6.271 — for #130 hard-gate + structured WARN. Hard-gate refuses
    # to render when <50% of class-required facts are satisfied unless
    # --allow-underspec is supplied. Either way, a WARN block is appended
    # to PROVENANCE.md (when --provenance-report is supplied) and a
    # single stderr summary line is printed.
    try:
        coverage = enforce_required_facts_threshold(
            graph,
            threshold=args.underspec_threshold,
            allow_underspec=args.allow_underspec,
        )
    except InsufficientRequiredFactsError as e:
        print(f"[render] ERROR: {e}", file=sys.stderr)
        # Still write a WARN block to PROVENANCE.md if the caller asked
        # for one — gives the field-agent a structured artefact even on
        # hard-gate refusal.
        if args.provenance_report:
            # Need a fresh provenance report first so the WARN block has
            # context; emit a minimal one with just the header.
            render_provenance_report(graph, Path(args.provenance_report))
            append_warn_insufficient_block(
                Path(args.provenance_report),
                {"pct": e.pct, "total": 0, "satisfied": 0,
                 "missing_by_layer": e.missing_by_layer},
            )
        return 2

    if coverage["pct"] < 1.0:
        n_missing = sum(len(v) for v in coverage["missing_by_layer"].values())
        print(
            f"[render] WARN_INSUFFICIENT_REQUIRED_FIELDS "
            f"pct={coverage['pct']:.2f} missing={n_missing} layers="
            f"{sorted(coverage['missing_by_layer'].keys())}",
            file=sys.stderr,
        )

    written = render_layers(graph, Path(args.out_dir), layers=args.layers)
    for code, p in sorted(written.items()):
        print(f"[render] {code} → {p}")
    if args.human_docs_dir:
        md_written = render_human_docs(graph, Path(args.human_docs_dir),
                                        layers=args.layers)
        for code, p in sorted(md_written.items()):
            print(f"[render] {code} → {p}")
    if args.provenance_report:
        render_provenance_report(graph, Path(args.provenance_report))
        if coverage["pct"] < 1.0:
            append_warn_insufficient_block(
                Path(args.provenance_report), coverage,
            )
        print(f"[render] provenance report → {args.provenance_report}")
    if args.fact_index:
        render_fact_index(graph, Path(args.fact_index))
        print(f"[render] fact index → {args.fact_index}")
    return 0


def _cmd_run_all(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if src.is_dir():
        graph = from_existing_docs(
            src, ic_name=args.ic_name, class_path=args.class_path
        )
    else:
        graph = from_structured_yaml(src)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    facts_path = out_dir / "facts.yaml"
    graph.save(facts_path)
    print(f"[run-all] ingested {len(graph.facts)} facts → {facts_path}")

    gaps = detect_gaps(graph)
    (out_dir / "gaps.json").write_text(
        json.dumps({"gap_count": len(gaps), "gaps": [g.as_dict() for g in gaps]},
                   indent=2)
    )
    print(f"[run-all] {len(gaps)} gaps → {out_dir/'gaps.json'}")

    # v1.6.271 — for #130 hard-gate + structured WARN before render so
    # an under-specified prompt is caught at Phase 1 rather than at
    # Phase 2b's phase1_doc_presence_check.
    try:
        coverage = enforce_required_facts_threshold(
            graph,
            threshold=args.underspec_threshold,
            allow_underspec=args.allow_underspec,
        )
    except InsufficientRequiredFactsError as e:
        print(f"[run-all] ERROR: {e}", file=sys.stderr)
        render_provenance_report(graph, out_dir / "PROVENANCE.md")
        append_warn_insufficient_block(
            out_dir / "PROVENANCE.md",
            {"pct": e.pct, "total": 0, "satisfied": 0,
             "missing_by_layer": e.missing_by_layer},
        )
        return 2

    if coverage["pct"] < 1.0:
        n_missing = sum(len(v) for v in coverage["missing_by_layer"].values())
        print(
            f"[run-all] WARN_INSUFFICIENT_REQUIRED_FIELDS "
            f"pct={coverage['pct']:.2f} missing={n_missing} layers="
            f"{sorted(coverage['missing_by_layer'].keys())}",
            file=sys.stderr,
        )

    docs_out = out_dir / "generated_docs"
    written = render_layers(graph, docs_out)
    print(f"[run-all] rendered {len(written)} layer JSONs → {docs_out}")

    # v0.60: emit human-readable Markdown views alongside the JSONs
    # so a Phase-1 prompt entry produces both deliverables (the JSON
    # is what Phase 2b consumes; the .md is what humans review).
    human_out = out_dir / "human_docs"
    md_written = render_human_docs(graph, human_out)
    print(f"[run-all] rendered {len(md_written)} human-readable .md → {human_out}")

    render_provenance_report(graph, out_dir / "PROVENANCE.md")
    if coverage["pct"] < 1.0:
        append_warn_insufficient_block(out_dir / "PROVENANCE.md", coverage)
    # v0.74 Task-C PoC: emit machine-readable fact-index JSON alongside
    # PROVENANCE.md so Phase 2b consumers have a stable path→uuid map.
    render_fact_index(graph, out_dir / "fact_index.json")
    return 0 if not gaps else 3


def _cmd_retrieve(args: argparse.Namespace) -> int:
    graph = FactGraph.load(Path(args.facts))
    results = top_k_for_graph(graph, k=args.k)
    print(json.dumps(results, indent=2))
    return 0


def _load_text_arg(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if args.text_file:
        return Path(args.text_file).read_text()
    return sys.stdin.read()


def _cmd_nl_prompt(args: argparse.Namespace) -> int:
    """Output the extraction prompt only — for callers without API access.

    The caller is expected to run an LLM on the returned prompt, then feed
    the resulting JSON back via `ingest-extracted`.
    """
    text = _load_text_arg(args)
    prompt = build_extract_prompt(
        text,
        class_path=args.class_path,
        class_kb_root=Path(args.class_kb_root),
    )
    print(prompt)
    return 0


def _cmd_nl_ingest(args: argparse.Namespace) -> int:
    """Full NL flow — calls Anthropic API if available, else falls back
    to printing the prompt and asking the caller to supply a facts JSON."""
    text = _load_text_arg(args)

    use_api = args.use_api or (
        not args.prompt_only and os.environ.get("ANTHROPIC_API_KEY")
    )
    if args.prompt_only or not use_api:
        prompt = build_extract_prompt(
            text, class_path=args.class_path,
            class_kb_root=Path(args.class_kb_root),
        )
        if args.out_prompt:
            Path(args.out_prompt).write_text(prompt)
            print(f"[nl-ingest] prompt → {args.out_prompt}")
            print("[nl-ingest] run an LLM on this prompt, then call "
                  "`ingest-extracted <json>` to load facts.")
        else:
            print(prompt)
        return 0

    model = args.model or os.environ.get("PHASE1_NL_MODEL")
    if not model:
        print("[nl-ingest] error: no model specified — pass --model <id> "
              "or set $PHASE1_NL_MODEL", file=sys.stderr)
        return 2
    extracted = call_anthropic_extract(
        text,
        class_path=args.class_path,
        class_kb_root=Path(args.class_kb_root),
        model=model,
    )
    graph = from_extracted_facts(
        extracted,
        class_path=args.class_path,
        ic_name=args.ic_name,
        source_text=text,
    )
    out = Path(args.out or "facts.yaml")
    graph.save(out)
    print(f"[nl-ingest] extracted {len(graph.facts)} facts → {out}")
    return 0


def _cmd_ingest_extracted(args: argparse.Namespace) -> int:
    extracted = json.loads(Path(args.json_file).read_text())
    text = Path(args.text_file).read_text() if args.text_file else None
    graph = from_extracted_facts(
        extracted,
        class_path=args.class_path,
        ic_name=args.ic_name,
        source_text=text,
    )
    out = Path(args.out or "facts.yaml")
    graph.save(out)
    print(f"[ingest-extracted] {len(graph.facts)} facts → {out}")
    return 0


def _cmd_set_fact(args: argparse.Namespace) -> int:
    """Interactive gap-fill: add/override a single fact.

    Used by PM Agent during gap dialogue. Each confirmed answer becomes one
    fact with source=user_stated.
    """
    graph = FactGraph.load(Path(args.facts))
    layer = args.path.split(".", 1)[0]
    try:
        value = json.loads(args.value)
    except (ValueError, json.JSONDecodeError):
        value = args.value  # plain string
    graph.add_fact(
        path=args.path,
        value=value,
        views=[layer],
        source=args.source,
        origin=args.origin or "pm_dialogue",
        confidence=1.0 if args.source == "user_stated" else 0.9,
        reasoning=args.reasoning or "",
    )
    graph.save(Path(args.facts))
    print(f"[set-fact] {args.path} = {value!r} ({args.source})")
    return 0


def _cmd_round_trip(args: argparse.Namespace) -> int:
    src = Path(args.docs_dir)
    out_dir = Path(args.out_dir or (src.parent / (src.name + "_rendered")))
    graph = from_existing_docs(src)
    facts_path = out_dir / "facts.yaml"
    out_dir.mkdir(parents=True, exist_ok=True)
    graph.save(facts_path)
    docs_out = out_dir / "generated_docs"
    render_layers(graph, docs_out)
    print(f"[round-trip] facts: {facts_path}")
    print(f"[round-trip] render: {docs_out}")
    print(f"[round-trip] diff these against {src} to verify semantic equivalence")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="phase1_engine", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ingest-docs", help="reverse-extract facts from L*.json dir")
    a.add_argument("docs_dir")
    a.add_argument("--out")
    a.add_argument("--ic-name")
    a.add_argument("--class-path")
    a.set_defaults(fn=_cmd_ingest_docs)

    a = sub.add_parser("ingest-yaml", help="ingest structured YAML (layer-keyed)")
    a.add_argument("yaml_path")
    a.add_argument("--out")
    a.set_defaults(fn=_cmd_ingest_yaml)

    a = sub.add_parser("ingest-pins",
                       help="ingest a pin-table CSV → L1.pinout.* facts")
    a.add_argument("csv_path")
    a.add_argument("--out")
    a.add_argument("--merge-into",
                   help="existing facts.yaml to merge into (leaves --out unset "
                        "to overwrite that file)")
    a.set_defaults(fn=_cmd_ingest_pins)

    a = sub.add_parser("ingest-regmap-csv",
                       help="ingest a register-map CSV → L4.registers.* facts")
    a.add_argument("csv_path")
    a.add_argument("--out")
    a.add_argument("--merge-into")
    a.set_defaults(fn=_cmd_ingest_regmap_csv)

    a = sub.add_parser("ingest-otp-hex",
                       help="ingest an OTP hex image (Intel HEX or raw hex) → L4.otp.* facts")
    a.add_argument("hex_path")
    a.add_argument("--out")
    a.add_argument("--merge-into")
    a.set_defaults(fn=_cmd_ingest_otp_hex)

    a = sub.add_parser("auto-fill",
                       help="apply every gap's suggested_default into facts.yaml "
                            "(training-loop drop-in for PM Agent dialogue)")
    a.add_argument("facts", help="path to facts.yaml to augment")
    a.add_argument("--out", help="output path (defaults to overwriting input)")
    a.set_defaults(fn=_cmd_auto_fill)

    a = sub.add_parser("gaps", help="detect required-but-missing facts")
    a.add_argument("facts")
    a.add_argument("--out-json")
    a.set_defaults(fn=_cmd_gaps)

    a = sub.add_parser("render",
                       help="render facts.yaml → L*.json (+ optional human-readable .md)")
    a.add_argument("facts")
    a.add_argument("out_dir")
    a.add_argument("--layers", nargs="*", default=None)
    a.add_argument("--provenance-report", help="also write a Markdown audit")
    a.add_argument("--fact-index",
                   help="also write a path→uuid JSON map (v0.74 PoC for "
                        "fact-level feedback from Phase 2/2b — see "
                        "docs/design/PHASE1_FACT_UUID_PROPOSAL.md)")
    a.add_argument("--human-docs-dir",
                   help="also render human-readable Markdown views of every "
                        "L*.json into this directory (Phase-1 prompt entry "
                        "should always emit these alongside the JSON; v0.60)")
    # v1.6.271 — for #130 partial-set WARN + hard-gate
    a.add_argument("--allow-underspec", action="store_true",
                   help="render even when required_facts_satisfied_pct is "
                        "below --underspec-threshold; a WARN block is still "
                        "written to --provenance-report and a stderr summary "
                        "line is printed (v1.6.271 — for #130)")
    a.add_argument("--underspec-threshold", type=float,
                   default=DEFAULT_HARD_GATE_THRESHOLD,
                   help=f"hard-gate threshold for required-facts coverage "
                        f"(default {DEFAULT_HARD_GATE_THRESHOLD})")
    a.set_defaults(fn=_cmd_render)

    a = sub.add_parser("run-all", help="ingest + gaps + render in one step")
    a.add_argument("input", help="structured yaml OR existing docs dir")
    a.add_argument("out_dir")
    a.add_argument("--ic-name")
    a.add_argument("--class-path")
    # v1.6.271 — for #130 partial-set WARN + hard-gate
    a.add_argument("--allow-underspec", action="store_true",
                   help="render even when required_facts_satisfied_pct is "
                        "below --underspec-threshold (v1.6.271 — for #130)")
    a.add_argument("--underspec-threshold", type=float,
                   default=DEFAULT_HARD_GATE_THRESHOLD,
                   help=f"hard-gate threshold for required-facts coverage "
                        f"(default {DEFAULT_HARD_GATE_THRESHOLD})")
    a.set_defaults(fn=_cmd_run_all)

    a = sub.add_parser("retrieve", help="top-K similar trained ICs")
    a.add_argument("facts")
    a.add_argument("--k", type=int, default=5)
    a.set_defaults(fn=_cmd_retrieve)

    a = sub.add_parser("round-trip",
                       help="reverse-extract then re-render for diff testing")
    a.add_argument("docs_dir")
    a.add_argument("--out-dir")
    a.set_defaults(fn=_cmd_round_trip)

    # Natural-language pipeline -------------------------------------------------
    class_kb_default = str(DEFAULT_CLASS_KB)

    a = sub.add_parser("nl-prompt",
                       help="print the LLM extraction prompt for user text")
    a.add_argument("--text", help="natural-language description inline")
    a.add_argument("--text-file", help="path to text file (or stdin if omitted)")
    a.add_argument("--class-path", required=True,
                   help="e.g. cable-side-id-ic")
    a.add_argument("--class-kb-root", default=class_kb_default)
    a.set_defaults(fn=_cmd_nl_prompt)

    a = sub.add_parser("nl-ingest",
                       help="natural-language → facts.yaml (calls Anthropic "
                            "API if ANTHROPIC_API_KEY set, else writes "
                            "extraction prompt only)")
    a.add_argument("--text", help="natural-language description inline")
    a.add_argument("--text-file", help="path to text file (or stdin if omitted)")
    a.add_argument("--class-path", required=True)
    a.add_argument("--class-kb-root", default=class_kb_default)
    a.add_argument("--ic-name", help="explicit IC name override")
    a.add_argument("--out", help="output facts.yaml path (default facts.yaml)")
    a.add_argument("--use-api", action="store_true",
                   help="force Anthropic API call even if --prompt-only")
    a.add_argument("--prompt-only", action="store_true",
                   help="never call API; only emit extraction prompt")
    a.add_argument("--out-prompt", help="write extraction prompt to this path")
    a.add_argument("--model",
                   default=None,
                   help="Anthropic model ID (required when calling API; "
                        "can also be set via $PHASE1_NL_MODEL env var)")
    a.set_defaults(fn=_cmd_nl_ingest)

    a = sub.add_parser("ingest-extracted",
                       help="load facts JSON produced externally by an LLM")
    a.add_argument("json_file")
    a.add_argument("--class-path", required=True)
    a.add_argument("--ic-name")
    a.add_argument("--text-file",
                   help="original user text (for provenance hash)")
    a.add_argument("--out", help="output facts.yaml path")
    a.set_defaults(fn=_cmd_ingest_extracted)

    a = sub.add_parser("set-fact",
                       help="set / override one fact (gap-dialogue drop-in)")
    a.add_argument("facts", help="path to facts.yaml")
    a.add_argument("--path", required=True,
                   help="layer-prefixed dotted path, e.g. "
                        "'L3.frame_format.crc.poly'")
    a.add_argument("--value", required=True,
                   help="fact value (scalar, or JSON for dict/list)")
    a.add_argument("--source", default="user_stated",
                   choices=[
                       "user_stated", "defaulted", "derived",
                       "retrieved", "class_floor", "class_required",
                       "inferred",
                   ])
    a.add_argument("--origin", default="")
    a.add_argument("--reasoning", default="")
    a.set_defaults(fn=_cmd_set_fact)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    sys.exit(main())
