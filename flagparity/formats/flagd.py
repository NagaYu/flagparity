"""flagd JSON: loading ($evaluators transposition) and concrete evaluation (flagd v0.19.0 json.go).

The fractional operator is delegated to a registered flagd semantics (G1/G2/G3); everything else
(JSONLogic, starts_with/ends_with/sem_ver, variant resolution) is the flagd v0.19.0 behaviour.
"""
import json

from ..jsonlogic import JSONLogic, JLError
from ..semantics.flagd import op_sem_ver, op_starts_with, op_ends_with


def _marshal(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def transpose_evaluators(doc):
    """flagd json.go transposeEvaluators: textual replacement of {"$ref":"name"} after normalisation."""
    evaluators = doc.get("$evaluators") if isinstance(doc, dict) else None
    result = _marshal(doc)
    if isinstance(evaluators, dict):
        for name in evaluators:
            val = _marshal(evaluators[name])
            if len(val) < 3:
                raise ValueError("evaluator object is empty")
            result = result.replace('{"$ref":%s}' % json.dumps(name, ensure_ascii=False), val)
    return json.loads(result)


class FlagdDoc:
    def __init__(self, raw):
        self.raw = raw
        self.doc = transpose_evaluators(raw)
        self.flags = self.doc.get("flags") if isinstance(self.doc.get("flags"), dict) else {}


def make_logic(sem):
    return JSONLogic({
        "fractional": sem.impl.fractional,
        "starts_with": op_starts_with,
        "ends_with": op_ends_with,
        "sem_ver": op_sem_ver,
    })


def evaluate_variant(fdoc, flag_key, ctx, sem, logic=None, now=0):
    """Returns (variant_name|None, reason, error_code|None) as flagd evaluateVariant does.
    reason in STATIC/DEFAULT/TARGETING_MATCH/DISABLED/FALLBACK/ERROR."""
    flag = fdoc.flags.get(flag_key)
    if not isinstance(flag, dict):
        return None, "ERROR", "FLAG_NOT_FOUND"
    if flag.get("state") == "DISABLED":
        return None, "DISABLED", None
    default = flag.get("defaultVariant") or ""
    variants = flag.get("variants") if isinstance(flag.get("variants"), dict) else {}
    targeting = flag.get("targeting")
    if targeting is not None and targeting != {}:
        data = dict(ctx) if isinstance(ctx, dict) else {}
        data["$flagd"] = {"flagKey": flag_key, "timestamp": now}
        logic = logic or make_logic(sem)
        try:
            res = logic.apply(targeting, data)
        except (JLError, RecursionError, TypeError, ValueError, ZeroDivisionError):
            return None, "ERROR", "PARSE_ERROR"
        if res is None:
            if default == "":
                return None, "FALLBACK", None
            return default, "DEFAULT", None
        text = json.dumps(res, separators=(",", ":"), ensure_ascii=False) if not isinstance(res, float) \
            else _go_json_float(res)
        variant = text.strip().replace('"', "")
        if variant in variants:
            return variant, "TARGETING_MATCH", None
        return None, "ERROR", "GENERAL"
    if default == "":
        return None, "FALLBACK", None
    return default, "STATIC", None


def _go_json_float(f):
    if f == int(f) and abs(f) < 1e21:
        return str(int(f))
    return repr(f)
