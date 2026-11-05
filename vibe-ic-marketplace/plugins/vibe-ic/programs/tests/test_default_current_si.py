"""Step27 current-subject controls, including logical/physical identity drift.

Transport substitution is SOURCE_FIXTURE_ONLY and provides no native credit.
"""
import ast
import inspect
import si_crosstalk_check as SG






def test_accepted_si_binding_precedes_both_ordinary_formats():
    tree = ast.parse(inspect.getsource(SG.audit))
    bindings = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "si_binding"]
    assert len(bindings) == 1
    json_branch = next(n for n in tree.body[0].body if isinstance(n, ast.If)
                       and ast.unparse(n.test) == "jsn.exists()")
    assert bindings[0].lineno < json_branch.lineno










































# The saved Step23 is neutral retained input, not a rerun of its native tool.
# Step27's producer, current readers, MCF and full canonical consumer are real.
