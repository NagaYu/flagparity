"""Phase 3 fuzz generator (DECISIONS.md §P3-B B-1). Deterministic: same seed + count -> same bytes.

  python3 -I fuzz/gen.py OUTDIR [--seed N] [--per-format N]

Writes OUTDIR/<format>-<nnnn>.<ext> and OUTDIR/index.json ({file: {format, families}}).
Imports nothing from flagparity/ (formerly flagbound/) (the detector) or holdout/ (the checker).

Families (weighted toward the Phase 2 misses and the Phase 1 weak points):
  flagd: plain-targeting (bare string/number/bool/array/null/{} targeting), frac-names (numeric / bool / null /
         undefined names, negative / fractional / zero / missing weights, bucketing expression), semver-pre
         (sem_ver with prerelease constants), multi-contains, string-order, mixed (random if-chains).
  flipt: yaml-bool (enabled/default/value spelled yes/no/on/off), yaml-keys (variant keys 1 / 012 / 0x10 / true /
         on), rollout-decimals (decimal rollouts and thresholds near boundaries, octal-looking numbers),
         multi-contains, mixed.
  goff:  yaml-bool (disable spelled yes/no/on/off), yaml-keys (variation keys true / false / 1 / 0x10 / on),
         semver-pre (version comparisons with prerelease), multi-contains, string-order, pct (sums != 100,
         percentage+variation, defaultRule disable), mixed.
"""
import json
import os
import random
import sys


class Raw(str):
    """A YAML scalar written without quotes (so the YAML resolver decides its type)."""


# ------------------------------------------------------------------ tiny YAML emitter (block style)
def _scalar(v):
    if isinstance(v, Raw):
        return str(v)
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(v, ensure_ascii=False)  # a YAML double-quoted scalar


def _emit(v, ind, out):
    pad = "  " * ind
    if isinstance(v, dict):
        if not v:
            out[-1] += " {}"
            return
        for k, x in v.items():
            ks = _scalar(k)
            if isinstance(x, (dict, list)) and x:
                out.append("%s%s:" % (pad, ks))
                _emit(x, ind + 1, out)
            elif isinstance(x, (dict, list)):
                out.append("%s%s: %s" % (pad, ks, "{}" if isinstance(x, dict) else "[]"))
            else:
                out.append("%s%s: %s" % (pad, ks, _scalar(x)))
    elif isinstance(v, list):
        for x in v:
            if isinstance(x, dict) and x:
                first = True
                for k, y in x.items():
                    lead = pad + ("- " if first else "  ")
                    first = False
                    ks = _scalar(k)
                    if isinstance(y, (dict, list)) and y:
                        out.append("%s%s:" % (lead, ks))
                        _emit(y, ind + 2, out)
                    elif isinstance(y, (dict, list)):
                        out.append("%s%s: %s" % (lead, ks, "{}" if isinstance(y, dict) else "[]"))
                    else:
                        out.append("%s%s: %s" % (lead, ks, _scalar(y)))
            elif isinstance(x, (dict, list)):
                out.append("%s- %s" % (pad, "{}" if isinstance(x, dict) else "[]"))
            else:
                out.append("%s- %s" % (pad, _scalar(x)))


def yaml_text(doc):
    out = []
    _emit(doc, 0, out)
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ shared pools
STR_ATTRS = ["email", "country", "tier", "name", "plan"]
NUM_ATTRS = ["age", "score"]
STR_CONSTS = ["a", "ab", "abc", "b", "bc", "m", "x@example.com", "@example.com", "example", "DE", "US", "gold",
              "silver", "", "z"]
CONTAINS = ["a", "b", "ab", "bc", "abc", "example", "@", ".com", "x"]
VERSIONS = ["1.0.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
            "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0-0", "1.0.1", "1.2.3", "1.2.3-rc.1", "2.0.0-0", "2.0.0",
            "v1.2", "1.0", "0.9.9", "1.0.0-alpha.0", "1.0.0-alpha.0.1"]
SEMVER_OPS = ["<", "<=", ">", ">=", "=", "!=", "~", "^"]


# ------------------------------------------------------------------ flagd
def _var(a):
    return {"var": a}


