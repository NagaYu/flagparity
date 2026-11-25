"""flagd fractional semantics, three generations (each re-implemented line-by-line from pinned source).

G1  flagd <= v0.14.x   open-feature/flagd@b9c099cb core/pkg/evaluator/fractional.go
    bucket input = explicit string, else flagKey+targetingKey (string); murmur3 StringSum32 as int32;
    bucket = |h| / MaxInt32 * 100 (float); weights int(float) (truncation), percentages w/total.
G2  v0.15.0..v0.17.x   @flagd/v0.17.1 (0c5b766d): same input; uint32 hash; bucket = (h*W)>>32;
    weights must be integral numbers (else error), negative -> 0, variants may be str/bool/number/nil.
G3  >= v0.18.0         @flagd/v0.18.0 (ac826d8e), unchanged in v0.19.0 except logging:
    input = deterministic CBOR of explicit value (any type), else CBOR [flagKey, targetingKey].

Each `fractional(values, data)` mirrors the Go `Evaluate(values, data any) any` contract:
values are the pre-evaluated JSONLogic arguments, data the evaluation context incl. "$flagd".
Returns the selected variant value, or None (Go nil) — G1 returns "" when no bucket matched.
"""
import math

from ..hashing import murmur3_32, cbor_core, flagd_normalize, CBORUnsupported
from .base import Semantics, register

MAXI32 = 2147483647


def _flag_key(data):
    p = data.get("$flagd") if isinstance(data, dict) else None
    return p.get("flagKey", "") if isinstance(p, dict) else ""


class FlagdG1:
    gen = "G1"

    def fractional(self, values, data):
        if not isinstance(values, list):
            return None
        if len(values) < 2:
            return None
        if not isinstance(data, dict):
            return None
        vals = list(values)
        if isinstance(vals[0], str):
            bucket_by = vals[0]
            vals = vals[1:]
        else:
            if vals[0] is None:
                vals = vals[1:]
            tk = data.get("targetingKey")
            if not isinstance(tk, str):
                return None
            bucket_by = _flag_key(data) + tk
        dist = []
        total = 0
        for d in vals:
            if not isinstance(d, list) or not d:
                return None
            if not isinstance(d[0], str):
                return None
            w = 1.0
            if len(d) >= 2 and isinstance(d[1], (int, float)) and not isinstance(d[1], bool):
                w = float(d[1])
            wi = int(w)  # Go int(float64) truncates toward zero
            total += wi
            dist.append((d[0], wi))
        h = murmur3_32(bucket_by.encode("utf-8"))
        hv = h - 2 ** 32 if h >= 2 ** 31 else h
        bucket = abs(float(hv)) / MAXI32 * 100
        end = 0.0
        for v, w in dist:
            end += (100 * float(w) / float(total)) if total != 0 else 0.0
            if bucket < end:
                return v
        return ""

    def describe_input(self):
        return "utf8(explicit string | flagKey+targetingKey)"


class _IntegerBucketing:
    def _parse_dists(self, vals):
        out = []
        total = 0
        for d in vals:
            if not isinstance(d, list) or not d:
                return None, "distribution element not an array / empty"
            v = d[0]
            if not (v is None or isinstance(v, (str, bool, int, float))):
                return None, "variant must be string, bool, number or nil"
            w = 1
            if len(d) >= 2:
                raw = d[1]
                if raw is not None and (isinstance(raw, bool) or not isinstance(raw, (int, float))):
                    return None, "weight must be a number"
                if raw is not None:
                    if float(raw) != float(int(raw)):
                        return None, "weights must be integers"
                    w = int(raw)
            if w > MAXI32:
                return None, "weight exceeds MaxInt32"
            if w < 0:
                w = 0
            total += w
            out.append((v, w))
        if total > MAXI32:
            return None, "sum of weights exceeds MaxInt32"
        return (out, total), None

    @staticmethod
    def _distribute(h, dist, total):
        if total == 0:
            return None
        bucket = (h * total) >> 32
        end = 0
        for v, w in dist:
            end += w
            if bucket < end:
                return v
        return None


class FlagdG2(_IntegerBucketing):
    gen = "G2"

    def fractional(self, values, data):
        if not isinstance(values, list) or len(values) < 1 or not isinstance(data, dict):
            return None
        vals = list(values)
        if isinstance(vals[0], str):
            bucket_by = vals[0]
            vals = vals[1:]
        else:
            if vals[0] is None:
                vals = vals[1:]
            tk = data.get("targetingKey")
            if tk is None:
                return None
            if not isinstance(tk, str):
                return None
            if tk == "":
                return None
            bucket_by = _flag_key(data) + tk
        parsed, err = self._parse_dists(vals)
        if err:
            return None
        dist, total = parsed
        return self._distribute(murmur3_32(bucket_by.encode("utf-8")), dist, total)

    def describe_input(self):
        return "utf8(explicit string | flagKey+targetingKey)"


class FlagdG3(_IntegerBucketing):
    gen = "G3"

    def fractional(self, values, data):
        if not isinstance(values, list) or len(values) < 1 or not isinstance(data, dict):
            return None
        vals = list(values)
        if vals[0] is None:
            return None
        if not isinstance(vals[0], list):
            try:
                b = cbor_core(flagd_normalize(vals[0]))
            except CBORUnsupported:
                return None
            vals = vals[1:]
        else:
            tk = data.get("targetingKey")
            if tk is None or not isinstance(tk, str) or tk == "":
                return None
            b = cbor_core([_flag_key(data), tk])
        parsed, err = self._parse_dists(vals)
        if err:
            return None
        dist, total = parsed
        return self._distribute(murmur3_32(b), dist, total)

    def describe_input(self):
        return "cbor(explicit value | [flagKey, targetingKey])"


