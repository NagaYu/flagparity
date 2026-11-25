"""Throwaway Phase 0 smoke helpers (NOT product code).

Re-implements, from public source only, the bucket computations of:
  flagd  G1 (<= v0.14.x, float 100-bucket, string hash)      core/pkg/evaluator/fractional.go @ b9c099cb7f
  flagd  G2 (v0.15.0 .. v0.17.x, int (h*W)>>32, string hash)  @ flagd/v0.17.1 (0c5b766d)
  flagd  G3 (>= v0.18.0, int (h*W)>>32, CBOR-encoded input)    @ flagd/v0.18.0 (ac826d8e)
  Flipt  server v1 (<= v1.62.x) and v2 < v2.9.0: no normalisation, remainder -> no match
  Flipt  server v2 >= v2.9.0 (PR #5581): normalised, int() truncation
  Flipt  Rust client engine (flipt-client-sdks@19e54652): normalised, round()
  GOFF   v1.59.1: fnv1a32(flagName+key) % (sum*1000), names sorted, iterated in reverse
"""
import math, struct, zlib

MAXI32 = 2147483647

# ---------- hashes ----------
def murmur3_32(data: bytes, seed: int = 0) -> int:
    c1, c2 = 0xcc9e2d51, 0x1b873593
    h = seed & 0xffffffff
    n = len(data) // 4
    for i in range(n):
        k = struct.unpack_from('<I', data, i * 4)[0]
        k = (k * c1) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = (k * c2) & 0xffffffff
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xffffffff
        h = (h * 5 + 0xe6546b64) & 0xffffffff
    tail = data[n * 4:]
    k = 0
    if len(tail) >= 3: k ^= tail[2] << 16
    if len(tail) >= 2: k ^= tail[1] << 8
    if len(tail) >= 1:
        k ^= tail[0]
        k = (k * c1) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = (k * c2) & 0xffffffff
        h ^= k
    h ^= len(data)
    h ^= h >> 16; h = (h * 0x85ebca6b) & 0xffffffff
    h ^= h >> 13; h = (h * 0xc2b2ae35) & 0xffffffff
    h ^= h >> 16
    return h

def fnv1a32(data: bytes) -> int:
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xffffffff
    return h

def crc32_ieee(data: bytes) -> int:
    return zlib.crc32(data) & 0xffffffff

# ---------- minimal deterministic CBOR (RFC 8949 4.2.1) for str / int / bool / list / dict ----------
def _head(major, n):
    if n < 24: return bytes([major << 5 | n])
    if n < 256: return bytes([major << 5 | 24, n])
    if n < 65536: return bytes([major << 5 | 25]) + struct.pack('>H', n)
    if n < 2**32: return bytes([major << 5 | 26]) + struct.pack('>I', n)
    return bytes([major << 5 | 27]) + struct.pack('>Q', n)

def cbor(v) -> bytes:
    if isinstance(v, bool): return b'\xf5' if v else b'\xf4'
    if isinstance(v, float) and v == math.trunc(v) and -2**63 <= v < 2**64:
        v = int(v)  # ADR number normalisation
    if isinstance(v, int): return _head(0, v) if v >= 0 else _head(1, -1 - v)
    if isinstance(v, str):
        b = v.encode('utf-8'); return _head(3, len(b)) + b
    if isinstance(v, list): return _head(4, len(v)) + b''.join(cbor(x) for x in v)
    if isinstance(v, dict):
        items = sorted(((cbor(k), cbor(x)) for k, x in v.items()), key=lambda kv: kv[0])
        return _head(5, len(v)) + b''.join(k + x for k, x in items)
    raise TypeError('unsupported in smoke CBOR: %r' % type(v))

# ---------- flagd ----------
def flagd_bucket_input(gen, flag_key, targeting_key, explicit=None):
    """explicit: already-resolved bucketing value (None => default)."""
    if gen in ('G1', 'G2'):
        s = explicit if isinstance(explicit, str) else flag_key + targeting_key
        return s.encode('utf-8')
    if explicit is not None:
        return cbor(explicit)
    return cbor([flag_key, targeting_key])

def flagd_distribute(gen, h, dist):
    """dist: list of (variant, weight int)."""
    total = sum(max(0, w) for _, w in dist)
    if total == 0: return None
    if gen == 'G1':
        hv = h - 2**32 if h >= 2**31 else h  # int32
        bucket = abs(float(hv)) / MAXI32 * 100
        end = 0.0
        for v, w in dist:
            end += 100 * float(w) / float(total)
            if bucket < end: return v
        return None  # unreachable except abs(MinInt32) edge
    bucket = (h * total) >> 32
    end = 0
    for v, w in dist:
        end += max(0, w)
        if bucket < end: return v
    return None

def flagd_fractional(gen, flag_key, targeting_key, dist, explicit=None):
    return flagd_distribute(gen, murmur3_32(flagd_bucket_input(gen, flag_key, targeting_key, explicit)), dist)

# ---------- Flipt (variant flag, one rule's distributions) ----------
def _f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]

def flipt_variant(engine, flag_key, entity_id, dists):
    """dists: list of (variant_key, rollout float). returns variant or None (=no distribution matched)."""
    valid = [(v, r) for v, r in dists if r > 0]
    if not valid: return ('MATCH_NO_VARIANT',)
    buckets = []
    if engine == 'server-legacy':  # Flipt v1.x and v2 < 2.9.0
        for v, r in valid:
            b = int(_f32(_f32(r) * _f32(10.0)))
            buckets.append(b if not buckets else buckets[-1] + b)
    else:
        total = _f32(0.0)
        for _, r in valid: total = _f32(total + _f32(r))
        cum = _f32(0.0)
        for i, (v, r) in enumerate(valid):
            cum = _f32(cum + _f32(_f32(_f32(r) / total) * _f32(100.0)))
            x = _f32(cum * _f32(10.0))
            b = int(x) if engine == 'server-v2.9+' else int(math.floor(x + 0.5))  # Rust f32::round (half away from zero; x>=0)
            if i + 1 == len(valid): b = 1000
            buckets.append(b)
    bucket = crc32_ieee((flag_key + entity_id).encode('utf-8')) % 1000
    import bisect
    idx = bisect.bisect_left(buckets, bucket + 1)
    if idx == len(valid): return None
    return valid[idx][0]

def flipt_threshold_hit(flag_key, entity_id, percentage):
    return float(crc32_ieee((entity_id + flag_key).encode('utf-8')) % 100) < percentage

# ---------- GOFF ----------
def goff_percentage(flag_name, key, percentages):
    m = sum(percentages.values())
    maxp = int(m * 1000) & 0xffffffff
    if maxp == 0: return None
    h = fnv1a32((flag_name + key).encode('utf-8')) % maxp
    names = sorted(percentages)
    start = 0.0
    for name in reversed(names):
        end = start + percentages[name] * 1000
        if int(start) <= h < int(end): return name
        start = end
    return None
