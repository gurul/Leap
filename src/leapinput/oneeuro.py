"""1€ filter — adaptive smoothing that beats a fixed EMA on both axes at once.

An EMA forces one choice for two conflicting needs: heavy smoothing kills jitter
when the hand is still but adds lag when it moves; light smoothing tracks motion but
lets a resting hand shiver. The 1€ filter varies its cutoff with speed, so it is
heavy when slow and light when fast.

Vendored rather than depended on. PyPI `OneEuroFilter==0.2.1` has two defects we
would have to work around anyway: a falsy-`0.0` timestamp silently skips the
frequency update, and `reset()` does not restore the constructor frequency. It is
~40 lines of BSD-3 maths (Casiez, Roussel & Vogel, CHI 2012); carrying a dependency
we patch twice is worse than owning it.
"""

from __future__ import annotations

import math
from typing import Optional


class _LowPass:
    def __init__(self) -> None:
        self.value: Optional[float] = None

    def __call__(self, x: float, alpha: float) -> float:
        self.value = x if self.value is None else alpha * x + (1.0 - alpha) * self.value
        return self.value


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    """Scalar 1€ filter.

    min_cutoff lowers the floor: smaller = smoother when still, more lag.
    beta raises the cutoff with speed: larger = less lag when moving fast.
    Tune min_cutoff first with beta at 0, then raise beta until a fast move
    stops lagging.
    """

    def __init__(self, freq: float = 110.0, min_cutoff: float = 1.0,
                 beta: float = 0.007, d_cutoff: float = 1.0) -> None:
        if freq <= 0 or min_cutoff <= 0 or d_cutoff <= 0:
            raise ValueError("freq, min_cutoff and d_cutoff must be positive")
        self.freq, self.min_cutoff = freq, min_cutoff
        self.beta, self.d_cutoff = beta, d_cutoff
        self._x, self._dx = _LowPass(), _LowPass()
        self._last_t: Optional[float] = None

    def reset(self) -> None:
        self._x, self._dx = _LowPass(), _LowPass()
        self._last_t = None

    def __call__(self, x: float, t: Optional[float] = None) -> float:
        # `is not None`, not truthiness: a timestamp of exactly 0.0 is a real time,
        # and treating it as missing is one of the upstream package's two bugs.
        if t is not None and self._last_t is not None:
            dt = t - self._last_t
            if dt > 0:
                self.freq = 1.0 / dt
        if t is not None:
            self._last_t = t

        prev = self._x.value
        dx = 0.0 if prev is None else (x - prev) * self.freq
        edx = self._dx(dx, _alpha(self.d_cutoff, 1.0 / self.freq))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x(x, _alpha(cutoff, 1.0 / self.freq))


class OneEuroVec3:
    """Three independent 1€ filters sharing tuning. Upstream is scalar-only."""

    def __init__(self, **kw) -> None:
        self.x, self.y, self.z = OneEuro(**kw), OneEuro(**kw), OneEuro(**kw)

    def reset(self) -> None:
        for f in (self.x, self.y, self.z):
            f.reset()

    def __call__(self, x: float, y: float, z: float,
                 t: Optional[float] = None) -> tuple[float, float, float]:
        return self.x(x, t), self.y(y, t), self.z(z, t)