SRC = "https://github.com/open-feature/flagd/blob/%s/core/pkg/evaluator/fractional.go"

register(Semantics(
    id="flagd/G1", format="flagd", label="flagd <= v0.14.x (float percentage bucketing)", order=1,
    kind="version", sources=(SRC % "b9c099cb7fa002a509a82c81b467f5e784c27e82",),
    vector_suites=("flagd-testbed@7690b548:G1",), impl=FlagdG1()))
register(Semantics(
    id="flagd/G2", format="flagd", label="flagd v0.15.0-v0.17.x (integer (h*W)>>32, string input)", order=2,
    kind="version", sources=(SRC % "0c5b766d365676e413ff31044a9d02ad83b356cc",),
    vector_suites=("flagd-testbed@7690b548:G2",), impl=FlagdG2()))
register(Semantics(
    id="flagd/G3", format="flagd", label="flagd >= v0.18.0 (integer, CBOR input)", order=3,
    kind="version", sources=(SRC % "ac826d8e9cf3f5b14ad56f6e9eeeb981f45321eb",
                             SRC.replace("%s", "flagd/v0.19.0")),
    vector_suites=("flagd-testbed@7690b548:G3",), impl=FlagdG3()))


# ---------------- shared custom operators (flagd v0.19.0; not version-split in this model) ----------------

def _semver_parse(v):
    """golang.org/x/mod/semver parse. Returns (major, minor, patch, prerelease-list) or None."""
    if not isinstance(v, str) or not v.startswith("v"):
        return None
    s = v[1:]
    build = None
    if "+" in s:
        s, build = s.split("+", 1)
        if build == "" or any(p == "" or not all(c.isalnum() or c == "-" for c in p) for p in build.split(".")):
            return None
    pre = None
    if "-" in s:
        s, pre = s.split("-", 1)
        if pre == "":
            return None
    parts = s.split(".")
    if len(parts) > 3 or any(p == "" for p in parts):
        return None
    for p in parts:
        if not p.isdigit() or (len(p) > 1 and p[0] == "0") or not p.isascii():
            return None
    if len(parts) < 3 and (pre is not None or build is not None):
        return None  # x/mod/semver: shorthand forms may not carry prerelease/build
    nums = [int(p) for p in parts] + [0] * (3 - len(parts))
    pl = []
    if pre is not None:
        for p in pre.split("."):
            if p == "" or not all(c.isalnum() or c == "-" for c in p) or not p.isascii():
                return None
            if p.isdigit() and len(p) > 1 and p[0] == "0":
                return None
            pl.append(p)
    return nums[0], nums[1], nums[2], pl


def _semver_cmp(a, b):
    pa, pb = _semver_parse(a), _semver_parse(b)
    if pa is None and pb is None:
        return 0
    if pa is None:
        return -1
    if pb is None:
        return 1
    if pa[:3] != pb[:3]:
        return -1 if pa[:3] < pb[:3] else 1
    xa, xb = pa[3], pb[3]
    if not xa and not xb:
        return 0
    if not xa:
        return 1
    if not xb:
        return -1
    for i in range(min(len(xa), len(xb))):
        p, q = xa[i], xb[i]
        if p == q:
            continue
        pd, qd = p.isdigit(), q.isdigit()
        if pd and qd:
            return -1 if int(p) < int(q) else 1
        if pd:
            return -1
        if qd:
            return 1
        return -1 if p < q else 1
    if len(xa) == len(xb):
        return 0
    return -1 if len(xa) < len(xb) else 1


def _semver_major(v):
    p = _semver_parse(v)
    return "" if p is None else "v%d" % p[0]


def _semver_major_minor(v):
    p = _semver_parse(v)
    return "" if p is None else "v%d.%d" % (p[0], p[1])


def _normalize_version(v):
    from ..jsonlogic import go_fmt
    s = v if isinstance(v, str) else go_fmt(v)
    if not s.startswith("v"):
        if s.startswith("V"):
            s = s[1:]
        s = "v" + s
    return s if _semver_parse(s) is not None else None


def op_sem_ver(values, _data):
    if not isinstance(values, list) or len(values) != 3:
        return None
    a = _normalize_version(values[0])
    if a is None:
        return None
    op = values[1]
    if not isinstance(op, str):
        return None
    b = _normalize_version(values[2])
    if b is None:
        return None
    c = _semver_cmp(a, b)
    if op == "<":
        return c == -1
    if op == "=":
        return c == 0
    if op == "!=":
        return c != 0
    if op == "<=":
        return c <= 0
    if op == ">=":
        return c >= 0
    if op == ">":
        return c == 1
    if op == "~":
        return _semver_cmp(_semver_major_minor(a), _semver_major_minor(b)) == 0
    if op == "^":
        return _semver_cmp(_semver_major(a), _semver_major(b)) == 0
    return None


def _string_cmp(fn):
    def op(values, _data):
        if not isinstance(values, list) or len(values) != 2:
            return None
        if values[0] is None:
            return None
        if not isinstance(values[0], str) or not isinstance(values[1], str):
            return None
        return fn(values[0], values[1])
    return op


op_starts_with = _string_cmp(lambda a, b: a.startswith(b))
op_ends_with = _string_cmp(lambda a, b: a.endswith(b))
