"""Build the dev bench (DECISIONS.md P1-C-5). Deterministic; no network.

Routes (recorded per case as `route`):
  phase0-oracle      F4 cases labelled by the independent Phase 0 smoke code (bench/oracle.py)
  phase0-f3-scan     F3 candidates from Phase 0 smoke/results/f3_static_scan.json (different code), manually confirmed
  phase0-smoke       the three Phase 0 named examples (52.1% flagd file, Flipt 110% file, mmd boolean rules)
  declared           F2 facts readable directly from the declaration (weights/rollouts/percentages)
  detector+manual    candidates surfaced by the Phase 1 detector on the census, each confirmed by reading the flag
                     (circular route: reported separately in the results)
  manual-negative    negatives chosen by reading the flag
  mutation           constructed: a real file with one injected defect, label known by construction
Outputs: bench/files/{real,constructed}/..., bench/cases.json, bench/review/candidates.md
"""
import copy
import csv
import hashlib
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bench"))
import oracle  # noqa: E402
# Phase 3: the frozen Phase 1 loader (git 1b8f1b6:flagbound/yaml12.py), so rebuilding reproduces the frozen bench bytes
import yaml12_phase1 as yaml12  # noqa: E402

B = os.path.join(ROOT, "bench")
INV = [r for r in csv.DictReader(open(os.path.join(ROOT, "smoke/census/inventory.csv"), encoding="utf-8"))
       if r["counted"] == "True"]
BY_SHA = {r["sha256"]: r for r in INV}


def ext(r):
    return os.path.splitext(r["path"])[1].lower()


def census_path(r):
    return os.path.join(ROOT, "smoke/census/files", r["sha256"] + ext(r))


def text(r):
    return open(census_path(r), encoding="utf-8").read()


def rank(r):
    """non-sample (strict) first, then pre-registered non-sample, then samples; then dictionary order."""
    return (0 if r["provenance_strict"] == "non-sample" else 1 if r["provenance_prereg"] == "non-sample" else 2,
            r["repo"].lower(), r["path"])


def src_of(r):
    return {"repo": r["repo"], "path": r["path"], "ref": r["ref"], "sha256": r["sha256"],
            "provenance_prereg": r["provenance_prereg"], "provenance_strict": r["provenance_strict"], "url": r["url"]}


CASES = []
REAL_FILES = {}


def add_real(r, cls, label, flag, route, rationale, expected_pairs=None):
    rel = "files/real/%s%s" % (r["sha256"], ext(r))
    REAL_FILES[r["sha256"]] = r
    c = {"id": "%s-%s-%03d" % (cls, label[:3], sum(1 for x in CASES if x["class"] == cls and x["label"] == label) + 1),
         "class": cls, "label": label, "origin": "real", "route": route, "file": rel, "flag": flag,
         "source": src_of(r), "rationale": rationale}
    if expected_pairs is not None:
        c["expected_pairs"] = expected_pairs
    CASES.append(c)
    return c


def add_constructed(base_r, cls, label, flag, mutation, content, extn, rationale, expected_pairs=None):
    cid = "%s-%s-%03d" % (cls, label[:3], sum(1 for x in CASES if x["class"] == cls and x["label"] == label) + 1)
    rel = "files/constructed/%s%s" % (cid, extn)
    os.makedirs(os.path.join(B, "files", "constructed"), exist_ok=True)
    with open(os.path.join(B, rel), "w", encoding="utf-8") as fh:
        fh.write(content)
    c = {"id": cid, "class": cls, "label": label, "origin": "constructed", "route": "mutation", "file": rel,
         "flag": flag, "mutation": mutation, "derived_from": src_of(base_r) if base_r else None, "rationale": rationale}
    if expected_pairs is not None:
        c["expected_pairs"] = expected_pairs
    CASES.append(c)
    return c


def flagd_files():
    return sorted((r for r in INV if r["format"] == "flagd"), key=rank)


def flipt_files():
    return sorted((r for r in INV if r["format"] == "flipt"), key=rank)


def goff_files():
    return sorted((r for r in INV if r["format"] == "goff"), key=rank)


