"""Finite witness sets for rule reachability (F1/F3).

For each context attribute that conditions mention, build a finite set of representative values from the
constants the conditions compare it with, so that every combination of atom truth values that is
achievable by *some* value is achieved by at least one representative. Reachability is then decided by
concretely evaluating the engine's own condition semantics on every combination (cartesian product).

A rule is reported *unreachable* only when every attribute's representative set is complete for the
operators used on it and the product stayed under the cap; otherwise the verdict is not-judgeable.
"""
import itertools
import re

MISSING = object()
FRESH = "\u0001fb-fresh\u0001"
CAP = 20000


class Collector:
    def __init__(self, mode="json", case_fold=False):
        self.mode = mode            # "json" (any JSON type) | "string" (Flipt: context values are strings)
        self.case_fold = case_fold
        self.attrs = {}
        self.incomplete = {}

    def _a(self, attr):
        return self.attrs.setdefault(attr, {"eq": [], "prefix": [], "suffix": [], "contains": [],
                                            "order": [], "semver": [], "bool": False, "datetime": []})

    def eq(self, attr, v):
        self._a(attr)["eq"].append(v)

    def prefix(self, attr, s):
        self._a(attr)["prefix"].append(s)

    def suffix(self, attr, s):
        self._a(attr)["suffix"].append(s)

    def contains(self, attr, s):
        self._a(attr)["contains"].append(s)

    def order(self, attr, n):
        self._a(attr)["order"].append(float(n))

    def semver(self, attr, v):
        self._a(attr)["semver"].append(v)

    def boolean(self, attr):
        self._a(attr)["bool"] = True

    def datetime(self, attr, v):
        self._a(attr)["datetime"].append(v)

    def present(self, attr):
        self._a(attr)

    def unknown(self, attr, why):
        self._a(attr)
        self.incomplete.setdefault(attr, why)

    # ---------------------------------------------------------------------------------------------
    def candidates(self, attr):
        o = self.attrs[attr]
        vals = [MISSING, FRESH]
        strs = []
        for v in o["eq"]:
            vals.append(v)
            if isinstance(v, str):
                strs.append(v)
        if len(set(o["contains"])) > 1:
            self.incomplete.setdefault(attr, "more than one 'contains' constant on one attribute")
        pre = sorted(set(o["prefix"])) + [""]
        suf = sorted(set(o["suffix"])) + [""]
        mids = ["\u0001"] + ["\u0001" + c + "\u0001" for c in sorted(set(o["contains"]))]
        if o["prefix"] or o["suffix"] or o["contains"]:
            for p in pre:
                for q in suf:
                    for m in mids:
                        vals.append(p + m + q)
            for s in strs:
                vals.append(s + "\u0001")
                vals.append("\u0001" + s)
        vals.append("")
        nums = sorted(set(o["order"]) | {float(v) for v in o["eq"] if isinstance(v, (int, float)) and not isinstance(v, bool)})
        if nums:
            pts = [nums[0] - 1.0]
            for i, n in enumerate(nums):
                pts.append(n)
                if i + 1 < len(nums):
                    pts.append((n + nums[i + 1]) / 2.0)
            pts.append(nums[-1] + 1.0)
            for x in pts:
                if self.mode == "string":
                    vals.append(_num_str(x))
                else:
                    vals.append(int(x) if x == int(x) else x)
                    if x == int(x):
                        vals.append(float(x))
                    vals.append(_num_str(x))
        if o["semver"]:
            vals.extend(semver_representatives(o["semver"]))
        if o["bool"] or self.mode == "json":
            vals.extend(["true", "false"] if self.mode == "string" else [True, False])
        if self.mode == "json":
            vals.append(None)
        for v in o["datetime"]:
            vals.extend(_dt_neighbours(v))
        if self.case_fold:
            extra = []
            for v in vals:
                if isinstance(v, str):
                    extra += [v.lower(), v.upper()]
            vals += extra
        out, seen = [], set()
        for v in vals:
            if self.mode == "string" and v is not MISSING and not isinstance(v, str):
                v = _num_str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v).lower()
            key = ("M",) if v is MISSING else (type(v).__name__, repr(v))
            if key not in seen:
                seen.add(key)
                out.append(v)
        return out

    def assignments(self):
        """Yields dicts attr->value (MISSING entries omitted). Returns (iterator, complete, reason)."""
        names = sorted(self.attrs)
        cands = [self.candidates(a) for a in names]
        total = 1
        for c in cands:
            total *= len(c)
        complete = not self.incomplete and total <= CAP
        reason = None
        if self.incomplete:
            a = sorted(self.incomplete)[0]
            reason = "attribute %r: %s" % (a, self.incomplete[a])
        elif total > CAP:
            reason = "witness space %d exceeds cap %d" % (total, CAP)

        def gen():
            if total > CAP:
                # still try a bounded diagonal sample so reachable rules get witnesses
                for i in range(CAP):
                    yield {n: c[(i * (k + 1)) % len(c)] for k, (n, c) in enumerate(zip(names, cands))}
                return
            for combo in itertools.product(*cands):
                yield {n: v for n, v in zip(names, combo)}
        return gen(), complete, reason, min(total, CAP)


