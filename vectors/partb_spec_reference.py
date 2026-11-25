"""Part B: run the Go reference implementation printed on the official flagd
'Fractional Operation Specification' page (docs/reference/specifications/custom-operations/
fractional-operation-spec.md @ flagd/v0.19.0) against the flagd-testbed fractional vectors.

The printed code does not compile as written (`value` is undefined, `values[i]` indexes an interface{},
`feDistribution` vs `feDistributions`). We apply only the identifier fixes needed to give it a meaning
(value -> valueToDistribute, values[i] -> valuesArray[i], feDistribution -> feDistributions) and keep
its semantics: explicit string bucketing value required (no targetingKey default), float hash ratio
bucket int(|int32(h)| / MaxInt32 * 100), and Go integer division (dist.weight / sumOfWeights) * 100.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from flagparity.hashing import murmur3_32  # noqa: E402
from flagparity.semantics.base import Semantics  # noqa: E402

MAXI32 = 2147483647


class SpecPageReference:
    def fractional(self, values, data):
        if not isinstance(values, list) or len(values) < 2:
            return None
        if not isinstance(values[0], str):
            return None
        value = values[0]
        total = 0
        dists = []
        for d in values[1:]:
            if not isinstance(d, list) or not d or not isinstance(d[0], str):
                return None
            w = 1.0
            if len(d) >= 2 and isinstance(d[1], (int, float)) and not isinstance(d[1], bool):
                w = float(d[1])
            total += int(w)
            dists.append((d[0], int(w)))
        h = murmur3_32(value.encode("utf-8"))
        hv = h - 2 ** 32 if h >= 2 ** 31 else h
        bucket = int(abs(float(hv)) / MAXI32 * 100)
        end = 0
        for v, w in dists:
            end += (w // total) * 100 if total else 0  # Go int division
            if bucket < end:
                return v
        return None


def main():
    import flagd_testbed as T
    out = {}
    for gen in ("G1", "G2", "G3"):
        sem = Semantics(id="flagd/" + gen, format="flagd", label="spec page reference code",
                        order=99, kind="doc", sources=(), impl=SpecPageReference())
        r = T.run(sem)
        frac = [f for f in r["failures"] if "ractional" in f["scenario"]]
        out["vs testbed rule for " + gen] = {"applicable": r["applicable"], "pass": r["pass"], "fail": r["fail"],
                                            "fractional_failures": len(frac), "non_fractional_failures": r["fail"] - len(frac)}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(main(), indent=1))
