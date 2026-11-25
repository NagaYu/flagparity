"""Flipt YAML (features.yml): parsing into flags/segments and concrete evaluation.

Loader behaviour follows flipt v2.14.2 internal/storage/fs/snapshot.go (also accepts the v1 file shapes):
- rule.segment is a key string, or {keys: [...], operator}; legacy `segments` list + `segment_operator`.
- default variant: variant with `default: true`, or flag `default_variant` (v1 shape).
- missing match_type => ALL (proto enum 0); missing segment operator => OR (enum 0);
  missing flag type => VARIANT (toEvaluationFlagType default).
"""
import json
import re
from datetime import datetime, timezone

from ..yaml12 import GoDecodeError, go_bool, go_float, go_str


class FliptLoadError(Exception):
    pass


def _seg_ref(obj):
    """Returns (keys, operator) for a rule/rollout segment reference."""
    seg = obj.get("segment")
    if isinstance(seg, (str, int, float)) and not isinstance(seg, bool):
        keys = [_s(seg)]
        op = obj.get("segment_operator") or "OR_SEGMENT_OPERATOR"
    elif isinstance(seg, dict):
        if "keys" in seg and isinstance(seg["keys"], list):
            keys = [_s(k) for k in seg["keys"]]
        elif "key" in seg:
            keys = [_s(seg["key"])]
        else:
            keys = []
        op = seg.get("operator") or "OR_SEGMENT_OPERATOR"
    elif isinstance(obj.get("segments"), list):
        keys = [_s(k) for k in obj["segments"]]
        op = obj.get("segment_operator") or "OR_SEGMENT_OPERATOR"
    else:
        keys, op = [], "OR_SEGMENT_OPERATOR"
    return keys, op


def _s(v):
    try:
        return go_str(v)
    except GoDecodeError:
        return v


class FliptFlag:
    def __init__(self, raw, namespace, segments, doc_index):
        self.raw = raw
        self.decode_errors = []
        self.key = _s(raw.get("key"))
        self.namespace = namespace
        self.doc_index = doc_index
        t = raw.get("type")
        self.type = "BOOLEAN_FLAG_TYPE" if t == "BOOLEAN_FLAG_TYPE" else "VARIANT_FLAG_TYPE"
        self.type_declared = t
        self.enabled = self._bool(raw.get("enabled"), "enabled")
        self.variants = [v for v in (raw.get("variants") or []) if isinstance(v, dict)]
        self.variant_keys = [_s(v.get("key")) for v in self.variants]
        dv = [_s(v.get("key")) for v in self.variants if self._bool(v.get("default"), "variant default")]
        self.default_variant = dv[-1] if dv else raw.get("default_variant")
        self.segments = segments
        self.rules = []
        for i, r in enumerate(raw.get("rules") or []):
            if not isinstance(r, dict):
                continue
            keys, op = _seg_ref(r)
            dists = []
            for d in r.get("distributions") or []:
                if isinstance(d, dict):
                    dists.append({"variant": _s(d.get("variant")), "rollout": self._num(d.get("rollout"), "rollout")})
            self.rules.append({"index": i, "segment_keys": keys, "operator": op, "distributions": dists})
        self.rollouts = []
        for i, ro in enumerate(raw.get("rollouts") or []):
            if not isinstance(ro, dict):
                continue
            if isinstance(ro.get("threshold"), dict):
                th = ro["threshold"]
                self.rollouts.append({"index": i, "kind": "threshold", "percentage": self._num(th.get("percentage"), "threshold percentage"),
                                      "value": self._bool(th.get("value"), "threshold value")})
            elif isinstance(ro.get("segment"), dict):
                keys, op = _seg_ref(ro)
                self.rollouts.append({"index": i, "kind": "segment", "segment_keys": keys, "operator": op,
                                      "value": self._bool(ro["segment"].get("value"), "segment rollout value")})

    def _bool(self, v, what):
        """Go bool field via yaml.v3 (YAML 1.1 spellings accepted); a decode error rejects the file at load."""
        try:
            return go_bool(v, False)
        except GoDecodeError as e:
            self.decode_errors.append("flag %s %s: %s" % (self.key, what, e))
            return False

    def _num(self, v, what):
        """Go float32 field via yaml.v3 (0x.., 0o.., legacy 012 octal, underscores); a decode error rejects the file."""
        try:
            return go_float(v, 0)
        except GoDecodeError as e:
            self.decode_errors.append("flag %s %s: %s" % (self.key, what, e))
            return v


