#!/usr/bin/env python3
"""score_rtlrepo.py — RTL-Repo scorer (Edit-Similarity + Exact-Match).

⚠ READ THIS FIRST ⚠
RTL-Repo is documented Shape E in BENCHMARK_REGISTRY.json: out-of-scope for
Vibe-IC's "doc → correct silicon" value proposition. The metric here is
**string similarity to the upstream repo's verbatim next line** — not
functional correctness. A clean, functionally-correct module that uses
different identifier names, comment style, or whitespace scores LOW even
when behaviorally identical. This scorer exists so users who want to
publish an RTL-Repo number can do so honestly (and see the misalignment),
not because it measures anything Vibe-IC optimizes for.

How RTL-Repo works:
  - Test split: 4000+ samples from real GitHub Verilog repos.
  - Each sample = (context: surrounding repo files + cropped current file,
                   target: the next line(s) that immediately follow).
  - Metric: per-sample Edit-Similarity (1 - normalized Levenshtein) and
            Exact-Match (1 iff prediction == target verbatim). Corpus-wide
            ES = mean over samples; EM = fraction of samples with EM=1.
  - Upstream evaluator: src/evaluate.py — reads predictions.jsonl with
    {id, prediction} entries, prints ES/EM. We re-implement the same metric
    here so users don't need to clone the RTL-Repo repo just to score.

Usage:
    # 1. Download the HF dataset (one-time)
    python3 score_rtlrepo.py --download ./rtlrepo_data

    # 2. Inspect a few samples (sanity, see what the task looks like)
    python3 score_rtlrepo.py --data ./rtlrepo_data --preview 3

    # 3. After producing predictions.jsonl (one {id, prediction} per line)
    python3 score_rtlrepo.py --data ./rtlrepo_data --predictions ./predictions.jsonl
    # → prints ES + EM + writes <predictions>.score.json

We intentionally do NOT bundle a prediction-generation loop: Vibe-IC's runner
authors RTL from L1-L23 SPECS, not next-line autocompletion. If you want to
generate predictions with Claude directly (an autocompletion task, not a
Vibe-IC task), the prompt convention is documented in the upstream README.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path


def _levenshtein(a: str, b: str) -> int:
    """Standard DP Levenshtein distance. Pure-stdlib; O(|a|·|b|)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j-1] + 1, prev[j-1] + (ca != cb))
        prev = curr
    return prev[-1]


def edit_similarity(pred: str, target: str) -> float:
    if not pred and not target:
        return 1.0
    n = max(len(pred), len(target))
    if n == 0:
        return 1.0
    return 1.0 - _levenshtein(pred, target) / n


def exact_match(pred: str, target: str) -> int:
    return 1 if pred == target else 0


def cmd_download(out_dir: str):
    try:
        from datasets import load_dataset
    except ImportError:
        raise SystemExit("`datasets` not installed.  pip install datasets")
    print(f"Downloading ahmedallam/RTL-Repo test split → {out_dir} …")
    ds = load_dataset("ahmedallam/RTL-Repo", split="test")
    ds.save_to_disk(out_dir)
    print(f"  saved {len(ds)} samples to {out_dir}")
    # tiny manifest so other commands know layout
    Path(out_dir, "MANIFEST.json").write_text(json.dumps({
        "source": "ahmedallam/RTL-Repo",
        "split": "test",
        "n_samples": len(ds),
        "fields": list(ds.features.keys()),
    }, indent=2) + "\n")


def _load_dataset(data_dir: str):
    try:
        from datasets import load_from_disk
    except ImportError:
        raise SystemExit("`datasets` not installed.  pip install datasets")
    p = Path(data_dir)
    if not p.is_dir():
        raise SystemExit(f"Dataset dir not found: {p}.  Use --download first.")
    return load_from_disk(str(p))


def cmd_preview(data_dir: str, n: int):
    ds = _load_dataset(data_dir)
    print(f"# RTL-Repo test split — {len(ds)} samples ({', '.join(ds.features.keys())})")
    for i in range(min(n, len(ds))):
        s = ds[i]
        print(f"\n## Sample {i}")
        for k, v in s.items():
            vs = repr(v)[:200]
            print(f"  {k}: {vs}{'…' if len(repr(v)) > 200 else ''}")


def cmd_score(data_dir: str, predictions_path: str):
    ds = _load_dataset(data_dir)
    # build id → target map. RTL-Repo's typical fields:
    #   'id' or 'context_id', 'context' (repo + cropped file), 'target' (next line(s))
    target_field = None
    id_field = None
    for cand in ("target", "ground_truth", "label", "completion"):
        if cand in ds.features:
            target_field = cand; break
    for cand in ("id", "context_id", "sample_id"):
        if cand in ds.features:
            id_field = cand; break
    if not target_field:
        raise SystemExit(f"Dataset has no recognizable target field. Fields: {list(ds.features.keys())}")
    target_by_id = {}
    for i, s in enumerate(ds):
        sid = s[id_field] if id_field else i
        target_by_id[sid] = s[target_field]

    # Load predictions
    p = Path(predictions_path)
    if not p.is_file():
        raise SystemExit(f"Predictions file not found: {p}")
    preds = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        preds.append((d.get("id"), d.get("prediction", "")))
    if not preds:
        raise SystemExit("No predictions found in file")

    # Score
    n_scored, em_sum, es_sum = 0, 0, 0.0
    missing = []
    for pid, pred in preds:
        if pid not in target_by_id:
            missing.append(pid)
            continue
        target = target_by_id[pid] or ""
        em_sum += exact_match(pred, target)
        es_sum += edit_similarity(pred, target)
        n_scored += 1

    em = em_sum / n_scored if n_scored else 0.0
    es = es_sum / n_scored if n_scored else 0.0

    summary = {
        "benchmark": "RTL-Repo (next-line autocompletion)",
        "shape": "E (out-of-scope for Vibe-IC functional metric)",
        "caveat": "Edit-Similarity / Exact-Match score string similarity to upstream verbatim — NOT functional correctness. A correct module that differs textually from the upstream line scores low. See open-benchmark-methodology skill § 2 Shape E + § 5 cheat sheet.",
        "n_predictions": len(preds),
        "n_scored": n_scored,
        "n_missing_id": len(missing),
        "Edit_Similarity": round(es, 4),
        "Exact_Match": round(em, 4),
    }
    out = p.with_suffix(p.suffix + ".score.json")
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"RTL-Repo  ES = {es:.4f}  EM = {em:.4f}  (n={n_scored}/{len(preds)})")
    print(f"  CAVEAT: this is a STRING metric, not functional correctness.")
    print(f"  Score detail: {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--download", metavar="OUT_DIR",
                     help="download the HF dataset to OUT_DIR (one-time)")
    grp.add_argument("--preview", type=int, metavar="N",
                     help="print first N samples for inspection (needs --data)")
    grp.add_argument("--predictions", metavar="PATH",
                     help="score this predictions.jsonl (needs --data)")
    ap.add_argument("--data", help="path to the saved HF dataset dir")
    a = ap.parse_args()

    if a.download:
        cmd_download(a.download)
        return
    if not a.data:
        raise SystemExit("--preview / --predictions both require --data <dataset-dir>")
    if a.preview is not None:
        cmd_preview(a.data, a.preview)
        return
    if a.predictions:
        cmd_score(a.data, a.predictions)


if __name__ == "__main__":
    main()
