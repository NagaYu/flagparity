"""Independent oracle for F4 expected semantics pairs: the Phase 0 smoke code (smoke/lib/engines.py,
smoke/f4_flagd_smoke.py), written before the Phase 1 core and checked against flagd-testbed and Flipt
tests in Phase 0. It is used ONLY to label bench cases, never by the verifier.

Coverage limits (inherited from the Phase 0 smoke parser): flagd fractionals with literal string variants
and integer weights, bucketing by default / var / cat; Flipt variant-rule distributions; GOFF percentages
(v1.32+ from engines.goff_percentage; pre-v1.32 = "sum must be exactly 100 else every context errors",
read from v1.31.2 rule.go getPercentageBuckets).
"""
import io
import itertools
import json
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "smoke", "lib"))
sys.path.insert(0, os.path.join(ROOT, "smoke"))
import engines  # noqa: E402
import f4_flagd_smoke  # noqa: E402

KEYS = ["user-%04d" % i for i in range(1000)]
FLAGD = {"G1": "flagd/G1", "G2": "flagd/G2", "G3": "flagd/G3"}


def flagd_pairs(path, flag):
    """Union over the flag's fractionals of semantics pairs with >= 1 flip; None if the oracle cannot judge."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        f4_flagd_smoke.main(path)
    rep = json.loads(buf.getvalue())
    ents = [e for e in rep["flags"] if e["flag"] == flag]
    if not ents or any(e["verdict"] != "judged" for e in ents):
        return None
    pairs = set()
    for e in ents:
        if e["flips_G1_vs_G2"]:
            pairs.add("flagd/G1 ~ flagd/G2")
        if e["flips_G1_vs_G3"]:
            pairs.add("flagd/G1 ~ flagd/G3")
        if e["flips_G2_vs_G3"]:
            pairs.add("flagd/G2 ~ flagd/G3")
    return sorted(pairs)


FLIPT = {"server-legacy": "flipt/server-legacy", "server-v2.9+": "flipt/server-v2.9+", "rust-client": "flipt/rust-client"}


def flipt_pairs(flag_key, rules_dists):
    """rules_dists: list of [(variant, rollout)] per rule (rules whose segment can match)."""
    pairs = set()
    for d in rules_dists:
        res = {e: [engines.flipt_variant(e, flag_key, k, d) for k in KEYS] for e in FLIPT}
        for a, b in itertools.combinations(FLIPT, 2):
            if any(x != y for x, y in zip(res[a], res[b])):
                pairs.add(" ~ ".join(sorted([FLIPT[a], FLIPT[b]], key=lambda s: ["flipt/server-legacy", "flipt/server-v2.9+", "flipt/rust-client"].index(s))))
    return sorted(pairs)


def goff_pairs(flag_name, pct_list):
    pairs = set()
    for pct in pct_list:
        post = [engines.goff_percentage(flag_name, k, pct) for k in KEYS]
        pre_ok = abs(sum(pct.values()) - 100) < 1e-9
        pre = post if pre_ok else [None] * len(KEYS)
        if any(x != y for x, y in zip(pre, post)):
            pairs.add("goff/pre-v1.32 ~ goff/v1.32+")
    return sorted(pairs)