class FliptDoc:
    def __init__(self, docs):
        self.flags = []
        self.load_errors = []
        for di, d in enumerate(docs):
            if not isinstance(d, dict):
                continue
            ns = d.get("namespace") or "default"
            if isinstance(ns, dict):
                ns = ns.get("key") or "default"
            segs = {}
            for s in d.get("segments") or []:
                if isinstance(s, dict) and s.get("key") is not None:
                    segs[_s(s["key"])] = {"key": _s(s["key"]), "match_type": s.get("match_type") or "ALL_MATCH_TYPE",
                                      "constraints": [c for c in (s.get("constraints") or []) if isinstance(c, dict)]}
            for f in d.get("flags") or []:
                if isinstance(f, dict) and f.get("key") is not None:
                    self.flags.append(FliptFlag(f, ns, segs, di))
        # snapshot.go: unknown segment / unknown variant references reject the whole snapshot
        for fl in self.flags:
            self.load_errors.extend("YAML decode (gopkg.in/yaml.v3): %s" % e for e in fl.decode_errors)
            for r in fl.rules:
                for k in r["segment_keys"]:
                    if k not in fl.segments:
                        self.load_errors.append("flag %s rule %d references unknown segment %r" % (fl.key, r["index"] + 1, k))
                for dd in r["distributions"]:
                    if dd["variant"] not in fl.variant_keys:
                        self.load_errors.append("flag %s rule %d references unknown variant %r" % (fl.key, r["index"] + 1, dd["variant"]))
            for ro in fl.rollouts:
                for k in ro.get("segment_keys", []):
                    if k not in fl.segments:
                        self.load_errors.append("flag %s rollout %d references unknown segment %r" % (fl.key, ro["index"] + 1, k))


# ---------------- constraint matching (go = flipt v1.62.1/v2.14.2 server, rust = client engine) ----------------

def _go_parse_float(s):
    s2 = s
    if re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?|[+-]?(inf|infinity|nan)", s2, re.I) is None:
        return None
    try:
        return float(s2)
    except ValueError:
        return None


def _parse_dt_go(v):
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_dt_rust(v):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})", v or ""):
        return None
    return _parse_dt_go(v.replace("t", "T").replace("z", "Z"))


def _go_parse_bool(v):
    if v in ("1", "t", "T", "TRUE", "true", "True"):
        return True
    if v in ("0", "f", "F", "FALSE", "false", "False"):
        return False
    return None


def match_constraint(c, v, dialect="go"):
    """Returns (match: bool, error: bool) for one constraint against context string v ('' = absent)."""
    ctype = c.get("type") or "STRING_COMPARISON_TYPE"
    op = c.get("operator")
    value = c.get("value")
    value = "" if value is None else (value if isinstance(value, str) else json.dumps(value))
    rust = dialect == "rust"
    if ctype in ("STRING_COMPARISON_TYPE", "ENTITY_ID_COMPARISON_TYPE"):
        if op == "empty":
            return (v == "") if rust else (v.strip() == ""), False
        if op == "notempty":
            return (v != "") if rust else (v.strip() != ""), False
        if v == "":
            return False, False
        vv = v if rust else v.strip()
        if op == "eq":
            return value == v, False
        if op == "neq":
            return value != v, False
        if op == "prefix":
            return vv.startswith(value), False
        if op == "suffix":
            return vv.endswith(value), False
        if op in ("isoneof", "isnotoneof"):
            try:
                lst = json.loads(value)
                ok = isinstance(lst, list) and all(isinstance(x, str) for x in lst)
            except ValueError:
                ok = False
            if not ok:
                return False, not rust  # go: prepare fails (load error); rust: false
            hit = v in lst
            return (hit if op == "isoneof" else not hit), False
        if op == "contains":
            return value in v, False
        if op == "notcontains":
            return value not in v, False
        return False, False
    if ctype == "NUMBER_COMPARISON_TYPE":
        if op == "notpresent":
            return (v == "") if rust else (v.strip() == ""), False
        if op == "present":
            return (v != "") if rust else (v.strip() != ""), False
        if v == "":
            return False, False
        if rust:
            if not re.fullmatch(r"[+-]?\d+", v) or not (-2 ** 31 <= int(v) < 2 ** 31):
                return False, True
            n = int(v)
        else:
            n = _go_parse_float(v)
            if n is None:
                return False, True
        if op in ("isoneof", "isnotoneof"):
            try:
                lst = json.loads(value)
                if rust:
                    ok = isinstance(lst, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in lst)
                else:
                    ok = isinstance(lst, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in lst)
            except ValueError:
                ok = False
            if not ok:
                return False, True
            hit = any(float(x) == float(n) for x in lst)
            return (hit if op == "isoneof" else not hit), False
        if rust:
            if not re.fullmatch(r"[+-]?\d+", value):
                return False, True
            ref = int(value)
        else:
            ref = _go_parse_float(value)
            if ref is None:
                return False, True
        return {"eq": n == ref, "neq": n != ref, "lt": n < ref, "lte": n <= ref,
                "gt": n > ref, "gte": n >= ref}.get(op, False), False
    if ctype == "BOOLEAN_COMPARISON_TYPE":
        if op == "notpresent":
            return (v == "") if rust else (v.strip() == ""), False
        if op == "present":
            return (v != "") if rust else (v.strip() != ""), False
        if v == "":
            return False, False
        b = (True if v == "true" else False if v == "false" else None) if rust else _go_parse_bool(v)
        if b is None:
            return False, True
        return {"true": b, "false": not b}.get(op, False), False
    if ctype == "DATETIME_COMPARISON_TYPE":
        if op == "notpresent":
            return (v == "") if rust else (v.strip() == ""), False
        if op == "present":
            return (v != "") if rust else (v.strip() != ""), False
        if v == "":
            return False, False
        p = _parse_dt_rust if rust else _parse_dt_go
        d, ref = p(v), p(value)
        if d is None or ref is None:
            return False, True
        return {"eq": d == ref, "neq": d != ref, "lt": d < ref, "lte": d <= ref,
                "gt": d > ref, "gte": d >= ref}.get(op, False), False
    return False, True  # unknown constraint type


