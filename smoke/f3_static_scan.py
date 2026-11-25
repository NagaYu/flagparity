"""Supplementary F3 scan (throwaway): variants never produced by any literal source.
flagd: sources = defaultVariant + string literals in targeting (if-results, fractional variants). Flags whose targeting
       contains a non-literal variant producer (var/cat in result position) are not-judgeable -> counted separately.
Flipt (variant flags): sources = default_variant + rules[].distributions[].variant.
GOFF: sources = defaultRule/targeting variation, percentage keys, progressiveRollout initial/end variation."""
import csv, os, json, yaml, collections, sys
rows = [r for r in csv.DictReader(open('census/inventory.csv')) if r['counted'] == 'True']
def strings(n):
    if isinstance(n, str): yield n
    elif isinstance(n, list):
        for x in n: yield from strings(x)
    elif isinstance(n, dict):
        for k, v in n.items():
            if k == 'var': continue
            yield from strings(v)
def dynamic(t):
    if isinstance(t, dict):
        if 'if' in t and isinstance(t['if'], list):
            a = t['if']; res = a[1::2] + ([a[-1]] if len(a) % 2 else [])
            if any(isinstance(x, dict) and not ('if' in x or 'fractional' in x) for x in res): return True
            return any(dynamic(x) for x in a)
        if 'fractional' in t and isinstance(t['fractional'], list):
            return any(isinstance(d, list) and d and not isinstance(d[0], str) for d in t['fractional'][1:] if isinstance(d, list))
        return any(dynamic(v) for v in t.values()) if not ('if' in t or 'fractional' in t) else False
    return False
st = collections.Counter(); hits = []
for r in rows:
    fn = 'census/files/' + r['sha256'] + os.path.splitext(r['path'])[1].lower()
    t = open(fn).read()
    if r['format'] == 'flagd':
        for k, f in json.loads(t)['flags'].items():
            if not isinstance(f, dict) or not isinstance(f.get('variants'), dict): continue
            st['flagd_flags'] += 1; tg = f.get('targeting') or {}
            if tg and dynamic(tg): st['flagd_not_judgeable'] += 1; continue
            src = set(strings(tg)) | {f.get('defaultVariant')}
            ghost = [v for v in f['variants'] if v not in src]
            if ghost: hits.append((r['format'], r['provenance_strict'], r['repo'], r['path'], k, ghost))
    elif r['format'] == 'flipt':
        for d in yaml.safe_load_all(t):
            if not isinstance(d, dict): continue
            for f in d.get('flags') or []:
                if not isinstance(f, dict) or f.get('type') == 'BOOLEAN_FLAG_TYPE' or not f.get('variants'): continue
                st['flipt_variant_flags'] += 1
                src = {f.get('default_variant')} | {x.get('variant') for ru in (f.get('rules') or []) for x in (ru.get('distributions') or []) if isinstance(x, dict)}
                ghost = [v.get('key') for v in f['variants'] if isinstance(v, dict) and v.get('key') not in src]
                if ghost: hits.append((r['format'], r['provenance_strict'], r['repo'], r['path'], f.get('key'), ghost))
    else:
        for d in yaml.safe_load_all(t):
            if not isinstance(d, dict): continue
            for k, f in d.items():
                if not isinstance(f, dict) or not isinstance(f.get('variations'), dict): continue
                st['goff_flags'] += 1
                rules = [f.get('defaultRule') or {}] + [x for x in (f.get('targeting') or []) if isinstance(x, dict)]
                src = set()
                for ru in rules:
                    src.add(ru.get('variation')); pc = ru.get('percentage')
                    if pc is not None and not isinstance(pc, dict): st['goff_malformed_percentage'] += 1; continue
                    src |= set((pc or {}).keys())
                    pr = ru.get('progressiveRollout') or {}
                    for s in ('initial', 'end'): src.add((pr.get(s) or {}).get('variation'))
                if f.get('scheduledRollout') or f.get('experimentation'): st['goff_not_judgeable'] += 1; continue
                ghost = [v for v in f['variations'] if v not in src]
                if ghost: hits.append((r['format'], r['provenance_strict'], r['repo'], r['path'], k, ghost))
c = collections.Counter((h[0], h[1] == 'non-sample') for h in hits)
out = dict(stats=st, flags_with_static_ghost=len(hits), by_format_nonsample=[[f, ns, n] for (f, ns), n in c.items()], examples=hits)
json.dump(out, open('results/f3_static_scan.json', 'w'), indent=1)
print(dict(st), 'ghost flags', len(hits), dict(c))
