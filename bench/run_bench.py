"""Gate 1 measurement on the frozen dev bench (DECISIONS.md §P1-A, P1-C-4..6).

Writes bench/results/verdicts.json (run 1), bench/results/verdicts.run2.json (run 2, for G1-4),
bench/results/census_verdicts.json (G1-5 on the 634-file census) and bench/results/gate1.json.
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(ROOT, "bench")
RES = os.path.join(B, "results")
GATE = ("F1", "F2", "F3", "F4", "F7")


def run_core(files, out):
    """Separate process per run so no in-process state can leak between the two runs."""
    cmd = [sys.executable, "-m", "flagparity", "check", "--root", B, "--out", out] + [os.path.join(B, f) for f in files]
    subprocess.run(cmd, cwd=ROOT, check=True)
    with open(out, "rb") as fh:
        return fh.read()


def main():
    os.makedirs(RES, exist_ok=True)
    spec = json.load(open(os.path.join(B, "cases.json"), encoding="utf-8"))
    cases, clean = spec["cases"], spec["clean_set"]
    files = sorted({c["file"] for c in cases} | {c["file"] for c in clean})
    r1 = run_core(files, os.path.join(RES, "verdicts.json"))
    r2 = run_core(files, os.path.join(RES, "verdicts.run2.json"))
    doc = json.loads(r1)
    byfile = {f["path"]: f for f in doc["files"]}

    # ---- G1-4 determinism
    g14 = {"run1_sha256": hashlib.sha256(r1).hexdigest(), "run2_sha256": hashlib.sha256(r2).hexdigest(),
           "identical": r1 == r2, "bytes": len(r1)}

    # ---- G1-5 accounting (bench + census)
    s = doc["summary"]
    g15_bench = {"input_files": len(files), "judged": s["judged"], "not_judgeable": s["not_judgeable"],
                 "balanced": len(files) == s["judged"] + s["not_judgeable"] == s["input_files"]}
    cen_out = os.path.join(RES, "census_verdicts.json")
    subprocess.run([sys.executable, os.path.join(B, "census_run.py"), cen_out], cwd=ROOT, check=True, capture_output=True)
    cen = json.load(open(cen_out, encoding="utf-8"))
    cs = cen["summary"]
    nj_reasons = {}
    for f in cen["files"]:
        if f["status"] == "not-judgeable":
            nj_reasons[f["reason"]] = nj_reasons.get(f["reason"], 0) + 1
    flag_nj_unreasoned = sum(1 for f in cen["files"] + doc["files"] for fl in f["flags"] for c, v in fl["classes"].items()
                             if v["status"] == "not-judgeable" and not v.get("reason"))
    g15_census = {"input_files": 634, "reported_files": cs["input_files"], "judged": cs["judged"],
                  "not_judgeable": cs["not_judgeable"], "file_not_judgeable_reasons": nj_reasons,
                  "balanced": 634 == cs["input_files"] == cs["judged"] + cs["not_judgeable"],
                  "flag_class_not_judgeable_without_reason": flag_nj_unreasoned}

    # ---- per-case outcomes
    rows = []
    for c in cases:
        f = byfile[c["file"]]
        fl = [x for x in f["flags"] if x["flag"] == c["flag"]]
        if not fl:
            st, v = "missing-flag", {}
        else:
            # a flag key can occur in several YAML documents/namespaces of one file: the case label is about
            # the key, so the case counts as detected if any instance is detected (first detected instance used)
            det = [x for x in fl if x["classes"][c["class"]]["status"] == "detected"]
            v = (det or fl)[0]["classes"][c["class"]]
            st = v["status"]
        row = {"id": c["id"], "class": c["class"], "label": c["label"], "origin": c["origin"], "route": c["route"],
               "status": st, "hit": st == "detected"}
        if st == "not-judgeable":
            row["reason"] = v.get("reason")
        if c["class"] == "F4" and c["label"] == "positive":
            row["expected_pairs"] = sorted(c.get("expected_pairs") or [])
            row["predicted_pairs"] = sorted(v.get("divergent_pairs") or [])
            row["attribution_correct"] = st == "detected" and row["expected_pairs"] == row["predicted_pairs"]
        rows.append(row)

    def recall(sel):
        sel = list(sel)
        return {"n": len(sel), "detected": sum(r["hit"] for r in sel),
                "recall": (sum(r["hit"] for r in sel) / len(sel)) if sel else None,
                "misses": [{"id": r["id"], "status": r["status"], "reason": r.get("reason")} for r in sel if not r["hit"]]}

    pos = [r for r in rows if r["label"] == "positive"]
    per_class = {k: recall(r for r in pos if r["class"] == k) for k in GATE}
    overall = recall(pos)
    by_origin = {k: {o: recall(r for r in pos if r["class"] == k and r["origin"] == o) for o in ("real", "constructed")} for k in GATE}
    by_route = {}
    for r in pos:
        by_route.setdefault(r["route"], []).append(r)
    by_route = {k: recall(v) for k, v in sorted(by_route.items())}
    neg = [r for r in rows if r["label"] == "negative"]
    neg_fp = {k: {"n": sum(1 for r in neg if r["class"] == k), "false_positives": [r["id"] for r in neg if r["class"] == k and r["hit"]]}
              for k in GATE}

    # ---- clean set
    clean_fp = []
    for c in clean:
        f = byfile[c["file"]]
        for fl in f["flags"]:
            for k in GATE:
                if fl["classes"][k]["status"] == "detected":
                    clean_fp.append({"file": c["file"], "flag": fl["flag"], "class": k})
    g12 = {"per_class": per_class, "overall": overall, "by_origin": by_origin, "by_route": by_route,
           "negative_cases": neg_fp, "clean_set": {"files": len(clean), "false_positives": clean_fp},
           "pass": (overall["recall"] or 0) >= 0.95 and all((v["recall"] or 0) >= 0.90 for v in per_class.values()) and not clean_fp}

    # ---- G1-3 attribution
    f4 = [r for r in rows if r["class"] == "F4" and r["label"] == "positive" and r["hit"]]
    g13 = {"denominator": len(f4), "correct": sum(r["attribution_correct"] for r in f4),
           "accuracy": (sum(r["attribution_correct"] for r in f4) / len(f4)) if f4 else None,
           "wrong": [{"id": r["id"], "expected": r["expected_pairs"], "predicted": r["predicted_pairs"]} for r in f4 if not r["attribution_correct"]]}
    g13["pass"] = (g13["accuracy"] or 0) >= 0.90

    # ---- G1-1 fidelity
    fid = json.load(open(os.path.join(ROOT, "vectors", "fidelity.json"), encoding="utf-8"))["semantics"]
    caveat_missing = []
    for d in (doc, cen):
        for f in d["files"]:
            for fl in f["flags"]:
                v = fl["classes"]["F4"]
                if v["status"] != "detected":
                    continue
                used = {sid for p in v["divergent_pairs"] for sid in p.split(" ~ ")}
                unverified = sorted(sid for sid in used if fid.get(sid, {}).get("status") != "vector-verified")
                if unverified and not all(sid in (v.get("fidelity_caveat") or "") for sid in unverified):
                    caveat_missing.append((f["path"], fl["flag"], unverified))
    g11 = {"semantics": {k: {"status": v["status"], "applicable": v["results"]["applicable"], "pass": v["results"]["pass"],
                             "fail": v["results"]["fail"]} for k, v in sorted(fid.items())},
           "goff_source_only_caveat_missing": caveat_missing}
    # semantics with official vectors must match 100%; semantics without them must be marked source-only
    # (DECISIONS P1-Z-5: flagd G1 applicability; P1-Z-6: GOFF v1.32+ unit tests are official vectors)
    g11["pass"] = all((v["status"] == "vector-verified") if v["official_vectors_by_preregistration"] and v["results"]["applicable"]
                      else (v["status"] == "source-only") for v in fid.values()) and not caveat_missing

    gate = {"G1-1": g11, "G1-2": g12, "G1-3": g13, "G1-4": dict(g14, **{"pass": g14["identical"]}),
            "G1-5": {"bench": g15_bench, "census": g15_census,
                     "pass": g15_bench["balanced"] and g15_census["balanced"] and flag_nj_unreasoned == 0},
            "cases": rows}
    gate["GATE_1"] = "PASS" if all(gate[k]["pass"] for k in ("G1-1", "G1-2", "G1-3", "G1-4", "G1-5")) else "FAIL"
    with open(os.path.join(RES, "gate1.json"), "w", encoding="utf-8") as fh:
        json.dump(gate, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print("GATE 1:", gate["GATE_1"])
    for k in ("G1-1", "G1-2", "G1-3", "G1-4", "G1-5"):
        print(k, "PASS" if gate[k]["pass"] else "FAIL")
    print("recall overall %.3f (%d/%d)" % (overall["recall"], overall["detected"], overall["n"]))
    for k, v in per_class.items():
        print("  %s recall %.3f (%d/%d) misses=%s" % (k, v["recall"], v["detected"], v["n"], [m["id"] + ":" + m["status"] for m in v["misses"]]))
    print("clean-set FP", clean_fp)
    print("negative-case FP", {k: v["false_positives"] for k, v in neg_fp.items()})
    print("attribution", g13["correct"], "/", g13["denominator"], g13["wrong"])
    print("determinism", g14)
    print("accounting bench", g15_bench, "census", {k: g15_census[k] for k in ("input_files", "judged", "not_judgeable", "balanced")})


if __name__ == "__main__":
    main()
