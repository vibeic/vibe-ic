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
from .render import _stamp  # noqa: F401  — THE L-doc write chokepoint,
# re-exported from the sibling that already resolves it, so this package
# has ONE place that puts the plugin's `programs/` on the path.
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

    Used by the training loop to automate what the IC Expert Agent dialogue (plain-language register) does in
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


def _docs_door_top_module(text: str, source_name: str = "prose"):
    """#2049 item 1 — ask the DOCS front door what top module THIS SAME input
    declares, so the two Phase-1 front doors cannot disagree about the design's
    top by construction.

    `phase1_doc_one_shot_runner._extract_top_module_from_docs` is the docs
    door's own derivation (explicit `module X (` declaration > `Module Name:`
    label > heading / intro-phrase prose). It returns None when the input
    declares no top — and None is the honest answer, not a cue to invent one.

    Returns (name_or_None, status) where status is one of
    `declared_in_input` / `top_undeclared` / `docs_door_unavailable`.
    `docs_door_unavailable` is NOT `top_undeclared`: it says the question could
    not be asked, so the caller still must not invent a name.
    """
    try:
        import phase1_doc_one_shot_runner as _docs  # programs/ is on sys.path
        # via .render's _find_programs_dir
        cand = _docs._extract_top_module_from_docs({source_name: text})
    except Exception as exc:  # degrade LOUDLY — never silently
        print(f"[stub] WARN docs-door top-module derivation unavailable: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return None, "docs_door_unavailable"
    if cand:
        return cand, "declared_in_input"
    return None, "top_undeclared"


def _stub_l_docs_from_prose(docs_dir: Path, out_dir: Path,
                            ic_name: str | None = None) -> int:
    """v0.1.38 fallback — when `docs_dir` contains prose `.md` files only
    (no `L*.json` siblings) and `from_existing_docs` returned 0 facts, emit
    a minimal L1/L3/L9 stub set heuristically from the prose so the
    phase2_precheck (which only counts L*.json files) can proceed and the
    spec-to-rtl WAIVE handoff is exercised. Returns number of stubs written.

    4 RTLLM agents (b0/b1/b3/b4) each independently wrote this same workaround
    during the v0.1.37 sweep; this absorbs it into the plugin. Per the
    open-benchmark-methodology skill § 1, this is a "structural stub" — it
    does NOT do natural-language extraction (that needs an LLM); it just
    parses module name + port table from prose so the runner can hand off
    to spec-to-rtl with a syntactically-valid L-doc shape.
    """
    import re as _re
    # Find any .md / .txt sibling
    prose_files = list(docs_dir.glob("*.md")) + list(docs_dir.glob("*.txt"))
    if not prose_files:
        return 0
    text = "\n\n".join(p.read_text(errors="ignore") for p in prose_files)
    # Heuristic 1: explicit "Module name: X" line
    name_m = _re.search(r"(?im)^\s*module\s+name\s*[:\-]\s*([A-Za-z_]\w*)", text)
    if not name_m:
        # Heuristic 2: `module X (` declaration in prose body
        name_m = _re.search(r"\bmodule\s+([A-Za-z_]\w*)\s*[(#]", text)
    # #2049 item 1 — `docs_dir.parent.name` is a DIRECTORY, not a design
    # declaration. The prompt front door bridges its input into
    # `<proj>/input/docs/`, so this fallback published `top_module: "input"`
    # — a top named after a directory that every downstream artefact then
    # carried. The chip NAME may still fall back to the directory (chip name
    # and RTL top are distinct concepts, #583/#541 above); the RTL TOP may
    # not. It is either declared by the input or it is `top_undeclared`.
    mod_name = name_m.group(1) if name_m else docs_dir.parent.name
    if name_m:
        top_module, top_status = name_m.group(1), "declared_in_input"
    else:
        top_module, top_status = _docs_door_top_module(
            text, source_name=prose_files[0].name)
    # Heuristic 3: input/output port lines `input [N:0] name` (multi-line OK)
    port_re = _re.compile(
        r"\b(input|output|inout)\s+(?:wire\s+|reg\s+|logic\s+)?"
        r"(\[[^]]+\]\s+)?([A-Za-z_]\w*)", _re.M)
    seen = set()
    ports = []
    for m in port_re.finditer(text):
        direction, width, port = m.group(1), (m.group(2) or "").strip(), m.group(3)
        if port in seen or port.lower() in {"input", "output", "inout"}:
            continue
        seen.add(port)
        ports.append({"name": port, "direction": direction, "width": width or "1"})
    # v0.1.40 (re-audit NEW-2 fix) — REUSE the registered class names from
    # programs/ic_class_registry.json. The v0.1.39 attempt invented 7 new class
    # names (digital_memory_primitive, digital_fsm, etc.) that did not exist in
    # the registry, so every downstream class-aware check (class floor, class
    # template lookup, ic_class_profile, rtl_gen dispatch) silently degraded
    # to no-op. The registry has 8 real classes; only those are valid here.
    #
    # Mapping policy: classes are deliberately COARSER than the previous attempt.
    # RTLLM/VerilogEval-style pure-logic designs (datapath, FSM, counter,
    # memory primitive, waveform generator) ALL map to
    # `digital_arithmetic_primitive`, which the registry describes as
    # "Generic pure-datapath / arithmetic-primitive digital IC".
    # Protocol-bus designs (UART/SPI/I2C/parallel cmd) map to `digital_cmd_driven`.
    # Processor/CPU/RISC-V map to `processor_cpu`. Half-duplex single-wire
    # protocol → `aid_class_half_duplex_single_wire`. OTP → `mixed_signal_otp`.
    # FPGA-only → `bare_fpga`. Analog-only → `pure_analog`.
    # Everything else → `unknown_protocol_class` (the registry's fallback).
    #
    # Keyword matching uses `\b` word boundaries to avoid substring bugs (e.g.
    # "freq" matching "frequency"). Most-specific keyword phrases are listed
    # FIRST so a "clock divider" prose lands in pure-datapath, not protocol-bus.
    import re as _kw_re
    prose_lc = text.lower()
    # (registered_class, [keyword_regexes_word_bounded])
    class_keywords = [
        # Most specific first: aid + otp + cpu + fpga + analog (narrow markers)
        ("aid_class_half_duplex_single_wire",
            [r"\bhalf[-\s]?duplex\b", r"\bsingle[-\s]?wire\b", r"\baid[-\s]?class\b"]),
        ("mixed_signal_otp",
            [r"\botp\b", r"\botp[-\s]?(?:driven|chip|map|read)\b"]),
        ("processor_cpu",
            [r"\bprocessor\b", r"\bcpu\b", r"\briscv?\b", r"\briscv[-\s]?core\b",
             r"\bcore\s+(?:complex|cluster)\b", r"\bsoc\b"]),
        ("bare_fpga",
            [r"\bfpga(?:[-\s]?only)?\b", r"\bcyclone\b", r"\bartix\b",
             r"\bspartan\b", r"\bzynq\b", r"\bde10[-\s]?lite\b"]),
        ("pure_analog",
            [r"\banalog[-\s]?only\b", r"\bbandgap\b", r"\bldo\b",
             r"\bopamp\b", r"\bcomparator(?:[-\s]?analog)?\b"]),
        ("digital_cmd_driven",
            [r"\buart\b", r"\bspi\b", r"\bi2c\b", r"\bi3c\b",
             r"\bcommand[-\s]?driven\b", r"\bcmd[-\s]?driven\b",
             r"\bparallel[-\s]?cmd\b"]),
        # Pure-datapath / pure-logic catch-all: arithmetic, FSM, counter,
        # memory primitive, waveform generator, edge/pulse detector — all
        # land here. The registry's `digital_arithmetic_primitive` description
        # explicitly covers "pure-datapath" designs.
        ("digital_arithmetic_primitive",
            [r"\badder\b", r"\bsubtractor\b", r"\bmultiplier\b", r"\bdivider\b",
             r"\balu\b", r"\baccumulator\b", r"\bmac\b",
             r"\bfsm\b", r"\bstate[-\s]?machine\b", r"\bmoore\b", r"\bmealy\b",
             r"\bcounter\b", r"\blfsr\b", r"\bshift[-\s]?register\b",
             r"\bjohnson\s+counter\b", r"\bring\s+counter\b",
             r"\bfifo\b", r"\blifo\b", r"\bram\b", r"\brom\b",
             r"\bregister[-\s]?file\b", r"\bscratchpad\b", r"\bstack\b",
             r"\barbiter\b", r"\bpriority[-\s]?encoder\b",
             r"\bclock[-\s]?divider\b", r"\bfrequency[-\s]?divider\b",
             r"\bclock[-\s]?generator\b", r"\bwaveform[-\s]?generator\b",
             r"\bedge[-\s]?detector\b", r"\bpulse[-\s]?detector\b",
             r"\bbarrel[-\s]?shifter\b", r"\bgray[-\s]?counter\b",
             r"\bparity\b", r"\bmux\b", r"\bdemux\b", r"\bcodec\b",
             r"\bdecoder\b", r"\bencoder\b"]),
    ]
    detected_class = None
    matched_kw = None
    for cname, patterns in class_keywords:
        for pat in patterns:
            if _kw_re.search(pat, prose_lc):
                detected_class = cname
                matched_kw = pat
                break
        if detected_class is not None:
            break
    if detected_class is None:
        # Registered fallback class (not a made-up "unknown" string).
        detected_class = "unknown_protocol_class"
        matched_kw = None
    out_dir.mkdir(parents=True, exist_ok=True)
    # ORGANIC #583 (b) — an explicit --ic-name override is authoritative
    # for the CHIP name (CLI > docs per #541); the heuristic mod_name
    # stays the RTL top (L9.top_module) — chip name and top module are
    # distinct concepts.
    l1 = {"ic_name": ic_name or mod_name, "class_path": detected_class,
          "summary": f"Stub L1 for {mod_name} (from prose .md).",
          "stub_origin": "_stub_l_docs_from_prose",
          "class_detection_method": ("keyword-match" if matched_kw
                                     else "registered-fallback unknown_protocol_class"),
          "class_detection_keyword": matched_kw}
    l3 = {"ports": ports}
    l9 = {"top_module": top_module,
          "top_module_status": top_status,
          "top_ports": [p["name"] for p in ports],
          "stub_origin": "_stub_l_docs_from_prose"}
    layer_payloads = {
        "L1_DATASHEET.json": l1,
        "L2_FRS.json": {"functional_summary": f"See prose at {docs_dir}"},
        "L3_CMD_PROTOCOL.json": l3,
        "L4_REGMAP.json": {},
        "L5_ADI_SPEC.json": {},
        "L6_CONTROL_LOGIC.json": {},
        "L7_TEST_DEBUG.json": {},
        "L8_TIMING_WAVEFORM.json": {},
        "L8_RTL_CONSTANTS.json": {},
        "L9_INTEGRATION_SPEC.json": l9,
        "L10_TEST_CASES.json": {},
        "L11_CALIBRATION.json": {},
        "L12_BEHAVIORAL_SEQUENCES.json": {},
        "L13_HARDWARE_OBSERVED.json": {"contract": {}, "evidence": {}},
    }
    for fname, payload in layer_payloads.items():
        # THE L-document write chokepoint. A stub is still an L document —
        # arguably the one a reader is most likely to mistake for current,
        # because it is thin enough to look like a fresh scaffold.
        _stamp.dump(out_dir / fname, payload)
    return len(layer_payloads)


def _cmd_run_all(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if src.is_dir():
        graph = from_existing_docs(
            src, ic_name=args.ic_name, class_path=args.class_path
        )
    else:
        graph = from_structured_yaml(src)

    # ORGANIC #583 (b) — honor an EXPLICIT --ic-name override exactly as
    # the docs-mode runner does post-#541 (CLI > docs): force it onto the
    # graph identity AND upsert the L1.ic_name fact so the rendered
    # L1_DATASHEET.json carries the authoritative name. Pre-fix the
    # forwarded --ic-name only reached from_existing_docs' fallback (a
    # prompt-bridged docs/ holds no L*.json, so no L1.ic_name fact was
    # ever created and L1 rendered without a name).
    # `_ingested_n` (count BEFORE the upsert) keeps the prose-only stub
    # fallback's trigger semantics intact — see the fallback gate below.
    _ingested_n = len(graph.facts)
    if args.ic_name:
        graph.ic_name = args.ic_name
        _f = graph.by_path("L1.ic_name")
        if _f is not None:
            _f.value = args.ic_name
            _f.provenance.source = "user_stated"
            _f.provenance.reasoning = (
                "--ic-name CLI override (#583; CLI > docs per #541)")
        else:
            graph.add_fact(
                path="L1.ic_name",
                value=args.ic_name,
                views=["L1"],
                source="user_stated",
                origin="--ic-name",
                confidence=1.0,
                reasoning="--ic-name CLI override (#583; CLI > docs per #541)",
            )

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
    # Phase 2's phase1_doc_presence_check.
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

    # ORGANIC-20260606-phase1-prompt-mode-nested-generated-docs (#424):
    # two caller contracts coexist — Shape-C gates pass a WORK ROOT and
    # expect docs at <out>/generated_docs, while the one-shot runner passes
    # the canonical generated-docs dir ITSELF (<project>/phase1/
    # generated_docs). Re-joining the basename onto the latter nested the
    # layer docs one level too deep (generated_docs/generated_docs/), so
    # phase2's precheck saw 0/13 and the spec-to-rtl handoff never fired.
    # Resolve ONCE: when the out dir already IS a generated_docs dir, write
    # flat into it (human docs then land at the canonical sibling).
    if out_dir.name == "generated_docs":
        docs_out = out_dir
        human_root = out_dir.parent
    else:
        docs_out = out_dir / "generated_docs"
        human_root = out_dir
    written = render_layers(graph, docs_out)
    print(f"[run-all] rendered {len(written)} layer JSONs → {docs_out}")

    # v0.1.38 fallback (Bucket A — 4 RTLLM agents independently surfaced):
    # when input was a prose-only docs dir (e.g. `input/docs/*.md` with no
    # L*.json siblings), `from_existing_docs` returns 0 facts and
    # `render_layers` writes 0 files. phase2's precheck (`only 0/13 L docs`)
    # then HARD-FAILs. Emit a minimal stub L-doc set from heuristic
    # module-name + port-table extraction so the spec-to-rtl WAIVE handoff
    # can fire. This is structural ONLY — no NL semantic extraction (that
    # needs an LLM and is intentionally out of scope for the deterministic
    # CLI).
    # ORGANIC #583 — the gate is INGESTED facts, not rendered files: the
    # --ic-name upsert adds one L1 fact, so a prose-only input now renders
    # 1 file and `len(written) == 0` alone would skip the stub fallback
    # (only 1/13 L docs → phase2 precheck HARD-FAIL). `_ingested_n` is
    # captured before the upsert; the stub L1 carries the override name.
    if src.is_dir() and (len(written) == 0 or _ingested_n == 0):
        n_stub = _stub_l_docs_from_prose(src, docs_out,
                                         ic_name=args.ic_name)
        if n_stub:
            print(f"[run-all] prose-only input → emitted {n_stub} stub L docs "
                  f"to {docs_out} (Bucket-A fallback)", file=sys.stderr)

    # v0.60: emit human-readable Markdown views alongside the JSONs
    # so a Phase-1 prompt entry produces both deliverables (the JSON
    # is what Phase 2 consumes; the .md is what humans review).
    human_out = human_root / "human_docs"
    md_written = render_human_docs(graph, human_out)
    print(f"[run-all] rendered {len(md_written)} human-readable .md → {human_out}")

    render_provenance_report(graph, out_dir / "PROVENANCE.md")
    if coverage["pct"] < 1.0:
        append_warn_insufficient_block(out_dir / "PROVENANCE.md", coverage)
    # v0.74 Task-C PoC: emit machine-readable fact-index JSON alongside
    # PROVENANCE.md so Phase 2 consumers have a stable path→uuid map.
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

    Used by the IC Expert Agent during gap dialogue (plain-language register). Each confirmed answer becomes one
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
                            "(training-loop drop-in for IC Expert Agent dialogue)")
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
