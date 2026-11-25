"""Run every vector suite for every registered semantics and write vectors/fidelity.json (G1-1).

fidelity status per semantics:
  vector-verified : official vectors exist and all applicable vectors pass (100%)
  FAILED          : official vectors exist and at least one applicable vector fails
  source-only     : no official vectors by pre-registration (GOFF); supplementary checks reported only
Usage: python3 -I vectors/run_vectors.py [--out vectors/fidelity.json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import flagparity.semantics as S  # noqa: E402
import flagd_testbed  # noqa: E402
import flipt_vectors  # noqa: E402
import goff_vectors  # noqa: E402

RUNNERS = {"flagd": flagd_testbed.run, "flipt": flipt_vectors.run, "goff": goff_vectors.run}


def flagd_g1_supplement():
    """Supplementary (not the pre-registered rule): G1 restricted to examples tagged @fractional-v1
    plus scenarios that do not exercise the fractional operator at all."""
    sem = S.get("flagd/G1")
    full = flagd_testbed.run(sem)
    fails = full["failures"]
    frac_untagged_fail = [f for f in fails if "ractional" in f["scenario"] or "fractional" in f["feature"]]
    return {"failures_all_in_untagged_fractional_scenarios": len(frac_untagged_fail) == len(fails),
            "failing_examples": [{"feature": f["feature"], "scenario": f["scenario"], "row": f["row"]} for f in fails]}


def main(out):
    table = {"schema": "flagparity.fidelity/v1", "semantics": {}}
    for sem in S.all_semantics():
        r = RUNNERS[sem.format](sem)
        failures = r.pop("failures")
        if not sem.vectors_declared_official:
            status = "source-only"
        elif r["applicable"] == 0:
            status = "source-only"
        else:
            status = "vector-verified" if r["fail"] == 0 else "FAILED"
        table["semantics"][sem.id] = {
            "label": sem.label, "format": sem.format, "kind": sem.kind, "order": sem.order,
            "sources": list(sem.sources), "vector_suites": list(sem.vector_suites),
            "official_vectors_by_preregistration": sem.vectors_declared_official,
            "status": status, "results": r,
            "failures": failures[:50],
        }
    table["supplement"] = {"flagd/G1": flagd_g1_supplement(),
                           "flagd/G1_note": "applicability per DECISIONS P1-Z-5 (owner decision A, 2026-11-25); "
                                            "under the original P1-Z-2 rule G1 was 223/241 (FAILED)",
                           "goff/v1.32+_note": "official vectors per DECISIONS P1-Z-6 (owner decision B, 2026-11-25); "
                                               "source-only before that decision"}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    for k, v in table["semantics"].items():
        print("%-22s %-16s %s" % (k, v["status"], json.dumps(v["results"], sort_keys=True)))


if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(HERE, "fidelity.json")
    main(out)