def flagd_atom(r, fam):
    if fam == "semver-pre" or (fam == "mixed" and r.random() < 0.15):
        return {"sem_ver": [_var("version"), r.choice(SEMVER_OPS), r.choice(VERSIONS)]}
    if fam == "multi-contains" or (fam == "mixed" and r.random() < 0.1):
        return {"in": [r.choice(CONTAINS), _var(r.choice(["email", "name"]))]}
    if fam == "string-order" or (fam == "mixed" and r.random() < 0.1):
        return {r.choice(["<", "<=", ">", ">="]): [_var(r.choice(["name", "tier"])), r.choice(["b", "m", "abc", "z"])]}
    k = r.randrange(7)
    a = r.choice(STR_ATTRS)
    if k == 0:
        return {"==": [_var(a), r.choice(STR_CONSTS)]}
    if k == 1:
        return {"!=": [_var(a), r.choice(STR_CONSTS)]}
    if k == 2:
        return {"in": [_var(a), r.sample(["DE", "US", "FR", "gold", "silver"], r.randint(1, 3))]}
    if k == 3:
        return {"starts_with": [_var(a), r.choice(["a", "ab", "x", "s"])]}
    if k == 4:
        return {"ends_with": [_var(a), r.choice(["@example.com", ".com", "c", "b"])]}
    if k == 5:
        n = r.choice([0, 10, 18, 21, 65])
        return {r.choice(["<", "<=", ">", ">=", "=="]): [_var(r.choice(NUM_ATTRS)), n]}
    return {"==": [_var(r.choice(NUM_ATTRS)), r.choice([1, 2, "1", 1.5])]}


def flagd_cond(r, fam, depth=0):
    p = r.random()
    if depth < 2 and p < 0.25:
        return {"and": [flagd_cond(r, fam, depth + 1) for _ in range(r.randint(2, 3))]}
    if depth < 2 and p < 0.4:
        return {"or": [flagd_cond(r, fam, depth + 1) for _ in range(r.randint(2, 3))]}
    if depth < 2 and p < 0.47:
        return {"!": flagd_cond(r, fam, depth + 1)}
    return flagd_atom(r, fam)


def flagd_frac(r, names, fam):
    ents = []
    for _ in range(r.randint(1, 4)):
        c = r.random()
        if fam == "frac-names" and c < 0.25:
            nm = r.choice([3, 4, 1, 0, True, False, None, 2.5])
        elif fam == "frac-names" and c < 0.35:
            nm = r.choice(["ghost", "undefined-x"])
        else:
            nm = r.choice(names)
        if fam == "frac-names":
            w = r.choice([50, 50, 25, 0, -10, 12.5, 33, 100, None, 1])
        else:
            w = r.choice([50, 25, 10, 0, 34, 33, None])
        ents.append([nm] if w is None else [nm, w])
    if r.random() < 0.3:
        b = r.choice([_var("email"), {"cat": [{"var": "$flagd.flagKey"}, _var("email")]}, "fixed-bucket"])
        return {"fractional": [b] + ents}
    return {"fractional": ents}


def flagd_result(r, names, fam, depth):
    c = r.random()
    if depth < 2 and c < 0.12:
        return flagd_if(r, names, fam, depth + 1)
    if c < 0.3:
        return flagd_frac(r, names, fam)
    if c < 0.36:
        return None
    if c < 0.42:
        return r.choice(["ghost", "on", "true"])
    return r.choice(names)


def flagd_if(r, names, fam, depth=0):
    args = []
    for _ in range(r.randint(1, 4)):
        args.append(flagd_cond(r, fam))
        args.append(flagd_result(r, names, fam, depth))
    if r.random() < 0.6:
        args.append(flagd_result(r, names, fam, depth))
    return {"if": args}


def flagd_flag(r, fam):
    pool = ["on", "off", "red", "blue", "green", "3", "4", "true", "false", "default"]
    names = r.sample(pool, r.randint(1, 4))
    vals = {}
    for n in names:
        vals[n] = r.choice([True, False, n, 1, 2.5, {"k": n}]) if r.random() < 0.3 else (n == "on" if n in ("on", "off") else n)
    f = {"state": "DISABLED" if r.random() < 0.06 else "ENABLED", "variants": vals}
    dv = r.random()
    if dv < 0.8:
        f["defaultVariant"] = r.choice(names)
    elif dv < 0.9:
        f["defaultVariant"] = r.choice(["", "ghost"])
    else:
        f["defaultVariant"] = None
    if fam == "plain-targeting":
        f["targeting"] = r.choice(["yes", "ghost", r.choice(names), r.choice(names), 3, True, False, [], None, {}, ""])
    elif fam == "frac-names":
        f["targeting"] = flagd_frac(r, names, fam) if r.random() < 0.6 else flagd_if(r, names, fam)
    else:
        c = r.random()
        if c < 0.08:
            pass
        elif c < 0.15:
            f["targeting"] = flagd_cond(r, fam)  # a boolean expression as the whole targeting
        else:
            f["targeting"] = flagd_if(r, names, fam)
    return f


