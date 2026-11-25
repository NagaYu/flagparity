"""Apply DECISIONS.md D-7 to smoke/census/inventory.csv (sort order: repo lower-case, then path).
'non-sample' here = non-sample under BOTH the pre-registered and the strict provenance."""
import csv, json, os, sys
import yaml
BASE = os.path.dirname(os.path.abspath(__file__))
rows = [r for r in csv.DictReader(open(os.path.join(BASE, 'census', 'inventory.csv'))) if r['counted'] == 'True']
def fpath(r): return os.path.join(BASE, 'census', 'files', r['sha256'] + os.path.splitext(r['path'])[1].lower())
def nonsample(r): return r['provenance_prereg'] == 'non-sample' and r['provenance_strict'] == 'non-sample'
def load(r):
    t = open(fpath(r)).read()
    return json.loads(t) if r['format'] == 'flagd' else [d for d in yaml.safe_load_all(t) if isinstance(d, dict)]

def flagd_branches(t):
    if isinstance(t, dict) and 'if' in t and isinstance(t['if'], list):
        a = t['if']; n = len(a) // 2 + (1 if len(a) % 2 else 0)
        return n + sum(flagd_branches(x) - 1 for x in a[1::2] if isinstance(x, dict) and 'if' in x)
    return 1 if t else 0

def n_rules(r):
    d = load(r)
    if r['format'] == 'flagd':
        return max((flagd_branches(f.get('targeting') or {}) for f in d['flags'].values() if isinstance(f, dict)), default=0)
    if r['format'] == 'flipt':
        return max((len(f.get('rules') or []) + len(f.get('rollouts') or []) for doc in d for f in (doc.get('flags') or []) if isinstance(f, dict)), default=0)
    return max((len(v.get('targeting') or []) for doc in d for v in doc.values() if isinstance(v, dict)), default=0)

def flipt_has_sum_ne_100(r):
    for doc in load(r):
        for f in doc.get('flags') or []:
            for ru in (f.get('rules') or []) if isinstance(f, dict) else []:
                ds = ru.get('distributions') if isinstance(ru, dict) else None
                if ds and abs(sum(float(x.get('rollout', 0)) for x in ds if isinstance(x, dict)) - 100) > 1e-9: return True
    return False

def has_fractional(r): return '"fractional"' in open(fpath(r)).read()

out = {}
fl = [r for r in rows if r['format'] == 'flipt']
out['F2'] = next((r for r in fl if flipt_has_sum_ne_100(r)), None)
out['F2_denominator'] = dict(flipt_files=len(fl))
fd = [r for r in rows if r['format'] == 'flagd']
out['F4'] = next((r for r in fd if nonsample(r) and has_fractional(r)), None) or next((r for r in fd if has_fractional(r)), None)
out['F4_pool'] = dict(flagd_files=len(fd), with_fractional=sum(map(has_fractional, fd)), nonsample_with_fractional=sum(1 for r in fd if nonsample(r) and has_fractional(r)))
out['F1F3'] = next((r for r in rows if nonsample(r) and n_rules(r) >= 2), None) or next((r for r in rows if n_rules(r) >= 2), None)
for k in ('F2', 'F4', 'F1F3'):
    r = out[k]; out[k] = None if r is None else {c: r[c] for c in ('repo', 'path', 'ref', 'sha256', 'format', 'provenance_prereg', 'provenance_strict', 'url')} | {'local': os.path.relpath(fpath(r), BASE)}
print(json.dumps(out, indent=1))
