"""Composite score: upward strength U, market strength M, penalties (plan 7)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import ScoreConfig


def lin(x: float | None, lo: float, hi: float) -> float:
    if x is None or not math.isfinite(float(x)):
        return 0.0
    if hi == lo:
        return 1.0 if float(x) >= hi else 0.0
    return max(0.0, min(1.0, (float(x) - lo) / (hi - lo)))


def tri(x: float | None, a: float, b: float, c: float, d: float) -> float:
    if x is None or not math.isfinite(float(x)):
        return 0.0
    value = float(x)
    if value <= a or value >= d:
        return 0.0
    if value < b:
        return (value - a) / (b - a) if b != a else 1.0
    if value <= c:
        return 1.0
    return (d - value) / (d - c) if d != c else 1.0


@dataclass(slots=True)
class ScoreResult:
    score: float
    grade: str
    multiplier: float
    u: float
    m: float
    p: float
    u1: float
    u2: float
    u3: float
    m1: float
    m2: float
    m3: float
    m4: float
    m5: float
    m6: float
    p_ext: float
    p_vi: float
    p_div: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "score": self.score,
            "grade": self.grade,
            "u": self.u,
            "m": self.m,
            "p": self.p,
            "u1": self.u1,
            "u2": self.u2,
            "u3": self.u3,
            "m1": self.m1,
            "m2": self.m2,
            "m3": self.m3,
            "m4": self.m4,
            "m5": self.m5,
            "m6": self.m6,
            "p_ext": self.p_ext,
            "p_vi": self.p_vi,
            "p_div": self.p_div,
        }


EMPTY_SCORE = ScoreResult(
    0.0, "C", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
)


def compute_score(
    cfg: ScoreConfig,
    *,
    close: float,
    vwap: float | None,
    sigma_eff: float | None,
    vwap_slope_atr: float | None,
    above_vwap_ratio: float | None,
    rti_3: float | None,
    accel: float | None,
    buy_ratio: float | None,
    er_tick: float | None,
    atv_ratio: float | None,
    tov: float | None,
    tov_p50: float | None,
    tov_p95: float | None,
    st_line: float | None,
    atr: float | None,
    vi_up: float | None,
    ext_value: float | None = None,
    ext_kind: str | None = None,
    feature_mode: str = "bar",
    grade_multipliers: dict[str, float] | None = None,
) -> ScoreResult:
    if not cfg.enabled:
        # Stage-1 validation (plan 8.1): no score, no grade-based sizing.
        return ScoreResult(
            0.0, "-", 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )

    z = None
    if vwap is not None and sigma_eff is not None and sigma_eff > 0:
        z = (close - vwap) / sigma_eff
    u1 = tri(z, *cfg.u1_tri)
    u2 = lin(vwap_slope_atr, *cfg.u2_lin)
    u3 = lin(above_vwap_ratio, *cfg.u3_lin)
    u = (
        cfg.u_weights[0] * u1
        + cfg.u_weights[1] * u2
        + cfg.u_weights[2] * u3
    )

    tick_mode = feature_mode == "tick"
    m1_range = cfg.m1_lin_tick if tick_mode else cfg.m1_lin
    m4_range = cfg.m4_lin_tick if tick_mode else cfg.m4_lin
    div_er = cfg.p_div_er_tick if tick_mode else cfg.p_div_er

    m1 = lin(math.log2(rti_3) if rti_3 and rti_3 > 0 else None, *m1_range)
    m2 = lin(accel, *cfg.m2_lin)
    m3 = lin(buy_ratio, *cfg.m3_lin)
    m4 = lin(er_tick, *m4_range)
    # A missing ATV/TOV feed is treated as neutral, not as "large hands".
    m5 = lin(atv_ratio, *cfg.m5_lin) if atv_ratio is not None else 0.5
    if tov is not None and tov_p50 is not None and tov_p95 is not None:
        m6 = lin(tov, tov_p50, tov_p95)
    else:
        m6 = 0.5
    m = (
        cfg.m_weights[0] * m1
        + cfg.m_weights[1] * m2
        + cfg.m_weights[2] * m3
        + cfg.m_weights[3] * m4
        + cfg.m_weights[4] * m5
        + cfg.m_weights[5] * m6
    )

    if ext_value is not None and ext_kind is not None:
        ext_range = cfg.p_ext_lin_breakout if ext_kind == "E" else cfg.p_ext_lin
        p_ext = 0.5 * lin(ext_value, *ext_range)
    else:
        d_value = None
        if st_line is not None and atr is not None and atr > 0:
            d_value = (close - st_line) / atr
        p_ext = 0.5 * lin(d_value, *cfg.p_ext_lin)
    if vi_up is not None and close > 0:
        vi_distance_pct = (vi_up - close) / close
        p_vi = 0.5 * (1.0 - lin(vi_distance_pct, *cfg.p_vi_lin))
    else:
        p_vi = 0.0
    p_div = (
        cfg.p_div_penalty
        if (rti_3 is not None and rti_3 >= cfg.p_div_rti and er_tick is not None and er_tick < div_er)
        else 0.0
    )
    p = (1.0 - p_ext) * (1.0 - p_vi) * (1.0 - p_div)

    if u < cfg.min_component or m < cfg.min_component:
        raw = 0.0
    elif cfg.mode == "geo":
        raw = 100.0 * (max(u, 0.0) ** 0.4) * (max(m, 0.0) ** 0.6) * p
    else:
        raw = 100.0 * (0.4 * u + 0.6 * m) * p
    score = max(0.0, min(100.0, raw))

    if score + 1e-9 >= cfg.grade_a:
        grade = "A"
    elif score + 1e-9 >= cfg.grade_b:
        grade = "B"
    else:
        grade = "C"
    multipliers = grade_multipliers or {"A": 1.0, "B": 0.6, "C": 0.0}
    return ScoreResult(
        score=score,
        grade=grade,
        multiplier=float(multipliers.get(grade, 0.0)),
        u=u,
        m=m,
        p=p,
        u1=u1,
        u2=u2,
        u3=u3,
        m1=m1,
        m2=m2,
        m3=m3,
        m4=m4,
        m5=m5,
        m6=m6,
        p_ext=p_ext,
        p_vi=p_vi,
        p_div=p_div,
    )