def match_segment(seg, ctx, entity_id, dialect="go"):
    cons = seg["constraints"]
    mt = seg.get("match_type") or "ALL_MATCH_TYPE"
    n = 0
    err = False
    for c in cons:
        prop = c.get("property")
        v = entity_id if (c.get("type") == "ENTITY_ID_COMPARISON_TYPE") else str(ctx.get(prop, "")) if ctx.get(prop) is not None else ""
        m, e = match_constraint(c, v, dialect)
        err = err or e
        if m:
            n += 1
            if mt == "ANY_MATCH_TYPE":
                break
        elif mt == "ALL_MATCH_TYPE":
            break
    if mt == "ALL_MATCH_TYPE":
        return len(cons) == n, err
    if mt == "ANY_MATCH_TYPE":
        return not (len(cons) > 0 and n == 0), err
    return False, err


def rule_segments_match(flag, keys, operator, ctx, entity_id, dialect="go"):
    matches = 0
    err = False
    for k in keys:
        seg = flag.segments.get(k)
        if seg is None:
            continue
        m, e = match_segment(seg, ctx, entity_id, dialect)
        err = err or e
        matches += 1 if m else 0
    if operator == "AND_SEGMENT_OPERATOR":
        return len(keys) == matches, err
    return matches >= 1, err


def evaluate_variant(flag, ctx, entity_id, sem):
    """Returns (variant_key|None, match, reason, rule_index|None). Rust surfaces constraint errors."""
    impl = sem.impl
    dialect = impl.constraint_dialect
    if flag.type != "VARIANT_FLAG_TYPE":
        return None, False, "ERROR_FLAG_TYPE", None
    variant = flag.default_variant
    reason = "DEFAULT" if variant is not None else "UNKNOWN"
    if not flag.enabled:
        return variant, False, "FLAG_DISABLED", None
    for r in flag.rules:
        m, err = rule_segments_match(flag, r["segment_keys"], r["operator"], ctx, entity_id, dialect)
        if err and dialect == "rust":
            return None, False, "ERROR", r["index"]
        if not m:
            continue
        valid = [d for d in r["distributions"] if float(d["rollout"] or 0) > 0]
        if not valid:
            return variant, True, "MATCH", r["index"]
        idx = impl.variant_index(flag.key, entity_id, [float(d["rollout"]) for d in valid])
        if idx is None:
            return variant, False, "DEFAULT" if variant is not None else "UNKNOWN", r["index"]
        return valid[idx]["variant"], True, "MATCH", r["index"]
    return variant, False, reason, None


def evaluate_boolean(flag, ctx, entity_id, sem):
    impl = sem.impl
    dialect = impl.constraint_dialect
    if flag.type != "BOOLEAN_FLAG_TYPE":
        return None, "ERROR_FLAG_TYPE", None
    for ro in flag.rollouts:
        if ro["kind"] == "threshold":
            if impl.threshold_hit(flag.key, entity_id, ro["percentage"]):
                return ro["value"], "MATCH", ro["index"]
        else:
            m, err = rule_segments_match(flag, ro["segment_keys"], ro["operator"], ctx, entity_id, dialect)
            if err and dialect == "rust":
                return None, "ERROR", ro["index"]
            if m:
                return ro["value"], "MATCH", ro["index"]
    return flag.enabled, "DEFAULT", None
