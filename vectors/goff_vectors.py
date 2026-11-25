"""GO Feature Flag vectors. Phase 0 recorded "no official vectors"; Phase 1 found input->expected cases in
GOFF's own unit tests, and the owner decided (DECISIONS P1-Z-6) that they count as official vectors for
goff/v1.32+. goff/pre-v1.32 has none and stays source-only.

goff-unit@v1.59.1  : percentage cases hand-transcribed from modules/core/flag/rule_test.go (TestRuleEvaluate,
                     flagName "flagname+") and internal_flag_test.go.
goff-rules@e9704fa7: query-language cases extracted mechanically from go-feature-flag/rules parser tests.
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, "upstream")
sys.path.insert(0, os.path.dirname(HERE))

from flagparity.formats import nikunjy  # noqa: E402

RT = "goff@v1.59.1/modules/core/flag/rule_test.go"
IT = "goff@v1.59.1/modules/core/flag/internal_flag_test.go"
UNIT = [
    (RT + ":180", "flagname+", "userkey", {"variation_B": 0, "variation_C": 100}, "variation_C"),
    (RT + ":195", "flagname+", "userkey", {"variation_C": 9, "variation_B": 91}, "variation_C"),
    (RT + ":210", "flagname+", "userkey", {"variation_C": 91, "variation_B": 91}, "variation_B"),
    (RT + ":225", "flagname+", "randomUserID", {"variation_D": 70, "variation_C": 10, "variation_B": 20}, "variation_C"),
    (RT + ":241", "flagname+", "96ac59e6-7492-436b-b15a-ba1d797d2423", {"variation_D": 70, "variation_C": 10, "variation_B": 20}, "variation_B"),
    (RT + ":257", "flagname+", "96ac59e6-7492-436b-b15a-ba1d797d2423", {"variation_D": 70, "variation_C": 10, "variation_B": 20}, "variation_B"),
    (IT + ":1705", "my-flag", "user-key", {"variation_A": 50, "variation_B": 50}, "variation_A"),
    (IT + ":1324", "my-flag", "user-key-123", {"variation_B": 30, "variation_C": 70}, "variation_C"),
]


def _go_literal_to_py(s):
    parts = re.split(r'(`[^`]*`|"(?:[^"\\]|\\.)*")', s)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 1:
            out.append(repr(p[1:-1]) if p.startswith("`") else p)
            continue
        p = re.sub(r"\b(?:obj|map\[string\]interface\{\}|map\[string\]any)\{", "{", p)
        p = re.sub(r"\[\](?:interface\{\}|any|string|int|float64)\{", "[", p)
        p = re.sub(r"\bnil\b", "None", p)
        p = re.sub(r"\btrue\b", "True", p)
        p = re.sub(r"\bfalse\b", "False", p)
        out.append(p)
    return "".join(out)


def _balanced(src, i, open_c="{", close_c="}"):
    depth = 0
    j = i
    in_str = None
    while j < len(src):
        c = src[j]
        if in_str:
            if c == "\\" and in_str == '"':
                j += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"`":
            in_str = c
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def rules_cases():
    out = []
    pdir = os.path.join(UP, "gofr", "parser")
    for fn in sorted(os.listdir(pdir)):
        if not (fn.startswith("parse_") and fn.endswith("_test.go")):
            continue
        src = open(os.path.join(pdir, fn), encoding="utf-8").read()
        for m in re.finditer(r"tests\s*:=\s*\[\]testCase\{", src):
            end = _balanced(src, m.end() - 1)
            body = src[m.end():end]
            i = 0
            while True:
                k = body.find("{", i)
                if k < 0:
                    break
                e = _balanced(body, k)
                lit = body[k + 1:e]
                i = e + 1
                try:
                    py = ast.literal_eval("(" + _go_literal_to_py(lit) + ")")
                except (ValueError, SyntaxError):
                    continue
                if not (isinstance(py, tuple) and len(py) >= 3 and isinstance(py[0], str)):
                    continue
                line = src[:m.end()].count("\n") + body[:k].count("\n") + 1
                out.append({"ref": "gofr/parser/%s:%d" % (fn, line), "rule": py[0], "input": py[1],
                            "result": py[2], "has_error": py[3] if len(py) > 3 else False})
    return out


def run_rules():
    res = {"applicable": 0, "pass": 0, "fail": 0, "failures": []}
    for c in rules_cases():
        res["applicable"] += 1
        try:
            node = nikunjy.parse(c["rule"])
            got = nikunjy.evaluate(node, c["input"] or {})
        except nikunjy.QueryParseError:
            got = False
        ok = got == (False if c["has_error"] else c["result"])  # GOFF: query error => rule does not apply
        res["pass" if ok else "fail"] += 1
        if not ok:
            res["failures"].append({"ref": c["ref"], "rule": c["rule"], "input": c["input"], "want": c["result"], "got": got})
    return res


def run(sem):
    res = {"applicable": 0, "pass": 0, "fail": 0, "failures": []}
    if "goff-unit@v1.59.1" in sem.vector_suites:
        for ref, fname, key, pcts, exp in UNIT:
            res["applicable"] += 1
            got = sem.impl.percentage(fname, key, {k: float(v) for k, v in pcts.items()})
            ok = got == exp
            res["pass" if ok else "fail"] += 1
            if not ok:
                res["failures"].append({"ref": ref, "want": exp, "got": got})
    if "goff-rules@e9704fa7" in sem.vector_suites:
        r = run_rules()
        for k in ("applicable", "pass", "fail"):
            res[k] += r[k]
        res["failures"] += r["failures"]
    return res
