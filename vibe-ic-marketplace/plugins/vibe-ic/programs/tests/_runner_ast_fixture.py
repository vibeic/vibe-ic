"""Inspect a runner's called implementation, without accepting dead helpers."""
from __future__ import annotations

import ast


def live_nodes(root: ast.AST):
    """Walk executable syntax; omit nested definitions and constant dead arms.

    Dynamic conditions remain possible paths. This is a structural wiring
    check, not a claim that a particular run executed every possible branch.
    """
    def block(statements):
        for statement in statements:
            yield from visit(statement)
            if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                break

    def visit(node):
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Lambda)) and node is not root:
            return
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
            yield from visit(node.test)
            yield from block(node.body if node.test.value else node.orelse)
            return
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) \
                and not node.test.value:
            yield from visit(node.test)
            yield from block(node.orelse)
            return
        for _, value in ast.iter_fields(node):
            if isinstance(value, list):
                if value and all(isinstance(child, ast.stmt) for child in value):
                    yield from block(value)
                else:
                    for child in value:
                        if isinstance(child, ast.AST):
                            yield from visit(child)
            elif isinstance(value, ast.AST):
                yield from visit(value)

    yield from visit(root)


def called_main(tree: ast.Module) -> ast.FunctionDef:
    """Follow the canonical main -> _main return call, when a wrapper exists."""
    functions = {node.name: node for node in tree.body
                 if isinstance(node, ast.FunctionDef)}
    assert "main" in functions, "runner has no top-level main()"
    main = functions["main"]
    if "_main" not in functions:
        return main
    delegates = [node for node in live_nodes(main)
                 if isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
                 and isinstance(node.value.func, ast.Name)
                 and node.value.func.id == "_main"
                 and not node.value.args and not node.value.keywords]
    assert delegates, "main() does not return the called _main() implementation"
    return functions["_main"]
