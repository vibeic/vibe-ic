#!/usr/bin/env python3
"""rtllm_oracle_adapter.py — record-format mapping for the oracle sweep.

Thin by design: WHERE the RTLLM pieces live and WHAT the candidate file must be
called. Every verdict lives in `programs/oracle_self_consistency_sweep.py`.

RTLLM is a Shape-B dataset, one directory per design:

    <dataset>/<path>/<leaf>/design_description.txt   the problem statement
    <dataset>/<path>/<leaf>/testbench.v              the testbench
    <dataset>/<path>/<leaf>/verified_*.v             the golden
    <run>/samples/<name>.v                           the candidate

Two mappings are needed to submit the golden AS the candidate:

  * WHICH NAME the candidate must declare. The testbench compiles the candidate
    ALONE (`tb_compile_with_ref: false`), so the module name has to be the one
    the testbench instantiates. The scorer resolves the sample file as
    `samples/<leaf>.v` and then as `samples/<the spec's "Module name:" line>.v`,
    so the adapter writes whichever of those the golden actually provides.
  * WHICH MODULE in the golden is the top. Measured at RTLLM 51ed553d: every
    design has exactly one `verified_*.v`, some carry helper modules alongside
    the top, and the top's own name is variously `<leaf>`, `verified_<leaf>` or
    neither (`verified_adder_64bit` for design `adder_pipe_64bit`). The rule is
    therefore structural — the module no other module in the file instantiates —
    with the two name conventions tried first. If that leaves the top
    ambiguous the adapter RAISES; the sweep then reports NOT_MEASURED naming
    this design, and never guesses.
"""
from __future__ import annotations

import re
from pathlib import Path

_MODULE_DECL_RE = re.compile(r"^[ \t]*module\s+(\w+)", re.M)
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_SPEC_MODULE_RE = re.compile(r"Module\s*name\s*:\s*\n?\s*([A-Za-z_]\w*)")


def problems(dataset: Path, entry: dict) -> list[str]:
    prompt = entry["layout"]["prompt_filename"]
    ds = Path(dataset)
    return sorted(str(p.parent.relative_to(ds))
                  for p in ds.rglob(prompt) if p.is_file())


def _spec_module_name(design_dir: Path, entry: dict) -> str | None:
    spec = design_dir / entry["layout"]["prompt_filename"]
    if not spec.is_file():
        return None
    m = _SPEC_MODULE_RE.search(spec.read_text(errors="replace"))
    return m.group(1) if m else None


def _golden_file(design_dir: Path, entry: dict) -> Path:
    glob = entry["layout"].get("ref_glob", "verified_*.v")
    hits = sorted(design_dir.glob(glob))
    if len(hits) != 1:
        raise ValueError(f"expected exactly one {glob} in {design_dir}, found "
                         f"{[h.name for h in hits]}")
    return hits[0]


def top_module(text: str, preferred: list[str]) -> str:
    """The golden's top module name. `preferred` is tried first, then the
    structural rule (the module nothing else instantiates)."""
    decls = _MODULE_DECL_RE.findall(text)
    if not decls:
        raise ValueError("the golden declares no module")
    if len(decls) == 1:
        return decls[0]
    for name in preferred:
        if name in decls:
            return name
    body = _COMMENT_RE.sub(" ", text)
    instantiated = {n for n in decls
                    if re.search(rf"^(?![ \t]*module\b)[ \t]*{re.escape(n)}\s"
                                 r"*(?:#\s*\(.*?\))?\s*\w+\s*\(", body,
                                 re.M | re.S)}
    roots = [n for n in decls if n not in instantiated]
    if len(roots) == 1:
        return roots[0]
    raise ValueError(f"cannot decide the top module among {decls!r} "
                     f"(uninstantiated: {roots!r})")


def _rename_module(text: str, old: str, new: str) -> str:
    if old == new:
        return text
    return re.sub(rf"\b{re.escape(old)}\b", new, text)


def _slice_module(text: str, name: str) -> str:
    """Just `module <name> … endmodule`, for seeding the constant stub. A
    multi-module golden must not seed the stub from a helper module."""
    m = re.search(rf"^[ \t]*module\s+{re.escape(name)}\b", text, re.M)
    if not m:
        raise ValueError(f"module {name} not found for stub seeding")
    end = re.search(r"^[ \t]*endmodule", text[m.start():], re.M)
    if not end:
        raise ValueError(f"module {name} has no endmodule")
    return text[m.start(): m.start() + end.end()] + "\n"


def golden_candidate(dataset: Path, pid: str, entry: dict):
    """(sample relpath, candidate text, stub seed text) for ARM G."""
    design_dir = Path(dataset) / pid
    leaf = pid.split("/")[-1]
    spec_name = _spec_module_name(design_dir, entry)
    gold = _golden_file(design_dir, entry)
    text = gold.read_text(errors="replace")
    top = top_module(text, [leaf, spec_name or "", f"verified_{leaf}"])
    # The name the scorer will look for, in the order it looks: `samples/<leaf>.v`
    # first, then `samples/<the spec's Module name>.v`. When the golden's top
    # already carries one of those names, keep it; otherwise rename it to the
    # spec's name (the authoritative one) and fall back to the leaf.
    if top in (leaf, spec_name):
        required = top
    elif spec_name and spec_name != leaf:
        required = spec_name
    else:
        required = leaf
    others = [d for d in _MODULE_DECL_RE.findall(text) if d != top]
    if required in others:
        raise ValueError(
            f"renaming the top {top!r} to {required!r} would collide with a "
            f"helper module of that name in {gold.name}")
    cand = _rename_module(text, top, required)
    return (f"{required}.v", cand, _slice_module(cand, required))