FLAGD_FAMS = [("plain-targeting", 3), ("frac-names", 4), ("semver-pre", 4), ("multi-contains", 3), ("string-order", 2), ("mixed", 4)]


# ------------------------------------------------------------------ Flipt
def ybool(r, v, fam):
    if fam == "yaml-bool" and r.random() < 0.7:
        return Raw(r.choice(["yes", "Yes", "on", "ON", "y"] if v else ["no", "No", "off", "OFF", "n"]))
    return v


def flipt_constraint(r, fam):
    k = r.random()
    if fam == "multi-contains" and k < 0.6:
        return {"type": "STRING_COMPARISON_TYPE", "property": r.choice(["email", "name"]),
                "operator": r.choice(["contains", "contains", "notcontains"]), "value": r.choice(CONTAINS)}
    if k < 0.45:
        op = r.choice(["eq", "neq", "prefix", "suffix", "contains", "notcontains", "isoneof", "isnotoneof", "empty", "notempty"])
        if op in ("isoneof", "isnotoneof"):
            val = json.dumps(r.sample(["DE", "US", "FR", "gold"], r.randint(1, 3)))
        elif op in ("empty", "notempty"):
            val = None
        else:
            val = r.choice(["DE", "US", "a", "ab", "gold", "@example.com"])
        c = {"type": "STRING_COMPARISON_TYPE", "property": r.choice(STR_ATTRS), "operator": op}
        if val is not None:
            c["value"] = val
        return c
    if k < 0.75:
        op = r.choice(["eq", "neq", "lt", "lte", "gt", "gte", "present", "notpresent"])
        c = {"type": "NUMBER_COMPARISON_TYPE", "property": r.choice(NUM_ATTRS), "operator": op}
        if op not in ("present", "notpresent"):
            c["value"] = r.choice(["10", "18", "21", "0", "1.5"])
        return c
    if k < 0.9:
        return {"type": "BOOLEAN_COMPARISON_TYPE", "property": r.choice(["beta", "admin"]),
                "operator": r.choice(["true", "false", "present", "notpresent"])}
    return {"type": "ENTITY_ID_COMPARISON_TYPE", "property": "entity", "operator": r.choice(["eq", "prefix"]),
            "value": r.choice(["user-0001", "user-00"])}


def flipt_rollouts(r, fam):
    if fam == "rollout-decimals":
        return r.choice([[50, 50], [33.33, 33.33, 33.34], [33.33, 33.33, 33.33], [49.99, 50], [0.5, 99.5], [12.5, 87.5],
                         [Raw("012"), 90], [Raw("1_0"), 90], [10, 90], [Raw("0x0A"), 90], [100], [99.999, 0.001]])
    return r.choice([[100], [50, 50], [40, 40], [60, 50], [25, 25, 50], [30, 30], [0, 100]])


