"""`invocation proved by parse not by text` — a wiring audit loses its parse.

WHY THE SUBJECT IS THIS BIG
===========================
The gate holds its findings against a SHIPPED inventory
(`programs/invocation_text_scan_inventory.json`), read from the real programs
directory because the declaration passes `--root` and not `--inventory`. An
inventory row that matches nothing is rc 1 in its own right — "MAY ONLY SHRINK"
— so a subject containing none of the known sites is refused for STALENESS, not
for the predicate, and would have proved the wrong half of the gate.

So the passing subject reconstructs, at their inventoried paths, one minimal
stand-in per inventoried row: the four modules and the eight
`file::name::how` keys the shipped inventory names. Nothing here is copied from
those programs — each stand-in is a few lines that reproduce only the SHAPE the
key describes (a name bound to python source text, and the search over it).

THE MUTATION: A PARSE REMOVED, NOT A MODULE ADDED
=================================================
Both arms ship the SAME five enforcement modules, so both print

    enforcement modules:            5
    reading python source text:     5

The fifth, `wiring_parse_check.py`, is the CONTROL: it reads a caller's source
and greps it, but it also calls `ast.parse`, which is clause 3 of the
predicate — a module with a syntax tree available is exempt, and the gate must
stay quiet about it. `can_fail` changes exactly one call, `ast.parse(...)` to a
helper that returns tokens, and changes nothing else. The population is
untouched; what moves is the answer, `invocation decided by text` going 8 -> 10.

Adding a sixth module instead would have grown the denominator alongside the
verdict, and a red arm that also enlarged its corpus cannot say which of the
two the gate reacted to.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "invocation proved by parse not by text"

_PROGRAMS = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs")

# --- one stand-in per inventoried key ---------------------------------------
# flow_step_executor_coverage_check.py :: runner_text :: re.search()
# flow_step_executor_coverage_check.py :: runner_text :: `in` membership
_FLOW_STEP = '''\
#!/usr/bin/env python3
"""Decides which steps a runner dispatches by searching the runner's TEXT."""
import re
from pathlib import Path

_RUNNER_FILES = ["design_one_shot_runner.py"]


def covered(root):
    runner_text = Path(root, _RUNNER_FILES[0]).read_text(encoding="utf-8")
    out = []
    for producer in ("a_producer.py", "b_producer.py"):
        if producer in runner_text:
            out.append(producer)
        elif re.search(producer, runner_text):
            out.append(producer)
    return out
'''

# l18_interconnect_topology_factuality_check.py :: txt :: re.search()
_L18 = '''\
#!/usr/bin/env python3
"""Extracts a mapping from a schema module's source text by regex."""
import re
from pathlib import Path


def topology_map(schema_dir):
    txt = Path(schema_dir, "l18_schema.py").read_text(encoding="utf-8")
    m = re.search(r"TOPOLOGY\\s*=\\s*\\{([^}]*)\\}", txt)
    return m.group(1) if m else ""
'''

# phase1_gate_contract_check.py :: src :: re.search()
# phase1_gate_contract_check.py :: src :: `in` membership
_PHASE1 = '''\
#!/usr/bin/env python3
"""Decides contract compliance from a gate module's raw source text."""
import re
from pathlib import Path


def contract_ok(gate_dir):
    src = Path(gate_dir, "some_gate_check.py").read_text(encoding="utf-8")
    if "NOT CHECKED" in src:
        return True
    return bool(re.search(r"return 2", src))
'''

# plugin_full_audit.py :: test_blob :: re.findall()
# plugin_full_audit.py :: _words     :: `in` membership
# plugin_full_audit.py :: test_blob  :: re.search()
_FULL_AUDIT = '''\
#!/usr/bin/env python3
"""D1/D2 coverage decided by grepping a concatenation of test sources."""
import re
from pathlib import Path


def coverage(tests_dir):
    test_blob = Path(tests_dir, "test_everything.py").read_text(encoding="utf-8")
    _words = test_blob.split()
    named = re.findall(r"\\w+_check\\.py", test_blob)
    if "plugin_full_audit.py" in _words:
        named.append("plugin_full_audit.py")
    if re.search(r"programs/", test_blob):
        named.append("programs")
    return named
'''

# The control. `{decide}` is the only difference between the two arms.
_CONTROL = '''\
#!/usr/bin/env python3
"""Reads a caller's source, and decides invocation from its syntax tree."""
import ast
import re
from pathlib import Path


def _tokens(text):
    return text.split()


def invoked_by(caller_dir):
    caller_src = Path(caller_dir, "runner.py").read_text(encoding="utf-8")
    tree = {decide}
    names = {{n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}}
    if "dispatch_step" in caller_src:
        names.add("dispatch_step")
    if re.search(r"subprocess", caller_src):
        names.add("subprocess")
    return names
'''

_PARSES = "ast.parse(caller_src)"        # exempt: clause 3 of the predicate
_GREPS = "_tokens(caller_src)"           # no syntax tree anywhere in the module


def _tree(work: Path, decide: str) -> Path:
    root = work / "subject"
    pg = root.joinpath(*_PROGRAMS)
    pg.mkdir(parents=True, exist_ok=True)
    (pg / "flow_step_executor_coverage_check.py").write_text(_FLOW_STEP)
    (pg / "l18_interconnect_topology_factuality_check.py").write_text(_L18)
    (pg / "phase1_gate_contract_check.py").write_text(_PHASE1)
    (pg / "plugin_full_audit.py").write_text(_FULL_AUDIT)
    (pg / "wiring_parse_check.py").write_text(_CONTROL.format(decide=decide))
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, _PARSES)


def can_fail(work: Path):
    return _tree(work, _GREPS), "decide invocation by searching text"
