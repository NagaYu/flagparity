"""Flipt vector suites, taken from Flipt's own test files (pinned in vectors/upstream/).

1. Constraint tables, extracted mechanically from the Go table tests (Test_matches*) of
   flipt@v1.62.1 legacy_evaluator_test.go and flipt@v2.14.2 evaluation_test.go, and from the Rust
   macro tests (matches_*_tests!) of flipt-client-sdks@19e54652 flipt-evaluation/src/lib.rs.
2. Evaluation vectors, transcribed by hand from the evaluator tests (file:line recorded per vector).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, "upstream")
sys.path.insert(0, os.path.dirname(HERE))

from flagparity.formats.flipt import FliptDoc, match_constraint, evaluate_variant, evaluate_boolean  # noqa: E402

OPS = {"OpEQ": "eq", "OpNEQ": "neq", "OpLT": "lt", "OpLTE": "lte", "OpGT": "gt", "OpGTE": "gte",
       "OpEmpty": "empty", "OpNotEmpty": "notempty", "OpTrue": "true", "OpFalse": "false",
       "OpPresent": "present", "OpNotPresent": "notpresent", "OpPrefix": "prefix", "OpSuffix": "suffix",
       "OpIsOneOf": "isoneof", "OpIsNotOneOf": "isnotoneof", "OpContains": "contains",
       "OpNotContains": "notcontains"}
CTYPE = {"String": "STRING_COMPARISON_TYPE", "Number": "NUMBER_COMPARISON_TYPE",
         "Bool": "BOOLEAN_COMPARISON_TYPE", "DateTime": "DATETIME_COMPARISON_TYPE"}


def _go_str(tok):
    tok = tok.strip().rstrip(",")
    if tok.startswith("`"):
        return tok[1:-1]
    if tok.startswith('"'):
        return json.loads(tok)
    m = re.match(r"flipt\.(Op\w+)", tok)
    if m:
        return OPS[m.group(1)]
    raise ValueError(tok)


def go_constraint_tables(path, version):
    src = open(path, encoding="utf-8").read()
    out = []
    for m in re.finditer(r"^func Test_matches(String|Number|Bool|DateTime)(WithPreparedSets)?\(t \*testing\.T\) \{", src, re.M):
        kind = m.group(1)
        start = m.end()
        end = src.find("\nfunc ", start)
        body = src[start:end if end > 0 else len(src)]
        line0 = src[:m.start()].count("\n") + 1
        for e in re.finditer(r"\{\s*\n\s*name:\s*(\"[^\"]*\"),(.*?)\n\t\t\},?\n", body, re.S):
            blk = e.group(2)
            cm = re.search(r"constraint:\s*storage\.EvaluationConstraint\{(.*?)\n\t\t\t\},", blk, re.S)
            if not cm:
                continue
            cons = {}
            for k in ("Property", "Operator", "Value"):
                km = re.search(r"\b%s:\s*(`[^`]*`|\"(?:[^\"\\]|\\.)*\"|flipt\.Op\w+)" % k, cm.group(1))
                if km:
                    cons[k.lower()] = _go_str(km.group(1))
            vm = re.search(r"\n\s*value:\s*(`[^`]*`|\"(?:[^\"\\]|\\.)*\")", blk[cm.end():])
            value = _go_str(vm.group(1)) if vm else ""
            want = bool(re.search(r"wantMatch:\s*true", blk))
            wanterr = bool(re.search(r"wantErr:\s*true", blk))
            cons["type"] = CTYPE[kind]
            line = line0 + body[:e.start()].count("\n") + 1
            out.append({"suite": "flipt-constraints-go@" + version, "ref": "%s:%d" % (os.path.relpath(path, UP), line),
                        "name": json.loads(e.group(1)), "constraint": cons, "value": value,
                        "want_match": want, "want_err": wanterr})
    return out


def rust_constraint_tables(path):
    src = open(path, encoding="utf-8").read()
    out = []
    for m in re.finditer(r"matches_(string|number|datetime)_tests!\s*\{", src):
        kind = {"string": "STRING_COMPARISON_TYPE", "number": "NUMBER_COMPARISON_TYPE",
                "datetime": "DATETIME_COMPARISON_TYPE"}[m.group(1)]
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        body = src[m.end():i - 1]
        for e in re.finditer(r"(\w+):\s*\(&flipt::EvaluationConstraint\s*\{(.*?)\},\s*(\"(?:[^\"\\]|\\.)*\"),\s*(true|false)\s*\)", body, re.S):
            fields = {}
            for k in ("property", "operator", "value"):
                km = re.search(r"%s:\s*String::from\((r#\"(.*?)\"#|\"((?:[^\"\\]|\\.)*)\")\)" % k, e.group(2), re.S)
                if km:
                    fields[k] = km.group(2) if km.group(2) is not None else json.loads('"%s"' % km.group(3))
            fields["type"] = kind
            line = src[:m.end()].count("\n") + body[:e.start()].count("\n") + 1
            out.append({"suite": "flipt-constraints-rust@19e54652",
                        "ref": "flipt-client-sdks@19e54652/flipt-evaluation/src/lib.rs:%d" % line,
                        "name": e.group(1), "constraint": fields, "value": json.loads(e.group(3)),
                        "want_match": e.group(4) == "true", "want_err": False})
    return out


def _doc(flag, segments=None):
    return FliptDoc([{"namespace": "default", "segments": segments or [], "flags": [flag]}])


SEG_BAR_BAZ = [{"key": "bar", "match_type": "ALL_MATCH_TYPE",
                "constraints": [{"type": "STRING_COMPARISON_TYPE", "property": "bar", "operator": "eq", "value": "baz"}]}]
SEG_ANY_BAR_BAZ = [{"key": "bar", "match_type": "ANY_MATCH_TYPE",
                    "constraints": [{"type": "STRING_COMPARISON_TYPE", "property": "bar", "operator": "eq", "value": "baz"}]}]
SEG_NOCONS = [{"key": "bar", "match_type": "ALL_MATCH_TYPE", "constraints": []}]


def _vflag(key, dists, variants=None, default=None, seg="bar"):
    vs = variants or sorted({d[0] for d in dists})
    return {"key": key, "type": "VARIANT_FLAG_TYPE", "enabled": True,
            "variants": [{"key": v, **({"default": True} if v == default else {})} for v in vs],
            "rules": [{"segment": seg, "distributions": [{"variant": v, "rollout": r} for v, r in dists]}]}


LEG = "flipt@v1.62.1/internal/server/evaluation/legacy_evaluator_test.go"
V2 = "flipt@v2.14.2/internal/server/evaluation/evaluation_test.go"
RS = "flipt-client-sdks@19e54652/flipt-evaluation/src/lib.rs"

# (suite, ref, flag, segments, entity, ctx, expected (variant, match))
EVAL_VECTORS = [
    ("flipt-go@v1.62.1", LEG + ":1538", _vflag("foo", [("boz", 10)]), SEG_BAR_BAZ, "123", {"bar": "baz"}, (None, False)),
    ("flipt-go@v1.62.1", LEG + ":1605", _vflag("foo", [("boz", 10)], ["bar", "boz"], "bar"), SEG_BAR_BAZ, "123", {"bar": "baz"}, ("bar", False)),
    ("flipt-go@v1.62.1", LEG + ":1804", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_BAR_BAZ, "1", {"bar": "baz"}, ("boz", True)),
    ("flipt-go@v1.62.1", LEG + ":1804", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_BAR_BAZ, "2", {"bar": "baz"}, ("booz", True)),
    ("flipt-go@v1.62.1", LEG + ":1804", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_BAR_BAZ, "1", {"bar": "boz"}, (None, False)),
    ("flipt-go@v1.62.1", LEG + ":2002", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_NOCONS, "10", {}, ("boz", True)),
    ("flipt-go@v1.62.1", LEG + ":2002", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_NOCONS, "01", {}, ("booz", True)),
    ("flipt-go@v1.62.1", LEG + ":2412", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_ANY_BAR_BAZ, "1", {"bar": "baz"}, ("boz", True)),
    ("flipt-go@v1.62.1", LEG + ":2412", _vflag("foo", [("boz", 50), ("booz", 50)]), SEG_ANY_BAR_BAZ, "2", {"bar": "baz"}, ("booz", True)),
    ("flipt-go@v1.62.1", LEG + ":2794", _vflag("foo", [("boz", 0), ("booz", 100)]), SEG_ANY_BAR_BAZ, "1", {"bar": "baz"}, ("booz", True)),
    ("flipt-go@v1.62.1", LEG + ":2893", _vflag("foo", [("1", 0), ("2", 0), ("3", 50), ("4", 0), ("5", 0), ("6", 50)]), SEG_ANY_BAR_BAZ, "1", {"bar": "baz"}, ("3", True)),
    ("flipt-go@v2.14.2", V2 + ":2636", _vflag("test-flag", [("test-variant", 100)], seg="segment-1"),
     [{"key": "segment-1", "match_type": "ALL_MATCH_TYPE", "constraints": [{"type": "STRING_COMPARISON_TYPE", "property": "hello", "operator": "eq", "value": "world"}]}],
     "test-entity", {"hello": "world"}, ("test-variant", True)),
    ("flipt-rust@19e54652", RS + ":1453", _vflag("foo", [("variant1", 1.0)]), SEG_BAR_BAZ, "123", {"bar": "baz"}, ("variant1", True)),
    ("flipt-rust@19e54652", RS + ":2105", _vflag("foo", [("variant1", 50), ("variant2", 50)]), SEG_BAR_BAZ, "1", {"bar": "baz"}, ("variant1", True)),
    ("flipt-rust@19e54652", RS + ":2105", _vflag("foo", [("variant1", 50), ("variant2", 50)]), SEG_BAR_BAZ, "2", {"bar": "baz"}, ("variant2", True)),
    ("flipt-rust@19e54652", RS + ":2330", _vflag("foo", [("variant1", 50), ("variant2", 50)]), SEG_NOCONS, "10", {}, ("variant1", True)),
    ("flipt-rust@19e54652", RS + ":2330", _vflag("foo", [("variant1", 50), ("variant2", 50)]), SEG_NOCONS, "01", {}, ("variant2", True)),
    ("flipt-rust@19e54652", RS + ":1995", _vflag("foo", [("variant1", 100)]), SEG_BAR_BAZ, "123", {"bar": "baz"}, ("variant1", True)),
]

# Count/range assertions over entity ids "0".."999" (Rust tests), flag key, rollouts, per-variant inclusive ranges
RANGE_VECTORS = [
    ("flipt-rust@19e54652", RS + ":1551", "foo", [("variant1", 33.33), ("variant2", 33.33), ("variant3", 33.34)],
     {"variant1": (1, 1000), "variant2": (1, 1000), "variant3": (1, 1000)}),
    ("flipt-rust@19e54652", RS + ":1655", "bar", [("v1", 50.0), ("v2", 30.0), ("v3", 20.0)],
     {"v1": (450, 550), "v2": (250, 350), "v3": (150, 250)}),
    ("flipt-rust@19e54652", RS + ":1777", "baz", [("v1", 10.0), ("v2", 20.0)], {"v1": (300, 366), "v2": (634, 700)}),
    ("flipt-rust@19e54652", RS + ":1886", None, [("v1", 80.0), ("v2", 40.0)], {"v1": (600, 700), "v2": (300, 400)}),
]

# Boolean threshold vectors (flag "test-flag", entity "test-entity")
BOOL_VECTORS = [
    ("flipt-go@v2.14.2", V2 + ":564", 5, False),
    ("flipt-go@v2.14.2", V2 + ":613", 70, True),
    ("flipt-go@v1.62.1", "flipt@v1.62.1/internal/server/evaluation/evaluation_test.go:286", 5, False),
    ("flipt-go@v1.62.1", "flipt@v1.62.1/internal/server/evaluation/evaluation_test.go:330", 70, True),
]


def rust_flag_key(ref_line):
    """The 80/40 test's flag key, read from the test body."""
    src = open(os.path.join(UP, RS), encoding="utf-8").read().splitlines()
    for ln in src[ref_line:ref_line + 30]:
        m = re.search(r'key: String::from\("([^"]+)"\)', ln)
        if m:
            return m.group(1)
    raise ValueError("flag key not found")


