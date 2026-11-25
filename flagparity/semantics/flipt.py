"""Flipt evaluation semantics: two server generations and the Rust client engine.

server-legacy : Flipt v1.x (<= v1.62.1) and v2 < v2.9.0. Distribution buckets int(float32(rollout)*10),
                cumulative, NOT normalised; bucket beyond the last edge => no match (no later rule).
                flipt-io/flipt@v1.62.1 internal/server/evaluation/legacy_evaluator.go
server-v2.9+  : Flipt v2 >= v2.9.0 (PR #5581). Normalised float32 cumulative, int() truncation,
                last edge forced to 1000. flipt-io/flipt@v2.14.2 internal/server/evaluation/evaluation.go
rust-client   : flipt-client-sdks@19e54652 flipt-evaluation/src/lib.rs. Normalised, .round(),
                last edge 1000; constraint matching dialect differs (no whitespace trim, i32 numbers,
                RFC3339-only datetimes).
All three: variant bucket = crc32(flagKey+entityId) % 1000; boolean threshold = crc32(entityId+flagKey) % 100.
"""
import bisect
import math

from ..hashing import crc32_ieee, f32
from .base import Semantics, register


class _FliptBase:
    constraint_dialect = "go"

    def edges(self, rollouts):
        raise NotImplementedError

    def variant_index(self, flag_key, entity_id, rollouts):
        """rollouts: list of floats for the *valid* (rollout > 0) distributions, in order.
        Returns index into that list, or None (no distribution matched)."""
        if not rollouts:
            return None
        edges = self.edges(rollouts)
        bucket = crc32_ieee((flag_key + entity_id).encode("utf-8")) % 1000
        return self.index_for_bucket(edges, bucket, len(rollouts))

    @staticmethod
    def index_for_bucket(edges, bucket, n):
        idx = bisect.bisect_left(sorted(edges), bucket + 1)
        return None if idx >= n else idx

    @staticmethod
    def threshold_hit(flag_key, entity_id, percentage):
        return float(crc32_ieee((entity_id + flag_key).encode("utf-8")) % 100) < f32(float(percentage))


class FliptLegacy(_FliptBase):
    def edges(self, rollouts):
        out = []
        for r in rollouts:
            b = int(f32(f32(float(r)) * f32(10.0)))
            out.append(b if not out else out[-1] + b)
        return out


class FliptV29(_FliptBase):
    rounding = "trunc"

    def edges(self, rollouts):
        total = f32(0.0)
        for r in rollouts:
            total = f32(total + f32(float(r)))
        cum = f32(0.0)
        out = []
        for i, r in enumerate(rollouts):
            cum = f32(cum + f32(f32(f32(float(r)) / total) * f32(100.0)))
            x = f32(cum * f32(10.0))
            b = int(x) if self.rounding == "trunc" else int(math.floor(x + 0.5))
            if i + 1 == len(rollouts):
                b = 1000
            out.append(b)
        return out


class FliptRust(FliptV29):
    rounding = "round"  # f32::round: half away from zero (x >= 0 here)
    constraint_dialect = "rust"


SRC = "https://github.com/flipt-io/flipt/blob/%s/internal/server/evaluation/%s"
register(Semantics(
    id="flipt/server-legacy", format="flipt", label="Flipt server v1.x and v2 < v2.9.0 (no normalisation)",
    order=1, kind="version", sources=(SRC % ("v1.62.1", "legacy_evaluator.go"), SRC % ("v1.62.1", "evaluation.go")),
    vector_suites=("flipt-go@v1.62.1", "flipt-constraints-go@v1.62.1"), impl=FliptLegacy()))
register(Semantics(
    id="flipt/server-v2.9+", format="flipt", label="Flipt server v2 >= v2.9.0 (normalised, int())",
    order=2, kind="version", sources=(SRC % ("v2.14.2", "evaluation.go"), "https://github.com/flipt-io/flipt/pull/5581"),
    vector_suites=("flipt-go@v2.14.2", "flipt-constraints-go@v2.14.2"), impl=FliptV29()))
register(Semantics(
    id="flipt/rust-client", format="flipt", label="Flipt client-side Rust engine (normalised, round())",
    order=3, kind="engine",
    sources=("https://github.com/flipt-io/flipt-client-sdks/blob/19e546523ed82a49123b681d086fadbe07833e78/flipt-evaluation/src/lib.rs",),
    vector_suites=("flipt-rust@19e54652", "flipt-constraints-rust@19e54652"), impl=FliptRust()))