def _num_str(x):
    return str(int(x)) if x == int(x) else repr(x)


_SV = re.compile(r"[vV]?(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:\.(0|[1-9]\d*))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?")


def _sv_parse(v):
    m = _SV.fullmatch(str(v))
    if not m:
        return None
    a, b, c, pre = m.groups()
    ids = pre.split(".") if pre else []
    if any(x.isdigit() and len(x) > 1 and x[0] == "0" for x in ids):
        return None
    return (int(a), int(b or 0), int(c or 0), tuple(ids))


def _sv_cmp(x, y):
    """SemVer 2.0 precedence (golang.org/x/mod/semver and blang/semver/v4 agree on it)."""
    if x[:3] != y[:3]:
        return -1 if x[:3] < y[:3] else 1
    p, q = x[3], y[3]
    if p == q:
        return 0
    if not p:
        return 1
    if not q:
        return -1
    for i, j in zip(p, q):
        if i == j:
            continue
        di, dj = i.isdigit(), j.isdigit()
        if di and dj:
            return -1 if int(i) < int(j) else 1
        if di != dj:
            return -1 if di else 1
        return -1 if i < j else 1
    return -1 if len(p) < len(q) else 1


def _sv_str(x):
    return "%d.%d.%d" % x[:3] + ("-" + ".".join(x[3]) if x[3] else "")


def _sv_succ(x):
    """Smallest version strictly greater than x: x.0 for a prerelease, M.m.(p+1)-0 for a release."""
    if x[3]:
        return x[:3] + (x[3] + ("0",),)
    return (x[0], x[1], x[2] + 1, ("0",))


def semver_representatives(consts):
    """Complete witness set for sem_ver / GOFF version comparisons (=, !=, <, <=, >, >=, ~, ^) against `consts`.

    Points = every parseable constant, plus the ~ and ^ class boundaries of each (M.m.0-0, M.(m+1).0-0, M.0.0-0,
    (M+1).0.0-0) and the global minimum 0.0.0-0. Any version v equals a point or lies strictly between two
    consecutive points (or above the last); the successor of the lower point lies in the same open interval, so it
    has the same relation to every constant and the same ~/^ class membership. Representatives = points and their
    successors, plus one string that is not a version (comparisons on it are false / null)."""
    import functools
    pts = {(0, 0, 0, ("0",))}
    for c in consts:
        x = _sv_parse(c)
        if x is None:
            continue
        pts.add(x)
        M, m = x[0], x[1]
        pts |= {(M, m, 0, ("0",)), (M, m + 1, 0, ("0",)), (M, 0, 0, ("0",)), (M + 1, 0, 0, ("0",))}
    reps = set(pts) | {_sv_succ(p) for p in pts}
    out = [_sv_str(x) for x in sorted(reps, key=functools.cmp_to_key(_sv_cmp))]
    return out + ["not-a-version"]


def _semver_neighbours(v):
    m = re.fullmatch(r"[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?", str(v))
    if not m:
        return [str(v)]
    a, b, c = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    out = [str(v), "%d.%d.%d" % (a, b, c), "%d.%d.%d-0" % (a, b, c), "%d.%d.%d" % (a, b, c + 1),
           "%d.%d.0" % (a, b + 1), "%d.0.0" % (a + 1)]
    if c > 0:
        out.append("%d.%d.%d" % (a, b, c - 1))
    if b > 0:
        out.append("%d.%d.99999" % (a, b - 1))
    if a > 0:
        out.append("%d.99999.0" % (a - 1))
    return out


def _dt_neighbours(v):
    from datetime import datetime, timedelta, timezone
    out = [v]
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            d = datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        for delta in (timedelta(seconds=-1), timedelta(seconds=1)):
            out.append((d + delta).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        out.append("1970-01-01T00:00:00Z")
        out.append("2999-01-01T00:00:00Z")
    except (ValueError, TypeError):
        pass
    return out
