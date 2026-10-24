"""Read the native metal-width/parallel-run spacing predicates we support."""
import json
import math
from pathlib import Path
import re
import shlex


def parse_native_rules(configuration: str, source: str) -> dict:
    """Recognize the native constant-distance, width-opening, parallel rule.

    This deliberately is not a Ruby evaluator. Different predicates stay
    unsupported and the actual native DRC remains their authority.
    """
    config = json.loads(configuration).get("drc_rules", {})
    if not isinstance(config, dict):
        raise ValueError("native DRC rules must be an object")
    source = "\n".join(line for line in source.splitlines()
                       if not line.lstrip().startswith("#"))
    lines = source.splitlines()
    def statements(pattern):
        return [match for line in lines
                if (match := re.fullmatch(r"[ \t]*" + pattern + r"[ \t]*(?:#[^\r\n]*)?", line))]
    layers = statements(r"mets_lay\s*=\s*\[([^]]+)\]")
    assignments = r"\s*(?:[+\-*/%&|^]?=|<<)"
    layer_writes = re.findall(r"(?m)^[ \t]*mets_lay(?:\s*\[[^\n]*?\])?" + assignments, source)
    if len(layers) != 1 or len(layer_writes) != 1:
        raise ValueError("native metal layer declaration is unsupported")
    metals = [re.fullmatch(r"metal(\d+)_drw", name.strip())
              for name in layers[0][1].split(",")]
    if not metals or any(match is None for match in metals):
        raise ValueError("native metal layer declaration is unsupported")
    result = {}
    for suffix in ("e", "f"):
        stem, key = "mn_" + suffix, "Mn_" + suffix
        required = [
            rf"{stem}_value\s*=\s*drc_rules\['{key}'\]\.to_f",
            rf"{stem}_width\s*=\s*drc_rules\['{key}_w'\]\.to_f\s*/\s*2\b",
            rf"{stem}_length\s*=\s*drc_rules\['{key}_cr'\]\.to_f",
            rf"{stem}_l1\s*=\s*met_lay\.sized\(-1\s*\*\s*{stem}_width\.um\)\.sized\({stem}_width\.um\)",
            rf"(?:{stem}_l\s*=\s*)?met_lay\.sep\({stem}_l1,\s*{stem}_value\.um,\s*projection_limits\({stem}_length\.um\s*\+\s*0\.001\.um,\s*nil\)\)",
        ]
        if any(len(statements(pattern)) != 1 for pattern in required):
            raise ValueError("unsupported native width/parallel predicate: " + key)
        if any(len(re.findall(r"(?m)^[ \t]*" + stem + ending + assignments, source)) != 1
               for ending in ("_value", "_width", "_length", "_l1")):
            raise ValueError("native width/parallel predicate was reassigned: " + key)
        values = [config.get(key + ending) for ending in ("", "_w", "_cr")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("native width/parallel spacing values are absent or invalid")
        rule = dict(source_rule=key, spacing_um=values[0],
                    width_gt_um=values[1], parallel_gt_um=values[2])
        for match in metals:
            result.setdefault(int(match[1]), []).append(dict(rule))
    return result


def read_native_rules(stage, pdk_root: str, family: str) -> dict:
    root = str(Path(pdk_root) / family / "libs.tech/klayout/tech/drc/rule_decks")
    script = ("import json,hashlib;from pathlib import Path;"
              "r=Path(" + repr(root) + ");"
              "a=list(r.glob('*tech_default.json'));b=list(r.glob('**/*metaln.drc'));"
              "p=(a+b) if len(a)==len(b)==1 else [];"
              "print(json.dumps({str(x):{'text':x.read_text(),"
              "'sha256':hashlib.sha256(x.read_bytes()).hexdigest()}for x in p}))")
    try:
        rc, out, error = stage.sh("python3 -c " + shlex.quote(script), timeout=120)
        if rc:
            raise ValueError("native conditional-spacing sources unavailable: " + error[:160])
        files = json.loads(out)
        config = next(value["text"] for path, value in files.items() if path.endswith(".json"))
        source = next(value["text"] for path, value in files.items() if path.endswith(".drc"))
        rules = parse_native_rules(config, source)
        return {"status": "READ", "rules": rules,
                "sources": {path: {"path": path, "sha256": value["sha256"]}
                            for path, value in files.items()}}
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        return {"status": "UNSUPPORTED_OR_ABSENT", "detail": str(exc), "rules": {},
                "scope": "native DRC adjudicates unsupported spacing predicates"}
