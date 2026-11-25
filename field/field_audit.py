"""Phase 3 field audit (DECISIONS.md §P3-D).

  python3 field/field_audit.py --detector DIR --out OUT.json

Population: the Phase 0 census counted files (smoke/census/inventory.csv, counted == True; 634) plus the Phase 2
never-fetched files (holdout/pool.json; 25). Runs the detector found in DIR (DIR/flagparity, or DIR/flagbound before the Phase 3 rename) on every file and reports,
per class, flags `detected` / `not-judgeable` and files with >= 1 detection, split by provenance:
  sample     = Z-2 strict provenance `sample:*` (tutorial / provider-owned / provider-mirror / sample-identical)
  non-sample = everything else (looks like real use)
Detector output = unverified candidates, not labels. Representatives (up to 3 per class x group) are chosen
mechanically by sha256 order for hand reading.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLASSES = ("F1", "F2", "F3", "F4", "F7")


def population():
    pop = []
    for r in csv.DictReader(open(os.path.join(ROOT, "smoke", "census", "inventory.csv"), encoding="utf-8")):
        if r["counted"] != "True":
            continue
        pop.append({"source": "census", "repo": r["repo"], "path": r["path"], "ref": r["ref"], "sha256": r["sha256"],
                    "url": r["url"], "provenance_prereg": r["provenance_prereg"], "provenance_strict": r["provenance_strict"],
                    "fixture_path": r["fixture_path"] == "True", "format_census": r["format"],
                    "local": os.path.join(ROOT, "smoke", "census", "files", r["sha256"] + os.path.splitext(r["path"])[1].lower())})
    for f in json.load(open(os.path.join(ROOT, "holdout", "pool.json"), encoding="utf-8"))["files"]:
        pop.append({"source": "never-fetched", "repo": f["repo"], "path": f["path"], "ref": f["ref"], "sha256": f["sha256"],
                    "url": f.get("url", ""), "provenance_prereg": f["provenance_prereg"], "provenance_strict": f["provenance_strict"],
                    "fixture_path": bool(f.get("fixture_path")), "format_census": f["format"],
                    "local": os.path.join(ROOT, "holdout", f["local"])})
    return pop


def bench_repos():
    spec = json.load(open(os.path.join(ROOT, "bench", "cases.json"), encoding="utf-8"))
    return {c["source"]["repo"].lower() for c in spec["cases"] + spec["clean_set"] if (c.get("source") or {}).get("repo")}


def group(p):
    return "sample" if p["provenance_strict"].startswith("sample") else "non-sample"


def main(argv):
    det = os.path.abspath(argv[argv.index("--detector") + 1])
    out = argv[argv.index("--out") + 1]
    pop = population()
    brepos = bench_repos()
    tmp = tempfile.mkdtemp(prefix="fb-field-")
    names = []
    for i, p in enumerate(pop):
        name = "%04d-%s%s" % (i, p["sha256"][:12], os.path.splitext(p["path"])[1].lower())
        with open(p["local"], "rb") as src, open(os.path.join(tmp, name), "wb") as dst:
            dst.write(src.read())
        p["label"] = name
        names.append(name)
    vout = os.path.join(tmp, "verdicts.json")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    subprocess.run([sys.executable, "-m", "flagparity" if os.path.isdir(os.path.join(det, "flagparity")) else "flagbound", "check", "--root", tmp, "--out", vout] +
                   [os.path.join(tmp, n) for n in names], cwd=det, env=env, check=True)
    verdicts = {f["path"]: f for f in json.load(open(vout, encoding="utf-8"))["files"]}
    groups = ("sample", "non-sample")
    files_by_group = {g: sum(1 for p in pop if group(p) == g) for g in groups}
    table = {c: {g: {"flags_detected": 0, "files_with_detection": 0, "flags_not_judgeable": 0} for g in groups} for c in CLASSES}
    by_prov = {}
    sub = {c: {} for c in CLASSES}  # (group, fixture_path) split of files with a detection
    sub_files = {}
    nb = {c: {} for c in CLASSES}  # same split, files outside the Phase 1 dev bench source repos only
    nb_files = {}
    reps = {c: {g: [] for g in groups} for c in CLASSES}
    status = {"judged": 0, "not-judgeable": 0}
    formats = {}
    for p in sorted(pop, key=lambda x: x["sha256"]):
        v = verdicts[p["label"]]
        status[v["status"]] = status.get(v["status"], 0) + 1
        formats[v.get("format") or "none"] = formats.get(v.get("format") or "none", 0) + 1
        g = group(p)
        sk = "%s|%s" % (g, "fixture-path" if p["fixture_path"] else "other-path")
        sub_files[sk] = sub_files.get(sk, 0) + 1
        in_bench = p["repo"].lower() in brepos
        if not in_bench:
            nb_files[sk] = nb_files.get(sk, 0) + 1
        for c in CLASSES:
            hits = [fl for fl in v.get("flags", []) if fl["classes"][c]["status"] == "detected"]
            nj = [fl for fl in v.get("flags", []) if fl["classes"][c]["status"] == "not-judgeable"]
            table[c][g]["flags_detected"] += len(hits)
            table[c][g]["flags_not_judgeable"] += len(nj)
            if hits:
                table[c][g]["files_with_detection"] += 1
                sub[c][sk] = sub[c].get(sk, 0) + 1
                if not in_bench:
                    nb[c][sk] = nb[c].get(sk, 0) + 1
                k = (c, p["provenance_strict"])
                by_prov[k] = by_prov.get(k, 0) + 1
                if len(reps[c][g]) < 3:
                    reps[c][g].append({"repo": p["repo"], "path": p["path"], "ref": p["ref"], "url": p["url"],
                                       "sha256": p["sha256"], "provenance_strict": p["provenance_strict"],
                                       "fixture_path": p["fixture_path"], "source": p["source"],
                                       "flag": hits[0]["flag"], "verdict": hits[0]["classes"][c]})
    doc = {"schema": "flagparity.field-audit/v1", "detector_dir": os.path.basename(det),
           "population": {"files": len(pop), "census": sum(1 for p in pop if p["source"] == "census"),
                          "never_fetched": sum(1 for p in pop if p["source"] == "never-fetched"),
                          "by_group": files_by_group, "file_status": status, "formats": formats},
           "per_class": table,
           "files_by_group_and_path": dict(sorted(sub_files.items())),
           "files_with_detection_by_group_and_path": {c: dict(sorted(v.items())) for c, v in sub.items()},
           "outside_bench_source_repos": {"files_by_group_and_path": dict(sorted(nb_files.items())),
                                          "files_with_detection_by_group_and_path": {c: dict(sorted(v.items())) for c, v in nb.items()}},
           "files_with_detection_by_strict_provenance": {"%s|%s" % k: n for k, n in sorted(by_prov.items())},
           "representatives": reps}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(json.dumps({k: doc[k] for k in ("population", "files_by_group_and_path", "files_with_detection_by_group_and_path", "outside_bench_source_repos")}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