def suites_for(sem):
    return sem.vector_suites


def run(sem):
    res = {"applicable": 0, "pass": 0, "fail": 0, "failures": []}
    suites = set(sem.vector_suites)
    dialect = sem.impl.constraint_dialect
    cons = []
    if "flipt-constraints-go@v1.62.1" in suites:
        cons += go_constraint_tables(os.path.join(UP, LEG), "v1.62.1")
    if "flipt-constraints-go@v2.14.2" in suites:
        cons += go_constraint_tables(os.path.join(UP, V2), "v2.14.2")
    if "flipt-constraints-rust@19e54652" in suites:
        cons += rust_constraint_tables(os.path.join(UP, RS))
    for v in cons:
        res["applicable"] += 1
        m, err = match_constraint(v["constraint"], v["value"], dialect)
        ok = (m == v["want_match"]) and (not v["want_err"] or err)
        res["pass" if ok else "fail"] += 1
        if not ok:
            res["failures"].append({"ref": v["ref"], "name": v["name"], "got": [m, err], "want": [v["want_match"], v["want_err"]]})
    for suite, ref, flag, segs, ent, ctx, exp in EVAL_VECTORS:
        if suite not in suites:
            continue
        res["applicable"] += 1
        doc = _doc(flag, segs)
        got = evaluate_variant(doc.flags[0], ctx, ent, sem)
        ok = (got[0], got[1]) == exp
        res["pass" if ok else "fail"] += 1
        if not ok:
            res["failures"].append({"ref": ref, "entity": ent, "got": got[:2], "want": exp})
    for suite, ref, fkey, dists, ranges in RANGE_VECTORS:
        if suite not in suites:
            continue
        res["applicable"] += 1
        fkey = fkey or rust_flag_key(int(ref.rsplit(":", 1)[1]))
        doc = _doc(_vflag(fkey, dists), SEG_NOCONS)
        counts = {}
        allmatch = True
        for i in range(1000):
            v, m, _, _ = evaluate_variant(doc.flags[0], {}, str(i), sem)
            allmatch &= m
            counts[v] = counts.get(v, 0) + 1
        ok = allmatch and all(lo <= counts.get(k, 0) <= hi for k, (lo, hi) in ranges.items())
        res["pass" if ok else "fail"] += 1
        if not ok:
            res["failures"].append({"ref": ref, "counts": counts})
    for suite, ref, pct, hit in BOOL_VECTORS:
        if suite not in suites:
            continue
        res["applicable"] += 1
        doc = FliptDoc([{"flags": [{"key": "test-flag", "type": "BOOLEAN_FLAG_TYPE", "enabled": False,
                                    "rollouts": [{"threshold": {"percentage": pct, "value": True}}]}]}])
        val, reason, _ = evaluate_boolean(doc.flags[0], {}, "test-entity", sem)
        ok = (reason == "MATCH") == hit and (val is True) == hit
        res["pass" if ok else "fail"] += 1
        if not ok:
            res["failures"].append({"ref": ref, "got": [val, reason]})
    return res
