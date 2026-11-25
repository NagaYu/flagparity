"""Aggregate smoke/census/inventory.csv into smoke/census/summary.json (Gate (b) and KT-2)."""
import csv, json, os, collections
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
rows = list(csv.DictReader(open(os.path.join(BASE, 'inventory.csv'))))
C = [r for r in rows if r['counted'] == 'True']
out = dict(fetchable_unique_candidates=len(rows),
           fetch_status=collections.Counter(r['status'] for r in rows),
           identified=collections.Counter(r['format'] for r in rows),
           exclusions=collections.Counter(r['exclusion'] for r in rows if r['format'] in ('flagd', 'flipt', 'goff') and r['exclusion']),
           counted_files=len(C), counted_repos=len({r['repo'].lower() for r in C}),
           by_format={f: dict(files=sum(1 for r in C if r['format'] == f), repos=len({r['repo'].lower() for r in C if r['format'] == f})) for f in ('flagd', 'flipt', 'goff')})
for ver in ('provenance_prereg', 'provenance_strict'):
    ns = [r for r in C if r[ver] == 'non-sample']
    out[ver] = dict(by_class=collections.Counter(r[ver] for r in C),
                    by_format_class={f: collections.Counter(r[ver] for r in C if r['format'] == f) for f in ('flagd', 'flipt', 'goff')},
                    nonsample_files=len(ns), nonsample_repos=len({r['repo'].lower() for r in ns}),
                    nonsample_share=round(len(ns) / len(C), 4) if C else None,
                    nonsample_fixture_path=sum(1 for r in ns if r['fixture_path'] == 'True'),
                    nonsample_not_fixture=sum(1 for r in ns if r['fixture_path'] != 'True'),
                    nonsample_not_fixture_repos=len({r['repo'].lower() for r in ns if r['fixture_path'] != 'True'}),
                    nonsample_top_repos=collections.Counter(r['repo'] for r in ns).most_common(15))
json.dump(out, open(os.path.join(BASE, 'summary.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
