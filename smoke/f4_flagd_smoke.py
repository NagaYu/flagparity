"""F4 smoke (throwaway): flagd fractional assignment under G3 (current, >= v0.18.0) vs G2 (v0.15.0-v0.17.x,
the semantics immediately before v0.18.0), plus G1 (<= v0.14.x) for reference.
Context set fixed in DECISIONS.md D-6: N=1000, targetingKey user-0000..user-0999, referenced attrs = targetingKey.
Input: one flagd JSON file (parsed as data only). Output: JSON report on stdout."""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from engines import flagd_fractional

N = 1000
KEYS = ['user-%04d' % i for i in range(N)]

class NotJudgeable(Exception): pass

def resolve_bucketing(expr, flag_key, tk):
    """tiny JSONLogic subset: literals, var, cat. Anything else -> NotJudgeable."""
    if isinstance(expr, (str, int, float, bool)): return expr
    if isinstance(expr, dict) and len(expr) == 1:
        op, arg = next(iter(expr.items()))
        if op == 'var':
            name = arg[0] if isinstance(arg, list) else arg
            if name == '$flagd.flagKey': return flag_key
            return tk  # D-6: every referenced attribute (incl. targetingKey) := targetingKey string
        if op == 'cat':
            parts = [resolve_bucketing(a, flag_key, tk) for a in (arg if isinstance(arg, list) else [arg])]
            return ''.join(str(p) for p in parts)
    raise NotJudgeable('unsupported bucketing expression: %s' % json.dumps(expr)[:120])

def parse_fractional(args):
    if not isinstance(args, list) or not args: raise NotJudgeable('fractional args not a list')
    explicit = None
    if not isinstance(args[0], list):
        explicit, dists = args[0], args[1:]
    else:
        dists = args
    out = []
    for d in dists:
        if not isinstance(d, list) or not d or not isinstance(d[0], str): raise NotJudgeable('non-literal variant in distribution: %s' % json.dumps(d)[:80])
        w = d[1] if len(d) > 1 else 1
        if not isinstance(w, (int, float)) or w != int(w): raise NotJudgeable('non-integer/computed weight: %s' % json.dumps(d)[:80])
        out.append((d[0], int(w)))
    return explicit, out

def find_fractionals(node, path='targeting'):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ('fractional', 'fractionalEvaluation'): yield path + '.' + k, k, v
            yield from find_fractionals(v, path + '.' + k)
    elif isinstance(node, list):
        for i, v in enumerate(node): yield from find_fractionals(v, '%s[%d]' % (path, i))

def main(fn):
    doc = json.load(open(fn))
    report = dict(file=fn, n_contexts=N, flags=[])
    for fk, f in doc['flags'].items():
        for p, op, args in find_fractionals(f.get('targeting') or {}):
            entry = dict(flag=fk, path=p, operator=op)
            try:
                if op == 'fractionalEvaluation': raise NotJudgeable('legacy fractionalEvaluation operator (pre-#1266 syntax)')
                explicit_expr, dist = parse_fractional(args)
                entry['distribution'] = dist
                entry['bucketing'] = 'default [flagKey, targetingKey]' if explicit_expr is None else json.dumps(explicit_expr)
                res = {g: [] for g in ('G1', 'G2', 'G3')}
                for tk in KEYS:
                    ex = None if explicit_expr is None else resolve_bucketing(explicit_expr, fk, tk)
                    for g in res: res[g].append(flagd_fractional(g, fk, tk, dist, explicit=ex))
                def share(g): return {v: res[g].count(v) for v, _ in dist}
                def flips(a, b): return sum(1 for x, y in zip(res[a], res[b]) if x != y)
                entry.update(alloc={g: share(g) for g in res},
                             flips_G2_vs_G3=flips('G2', 'G3'), flip_rate_G2_vs_G3=flips('G2', 'G3') / N,
                             flips_G1_vs_G3=flips('G1', 'G3'), flips_G1_vs_G2=flips('G1', 'G2'),
                             sample=[dict(targetingKey=KEYS[i], G1=res['G1'][i], G2=res['G2'][i], G3=res['G3'][i]) for i in range(5)])
                entry['verdict'] = 'judged'
            except NotJudgeable as e:
                entry['verdict'] = 'not-judgeable'; entry['reason'] = str(e)
            report['flags'].append(entry)
    print(json.dumps(report, indent=1))

if __name__ == '__main__': main(sys.argv[1])
