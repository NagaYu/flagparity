"""JSONLogic evaluator modelled on diegoholiveira/jsonlogic v3 as used by flagd.

Concrete evaluation only. Custom operators receive pre-evaluated arguments (as in flagd).
Unknown operators raise JLError (flagd maps this to PARSE_ERROR).

Comparison, equality, `in` and truthiness follow diegoholiveira/jsonlogic v3.10.2 (the version flagd v0.19.0 pins in
core/go.mod; sources in vectors/upstream/jsonlogic@v3.10.2/): comp.go less/equals/hardEquals,
internal/javascript ToNumber/IsTrue, lists.go _in, types.go sameType/toNumber (Phase 3, DECISIONS §P3-Z).
"""
import math
import re

_GO_FLOAT = re.compile(r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|inf|infinity|nan)", re.I)
_GO_HEXFLOAT = re.compile(r"[+-]?0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)[pP][+-]?[0-9]+")


def go_parse_float(s):
    """strconv.ParseFloat(s, 64) for the forms JSON strings carry: None on a syntax error (no trimming; the
    underscore digit separators Go allows only after a base prefix are not accepted here)."""
    if _GO_FLOAT.fullmatch(s):
        return float(s)
    if _GO_HEXFLOAT.fullmatch(s):
        return float.fromhex(s)
    return None


class JLError(Exception):
    pass


