"""Pure-Python 2D noise for terrain generation."""

from __future__ import annotations

import hashlib
import math


class SimplexNoise:
    __slots__ = ("_perm",)

    def __init__(self, seed: int = 0):
        seed_bytes = str(seed).encode("utf-8")
        perm = list(range(256))
        for i in range(255, 0, -1):
            j = int(
                hashlib.sha256(seed_bytes + bytes([i])).hexdigest(),
                16,
            ) % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]
        self._perm = perm + perm

    @staticmethod
    def _fade(t: float) -> float:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    @staticmethod
    def _grad(hash_val: int, x: float, y: float) -> float:
        h = hash_val & 7
        u = x if h < 4 else y
        v = y if h < 4 else x
        return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + t * (b - a)

    def noise2(self, x: float, y: float) -> float:
        X = int(math.floor(x)) & 255
        Y = int(math.floor(y)) & 255
        xf = x - math.floor(x)
        yf = y - math.floor(y)
        u = self._fade(xf)
        v = self._fade(yf)
        aa = self._perm[self._perm[X] + Y]
        ab = self._perm[self._perm[X] + Y + 1]
        ba = self._perm[self._perm[X + 1] + Y]
        bb = self._perm[self._perm[X + 1] + Y + 1]
        x1 = self._lerp(
            self._grad(aa, xf, yf),
            self._grad(ba, xf - 1.0, yf),
            u,
        )
        x2 = self._lerp(
            self._grad(ab, xf, yf - 1.0),
            self._grad(bb, xf - 1.0, yf - 1.0),
            u,
        )
        return self._lerp(x1, x2, v)
