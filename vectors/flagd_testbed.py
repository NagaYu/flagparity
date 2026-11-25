"""Run the official flagd-testbed Gherkin scenarios against each registered flagd semantics.

Applicability (DECISIONS.md P1-Z-2): an Examples row applies to generation Gk iff its combined
Feature/Scenario/Examples tags carry no @fractional-vN with N != k. Scenarios containing steps that
are not evaluation semantics (provider connection, events, caching, metadata, ...) are out of scope
and counted separately.
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TB = os.path.join(HERE, "upstream", "flagd-testbed")

# Out of scope per P1-Z-2: context enrichment (provider-side), and the deprecated RPC-protocol
# mapping of a missing defaultVariant (json.go L457-L460 / L481-L484, keyed on ProtoVersionKey,
# i.e. the transport protocol, not the flag file).
OUT_OF_SCOPE_TAGS = {"@contextEnrichment": "context enrichment (provider)",
                     "@deprecated": "deprecated RPC protocol mapping (ProtoVersionKey)"}
FIXED_NOW = 1795564800  # 2026-11-25T00:00:00Z, used for $flagd.timestamp in vectors only

GEN_TAG = {"G1": "@fractional-v1", "G2": "@fractional-v2", "G3": "@fractional-v3"}

STEP_PATTERNS = [
    ("noop", re.compile(r'^(?:an evaluator|a stable flagd provider|an option "cache" of type "CacheType" with value "disabled")$')),
    ("flag", re.compile(r'^a (\w+)-flag with key "([^"]*)" and a (?:default|fallback) value "(.*)"$')),
    ("tk", re.compile(r'^a context containing a targeting key with value "(.*)"$')),
    ("nested", re.compile(r'^a context containing a nested property with outer key "([^"]*)" and inner key "([^"]*)", with value "(.*)"$')),
    ("key", re.compile(r'^a context containing a key "([^"]*)", with type "([^"]*)" and with value "(.*)"$')),
    ("eval", re.compile(r'^the flag was evaluated with details$')),
    ("value", re.compile(r'^the resolved details value should be "(.*)"$')),
    ("reason", re.compile(r'^the reason should be "(.*)"$')),
    ("variant", re.compile(r'^the variant should be "(.*)"$')),
    ("error", re.compile(r'^the error-code should be "(.*)"$')),
]


def parse_feature(path):
    """Minimal Gherkin parser: returns list of (tags, steps, row_dict) per runnable example."""
    lines = open(path, encoding="utf-8").read().splitlines()
    feature_tags, pending_tags = [], []
    background, scenarios = [], []
    cur = None
    in_examples = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith('"""'):
            in_doc = not globals().get("_in_doc_dummy", False)
            if cur is not None and cur["steps"]:
                cur["steps"][-1] += " <<doc-string>>"
            continue
        if line.startswith("@"):
            pending_tags += line.split()
            continue
        if line.startswith("Feature:"):
            feature_tags, pending_tags = pending_tags, []
            continue
        if line.startswith("Background:"):
            cur = {"kind": "bg", "steps": background}
            pending_tags = []
            continue
        if line.startswith("Scenario"):
            cur = {"kind": "sc", "name": line, "tags": pending_tags, "steps": [], "examples": []}
            scenarios.append(cur)
            pending_tags, in_examples = [], None
            continue
        if line.startswith("Examples"):
            in_examples = {"tags": pending_tags, "header": None, "rows": []}
            cur["examples"].append(in_examples)
            pending_tags = []
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if in_examples is None:
                if cur is not None and cur["steps"] and not cur["steps"][-1].endswith(" <<data-table>>"):
                    cur["steps"][-1] += " <<data-table>>"
                continue
            if in_examples["header"] is None:
                in_examples["header"] = cells
            else:
                in_examples["rows"].append(dict(zip(in_examples["header"], cells)))
            continue
        m = re.match(r"^(Given|When|Then|And|But)\s+(.*)$", line)
        if m:
            cur["steps"].append(m.group(2))
    out = []
    for sc in scenarios:
        steps = background + sc["steps"]
        if not sc["examples"]:
            out.append((feature_tags + sc["tags"], sc["name"], steps, {}))
        for ex in sc["examples"]:
            for row in ex["rows"]:
                out.append((feature_tags + sc["tags"] + ex["tags"], sc["name"], steps, row))
    return out


def _subst(s, row):
    return re.sub(r"<([^>]+)>", lambda m: row.get(m.group(1), m.group(0)), s)


def _unescape(v):
    return v.replace('\\"', '"')


def _typed(t, v):
    t = t.lower()
    if t == "string":
        return v
    if t == "integer":
        return int(v)
    if t in ("float", "double", "number"):
        return float(v)
    if t == "boolean":
        return v.lower() == "true"
    if t == "object":
        return json.loads(_unescape(v)) if v else {}
    raise ValueError("unknown type %s" % t)


