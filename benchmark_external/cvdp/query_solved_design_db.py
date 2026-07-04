#!/usr/bin/env python3
"""query_solved_design_db.py — DB-native retrieval over the solved-design index.

Structured + lexical ranked match (NO vectors) — the same access pattern as
ip_catalog_query.query_catalog. Given a NEW design's prompt (its facts), returns
the top-K nearest SOLVED designs + their exemplar RTL path + lesson, so the
IC-Expert Agent can consult proven neighbours at author time.

Score = ic_class match (weight 3) + Jaccard over matches_when keywords (weight 10)
      + toplevel/port-name lexical overlap (weight 2). Deterministic.

Usage: query_solved_design_db.py --prompt <file> [--k 5] [--exclude <id>]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "solved_design_db" / "solved_design_index.json"

_CLASS_KW = {  # kept in sync with the builder
    "digital_arithmetic_primitive": ["adder","multiplier","divider","alu","mac","booth","cordic","sqrt","accumulat"],
    "crypto": ["aes","sha","hmac","cipher","crc","galois","rsa","md5","scrambl","lfsr","prbs"],
    "protocol_interface": ["axi","apb","ahb","wishbone","spi","uart","i2c","gmii","sata","usb","fifo","stream"],
    "memory_control": ["cache","sdram","ddr","tlb","lru","register_file","memory","ram","buffer"],
    "dsp_filter": ["fir","iir","filter","fft","dft","convolut","sigma_delta","interpolat","decimat"],
    "fsm_control": ["fsm","controller","sequencer","arbiter","vending","elevator","traffic","stopwatch","state"],
    "image_pixel": ["image","pixel","sprite","rotate","grayscale","border","line_buffer","vga"],
}

def infer_class(t: str) -> str:
    t = t.lower(); best, sc = "unknown_class", 0
    for cls, kws in _CLASS_KW.items():
        s = sum(t.count(k) for k in kws)
        if s > sc: best, sc = cls, s
    return best

def keywords(prompt: str) -> set:
    toks = re.findall(r"[A-Za-z_]{4,}", prompt.lower())
    stop = {"module","input","output","the","and","for","with","that","this","should","must","when","value","signal","width","bit","bits","data","design","implement","following","using","based"}
    return {w for w in toks if w not in stop}

# function-noun stems: the STRONGEST signal for "same kind of design"
_FN_STEMS = ["divid","divis","multipl","adder","add","subtract","alu","mac","booth",
    "aes","sha","hmac","cipher","crc","galois","scrambl","lfsr","prbs",
    "axi","apb","ahb","wishbone","spi","uart","i2c","fifo","stream","gmii",
    "cache","sdram","tlb","lru","register_file","ram","buffer",
    "fir","iir","filter","fft","sigma_delta","interpolat","decimat",
    "arbiter","sequencer","vending","elevator","stopwatch","counter",
    "sprite","rotate","grayscale","border","line_buffer","vga",
    "sort","priority","encoder","decoder","mux","shift","gcd","fibonacci"]

def _fn_stems(text: str) -> set:
    t = text.lower()
    return {s for s in _FN_STEMS if s in t}

def _port_sig(prompt: str) -> set:
    # port-like identifiers named in the prompt (Port List / interface) — the
    # strongest STRUCTURED match signal for "same interface family".
    toks = re.findall(r"`([A-Za-z_]\w{2,})`", prompt)          # backticked idents
    toks += re.findall(r"\b(clk|rst_?n?|start|valid|ready|dividend|divisor|quotient|remainder|"
                       r"tvalid|tready|tlast|tdata|tuser|psel|penable|pready|pwrite|addr|wdata|rdata|"
                       r"cmd|dq|din|dout|sel|enable|done|busy)\b", prompt.lower())
    return set(toks)

def _base(design_id: str) -> str:
    # strip cvdp_copilot_ prefix + trailing _NNNN → the design-family base name
    b = re.sub(r"^cvdp_(copilot|agentic)_", "", design_id)
    b = re.sub(r"_\d{3,4}$", "", b)
    return b.lower()

def query(prompt: str, k: int = 5, exclude: str = None, exclude_base: str = None):
    db = json.loads(DB.read_text())["designs"]
    q_cls = infer_class(prompt)
    q_kw = keywords(prompt)
    q_fn = _fn_stems(prompt)
    q_ps = _port_sig(prompt)
    ranked = []
    for d in db:
        if exclude and d["id"] == exclude: continue
        if exclude_base and _base(d["id"]) == exclude_base: continue   # no same-family leak
        dkw = set(d.get("matches_when", []))
        jac = len(q_kw & dkw) / max(1, len(q_kw | dkw))
        # function-noun overlap over the design's id + toplevel + modules (dominant)
        d_fn = _fn_stems(" ".join([d["id"], d.get("toplevel") or ""] + d.get("modules", [])))
        fn_ov = len(q_fn & d_fn)
        # interface-signature overlap over the design's ports (structured)
        ps_ov = len(q_ps & set(d.get("ports", [])))
        score = (3.0 if d["ic_class"] == q_cls else 0.0) + 3.0 * jac \
            + 12.0 * fn_ov + 2.0 * ps_ov
        ranked.append((score, fn_ov, d))
    ranked.sort(key=lambda x: (-x[0], -x[1]))
    return [{"id": d["id"], "ic_class": d["ic_class"], "toplevel": d["toplevel"],
             "score": round(s, 2), "fn_match": fo, "rtl_path": d["rtl_path"], "lesson": d.get("lesson", "")}
            for s, fo, d in ranked[:k] if s > 0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True, type=Path)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--exclude", default=None)
    ap.add_argument("--exclude-base", default=None,
                    help="exclude all designs of this family base (auto from --exclude if omitted)")
    a = ap.parse_args()
    xb = a.exclude_base or (_base(a.exclude) if a.exclude else None)
    hits = query(a.prompt.read_text(), a.k, a.exclude, xb)
    print(json.dumps(hits, indent=2))

if __name__ == "__main__":
    main()
