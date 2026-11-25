"""GO Feature Flag percentage-bucketing semantics. v1.32+ is checked against GOFF's own unit tests (owner decision
P1-Z-6); pre-v1.32 has no vectors and stays source-only.

goff/pre-v1.32 : v1.31.2 internal/flag/rule.go + internal_flag.go. hash = fnv1a32(flagName+key) % 100000;
                 buckets over reverse-sorted variation names, percentage*1000 each; if the buckets do not
                 end exactly at 100000 the rule errors ("percentage are not representing 100%") and the
                 SDK default is served.
goff/v1.32+    : v1.59.1 modules/core/flag/rule.go + utils/hash.go (PR #2136, v1.32.0, 2024-07-25).
                 maxPercentage = uint32(sum*1000); hash = fnv1a32(flagName+key) % maxPercentage;
                 same reverse-sorted buckets — sums != 100 are silently normalised.
"""
from ..hashing import fnv1a32
from .base import Semantics, register

MULT = 1000.0


class _GoffBase:
    def percentage(self, flag_name, key, percentages):
        """percentages: dict name->float. Returns variation name, or None (= rule error, SDK default)."""
        raise NotImplementedError

    @staticmethod
    def _pick(h, percentages):
        start = 0.0
        for name in sorted(percentages, reverse=True):
            end = start + percentages[name] * MULT
            if int(start) <= h < int(end):
                return name
            start = end
        return None


class GoffPre132(_GoffBase):
    def percentage(self, flag_name, key, percentages):
        if not percentages:
            return None
        end = 0.0
        for name in sorted(percentages, reverse=True):
            end = end + percentages[name] * MULT
        if end != 100000.0:
            return None
        h = fnv1a32((flag_name + key).encode("utf-8")) % 100000
        return self._pick(h, percentages)


class GoffV132(_GoffBase):
    def percentage(self, flag_name, key, percentages):
        if not percentages:
            return None
        m = 0.0
        for p in percentages.values():
            m += p
        maxp = int(m * MULT) & 0xFFFFFFFF
        if maxp == 0:
            h = 0
        else:
            h = fnv1a32((flag_name + key).encode("utf-8")) % maxp
        return self._pick(h, percentages)


SRC = "https://github.com/thomaspoignant/go-feature-flag/blob/%s/%s"
register(Semantics(
    id="goff/pre-v1.32", format="goff", label="GO Feature Flag v1.0.0-v1.31.x (sum must be 100)", order=1,
    kind="version", sources=(SRC % ("v1.31.2", "internal/flag/rule.go"), SRC % ("v1.31.2", "internal/flag/internal_flag.go")),
    vector_suites=(), vectors_declared_official=False, impl=GoffPre132()))
register(Semantics(
    id="goff/v1.32+", format="goff", label="GO Feature Flag >= v1.32.0 (silent normalisation)", order=2,
    kind="version", sources=(SRC % ("v1.59.1", "modules/core/flag/rule.go"), SRC % ("v1.59.1", "modules/core/utils/hash.go"),
                             "https://github.com/thomaspoignant/go-feature-flag/pull/2136"),
    vector_suites=("goff-unit@v1.59.1", "goff-rules@e9704fa7"), vectors_declared_official=True,  # DECISIONS P1-Z-6
    impl=GoffV132()))