def flipt_doc(r, fam):
    nseg = r.randint(1, 3)
    segs = []
    for i in range(nseg):
        segs.append({"key": "seg-%d" % i, "match_type": r.choice(["ALL_MATCH_TYPE", "ANY_MATCH_TYPE"]),
                     "constraints": [flipt_constraint(r, fam) for _ in range(r.randint(1, 3))]})
    flags = []
    for fi in range(r.randint(1, 3)):
        boolean = r.random() < 0.35
        f = {"key": "flag-%d" % fi, "name": "Flag %d" % fi}
        if boolean:
            f["type"] = "BOOLEAN_FLAG_TYPE"
            f["enabled"] = ybool(r, r.random() < 0.5, fam)
            ros = []
            for _ in range(r.randint(1, 3)):
                if r.random() < 0.5:
                    pct = r.choice([50, 33.3, 0, 100, 49.5, 99.9, 10]) if fam == "rollout-decimals" else r.choice([50, 25, 100, 0])
                    ros.append({"threshold": {"percentage": pct, "value": ybool(r, r.random() < 0.5, fam)}})
                else:
                    ros.append({"segment": {"key": "seg-%d" % r.randrange(nseg), "value": ybool(r, r.random() < 0.5, fam)}})
            f["rollouts"] = ros
            if r.random() < 0.15:
                f["rules"] = [{"segment": "seg-0", "distributions": [{"variant": "x", "rollout": 10}]}]
        else:
            if r.random() < 0.6:
                f["type"] = "VARIANT_FLAG_TYPE"
            f["enabled"] = ybool(r, r.random() < 0.85, fam)
            if fam == "yaml-keys":
                keys = r.sample([Raw("1"), Raw("012"), Raw("0x10"), Raw("true"), Raw("on"), Raw("1e3"), "blue", "red"], r.randint(2, 4))
            else:
                keys = r.sample(["red", "blue", "green", "on", "off"], r.randint(1, 3))
            vs = []
            dflt = r.randrange(len(keys)) if r.random() < 0.6 else None
            for i, k in enumerate(keys):
                v = {"key": k}
                if dflt == i:
                    v["default"] = ybool(r, True, fam)
                vs.append(v)
            f["variants"] = vs
            rules = []
            for _ in range(r.randint(1, 3)):
                ro = flipt_rollouts(r, fam)
                ks = [keys[r.randrange(len(keys))] for _ in ro]
                if fam == "yaml-keys" and r.random() < 0.5:
                    ks = [Raw(str(k)) if not isinstance(k, Raw) else str(k) for k in ks]  # flip quoting
                rule = {"segment": "seg-%d" % r.randrange(nseg) if r.random() < 0.7 else
                        {"keys": ["seg-%d" % r.randrange(nseg) for _ in range(2)],
                         "operator": r.choice(["AND_SEGMENT_OPERATOR", "OR_SEGMENT_OPERATOR"])}}
                if r.random() < 0.85:
                    rule["distributions"] = [{"variant": k, "rollout": w} for k, w in zip(ks, ro)]
                rules.append(rule)
            f["rules"] = rules
            if r.random() < 0.1:
                f["rollouts"] = [{"threshold": {"percentage": 50, "value": True}}]
        flags.append(f)
    return {"namespace": "default", "flags": flags, "segments": segs}


FLIPT_FAMS = [("yaml-bool", 4), ("yaml-keys", 4), ("rollout-decimals", 4), ("multi-contains", 2), ("mixed", 4)]


# ------------------------------------------------------------------ GOFF
def goff_atom(r, fam):
    if fam == "semver-pre" or (fam == "mixed" and r.random() < 0.15):
        v = r.choice([x for x in VERSIONS if x[0].isdigit() and x.count(".") >= 2])
        return "version %s %s" % (r.choice(["gt", "lt", "ge", "le", "eq", "ne"]), v)
    if fam == "multi-contains" or (fam == "mixed" and r.random() < 0.1):
        return "%s co \"%s\"" % (r.choice(["email", "name"]), r.choice(CONTAINS))
    if fam == "string-order" or (fam == "mixed" and r.random() < 0.1):
        return "%s %s \"%s\"" % (r.choice(["name", "tier"]), r.choice(["lt", "gt", "le", "ge"]), r.choice(["b", "m", "abc", "z"]))
    k = r.randrange(6)
    a = r.choice(STR_ATTRS)
    if k == 0:
        return "%s eq \"%s\"" % (a, r.choice(["DE", "US", "gold", "a"]))
    if k == 1:
        return "%s ne \"%s\"" % (a, r.choice(["DE", "US", "gold"]))
    if k == 2:
        return "%s sw \"%s\"" % (a, r.choice(["a", "ab", "x"]))
    if k == 3:
        return "%s ew \"%s\"" % (a, r.choice(["@example.com", ".com", "b"]))
    if k == 4:
        return "%s %s %d" % (r.choice(NUM_ATTRS), r.choice(["gt", "lt", "eq", "ge"]), r.choice([0, 10, 18, 65]))
    return "%s in [\"DE\", \"US\"]" % a


def goff_query(r, fam):
    parts = [goff_atom(r, fam) for _ in range(r.randint(1, 3))]
    q = parts[0]
    for p in parts[1:]:
        q += " %s %s" % (r.choice(["and", "or"]), p)
    if r.random() < 0.1:
        q = "not (%s)" % q
    return q


