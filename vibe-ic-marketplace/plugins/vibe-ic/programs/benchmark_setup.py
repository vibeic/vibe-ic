#!/usr/bin/env python3
"""benchmark_setup.py — environment check + dataset-clone helper for open benchmarks.

Companion to /vibe-ic-benchmark. Verifies the host has the tools each registry
entry needs (iverilog, vibeic-eda container, MCP server, optionally docker), and
prints the clone command for the requested benchmark's dataset (NEVER auto-runs
git clone — explicit user consent for third-party data).

Usage:
    python3 benchmark_setup.py                  # check env for all benchmarks
    python3 benchmark_setup.py rtllm            # focused check for one benchmark
    python3 benchmark_setup.py rtllm --print-clone   # just print the clone cmd
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

HARNESS = Path(__file__).resolve().parent.parent / "benchmark"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _docker_ps() -> set[str]:
    if not _has("docker"):
        return set()
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                             capture_output=True, text=True, timeout=5).stdout
        return set(l.strip() for l in out.splitlines() if l.strip())
    except Exception:
        return set()


def _mcp_alive() -> bool:
    if not _has("pgrep"):
        return False
    return subprocess.run(["pgrep", "-fa", "mcp-eda/src/bootstrap"],
                          capture_output=True).returncode == 0


def env_summary() -> dict:
    ps = _docker_ps()
    return {
        "iverilog": _has("iverilog"),
        "yosys": _has("yosys"),
        "docker": _has("docker"),
        # THE PINNED CONTAINER, not "something called vibeic-eda". The derived
            # name carries the digest, so this now answers the question the
            # operator actually has: is the toolchain I pinned running here?
            "iic_eda_running": _pin.default_container_name() in ps,
        "mcp_server_alive": _mcp_alive(),
        "git": _has("git"),
        "python3": _has("python3"),
    }


def _entry(reg: dict, name: str) -> dict | None:
    return reg.get("benchmarks", {}).get(name)


def needs(entry: dict) -> set[str]:
    shape = entry.get("shape")
    common = {"iverilog", "python3", "git"}
    if shape in ("A", "B"):
        return common | {"yosys", "iic_eda_running"}
    if shape == "C":
        return common
    if shape == "D":
        return common | {"docker", "iic_eda_running"}
    return common


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bench", nargs="?", help="benchmark name (omit for env summary)")
    ap.add_argument("--print-clone", action="store_true",
                    help="print git clone command for this benchmark and exit")
    a = ap.parse_args()

    env = env_summary()
    reg = json.loads(REGISTRY.read_text())

    if a.bench:
        e = _entry(reg, a.bench)
        if not e:
            raise SystemExit(f"Unknown benchmark '{a.bench}'. Run --list via benchmark_dispatch.py.")
        if a.print_clone:
            ds = e.get("dataset", {})
            if ds.get("repo"):
                print(f"git clone {ds['repo']}  # license: {ds.get('license','?')}")
            elif ds.get("huggingface"):
                print(f"# HuggingFace dataset: {ds['huggingface']}")
                print(f"#   pip install datasets")
                print(f"#   python3 -c \"from datasets import load_dataset; load_dataset('{ds['huggingface']}', split='test').save_to_disk('./{a.bench}_data')\"")
            else:
                print("# no external dataset (internal or gated)")
            return
        print(f"# {e.get('title', a.bench)}  (Shape {e.get('shape')})")
        print(f"# Status: {e.get('status','')}")
        if e.get("blocker"):
            print(f"# BLOCKER: {e['blocker']}")
        needed = needs(e)
        print()
        print("Requirements:")
        for k in sorted(needed):
            ok = env.get(k, False)
            print(f"  [{'OK' if ok else '  '}] {k}")
        missing = [k for k in needed if not env.get(k)]
        if missing:
            print()
            print("Missing:")
            for m in missing:
                print(f"  - {m} — see docs/install for setup")
            sys.exit(2)
        print()
        print("Environment ready. Next:")
        print(f"  python3 {Path(__file__).parent / 'benchmark_dispatch.py'} {a.bench}")
        return

    print("# Host environment for Vibe-IC benchmarks")
    for k, v in sorted(env.items()):
        print(f"  [{'OK' if v else '  '}] {k}")
    print()
    print("# Run with a benchmark name for a focused check + next-step:")
    print(f"  python3 {Path(__file__).name} <benchmark>")
    print(f"  python3 {Path(__file__).parent / 'benchmark_dispatch.py'} --list")


if __name__ == "__main__":
    main()
