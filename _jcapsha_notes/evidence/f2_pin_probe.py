"""The F2 pin, as a deterministic predicate, run against BOTH trees.

UPSTREAM (read out of the pinned image, not remembered):
  librelane/scripts/openroad/common/pad_cfg.tcl computes BOTH
  `[[$inst getMaster] getWidth]` and `[[$inst getMaster] getHeight]` per
  instance and sums ONLY the width, in a loop that is side-agnostic.

OURS: the value summed for the side fit must therefore not flow from an
ORIENTATION-DEPENDENT footprint. `footprint()` swaps the axes for rotated
orientations, so a side whose orientation does not swap sums the HEIGHT.

The predicate: inside the function that computes the side fit, the name bound
to the along-the-row extents must not trace to a call to `footprint`.
"""
import ast, sys, subprocess

SRC = "vibe-ic-marketplace/plugins/vibe-ic/programs/pad_ring_gen.py"


def along_traces_to_footprint(text: str):
    tree = ast.parse(text)
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name != "_place":
            continue
        # names whose value flows from a `footprint(...)` call
        tainted = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            calls = {c.func.attr if isinstance(c.func, ast.Attribute)
                     else getattr(c.func, "id", "")
                     for c in ast.walk(node.value) if isinstance(c, ast.Call)}
            names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            if "footprint" in calls or (names & tainted):
                for t in node.targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            tainted.add(n.id)
        return "along" in tainted, sorted(tainted)
    raise SystemExit("_place not found")


for ref in sys.argv[1:]:
    text = subprocess.run(["git", "show", f"{ref}:{SRC}"],
                          capture_output=True, text=True, check=True).stdout
    bad, tainted = along_traces_to_footprint(text)
    print(f"{ref:34s} along-from-oriented-footprint={bad}   "
          f"orientation-tainted names in _place: {tainted}")
