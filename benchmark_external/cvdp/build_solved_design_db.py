#!/usr/bin/env python3
"""build_solved_design_db.py — build a DB-native solved-design knowledge index.

Answers the owner's architecture question (2026-07-02): enrich the IC-Expert
Agent's knowledge via a NORMAL structured database (reusing the ip-catalog
manifest pattern) — NOT a bolt-on vector RAG. IC knowledge is structured
(ic_class / interface / algorithm / layer), so structured + lexical ranked
match is MORE precise than embeddings.

Each solved (officially-scored PASS) design becomes one record:
  { id, ic_class, category, toplevel, ports[], algorithm_keywords[],
    matches_when[], lesson, rtl_path }
Retrieval (query_solved) = structured/lexical ranked match against a new
design's prompt facts — the same access pattern ip_catalog_query.query_catalog
uses. No vectors, no external service.

chip-AGNOSTIC: pure structural extraction from solved RTL + prompt.
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

# Both were absolute personal-home paths, which the shipped-path
# portability gate rejects. A hard-coded home is one machine's layout, not a
# default: on any other checkout this reads a dataset that is not there and
# writes a database somewhere that does not exist.
#
# DS has no anchor inside the repo — the CVDP dataset is an EXTERNAL corpus
# that lives wherever the operator unpacked it — so it comes from an env var
# and there is no fallback. Guessing would make the script fail by reading the
# wrong corpus rather than by saying what it needs.
#
# OUT_DIR is derived from this file's own location: the database it builds
# belongs beside the script, in the repo, wherever the repo is cloned.
DS = os.environ.get("CVDP_DATASET_JSONL")
OUT_DIR = Path(__file__).resolve().parent / "solved_design_db"

_MODRE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_PORTRE = re.compile(r"\b(input|output|inout)\b[^;]*?\b([A-Za-z_]\w*)\s*(?:,|;|\)|=)")
# lightweight IC-class inference from prompt/module tokens (mirrors ic_class spirit)
_CLASS_KW = {
    "digital_arithmetic_primitive": ["adder","multiplier","divider","alu","mac","booth","cordic","sqrt","accumulat"],
    "crypto": ["aes","sha","hmac","cipher","crc","galois","rsa","md5","scrambl","lfsr","prbs"],
    "protocol_interface": ["axi","apb","ahb","wishbone","spi","uart","i2c","gmii","sata","usb","fifo","stream"],
    "memory_control": ["cache","sdram","ddr","tlb","lru","register_file","memory","ram","buffer"],
    "dsp_filter": ["fir","iir","filter","fft","dft","convolut","sigma_delta","interpolat","decimat"],
    "fsm_control": ["fsm","controller","sequencer","arbiter","vending","elevator","traffic","stopwatch","state"],
    "image_pixel": ["image","pixel","sprite","rotate","grayscale","border","line_buffer","vga"],
}

def infer_class(text: str) -> str:
    t = text.lower()
    best, score = "unknown_class", 0
    for cls, kws in _CLASS_KW.items():
        s = sum(t.count(k) for k in kws)
        if s > score:
            best, score = cls, s
    return best

def extract_rtl(completion: str) -> str:
    """Unwrap the completion to raw RTL (handles {"code":[{path:src}]} + bare)."""
    s = completion.lstrip()
    if s.startswith(("{", "[")):
        try:
            obj = json.loads(completion)
            acc = []
            def walk(n):
                if isinstance(n, str) and "module" in n and "endmodule" in n: acc.append(n)
                elif isinstance(n, dict):
                    for v in n.values(): walk(v)
                elif isinstance(n, list):
                    for v in n: walk(v)
            walk(obj)
            if acc: return "\n\n".join(acc)
        except Exception:
            pass
    return completion

def _keywords(prompt: str) -> list:
    # salient nouns/tokens for lexical match (dedup, lowercased, len>=4)
    toks = re.findall(r"[A-Za-z_]{4,}", prompt.lower())
    stop = {"module","input","output","the","and","for","with","that","this","should","must","when","value","signal","width","bit","bits","data","design","implement","following","using","based"}
    seen, out = set(), []
    for w in toks:
        if w in stop or w in seen: continue
        seen.add(w); out.append(w)
    return out[:40]

def build():
    # Say what is missing, rather than letting `open(None)` raise a TypeError
    # that names neither the variable nor the reason.
    if not DS:
        sys.exit("CVDP_DATASET_JSONL is not set — point it at the CVDP "
                 "non-agentic code-generation .jsonl. There is no default: the "
                 "dataset is an external corpus and its location is a property "
                 "of the machine, not of this repo.")
    recs = {json.loads(l)["id"]: json.loads(l) for l in open(DS) if l.strip()}
    # solved corpus: the converged responses (id+completion). Path passed as argv[1].
    solved_path = sys.argv[1] if len(sys.argv) > 1 else None
    solved = {}
    if solved_path and os.path.exists(solved_path):
        for l in open(solved_path):
            if l.strip():
                d = json.loads(l); solved[d["id"]] = d.get("completion", "")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "rtl").mkdir(exist_ok=True)
    index = []
    for did, comp in solved.items():
        rec = recs.get(did, {})
        prompt = rec.get("input", {}).get("prompt", "")
        cats = rec.get("categories", [])
        rtl = extract_rtl(comp)
        mods = _MODRE.findall(rtl)
        ports = sorted(set(m[1] for m in _PORTRE.findall(rtl)))[:40]
        toplevel = mods[-1] if mods else None   # top usually last-declared
        rtl_file = OUT_DIR / "rtl" / f"{did}.sv"
        rtl_file.write_text(rtl)
        index.append({
            "id": did,
            "category": cats[0] if cats else None,
            "difficulty": cats[1] if len(cats) > 1 else None,
            "ic_class": infer_class(prompt + " " + " ".join(mods)),
            "toplevel": toplevel,
            "modules": mods,
            "ports": ports,
            "matches_when": _keywords(prompt),
            "lesson": "",  # filled by distillation pass (RCA); empty = structural-only for now
            "rtl_path": f"rtl/{did}.sv",
        })
    (OUT_DIR / "solved_design_index.json").write_text(
        json.dumps({"_doc": "DB-native solved-design knowledge index (structured/lexical retrieval, no vectors)",
                    "count": len(index), "designs": index}, indent=2))
    # class distribution
    from collections import Counter
    dist = Counter(d["ic_class"] for d in index)
    print(f"built solved_design_index.json: {len(index)} designs")
    print("ic_class distribution:", dict(dist))
    print(f"rtl exemplars: {len(list((OUT_DIR/'rtl').glob('*.sv')))}")

if __name__ == "__main__":
    build()