def go_fmt(v):
    """Go fmt %v for JSON-decoded values (used by cat and sem_ver ensureString)."""
    if v is None:
        return "<nil>"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isinf(v):
            return "+Inf" if v > 0 else "-Inf"
        if math.isnan(v):
            return "NaN"
        if v == int(v) and abs(v) < 1e21:
            return str(int(v))
        r = repr(v)
        if "e" in r:
            mant, exp = r.split("e")
            e = int(exp)
            return "%se%s%02d" % (mant, "-" if e < 0 else "+", abs(e))
        return r
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "[" + " ".join(go_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "map[" + " ".join("%s:%s" % (k, go_fmt(v[k])) for k in sorted(v)) + "]"
    return str(v)


def truthy(v):
    """javascript.IsTrue (v3.10.2): NaN != 0, so NaN is true there."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def to_number(v):
    """javascript.ToNumber: nil -> 0, bool -> 1/0, "" (after TrimSpace) -> 0, else ParseFloat of the untrimmed
    string (error -> NaN); arrays/objects -> NaN."""
    if is_number(v):
        return float(v)
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if v is None:
        return 0.0
    if isinstance(v, str):
        if v.strip() == "":
            return 0.0
        f = go_parse_float(v)
        return float("nan") if f is None else f
    return float("nan")


def _types_to_number(v):
    """types.go toNumber (used by `in`): string -> ParseFloat (error -> 0), float64 -> itself, else a Go panic."""
    if isinstance(v, str):
        f = go_parse_float(v)
        return 0.0 if f is None else f
    if is_number(v):
        return float(v)
    raise JLError("toNumber on a %s (Go panic in jsonlogic types.go)" % type(v).__name__)


def loose_eq(a, b):
    """comp.go equals."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return to_number(a) == to_number(b)


def _same_type(a, b):
    for t in (bool, str, dict, list):
        if isinstance(a, t):
            return isinstance(b, t)
    if is_number(a):
        return is_number(b)
    return False


def strict_eq(a, b):
    """comp.go hardEquals: nil -> both nil; sameType, then equals (arrays/objects compare as NaN: never equal)."""
    if a is None or b is None:
        return a is None and b is None
    if not _same_type(a, b):
        return False
    return loose_eq(a, b)


def _less(a, b):
    """comp.go less: two strings by code point, otherwise ToNumber(b) > ToNumber(a) (NaN -> false)."""
    if isinstance(a, str) and isinstance(b, str):
        return a < b
    return to_number(b) > to_number(a)


def _cmp(op, a, b):
    if op == "<":
        return _less(a, b)
    if op == "<=":
        return _less(a, b) or loose_eq(a, b)
    if op == ">":
        return _less(b, a)
    return _less(b, a) or loose_eq(b, a)


def get_var(data, path, default=None):
    if path is None or path == "":
        return data
    if isinstance(path, (int, float)) and not isinstance(path, bool):
        path = go_fmt(path)
    if not isinstance(path, str):
        return default
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                i = int(part)
            except ValueError:
                return default
            if i < 0 or i >= len(cur):
                return default
            cur = cur[i]
        else:
            return default
    return cur


class JSONLogic:
    def __init__(self, custom_ops=None):
        self.custom = dict(custom_ops or {})

    def apply(self, rule, data):
        if isinstance(rule, list):
            return [self.apply(x, data) for x in rule]
        if not isinstance(rule, dict):
            return rule
        if len(rule) != 1:
            # diegoholiveira treats non-operator objects as values only when empty
            if not rule:
                return rule
            raise JLError("object with %d keys is not an operation" % len(rule))
        op, args = next(iter(rule.items()))
        if not isinstance(args, list):
            args_l = [args]
        else:
            args_l = args
        A = lambda i: self.apply(args_l[i], data) if i < len(args_l) else None  # noqa: E731

        if op == "var":
            path = self.apply(args_l[0], data) if args_l else None
            default = A(1) if len(args_l) > 1 else None
            return get_var(data, path, default)
        if op == "missing":
            keys = [self.apply(a, data) for a in args_l]
            if len(keys) == 1 and isinstance(keys[0], list):
                keys = keys[0]
            return [k for k in keys if get_var(data, k, None) is None]
        if op == "missing_some":
            need = A(0)
            keys = A(1) or []
            miss = [k for k in keys if get_var(data, k, None) is None]
            return [] if len(keys) - len(miss) >= need else miss
        if op == "if" or op == "?:":
            i = 0
            while i + 1 < len(args_l):
                if truthy(self.apply(args_l[i], data)):
                    return self.apply(args_l[i + 1], data)
                i += 2
            if i < len(args_l):
                return self.apply(args_l[i], data)
            return None
        if op == "and":
            v = None
            for a in args_l:
                v = self.apply(a, data)
                if not truthy(v):
                    return v
            return v
        if op == "or":
            v = None
            for a in args_l:
                v = self.apply(a, data)
                if truthy(v):
                    return v
            return v
        if op == "!":
            return not truthy(A(0))
        if op == "!!":
            return truthy(A(0))
        if op == "==":
            return loose_eq(A(0), A(1))
        if op == "!=":
            return not loose_eq(A(0), A(1))
        if op == "===":
            return strict_eq(A(0), A(1))
        if op == "!==":
            return not strict_eq(A(0), A(1))
        if op in ("<", "<=", ">", ">="):
            vals = [self.apply(a, data) for a in args_l]
            if len(vals) < 2:
                return False
            if len(vals) == 3:  # comp.go: a<b<c, a<=b<=c, c<b<a, c<=b<=a
                if op in ("<", "<="):
                    return _cmp(op, vals[0], vals[1]) and _cmp(op, vals[1], vals[2])
                return _cmp(op, vals[1], vals[2]) and _cmp(op, vals[0], vals[1])
            return _cmp(op, vals[0], vals[1])
        if op == "in":
            a, b = A(0), A(1)
            if isinstance(b, str):
                if not isinstance(a, str):
                    raise JLError("in: non-string needle (Go panic in lists.go _in)")
                return a in b
            if isinstance(b, list):
                for e in b:
                    if isinstance(e, list):  # lists.go _inRange
                        if len(e) < 2:
                            raise JLError("in: range with fewer than 2 bounds (Go panic)")
                        v = _types_to_number(a)
                        if v >= _types_to_number(e[0]) and _types_to_number(e[1]) >= v:
                            return True
                        continue
                    if is_number(a):
                        if _types_to_number(e) == float(a):
                            return True
                        continue
                    if isinstance(e, (dict, list)) and isinstance(a, type(e)):
                        raise JLError("in: comparing uncomparable values (Go panic)")
                    if _same_type(e, a) and e == a:
                        return True
                    if e is None and a is None:
                        return True
                return False
            return False
        if op == "cat":
            return "".join(go_fmt(v) for v in (self.apply(a, data) for a in args_l))
        if op == "substr":
            s = go_fmt(A(0)) if not isinstance(A(0), str) else A(0)
            start = int(to_number(A(1)))
            if start < 0:
                start = max(0, len(s) + start)
            if len(args_l) > 2:
                ln = int(to_number(A(2)))
                end = len(s) + ln if ln < 0 else start + ln
                return s[start:end]
            return s[start:]
        if op in ("+", "*"):
            vals = [to_number(self.apply(a, data)) for a in args_l]
            if op == "+":
                return float(sum(vals))
            r = 1.0
            for v in vals:
                r *= v
            return r
        if op == "-":
            vals = [to_number(self.apply(a, data)) for a in args_l]
            if len(vals) == 1:
                return -vals[0]
            return vals[0] - vals[1]
        if op == "/":
            return to_number(A(0)) / to_number(A(1))
        if op == "%":
            return math.fmod(to_number(A(0)), to_number(A(1)))
        if op in ("min", "max"):
            vals = [to_number(self.apply(a, data)) for a in args_l]
            if not vals:
                return None
            return min(vals) if op == "min" else max(vals)
        if op == "merge":
            out = []
            for a in args_l:
                v = self.apply(a, data)
                out.extend(v if isinstance(v, list) else [v])
            return out
        if op in self.custom:
            return self.custom[op]([self.apply(a, data) for a in args_l] if isinstance(args, list)
                                   else self.apply(args, data), data)
        raise JLError("The operator \"%s\" is not supported" % op)


def referenced_vars(node, out=None):
    """All literal var paths referenced anywhere in a JSONLogic tree."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for op, args in node.items():
            if op == "var":
                p = args[0] if isinstance(args, list) and args else args
                if isinstance(p, str) and p not in out:
                    out.append(p)
                elif not isinstance(p, str) and not (isinstance(p, list) and not p):
                    referenced_vars(p, out)
            else:
                referenced_vars(args, out)
    elif isinstance(node, list):
        for x in node:
            referenced_vars(x, out)
    return out
