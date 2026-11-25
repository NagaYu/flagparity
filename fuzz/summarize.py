"""Summarise the Phase 3 fuzz round into fuzz/results/SUMMARY.json (counts only; no checker evidence).

  python3 fuzz/summarize.py
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
SEQ = [  # (label, result file, what changed, category of the mismatches it removed)
    ("pre-fix detector (1b8f1b6) + final checker", "run1b.pre-fix.checker-ext.json", None, None),
    ("fix 1 YAML as yaml.v3 decodes it (1358029)", "attr.1358029.json", "detector", "detector defect"),
    ("fix 2 P3-A-1 bare-value flagd targeting (a5701d6)", "attr.a5701d6.json", "detector", "definition boundary handled by Step 0"),
    ("fix 3 undefined flagd defaultVariant reported (7946244)", "attr.7946244.json", "detector", "detector defect"),
    ("fix 4 P3-A-2 resolved-variant F4 (62dc17c)", "attr.62dc17c.json", "detector", "definition boundary handled by Step 0"),
    ("fixes 4b/5/6 default resolution, semver witnesses, jsonlogic v3.10.2 (fa43339)", "attr.fa43339.json", "detector", "see per-mismatch note"),
    ("fix 7 numeric witnesses for string constants (dbc67e2)", "attr.dbc67e2.json", "detector", "detector defect"),
]


def keys(p):
    return {(m["file"], m.get("flag"), m.get("doc"), m["cls"], m.get("kind")): m
            for m in json.load(open(os.path.join(R, p), encoding="utf-8"))["mismatches"]}


def main():
    first = json.load(open(os.path.join(R, "run1.pre-fix.json"), encoding="utf-8"))
    orig = keys("run1.pre-fix.json")
    steps, prev = [], None
    for label, f, what, cat in SEQ:
        cur = keys(f)
        st = {"step": label, "mismatches": len(cur), "by_class": dict(sorted(collections.Counter(k[3] for k in cur).items()))}
        if prev is not None:
            gone, new = set(prev) - set(cur), set(cur) - set(prev)
            st.update(removed=len(gone), removed_by_class=dict(sorted(collections.Counter(k[3] for k in gone).items())),
                      surfaced=len(new), category=cat)
        steps.append(st)
        prev = cur
    final = json.load(open(os.path.join(R, "step9.classified.json"), encoding="utf-8"))
    pre_ext = keys("run1b.pre-fix.checker-ext.json")
    doc = {"schema": "flagparity.fuzz-summary/v1", "seed": first["seed"], "files": first["files"], "per_format": first["per_format"],
           "cases_sha256": first["cases_sha256"],
           "original_phase2_checker": {"pre_fix_mismatches": len(orig),
                                       "by_class": dict(sorted(collections.Counter(k[3] for k in orig).items())),
                                       "removed_by_checker_fixes_C1_C8": len(set(orig) - set(pre_ext)),
                                       "surfaced_by_checker_fixes": len(set(pre_ext) - set(orig))},
           "final_checker_steps": steps,
           "residual_after_all_fixes": {"mismatches": sum(final["counts"].values()), "categories": final["counts"]},
           "compared_decisive_final": json.load(open(os.path.join(R, "attr.dbc67e2.json"), encoding="utf-8"))["compared_decisive"]}
    # owner decisions on B-1..B-3 (DECISIONS P3-Z-6) and the correction P3-Z-7
    cls = json.load(open(os.path.join(R, "final.classified.json"), encoding="utf-8"))["mismatches"]
    after = json.load(open(os.path.join(R, "decided.json"), encoding="utf-8"))
    cause = {"boundary:B-2": "detector fix P3-Z-7 (defaultVariant reachable when fractional returns nil, e.g. no targetingKey) - was misclassified as B-2",
             "boundary:B-3-goff-disabled-targeting": "checker applies owner decision B-3a (C9)",
             "boundary:B-3-dialect": "checker applies owner decision B-3b (C10)"}
    doc["after_owner_decisions"] = {"before": len(cls), "after": len(after["mismatches"]),
                                    "resolved_by": dict(sorted(collections.Counter(cause[m["category"]] for m in cls).items())),
                                    "compared_decisive": after["compared_decisive"]}
    with open(os.path.join(R, "SUMMARY.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(json.dumps(doc, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
