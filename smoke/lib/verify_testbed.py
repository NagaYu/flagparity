"""Check the flagd re-implementation against official flagd-testbed vectors
(open-feature/flagd-testbed@7690b548 gherkin/targeting.feature + flags/custom-ops.json)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engines import flagd_fractional, murmur3_32

suits = [('clubs', 25), ('diamonds', 25), ('hearts', 25), ('spades', 25)]
coin = [('heads', 1), ('tails', 1)]
V = {
 'fractional-flag': {'G1': dict(jack='spades', queen='clubs', ten='diamonds', nine='hearts', **{'3': 'diamonds'}),
                     'G2': dict(jack='hearts', queen='spades', ten='clubs', nine='diamonds', **{'3': 'clubs'}),
                     'G3': dict(jack='diamonds', queen='diamonds', ten='clubs', nine='clubs', **{'3': 'spades'})},
 'shared': {'G1': dict(jack='hearts', queen='spades', ten='hearts', nine='diamonds'),
            'G2': dict(seven='hearts', eight='diamonds', nine='clubs', two='spades'),
            'G3': dict(seven='hearts', eight='hearts', nine='diamonds', two='diamonds')},
 'shorthand': {'G1': {'jon@company.com': 'heads', 'jane@company.com': 'tails'},
               'G2': {'jon@company.com': 'heads', 'jane@company.com': 'tails'},
               'G3': {'jon@company.com': 'tails', 'jane@company.com': 'tails'}},
}
ok = bad = 0
for gen in ('G1', 'G2', 'G3'):
    for name, exp in V['fractional-flag'][gen].items():
        got = flagd_fractional(gen, 'fractional-flag', None, suits, explicit='fractional-flag' + name)
        ok, bad = (ok + 1, bad) if got == exp else (ok, bad + 1); print(gen, 'fractional-flag', name, exp, got, 'OK' if got == exp else 'MISMATCH')
    for name, exp in V['shared'][gen].items():
        got = flagd_fractional(gen, 'fractional-flag-A-shared-seed', None, suits, explicit='shared-seed' + name)
        ok, bad = (ok + 1, bad) if got == exp else (ok, bad + 1); print(gen, 'shared-seed', name, exp, got, 'OK' if got == exp else 'MISMATCH')
    for tk, exp in V['shorthand'][gen].items():
        got = flagd_fractional(gen, 'fractional-flag-shorthand', tk, coin)
        ok, bad = (ok + 1, bad) if got == exp else (ok, bad + 1); print(gen, 'shorthand', tk, exp, got, 'OK' if got == exp else 'MISMATCH')
# testbed hash edge vectors (MurmurHash3-x86-32 seed 0 preimages)
for k, h in [('ejOoVL', 0), ('bY9fO-', 1), ('SI7p-', 2147483647), ('6LvT0', 2147483648)]:
    got = murmur3_32(k.encode()); ok, bad = (ok + 1, bad) if got == h else (ok, bad + 1); print('murmur3', k, h, got, 'OK' if got == h else 'MISMATCH')
print('TOTAL ok=%d mismatch=%d' % (ok, bad))

# ---- Flipt vectors from flipt-io/flipt@v1.62.1 internal/server/evaluation/legacy_evaluator_test.go
#      and @v2.14.2 internal/server/evaluation/evaluation_test.go
from engines import flipt_variant, flipt_threshold_hit
fv = [
 ('server-legacy', 'foo', '123', [('boz', 10)], None),          # TestEvaluator_DistributionNotMatched -> no match
 ('server-legacy', 'foo', '1', [('boz', 50), ('booz', 50)], 'boz'),   # TestEvaluator_MatchAll_RolloutDistribution
 ('server-legacy', 'foo', '2', [('boz', 50), ('booz', 50)], 'booz'),
]
fok = fbad = 0
for eng, fk, eid, d, exp in fv:
    got = flipt_variant(eng, fk, eid, d); good = got == exp; fok += good; fbad += (not good)
    print('flipt', eng, fk, eid, d, exp, got, 'OK' if good else 'MISMATCH')
for pct, exp_hit in [(5, False), (70, True)]:   # TestBoolean_DefaultRuleFallthrough_WithPercentageRollout / TestBoolean_PercentageRuleMatch
    got = flipt_threshold_hit('test-flag', 'test-entity', pct); good = got == exp_hit; fok += good; fbad += (not good)
    print('flipt threshold', pct, exp_hit, got, 'OK' if good else 'MISMATCH')
print('FLIPT ok=%d mismatch=%d' % (fok, fbad))
