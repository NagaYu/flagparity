"""Run the verifier over the Phase 0 census population (634 counted files). G1-5 accounting.
Usage: python3 bench/census_run.py OUT.json"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from flagparity.core import check_files, dumps  # noqa: E402

rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "smoke/census/inventory.csv"), encoding="utf-8"))
        if r["counted"] == "True"]
items = []
for r in rows:
    fn = os.path.join(ROOT, "smoke/census/files", r["sha256"] + os.path.splitext(r["path"])[1].lower())
    label = "%s@%s/%s" % (r["repo"], r["ref"][:8], r["path"])
    items.append((label, open(fn, "rb").read()))
doc = check_files(items)
open(sys.argv[1], "w", encoding="utf-8").write(dumps(doc))
print(doc["summary"])
