from __future__ import annotations
import ast
import io
import re
import tokenize
from pathlib import Path
from typing import List, Tuple
def executable_text(path: Path, text: str) -> str:
    """`text` with everything that CANNOT invoke anything removed.

    A comment naming a gate is not a caller. MEASURED: vibe-ic#702 repaired
    `handoff_bundle_check` and deliberately left it OFF a rail, and this gate
    reported it newly wired — on the strength of one line in another program,

        #: reproduced end-to-end through `handoff_bundle_check`, where the …

    which is a comment. Believing it would have quietly shrunk the baseline by
    one and hidden a gate that still runs nowhere. Same shape as counting this
    program's own docstring; that was patched for this file alone, which fixed
    the instance and not the rule.

    A STRING is kept: `subprocess.run(["python3", "foo_check.py"])` is a real
    call and the name only ever appears there as a literal. A DOCSTRING is
    dropped — it is a string in expression position, executed for no effect.
    """
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text
        drop: List[Tuple[int, int]] = []
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not isinstance(
                    node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef)):
                continue
            first = body[0] if body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                drop.append((first.lineno, first.end_lineno or first.lineno))
        lines = text.splitlines()
        for lo, hi in drop:
            for i in range(lo - 1, min(hi, len(lines))):
                lines[i] = ""
        try:                                     # then the comments
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    r, c = tok.start
                    if r - 1 < len(lines) and lines[r - 1]:
                        lines[r - 1] = lines[r - 1][:c]
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return "\n".join(lines)
    if path.suffix in (".yaml", ".yml", ".sh") or path.suffix == "":
        # `#` starts a comment at line start or after whitespace; a `#` inside
        # a quoted scalar does not. Conservative: keep the line whole when the
        # `#` sits inside a quote that opened earlier on the same line.
        out = []
        for ln in text.splitlines():
            m = re.search(r'(?:^|\s)#', ln)
            if m and ln[:m.start()].count('"') % 2 == 0 \
                  and ln[:m.start()].count("'") % 2 == 0:
                ln = ln[:m.start()]
            out.append(ln)
        return "\n".join(out)
    return text
