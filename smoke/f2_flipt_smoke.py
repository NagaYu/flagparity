"""F2 smoke (throwaway): Flipt rule distributions whose rollout sum != 100.
Effective allocation is computed over Flipt's full bucket space (crc32 % 1000 -> buckets 0..999) from public source:
  server-legacy : Flipt v1.x and v2 < 2.9.0  (no normalisation; remainder -> Match=false -> flag defaultVariant or no variant)
  server-v2.9+  : Flipt v2 >= 2.9.0 (PR #5581; normalised, int() truncation)
  rust-client   : flipt-client-sdks engine (normalised, round())
Also evaluates the fixed D-6 key set (user-0000..user-0999) as an empirical cross-check.
Usage: f2_flipt_smoke.py <file> [--scan]   (--scan: only list rules with sum != 100)"""
import sys, os, json, struct, math, bisect
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
import yaml
from engines import flipt_variant, _f32

def docs_of(fn):
    return [d for d in yaml.safe_load_all(open(fn)) if isinstance(d, dict)]

def rules_with_dists(doc):
    for f in doc.get('flags') or []:
        if not isinstance(f, dict): continue
        for i, r in enumerate(f.get('rules') or []):
            if isinstance(r, dict) and isinstance(r.get('distributions'), list) and r['distributions']:
                d = [(x.get('variant'), float(x.get('rollout', 0))) for x in r['distributions'] if isinstance(x, dict)]
                yield f, i, r, d

def bucket_table(engine, dists):
    """map bucket 0..999 -> variant/None (same arithmetic as engines.flipt_variant)."""
    valid = [(v, r) for v, r in dists if r > 0]
    buckets = []
    if engine == 'server-legacy':
        for v, r in valid:
            b = int(_f32(_f32(r) * _f32(10.0))); buckets.append(b if not buckets else buckets[-1] + b)
    else:
        total = _f32(0.0)
        for _, r in valid: total = _f32(total + _f32(r))
        cum = _f32(0.0)
        for i, (v, r) in enumerate(valid):
            cum = _f32(cum + _f32(_f32(_f32(r) / total) * _f32(100.0))); x = _f32(cum * _f32(10.0))
            b = int(x) if engine == 'server-v2.9+' else int(math.floor(x + 0.5))
            if i + 1 == len(valid): b = 1000
            buckets.append(b)
    out = {}
    for bk in range(1000):
        idx = bisect.bisect_left(buckets, bk + 1)
        out[bk] = None if idx == len(valid) else valid[idx][0]
    return out

def main(fn, scan=False):
    rep = dict(file=fn, rules_total=0, rules_sum_ne_100=0, findings=[])
    for doc in docs_of(fn):
        for f, i, r, d in rules_with_dists(doc):
            rep['rules_total'] += 1
            s = sum(x for _, x in d)
            if abs(s - 100) < 1e-9: continue
            rep['rules_sum_ne_100'] += 1
            if scan: rep['findings'].append(dict(flag=f.get('key'), rule_index=i, rollouts=d, sum=s)); continue
            fdef = f.get('default_variant') or f.get('defaultVariant')
            eng = {}
            for e in ('server-legacy', 'server-v2.9+', 'rust-client'):
                tab = bucket_table(e, d)
                cnt = {}
                for v in tab.values(): cnt[str(v)] = cnt.get(str(v), 0) + 1
                emp = {}
                for k in ('user-%04d' % n for n in range(1000)):
                    v = flipt_variant(e, f['key'], k, d); emp[str(v)] = emp.get(str(v), 0) + 1
                eng[e] = dict(bucket_share_per_mille=cnt, d6_keys_count=emp)
            rep['findings'].append(dict(flag=f.get('key'), rule_index=i, segment=r.get('segment'), rollouts=d, sum=s,
                                        flag_default_variant=fdef, flag_enabled=f.get('enabled'), engines=eng))
    print(json.dumps(rep, indent=1, default=str))

if __name__ == '__main__': main(sys.argv[1], '--scan' in sys.argv)
