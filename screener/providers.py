"""Provider boundary. A future real provider must deliver point-in-time snapshots."""
from dataclasses import dataclass
from typing import Protocol
import hashlib
import numpy as np
import pandas as pd

AS_OF = pd.Timestamp('2026-10-29 20:00:00', tz='UTC')
METRICS = ['Revenue Growth YoY', 'EPS Growth YoY', 'Gross Margin', 'ROIC',
           'P/E', 'Forward P/E', 'Free Cash Flow', 'Debt-to-Equity', 'Share Count Growth']

@dataclass
class Snapshot:
    symbol: str
    bars: pd.DataFrame
    fundamentals: dict
    as_of: pd.Timestamp
    fundamental_as_of: pd.Timestamp
    source: str = 'DEMO synthetic'

class DataProvider(Protocol):
    def symbols(self) -> list[str]: ...
    def snapshot(self, symbol: str) -> Snapshot: ...

class DemoProvider:
    def symbols(self):
        return [f'DEMO{i:02}' for i in range(1, 13)]

    def snapshot(self, symbol):
        if symbol not in self.symbols() + ['SPY']:
            raise ValueError('Unknown DEMO symbol')
        seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], 'big')
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range(end=AS_OF.date(), periods=320)
        # Business-day simulation, not an actual US exchange calendar.
        close = 70 * np.exp(np.cumsum(rng.normal(.001 if symbol != 'SPY' else .0004, .015, len(dates))))
        opening = close * np.exp(rng.normal(0, .004, len(dates)))
        bars = pd.DataFrame({'Open': opening, 'High': np.maximum(opening, close) * (1+rng.uniform(.002,.02,len(dates))),
            'Low': np.minimum(opening, close) * (1-rng.uniform(.002,.02,len(dates))),
            'Close': close, 'Volume': rng.integers(300000, 2500000, len(dates)).astype(float)}, index=dates)
        values = [rng.uniform(-10,90),rng.uniform(-20,100),rng.uniform(20,80),rng.uniform(3,30),
                  rng.uniform(10,60),rng.uniform(8,40),rng.uniform(-1e8,2e9),rng.uniform(.1,2),rng.uniform(-4,12)]
        fundamentals = dict(zip(METRICS, values))
        if symbol == 'DEMO12':
            fundamentals['ROIC'] = None
            bars.loc[dates[-1], 'Volume'] = np.nan
        return Snapshot(symbol, bars, fundamentals, AS_OF, pd.Timestamp('2026-09-30', tz='UTC'))