def goff_pct(r, names, fam):
    ks = r.sample(names, min(len(names), r.randint(1, 3)))
    if fam == "pct" and r.random() < 0.6:
        ws = r.choice([[60, 50], [30, 30], [33.3, 33.3, 33.3], [99.9], [0, 100], [10, 10]])
    else:
        ws = r.choice([[100], [50, 50], [30, 70], [25, 25, 50], [20, 30, 50]])
    ws = (ws + [0, 0, 0])[:len(ks)]
    if sum(ws) == 0:
        ws[0] = 100
    return {k: w for k, w in zip(ks, ws)}


def goff_rule(r, names, fam, default=False):
    rule = {}
    if not default:
        rule["name"] = "rule-%d" % r.randrange(1000)
        rule["query"] = goff_query(r, fam)
    if r.random() < 0.4:
        rule["percentage"] = goff_pct(r, names, fam)
        if fam == "pct" and r.random() < 0.3:
            rule["variation"] = r.choice(names)
    else:
        rule["variation"] = r.choice(names) if r.random() < 0.92 else "ghost"
    if fam == "yaml-bool" and r.random() < 0.5:
        rule["disable"] = ybool(r, r.random() < 0.5, fam)
    elif not default and r.random() < 0.08:
        rule["disable"] = True
    elif default and fam == "pct" and r.random() < 0.2:
        rule["disable"] = True
    return rule


def goff_doc(r, fam):
    doc = {}
    for fi in range(r.randint(1, 3)):
        if fam == "yaml-keys":
            names = r.sample([Raw("true"), Raw("false"), Raw("1"), Raw("2"), Raw("0x10"), Raw("on"), Raw("1e3"), "enabled"], r.randint(2, 4))
        else:
            names = r.sample(["enabled", "disabled", "red", "blue", "on", "off"], r.randint(2, 3))
        f = {"variations": {k: r.choice([True, False, "v", 1]) for k in names}}
        refs = list(names)
        if fam == "yaml-keys" and r.random() < 0.5:
            refs = [str(k) if isinstance(k, Raw) else Raw(k) for k in names]  # reference with the other quoting
        if r.random() < 0.85:
            f["targeting"] = [goff_rule(r, refs, fam) for _ in range(r.randint(1, 3))]
        f["defaultRule"] = goff_rule(r, refs, fam, default=True)
        if fam == "yaml-bool" and r.random() < 0.5:
            f["disable"] = ybool(r, r.random() < 0.3, fam)
        doc["flag-%d" % fi] = f
    return doc


GOFF_FAMS = [("yaml-bool", 3), ("yaml-keys", 4), ("semver-pre", 3), ("multi-contains", 2), ("string-order", 2), ("pct", 3), ("mixed", 4)]


def pick(r, fams):
    tot = sum(w for _, w in fams)
    x = r.uniform(0, tot)
    for f, w in fams:
        x -= w
        if x <= 0:
            return f
    return fams[-1][0]


def main(argv):
    out = argv[0]
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 20261125
    per = int(argv[argv.index("--per-format") + 1]) if "--per-format" in argv else 600
    os.makedirs(out, exist_ok=True)
    index = {}
    for fmt in ("flagd", "flipt", "goff"):
        r = random.Random("%d|%s" % (seed, fmt))
        for i in range(per):
            if fmt == "flagd":
                fam = pick(r, FLAGD_FAMS)
                doc = {"$schema": "https://flagd.dev/schema/v0/flags.json",
                       "flags": {"flag-%d" % j: flagd_flag(r, fam) for j in range(r.randint(1, 3))}}
                text, ext = json.dumps(doc, indent=1, ensure_ascii=False) + "\n", "json"
            elif fmt == "flipt":
                fam = pick(r, FLIPT_FAMS)
                text, ext = yaml_text(flipt_doc(r, fam)), "yaml"
            else:
                fam = pick(r, GOFF_FAMS)
                text, ext = yaml_text(goff_doc(r, fam)), "yaml"
            name = "%s-%04d.%s" % (fmt, i, ext)
            with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
                fh.write(text)
            index[name] = {"format": fmt, "family": fam}
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"seed": seed, "per_format": per, "files": index}, fh, indent=1, sort_keys=True)
    print("wrote", len(index), "files to", out)


if __name__ == "__main__":
    main(sys.argv[1:])