def _resolve(fdoc, key, ftype, code_default, ctx, sem):
    from flagparity.formats.flagd import evaluate_variant
    variant, reason, err = evaluate_variant(fdoc, key, ctx, sem, now=FIXED_NOW)
    if err:
        return code_default, None, "ERROR", err
    if reason in ("FALLBACK",):
        return code_default, None, "DEFAULT", None
    if reason == "DISABLED":
        return code_default, None, "DISABLED", None
    value = fdoc.flags[key]["variants"][variant]
    t = ftype.lower()
    ok = (t == "boolean" and isinstance(value, bool)) or \
         (t == "string" and isinstance(value, str)) or \
         (t == "integer" and isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == int(value)) or \
         (t == "float" and isinstance(value, (int, float)) and not isinstance(value, bool)) or \
         (t == "object" and isinstance(value, (dict, list)))
    if not ok:
        return code_default, variant, "ERROR", "TYPE_MISMATCH"
    return value, variant, reason, None


def _eq_value(ftype, got, expected_text):
    t = ftype.lower()
    if t == "string":
        return got == expected_text
    if t == "boolean":
        return got is (expected_text.lower() == "true")
    if t in ("integer", "float"):
        return isinstance(got, (int, float)) and not isinstance(got, bool) and float(got) == float(expected_text) \
            and (t == "float" or float(got) == int(float(expected_text)))
    if t == "object":
        return got == (json.loads(_unescape(expected_text)) if expected_text else {})
    return False


def load_flag_files(kind):
    from flagparity.formats.flagd import FlagdDoc
    if kind == "evaluator":
        paths = [os.path.join(TB, "evaluator", "flags", "testkit-flags.json")]
    else:
        paths = sorted(p for p in glob.glob(os.path.join(TB, "flags", "*.json"))
                       if not os.path.basename(p).startswith("selector"))
    merged = {"flags": {}, "$evaluators": {}}
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        merged["flags"].update(d.get("flags", {}))
        merged["$evaluators"].update(d.get("$evaluators", {}))
    return FlagdDoc(merged)


def run(sem):
    gen = sem.id.split("/")[1]
    other = {t for g, t in GEN_TAG.items() if g != gen}
    docs = {"provider": load_flag_files("provider"), "evaluator": load_flag_files("evaluator")}
    results = {"applicable": 0, "pass": 0, "fail": 0, "out_of_scope": 0, "not_applicable_version": 0,
               "failures": []}
    feats = sorted(glob.glob(os.path.join(TB, "gherkin", "*.feature"))) + \
        sorted(glob.glob(os.path.join(TB, "evaluator", "gherkin", "*.feature")))
    for fp in feats:
        kind = "evaluator" if os.sep + "evaluator" + os.sep in fp else "provider"
        rel = os.path.relpath(fp, TB)
        for tags, name, steps, row in parse_feature(fp):
            if set(tags) & other:
                results["not_applicable_version"] += 1
                continue
            if gen == "G1" and "@fractional" in tags and "@fractional-v1" not in tags:
                # DECISIONS P1-Z-5 (owner-approved): untagged fractional scenarios are not G1 vectors
                results["not_applicable_version"] += 1
                results["g1_excluded_untagged_fractional"] = results.get("g1_excluded_untagged_fractional", 0) + 1
                continue
            oos = [OUT_OF_SCOPE_TAGS[t] for t in tags if t in OUT_OF_SCOPE_TAGS]
            if oos:
                results["out_of_scope"] += 1
                results.setdefault("out_of_scope_by_reason", {}).setdefault(oos[0], 0)
                results["out_of_scope_by_reason"][oos[0]] += 1
                continue
            parsed = []
            scope_ok = True
            for st in steps:
                s = _subst(st, row)
                for kindname, rx in STEP_PATTERNS:
                    m = rx.match(s)
                    if m:
                        parsed.append((kindname, m.groups()))
                        break
                else:
                    scope_ok = False
                    break
            if not scope_ok or not any(k == "eval" for k, _ in parsed):
                results["out_of_scope"] += 1
                continue
            results["applicable"] += 1
            ctx, flag, outcome, ok, why = {}, None, None, True, []
            for k, g in parsed:
                if k == "flag":
                    flag = (g[0], g[1], g[2])
                elif k == "tk":
                    ctx["targetingKey"] = g[0]
                elif k == "nested":
                    ctx.setdefault(g[0], {})[g[1]] = g[2]
                elif k == "key":
                    ctx[g[0]] = _typed(g[1], g[2])
                elif k == "eval":
                    ftype, fkey, fdef = flag
                    try:
                        cd = _typed(ftype, fdef)
                    except (ValueError, json.JSONDecodeError):
                        cd = fdef
                    outcome = _resolve(docs[kind], fkey, ftype, cd, ctx, sem)
                elif k == "value":
                    if not _eq_value(flag[0], outcome[0], g[0]):
                        ok = False
                        why.append("value %r != %r" % (outcome[0], g[0]))
                elif k == "reason":
                    if outcome[2] != g[0]:
                        ok = False
                        why.append("reason %s != %s" % (outcome[2], g[0]))
                elif k == "variant":
                    if outcome[1] != g[0]:
                        ok = False
                        why.append("variant %s != %s" % (outcome[1], g[0]))
                elif k == "error":
                    if outcome[3] != (g[0] or None):
                        ok = False
                        why.append("error %s != %s" % (outcome[3], g[0]))
            if ok:
                results["pass"] += 1
            else:
                results["fail"] += 1
                results["failures"].append({"feature": rel, "scenario": name, "row": row, "why": why})
    return results
