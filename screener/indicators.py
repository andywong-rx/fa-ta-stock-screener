"""Causal indicators: no centered windows, future shifts, or backfilling."""
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class Definitions:
    trend_window: int = 20
    relative_window: int = 63
    volume_window: int = 20
    breakout_window: int = 20
    obv_window: int = 10


def calculate(bars, benchmark, definitions=Definitions()):
    d = bars.sort_index().copy()
    if d.index.has_duplicates:
        raise ValueError('Duplicate bar timestamps')
    d = d.replace([np.inf, -np.inf], np.nan)
    c, v = d.Close, d.Volume
    d['SMA50'] = c.rolling(50).mean()
    d['SMA200'] = c.rolling(200).mean()
    delta = c.diff()
    # Wilder smoothing, seeded with the first 14 valid changes.
    def wilder(s):
        out = pd.Series(np.nan, index=s.index)
        if len(s) > 14:
            out.iloc[14] = s.iloc[1:15].mean() if s.iloc[1:15].notna().all() else np.nan
            for i in range(15, len(s)):
                out.iloc[i] = (out.iloc[i-1]*13+s.iloc[i])/14
        return out
    gain, loss = wilder(delta.clip(lower=0)), wilder(-delta.clip(upper=0))
    d['RSI(14)'] = 100 - 100/(1+gain/loss)
    d.loc[(gain == 0) & (loss == 0), 'RSI(14)'] = 50
    fast = c.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = c.ewm(span=26, adjust=False, min_periods=26).mean()
    d['MACD'] = (fast-slow).where(c.notna())
    d['Signal'] = d.MACD.ewm(span=9, adjust=False, min_periods=9).mean().where(d.MACD.notna())
    n = definitions.relative_window
    spy = benchmark.Close.reindex(d.index)
    d['Relative vs SPY'] = c.pct_change(n, fill_method=None)-spy.pct_change(n, fill_method=None)
    d['RVOL'] = v / v.shift(1).rolling(definitions.volume_window).mean().replace(0,np.nan)
    d['Previous high'] = d.High.shift(1).rolling(definitions.breakout_window).max()
    signed = np.sign(c.diff()) * v
    signed.iloc[0] = 0 if pd.notna(v.iloc[0]) else np.nan
    d['OBV'] = signed.cumsum(skipna=False)
    d['OBV SMA'] = d.OBV.rolling(definitions.obv_window).mean()
    def compare(a,b):
        return (a > b).astype(float).where(a.notna() & b.notna())
    for name,a,b in [('Price > SMA50',c,d.SMA50),('Price > SMA200',c,d.SMA200),
                     ('SMA50 > SMA200',d.SMA50,d.SMA200),('MACD > signal',d.MACD,d.Signal),
                     ('Close > previous high',c,d['Previous high']),('Rising OBV',d.OBV,d['OBV SMA'])]:
        d[name] = compare(a,b)
    w = definitions.trend_window
    hi, lo = d.High.rolling(w).max(), d.Low.rolling(w).min()
    # Last completed/current window vs preceding nonoverlapping window.
    d['Higher highs / higher lows'] = ((hi > hi.shift(w)) & (lo > lo.shift(w))).astype(float).where(hi.notna() & lo.notna() & hi.shift(w).notna() & lo.shift(w).notna())
    return d
