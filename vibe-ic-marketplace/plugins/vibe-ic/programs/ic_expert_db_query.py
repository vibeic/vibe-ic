#!/usr/bin/env python3
"""ic_expert_db_query.py — GENERAL-CORE retrieval over the IC Expert DB.

The IC Expert DB (`agents/ic_expert_db/ic_expert_db.json`) is a structured,
chip-AGNOSTIC design-class knowledge base (algorithm correctness / interface
convention / latency-reset discipline / common traps), distilled from
proven-correct designs. This module surfaces the RELEVANT lessons for a design
under authoring — consumed by the GENERAL Vibe-IC path (design_one_shot_runner's
spec-to-rtl / ic-expert authoring step), NOT a benchmark-only path. Any Phase-1
design doc or user prompt gets the same knowledge.

ADVISORY layer: lessons are design-craft ADVICE for the AI author; they never
override a deterministic gate/program verdict (enforced by
ic_expert_db_consistency_check.py).

Retrieval = structured ic_class match + lexical keyword/function-noun overlap
(NO vectors — IC knowledge is structured, so lexical+class match is precise).

Usage:
    ic_expert_db_query.py --prompt <file|-> [--k 5] [--db <path>]
    # prints the matched lessons (ready to inject into the author's context)
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

_DEFAULT_DB = (Path(__file__).resolve().parent.parent
               / "agents" / "ic_expert_db" / "ic_expert_db.json")

# design-family function-noun stems — the strongest "same kind of design" signal
_FN_STEMS = ["divid","divis","multipl","booth","adder","subtract","alu","mac","accumulat",
    "aes","sha","hmac","cipher","crc","galois","scrambl","lfsr","prbs","hamming","ecc",
    "axi","apb","ahb","wishbone","spi","uart","i2c","fifo","stream","serdes","serial",
    "cache","sdram","ddr","tlb","lru","register","ram","buffer","stack","lifo","skid",
    "fir","iir","filter","fft","sigma","delta","decimat","interpolat","cordic",
    "arbiter","interrupt","sequencer","microcode","vending","elevator","stopwatch",
    "counter","timer","sort","merge","priority","encoder","decoder","mux","shift",
    "gcd","fibonacci","booth","sprite","rotate","grayscale","border","line","vga",
    "clock","glitch","cdc","synchron","edge","perceptron","neuro","matrix","transform"]

def _fn(text: str) -> set:
    t = text.lower()
    return {s for s in _FN_STEMS if s in t}

def _kw(text: str) -> set:
    toks = re.findall(r"[A-Za-z_]{4,}", text.lower())
    stop = {"module","input","output","the","and","for","with","that","this","should",
            "must","when","value","signal","width","bit","bits","data","design",
            "implement","following","using","based","output","inputs","outputs"}
    return {w for w in toks if w not in stop}

def query(prompt: str, k: int = 5, db_path: Path = _DEFAULT_DB,
          expand_related: bool = False):
    """Retrieve the top-k relevant lessons for `prompt`.

    `expand_related` is OPT-IN (default False → byte-identical to the tuned
    lexical ranking). When True, after the ranked top-k is chosen, one lesson
    from each ic_class in the TOP hit's `related[]` graph is appended (score 0.0,
    tagged `related_to`) — a synthesis view that follows the concept links. It is
    off by default because an A/B on 94 designs showed that widening the author's
    context LOWERED recovery, so the production spec-to-rtl path keeps the tight
    top-k; the graph expansion is for maintenance / explicit synthesis queries.
    """
    db = json.loads(Path(db_path).read_text())
    entries = db.get("entries", [])
    q_fn, q_kw = _fn(prompt), _kw(prompt)
    ranked = []
    for e in entries:
        cls = e.get("ic_class", "")
        c_fn = _fn(cls)
        for les in e.get("lessons", []):
            l_fn = _fn(cls + " " + les)
            fn_ov = len(q_fn & l_fn)
            kw_ov = len(q_kw & _kw(les))
            score = 12.0 * len(q_fn & c_fn) + 4.0 * fn_ov + 0.5 * kw_ov
            if score > 0:
                ranked.append((score, cls, les))
    ranked.sort(key=lambda x: -x[0])
    # dedup identical lessons, keep top-k
    out, seen = [], set()
    for s, cls, les in ranked:
        if les in seen:
            continue
        seen.add(les)
        out.append({"ic_class": cls, "score": round(s, 2), "lesson": les})
        if len(out) >= k:
            break
    if expand_related and out:
        by_class = {e.get("ic_class"): e for e in entries}
        seed = out[0]["ic_class"]
        # `.get("related") or []` (not `.get("related", [])`) — an explicit
        # related:null (which the gate treats as "absent") must not crash expand.
        for r in (by_class.get(seed, {}).get("related") or []):
            rentry = by_class.get(r)
            if not rentry or not rentry.get("lessons"):
                continue
            les = rentry["lessons"][0]
            if les in seen:
                continue
            seen.add(les)
            out.append({"ic_class": r, "score": 0.0, "lesson": les, "related_to": seed})
            if len(out) >= 2 * k:
                break
    return out

def render(hits) -> str:
    if not hits:
        return ""
    lines = ["## IC Expert DB — relevant design-class knowledge (advisory)",
             "Proven design-craft for similar designs. Apply the algorithm / "
             "interface / latency insight; the deterministic gates still decide PASS.\n"]
    for h in hits:
        lines.append(f"- **[{h['ic_class']}]** {h['lesson']}")
    return "\n".join(lines) + "\n"

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True, help="prompt file, or '-' for stdin")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of rendered digest")
    ap.add_argument("--expand-related", action="store_true",
                    help="follow the top hit's related[] concept links (synthesis view; "
                         "OFF by default — the production path keeps the tight top-k)")
    a = ap.parse_args(argv)
    text = sys.stdin.read() if a.prompt == "-" else Path(a.prompt).read_text(errors="replace")
    hits = query(text, a.k, a.db, expand_related=a.expand_related)
    print(json.dumps(hits, indent=2, ensure_ascii=False) if a.json else render(hits))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