def jdump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def ydump(docs):
    import yaml
    return yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True)


# --------------------------------------------------------------------------------------------------------
def seen_key(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_f4():
    seen = set()
    pos = neg = 0
    for r in flagd_files():
        d = json.loads(text(r))
        for fk in sorted(d["flags"]):
            f = d["flags"][fk]
            if not isinstance(f, dict) or "fractional" not in json.dumps(f.get("targeting")):
                continue
            k = seen_key(f.get("targeting"))
            if k in seen:
                continue
            pairs = oracle.flagd_pairs(census_path(r), fk)
            if pairs is None:
                continue
            seen.add(k)
            if pairs and pos < 12 and f.get("state") == "ENABLED":
                add_real(r, "F4", "positive", fk, "phase0-oracle",
                         "fractional; Phase 0 smoke oracle finds flips for %s over the D-6 set" % pairs, pairs)
                pos += 1
            elif not pairs and neg < 4 and f.get("state") == "ENABLED":
                add_real(r, "F4", "negative", fk, "phase0-oracle",
                         "fractional; Phase 0 smoke oracle finds no flip between G1/G2/G3 over the D-6 set", [])
                neg += 1
    # Flipt real: rules with distributions that can be reached
    fpos = fneg = 0
    for r in flipt_files():
        for doc in yaml12.load_all(text(r)):
            if not isinstance(doc, dict):
                continue
            for f in doc.get("flags") or []:
                if not isinstance(f, dict) or f.get("type") == "BOOLEAN_FLAG_TYPE" or not f.get("enabled") or not f.get("rules"):
                    continue
                dl = []
                for ru in f["rules"]:
                    dd = [(x.get("variant"), float(x.get("rollout", 0))) for x in ru.get("distributions") or [] if isinstance(x, dict)]
                    if dd and all(isinstance(v, str) for v, _ in dd):
                        dl.append([x for x in dd if x[1] > 0])
                dl = [x for x in dl if x]
                if not dl:
                    continue
                k = seen_key([f.get("key"), dl])
                if k in seen:
                    continue
                seen.add(k)
                pairs = oracle.flipt_pairs(f["key"], dl)
                if pairs and fpos < 4:
                    add_real(r, "F4", "positive", f["key"], "phase0-oracle",
                             "Flipt rule distributions %s; Phase 0 engines oracle finds flips for %s" % (dl, pairs), pairs)
                    fpos += 1
                elif not pairs and fneg < 4:
                    add_real(r, "F4", "negative", f["key"], "phase0-oracle",
                             "Flipt rule distributions %s; oracle: identical assignment on all three engines" % dl, [])
                    fneg += 1
    gpos = gneg = 0
    for r in goff_files():
        for doc in yaml12.load_all(text(r)):
            if not isinstance(doc, dict):
                continue
            for name in sorted(doc, key=str):
                f = doc[name]
                if not isinstance(f, dict) or not isinstance(f.get("variations"), dict) or f.get("disable") or \
                        f.get("scheduledRollout") or f.get("experimentation"):
                    continue
                rules = [x for x in (f.get("targeting") or []) if isinstance(x, dict)] + [f.get("defaultRule") or {}]
                pl = [{str(a): float(b) for a, b in x["percentage"].items()} for x in rules
                      if isinstance(x.get("percentage"), dict) and x["percentage"] and not x.get("progressiveRollout")
                      and all(isinstance(b, (int, float)) for b in x["percentage"].values())]
                if not pl:
                    continue
                k = seen_key([str(name), pl])
                if k in seen:
                    continue
                seen.add(k)
                pairs = oracle.goff_pairs(str(name), pl)
                if pairs and gpos < 4:
                    add_real(r, "F4", "positive", str(name), "phase0-oracle",
                             "GOFF percentages %s; sum != 100 so pre-v1.32 errors while v1.32+ normalises" % pl, pairs)
                    gpos += 1
                elif not pairs and gneg < 3:
                    add_real(r, "F4", "negative", str(name), "phase0-oracle",
                             "GOFF percentages %s sum to 100: identical buckets pre/post v1.32" % pl, [])
                    gneg += 1


def build_f2():
    n_pos = {"flagd": 0, "flipt": 0, "goff": 0}
    n_neg = {"flagd": 0, "flipt": 0, "goff": 0}
    seen = set()
    for r in sorted(INV, key=rank):
        t = text(r)
        if r["format"] == "flagd":
            d = json.loads(t)
            for fk in sorted(d["flags"]):
                f = d["flags"][fk]
                tg = json.dumps(f.get("targeting")) if isinstance(f, dict) else ""
                if '"fractional"' not in tg:
                    continue
                ws = _flagd_weights(f.get("targeting"))
                if ws is None:
                    continue
                k = seen_key(ws)
                if k in seen:
                    continue
                seen.add(k)
                bad = [w for w in ws if w < 0 or w != int(w)] or (ws and sum(max(0, w) for w in ws) == 0)
                if bad and n_pos["flagd"] < 5:
                    add_real(r, "F2", "positive", fk, "declared", "fractional weights %s: negative / non-integer / zero total" % ws)
                    n_pos["flagd"] += 1
                elif not bad and n_neg["flagd"] < 3:
                    add_real(r, "F2", "negative", fk, "declared", "fractional weights %s: non-negative integers, positive total (relative weights; no implicit remainder)" % ws)
                    n_neg["flagd"] += 1
        elif r["format"] == "flipt":
            for doc in yaml12.load_all(t):
                if not isinstance(doc, dict):
                    continue
                for f in doc.get("flags") or []:
                    if not isinstance(f, dict):
                        continue
                    sums = [sum(float(x.get("rollout", 0)) for x in ru.get("distributions") or [] if isinstance(x, dict))
                            for ru in f.get("rules") or [] if ru.get("distributions")]
                    if not sums:
                        continue
                    k = seen_key([f.get("key"), sums, r["sha256"][:6]])
                    if k in seen:
                        continue
                    seen.add(k)
                    if any(abs(s - 100) > 1e-9 for s in sums) and n_pos["flipt"] < 6:
                        add_real(r, "F2", "positive", f["key"], "declared", "rule rollout sums %s (Phase 0 F2 scan route)" % sums)
                        n_pos["flipt"] += 1
                    elif all(abs(s - 100) <= 1e-9 for s in sums) and n_neg["flipt"] < 3:
                        add_real(r, "F2", "negative", f["key"], "declared", "every rule's rollouts sum to 100: %s" % sums)
                        n_neg["flipt"] += 1
        else:
            for doc in yaml12.load_all(t):
                if not isinstance(doc, dict):
                    continue
                for name in sorted(doc, key=str):
                    f = doc[name]
                    if not isinstance(f, dict) or not isinstance(f.get("variations"), dict):
                        continue
                    rules = [x for x in (f.get("targeting") or []) if isinstance(x, dict)] + [f.get("defaultRule") or {}]
                    sums = [sum(x["percentage"].values()) for x in rules if isinstance(x.get("percentage"), dict) and x["percentage"]
                            and all(isinstance(b, (int, float)) for b in x["percentage"].values())]
                    if not sums:
                        continue
                    k = seen_key([str(name), sums])
                    if k in seen:
                        continue
                    seen.add(k)
                    if any(abs(s - 100) > 1e-9 for s in sums) and n_pos["goff"] < 5:
                        add_real(r, "F2", "positive", str(name), "declared", "percentage sums %s" % sums)
                        n_pos["goff"] += 1
                    elif all(abs(s - 100) <= 1e-9 for s in sums) and n_neg["goff"] < 3:
                        add_real(r, "F2", "negative", str(name), "declared", "percentages sum to 100: %s" % sums)
                        n_neg["goff"] += 1


def _flagd_weights(t):
    out = []

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k == "fractional" and isinstance(v, list):
                    ds = v[1:] if v and not isinstance(v[0], list) else v
                    for d in ds:
                        if not isinstance(d, list) or not d:
                            raise ValueError
                        w = d[1] if len(d) > 1 else 1
                        if not isinstance(w, (int, float)) or isinstance(w, bool):
                            raise ValueError
                        out.append(w)
                else:
                    walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    try:
        walk(t)
    except ValueError:
        return None
    return out


def build_f3_from_phase0():
    s = json.load(open(os.path.join(ROOT, "smoke/results/f3_static_scan.json"), encoding="utf-8"))
    taken = 0
    seen = set()
    for fmt, prov, repo, path, flag, ghosts in sorted(s["examples"], key=lambda e: (e[1] != "non-sample", e[2].lower(), e[3], str(e[4]))):
        rows = [r for r in INV if r["repo"] == repo and r["path"] == path]
        if not rows:
            continue
        r = rows[0]
        if (repo, path, flag) in seen:
            continue
        seen.add((repo, path, flag))
        CAND_F3.append((r, flag, ghosts))
    return taken


CAND_F3 = []


def build_constructed():
    rnd = random.Random(20261125)
    # ---- F1 mutations ----
    k = 0
    for r in flagd_files():
        if k >= 4:
            break
        d = json.loads(text(r))
        for fk in sorted(d["flags"]):
            f = d["flags"][fk]
            t = f.get("targeting") if isinstance(f, dict) else None
            if isinstance(t, dict) and list(t) == ["if"] and isinstance(t["if"], list) and len(t["if"]) == 3 and \
                    isinstance(t["if"][1], str) and isinstance(t["if"][2], str) and "$ref" not in json.dumps(t) and \
                    "fractional" not in json.dumps(t) and "timestamp" not in json.dumps(t):
                d2 = copy.deepcopy(d)
                c, a, b = t["if"]
                d2["flags"][fk]["targeting"] = {"if": [c, a, c, b, b]}
                add_constructed(r, "F1", "positive", fk, "duplicate the first condition as a second branch: if[C, A, C, B, B]",
                                jdump(d2), ".json", "the second branch repeats condition C, which the first branch already captures")
                k += 1
                break
    k = 0
    for r in flagd_files():
        if k >= 3:
            break
        d = json.loads(text(r))
        for fk in sorted(d["flags"]):
            f = d["flags"][fk]
            if isinstance(f, dict) and f.get("state") == "ENABLED" and isinstance(f.get("variants"), dict) and len(f["variants"]) >= 2 \
                    and not f.get("targeting"):
                vs = sorted(f["variants"])
                d2 = copy.deepcopy(d)
                d2["flags"][fk]["targeting"] = {"if": [{"and": [{"==": [{"var": "region"}, "eu"]}, {"==": [{"var": "region"}, "us"]}]},
                                                       vs[0], {"==": [{"var": "region"}, "eu"]}, vs[1], None]}
                add_constructed(r, "F1", "positive", fk, "add if[region==eu AND region==us -> v0, region==eu -> v1, null]",
                                jdump(d2), ".json", "first branch condition is contradictory (eq 'eu' and eq 'us')")
                k += 1
                break
    k = 0
    for r in flipt_files():
        if k >= 4:
            break
        docs = yaml12.load_all(text(r))
        done = False
        for di, doc in enumerate(docs):
            if not isinstance(doc, dict) or done:
                continue
            for fi, f in enumerate(doc.get("flags") or []):
                if isinstance(f, dict) and f.get("type") != "BOOLEAN_FLAG_TYPE" and f.get("enabled") and f.get("rules") and f.get("variants"):
                    d2 = copy.deepcopy(docs)
                    segs = d2[di].setdefault("segments", []) or []
                    d2[di]["segments"] = segs
                    segs.append({"key": "fb-catch-all", "name": "fb catch all", "match_type": "ALL_MATCH_TYPE"})
                    v0 = f["variants"][0]["key"]
                    d2[di]["flags"][fi]["rules"] = [{"segment": "fb-catch-all", "distributions": [{"variant": v0, "rollout": 100}]}] + f["rules"]
                    add_constructed(r, "F1", "positive", f["key"], "prepend a rule on a constraint-less ALL segment",
                                    ydump(d2), ext(r), "every original rule is now preceded by a rule that matches every context")
                    k += 1
                    done = True
                    break
    k = 0
    for r in goff_files():
        if k >= 4:
            break
        docs = yaml12.load_all(text(r))
        done = False
        for di, doc in enumerate(docs):
            if not isinstance(doc, dict) or done:
                continue
            for name in sorted(doc, key=str):
                f = doc[name]
                tg = f.get("targeting") if isinstance(f, dict) else None
                if isinstance(tg, list) and tg and isinstance(tg[0], dict) and isinstance(tg[0].get("query"), str) and \
                        tg[0]["query"].strip() and not tg[0]["query"].strip().startswith("{") and not f.get("scheduledRollout") \
                        and not f.get("disable") and not tg[0].get("disable") and not f.get("experimentation"):
                    d2 = copy.deepcopy(docs)
                    dup = copy.deepcopy(tg[0])
                    if dup.get("name"):
                        dup["name"] = str(dup["name"]) + "-fb-dup"
                    d2[di][name]["targeting"] = [tg[0], dup] + tg[1:]
                    add_constructed(r, "F1", "positive", str(name), "duplicate targeting[0] (same query) right after it",
                                    ydump(d2), ext(r), "the copy has the same query as the rule before it")
                    k += 1
                    done = True
                    break
    # ---- F2 mutations ----
    k = 0
    for r in flipt_files():
        if k >= 3:
            break
        docs = yaml12.load_all(text(r))
        done = False
        for di, doc in enumerate(docs):
            if not isinstance(doc, dict) or done:
                continue
            for fi, f in enumerate(doc.get("flags") or []):
                rules = f.get("rules") if isinstance(f, dict) else None
                if rules and rules[0].get("distributions") and len(rules[0]["distributions"]) >= 2:
                    d2 = copy.deepcopy(docs)
                    ds = d2[di]["flags"][fi]["rules"][0]["distributions"]
                    ds[0]["rollout"] = float(ds[0].get("rollout", 0)) - 10 if float(ds[0].get("rollout", 0)) >= 10 else float(ds[0].get("rollout", 0)) + 10
                    add_constructed(r, "F2", "positive", f["key"], "rules[0].distributions[0].rollout -/+ 10",
                                    ydump(d2), ext(r), "rule 1 rollouts no longer sum to 100")
                    k += 1
                    done = True
                    break
    k = 0
    for r in goff_files():
        if k >= 3:
            break
        docs = yaml12.load_all(text(r))
        done = False
        for di, doc in enumerate(docs):
            if not isinstance(doc, dict) or done:
                continue
            for name in sorted(doc, key=str):
                f = doc[name]
                dr = f.get("defaultRule") if isinstance(f, dict) else None
                if isinstance(dr, dict) and isinstance(dr.get("percentage"), dict) and len(dr["percentage"]) >= 2:
                    d2 = copy.deepcopy(docs)
                    p = d2[di][name]["defaultRule"]["percentage"]
                    k0 = sorted(p, key=str)[0]
                    p[k0] = float(p[k0]) + 15
                    add_constructed(r, "F2", "positive", str(name), "defaultRule.percentage[%s] += 15" % k0,
                                    ydump(d2), ext(r), "percentages no longer sum to 100")
                    k += 1
                    done = True
                    break
    k = 0
    for r in flagd_files():
        if k >= 3:
            break
        d = json.loads(text(r))
        for fk in sorted(d["flags"]):
            f = d["flags"][fk]
            t = f.get("targeting") if isinstance(f, dict) else None
            if isinstance(t, dict) and list(t) == ["fractional"] and isinstance(t["fractional"], list) and \
                    all(isinstance(x, list) and len(x) == 2 and isinstance(x[1], int) for x in t["fractional"]) and len(t["fractional"]) >= 2:
                d2 = copy.deepcopy(d)
                if k % 2 == 0:
                    d2["flags"][fk]["targeting"]["fractional"][0][1] = -abs(t["fractional"][0][1]) - 1
                    mut, why = "fractional[0] weight made negative", "negative weight (clamped to 0 by G2/G3)"
                else:
                    for x in d2["flags"][fk]["targeting"]["fractional"]:
                        x[1] = 0
                    mut, why = "all fractional weights set to 0", "zero total weight: fractional returns null for everyone"
                add_constructed(r, "F2", "positive", fk, mut, jdump(d2), ".json", why)
                k += 1
                break
    # ---- F3 mutations: add a never-produced variant to a flag that has rules ----
    for fmt, files in (("flagd", flagd_files()), ("flipt", flipt_files()), ("goff", goff_files())):
        k = 0
        for r in files:
            if k >= 3:
                break
            if fmt == "flagd":
                d = json.loads(text(r))
                for fk in sorted(d["flags"]):
                    f = d["flags"][fk]
                    if isinstance(f, dict) and f.get("targeting") and f.get("state") == "ENABLED" and isinstance(f.get("variants"), dict):
                        vals = list(f["variants"].values())
                        d2 = copy.deepcopy(d)
                        d2["flags"][fk]["variants"]["fb-unused-variant"] = vals[0] if vals else "x"
                        add_constructed(r, "F3", "positive", fk, "add variant 'fb-unused-variant' (same type) referenced nowhere",
                                        jdump(d2), ".json", "no rule, allocation or default names the added variant")
                        k += 1
                        break
            elif fmt == "flipt":
                docs = yaml12.load_all(text(r))
                done = False
                for di, doc in enumerate(docs):
                    if not isinstance(doc, dict) or done:
                        continue
                    for fi, f in enumerate(doc.get("flags") or []):
                        if isinstance(f, dict) and f.get("type") != "BOOLEAN_FLAG_TYPE" and f.get("enabled") and f.get("rules") and f.get("variants"):
                            d2 = copy.deepcopy(docs)
                            d2[di]["flags"][fi]["variants"].append({"key": "fb-unused-variant", "name": "fb unused"})
                            add_constructed(r, "F3", "positive", f["key"], "append variant 'fb-unused-variant' referenced nowhere",
                                            ydump(d2), ext(r), "no rule distribution or default names the added variant")
                            k += 1
                            done = True
                            break
            else:
                docs = yaml12.load_all(text(r))
                done = False
                for di, doc in enumerate(docs):
                    if not isinstance(doc, dict) or done:
                        continue
                    for name in sorted(doc, key=str):
                        f = doc[name]
                        if isinstance(f, dict) and (f.get("targeting") or isinstance((f.get("defaultRule") or {}).get("percentage"), dict)) \
                                and isinstance(f.get("variations"), dict) and not f.get("disable") and not f.get("scheduledRollout") \
                                and not f.get("experimentation"):
                            vals = list(f["variations"].values())
                            d2 = copy.deepcopy(docs)
                            d2[di][name]["variations"]["fb-unused-variant"] = vals[0] if vals else "x"
                            add_constructed(r, "F3", "positive", str(name), "add variation 'fb-unused-variant' referenced nowhere",
                                            ydump(d2), ext(r), "no rule or default names the added variation")
                            k += 1
                            done = True
                            break
    # ---- F7 mutations ----
    k = {"a": 0, "e": 0}
    for r in flipt_files():
        docs = yaml12.load_all(text(r))
        done = False
        for di, doc in enumerate(docs):
            if not isinstance(doc, dict) or done:
                continue
            for fi, f in enumerate(doc.get("flags") or []):
                if not isinstance(f, dict) or done:
                    continue
                if f.get("type") == "BOOLEAN_FLAG_TYPE" and not f.get("rules") and k["a"] < 3:
                    d2 = copy.deepcopy(docs)
                    segs = d2[di].get("segments") or []
                    d2[di]["segments"] = segs
                    if not any(s.get("key") == "fb-all" for s in segs):
                        segs.append({"key": "fb-all", "name": "fb all", "match_type": "ALL_MATCH_TYPE"})
                    d2[di]["flags"][fi]["rules"] = [{"segment": "fb-all", "distributions": []}]
                    add_constructed(r, "F7", "positive", f["key"], "add a rules entry to a BOOLEAN_FLAG_TYPE flag", ydump(d2), ext(r),
                                    "F7-a by construction")
                    k["a"] += 1
                    done = True
                elif f.get("type") != "BOOLEAN_FLAG_TYPE" and f.get("variants") and not f.get("rollouts") and k["e"] < 3:
                    d2 = copy.deepcopy(docs)
                    d2[di]["flags"][fi]["rollouts"] = [{"threshold": {"percentage": 50, "value": True}}]
                    add_constructed(r, "F7", "positive", f["key"], "add a threshold rollout to a variant flag", ydump(d2), ext(r),
                                    "F7-e by construction")
                    k["e"] += 1
                    done = True
        if k["a"] >= 3 and k["e"] >= 3:
            break
    k = {"b": 0, "c": 0, "d": 0}
    for r in goff_files():
        docs = yaml12.load_all(text(r))
        done = False
        for di, doc in enumerate(docs):
            if not isinstance(doc, dict) or done:
                continue
            for name in sorted(doc, key=str):
                f = doc[name]
                dr = f.get("defaultRule") if isinstance(f, dict) else None
                if not isinstance(dr, dict) or not isinstance(f.get("variations"), dict) or done:
                    continue
                vs = sorted(map(str, f["variations"]))
                if isinstance(dr.get("percentage"), dict) and dr.get("variation") is None and k["b"] < 3:
                    d2 = copy.deepcopy(docs)
                    d2[di][name]["defaultRule"]["variation"] = vs[0]
                    add_constructed(r, "F7", "positive", str(name), "add variation next to percentage in defaultRule", ydump(d2), ext(r),
                                    "F7-b by construction")
                    k["b"] += 1
                    done = True
                elif dr.get("variation") is not None and not dr.get("percentage") and not dr.get("disable") and k["d"] < 3:
                    d2 = copy.deepcopy(docs)
                    d2[di][name]["defaultRule"]["disable"] = True
                    add_constructed(r, "F7", "positive", str(name), "set defaultRule.disable: true", ydump(d2), ext(r),
                                    "F7-d by construction")
                    k["d"] += 1
                    done = True
                elif dr.get("variation") is not None and not dr.get("progressiveRollout") and k["c"] < 2 and len(vs) >= 2:
                    d2 = copy.deepcopy(docs)
                    d2[di][name]["defaultRule"]["progressiveRollout"] = {
                        "initial": {"variation": vs[0], "percentage": 0, "date": "2020-01-01T00:00:00Z"},
                        "end": {"variation": vs[1], "percentage": 100, "date": "2020-01-02T00:00:00Z"}}
                    add_constructed(r, "F7", "positive", str(name), "add progressiveRollout next to variation in defaultRule",
                                    ydump(d2), ext(r), "F7-c by construction")
                    k["c"] += 1
                    done = True
        if all(v >= (2 if kk == "c" else 3) for kk, v in k.items()):
            break
    # ---- F4 mutations: GOFF sum != 100 and Flipt sum != 100 (labels from oracle) ----
    for c in [x for x in CASES if x["class"] == "F2" and x["origin"] == "constructed"]:
        pass


def write():
    os.makedirs(os.path.join(B, "files", "real"), exist_ok=True)
    for sha, r in REAL_FILES.items():
        dst = os.path.join(B, "files", "real", sha + ext(r))
        with open(census_path(r), "rb") as a, open(dst, "wb") as b:
            b.write(a.read())


if __name__ == "__main__":
    build_f4()
    build_f2()
    build_f3_from_phase0()
    build_constructed()
    write()
    json.dump({"cases": CASES, "f3_phase0_candidates": [
        {"repo": r["repo"], "path": r["path"], "sha256": r["sha256"], "flag": fl, "ghosts": g,
         "provenance_strict": r["provenance_strict"]} for r, fl, g in CAND_F3]},
        open(os.path.join(B, "build_out.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False, sort_keys=True)
    from collections import Counter
    print(Counter((c["class"], c["label"], c["origin"]) for c in CASES))
    print("F3 phase0 candidates", len(CAND_F3))
