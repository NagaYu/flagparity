"""Hash functions and deterministic CBOR, re-implemented from public specifications.

murmur3_32  : MurmurHash3 x86_32 (twmb/murmur3 Sum32 / StringSum32, seed 0) — used by flagd.
fnv1a32     : FNV-1a 32-bit (Go hash/fnv New32a) — used by GO Feature Flag.
crc32_ieee  : CRC-32 IEEE (Go hash/crc32 ChecksumIEEE, Rust crc32fast) — used by Flipt.
cbor_core   : RFC 8949 §4.2.1 core deterministic encoding as configured by fxamacker/cbor
              CoreDetEncOptions, after flagd's normalizeValue (flagd >= v0.18.0).
"""
import math
import struct
import zlib


def murmur3_32(data: bytes, seed: int = 0) -> int:
    c1, c2 = 0xCC9E2D51, 0x1B873593
    h = seed & 0xFFFFFFFF
    n = len(data) // 4
    for i in range(n):
        k = struct.unpack_from("<I", data, i * 4)[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xE6546B64) & 0xFFFFFFFF
    tail = data[n * 4:]
    k = 0
    if len(tail) >= 3:
        k ^= tail[2] << 16
    if len(tail) >= 2:
        k ^= tail[1] << 8
    if len(tail) >= 1:
        k ^= tail[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def fnv1a32(data: bytes) -> int:
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def crc32_ieee(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


class CBORUnsupported(Exception):
    pass


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    if n < 256:
        return bytes([major << 5 | 24, n])
    if n < 65536:
        return bytes([major << 5 | 25]) + struct.pack(">H", n)
    if n < 2 ** 32:
        return bytes([major << 5 | 26]) + struct.pack(">I", n)
    return bytes([major << 5 | 27]) + struct.pack(">Q", n)


def _float_shortest(v: float) -> bytes:
    """fxamacker CoreDetEncOptions: ShortestFloat16 — smallest of f16/f32/f64 that round-trips."""
    if math.isnan(v):
        return b"\xf9\x7e\x00"
    try:
        h = struct.pack(">e", v)
        if struct.unpack(">e", h)[0] == v:
            return b"\xf9" + h
    except (OverflowError, struct.error):
        pass
    try:
        f = struct.pack(">f", v)
        if struct.unpack(">f", f)[0] == v:
            return b"\xfa" + f
    except (OverflowError, struct.error):
        pass
    return b"\xfb" + struct.pack(">d", v)


def flagd_normalize(v):
    """flagd v0.18.0 fractional.go normalizeValue: integral floats become (u)int64."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return v
        if v == math.trunc(v):
            if 0 <= v < 2.0 ** 64:
                return int(v)
            if -(2.0 ** 63) <= v < 0:
                return int(v)
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, list):
        return [flagd_normalize(x) for x in v]
    if isinstance(v, dict):
        return {k: flagd_normalize(x) for k, x in v.items()}
    raise CBORUnsupported(type(v).__name__)


def cbor_core(v) -> bytes:
    if v is None:
        return b"\xf6"
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        if v >= 0:
            if v >= 2 ** 64:
                raise CBORUnsupported("int overflow")
            return _head(0, v)
        return _head(1, -1 - v)
    if isinstance(v, float):
        return _float_shortest(v)
    if isinstance(v, str):
        b = v.encode("utf-8")
        return _head(3, len(b)) + b
    if isinstance(v, list):
        return _head(4, len(v)) + b"".join(cbor_core(x) for x in v)
    if isinstance(v, dict):
        # Core deterministic: keys sorted by their encoded bytes (bytewise lexicographic).
        items = sorted(((cbor_core(k), cbor_core(x)) for k, x in v.items()), key=lambda kv: kv[0])
        return _head(5, len(v)) + b"".join(k + x for k, x in items)
    raise CBORUnsupported(type(v).__name__)


def f32(x: float) -> float:
    """Round a Python float to IEEE-754 binary32 (Go float32 / Rust f32 arithmetic)."""
    return struct.unpack("f", struct.pack("f", x))[0]
