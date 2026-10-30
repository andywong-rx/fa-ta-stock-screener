# Signal Studio — DEMO US Stock Screener V1

Python 3.12 + Streamlit. **All data, prices, financial metrics, SPY benchmark history and signals are deterministic synthetic DEMO values. Nothing is live or an actual company's financial result.** The fixed snapshot is 2026-10-29 20:00 UTC; fundamental snapshot is 2026-09-30 UTC. Evaluation time is displayed separately. Symbols DEMO01–DEMO12 are fictional. No brokerage, trading or order execution.

## Run locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Working features

- Four independently editable session presets: Quality Growth + Established Uptrend; Growth + Breakout; Strong Fundamentals + Awaiting Uptrend; Original Strict 19-Filter Strategy.
- Nine fundamental and ten technical criteria. Each can be enabled/disabled, mandatory/score-only, and assigned an operator and threshold/range.
- Original Strict defaults: revenue/EPS growth ≥50%, gross margin ≥50%, ROIC ≥12%, P/E ≤30, forward P/E ≤20, FCF >0, debt/equity ≤1, share growth ≤5%; price>SMA50, price>SMA200, SMA50>SMA200, higher highs and lows, RSI14 inclusive 50–70, MACD12/26/9>signal, 63-session return minus SPY return >0, RVOL≥1.5, close>previous 20-session maximum High, OBV>10-session OBV SMA. All 19 enabled and mandatory. Edited versions are explicitly CUSTOM.
- Separate FA/TA scores and adjustable 60/40 default weighting. Fully qualified, FA-only, TA-only, neither and unknown classifications.
- Ranked table, classification filter, per-stock pass/fail/unknown details, candlesticks, SMA50/200, RSI, MACD histogram and volume; responsive Streamlit layout and interactive Plotly charts.
- Session watchlist and watchlist-only filter; DEMO-labeled results, watchlist and detail CSV exports. Result exports include rules, weights, calculation windows and source timestamps.
- Configurable causal calculation windows; deterministic provider; automated engine and Streamlit interaction tests; GitHub Actions Python 3.12 workflow.

## Scoring and missing data

Enabled rules have equal weight within each group. Score = passing / enabled ×100. Unknown values earn no credit and remain in the denominator. Disabled rules are excluded. Combined score = FA×weight + TA×(1−weight). An empty group has no score and yields unknown, rather than vacuously passing.

All enabled mandatory rules must pass for group qualification; score-only rules only affect scores. If a group has no mandatory rules, all enabled score-only rules determine its qualification. A known mandatory failure makes the group fail even if another mandatory rule is unknown. Otherwise a missing mandatory value makes it unknown. Any unknown group produces overall unknown; the remaining combinations yield the other four classifications. A high score cannot override a mandatory failure. DEMO12 deliberately lacks ROIC and latest volume.

## Definitions and data contract

Fundamentals use percentage points: 50 means 50%, not 0.5. Defaults are latest fiscal-year revenue and diluted EPS growth vs prior year; gross margin = gross profit/revenue; ROIC = NOPAT/average invested capital; P/E = price/TTM diluted EPS; forward P/E = price/next fiscal-year estimated EPS; FCF = operating cash flow minus capital expenditure in USD; debt/equity = total debt/book equity; share growth = annual diluted weighted-average shares growth. The synthetic provider supplies these metrics directly, not simulated financial statements. Future providers must return unknown for undefined ratios, nonpositive EPS growth bases, nonpositive valuation denominators, or unavailable inputs. Changing fundamental accounting bases requires a new provider implementation; UI definition controls currently cover technical lookbacks.

Higher highs/lows uses maximum High and minimum Low of the latest 20 sessions vs the preceding nonoverlapping 20 sessions; no future-confirmed pivots. RVOL divides current volume by the mean of the **preceding** 20 sessions. Breakout uses preceding 20 High values, excluding today. Relative strength is 63-session stock return minus aligned benchmark return. RSI14 uses Wilder's initial 14-change mean then recursive smoothing; flat price yields 50. MACD uses adjust=False EMAs with warmup periods. OBV starts at zero and accumulates signed volume; a missing observation propagates unknown. SMA and OBV SMA require full windows. No centered windows, negative shifts, backfill or return forward-fill. Indicators use current completed session and past data only. Synthetic sessions are business weekdays, not a US exchange calendar.

`DataProvider` in `screener/providers.py` defines `symbols()` and `snapshot(symbol)`. `Snapshot` contains sorted unique OHLCV bars, fundamental metric mapping, price/fundamental UTC timestamps, and source. A future adapter must deliver aligned, adjusted, point-in-time bars and fundamentals known at the snapshot, enforce availability timestamps, supply a real US exchange calendar, handle corporate actions and validate vendor accounting definitions. It must never replace missing vendor data with demo values. V1 never calls a market-data API and has no credentials.

## Tests

```bash
python -m pytest -q
```

Tests cover the strict 19-rule contract, thresholds, classifications, missing mandatory metrics, score-only and disabled rules, deterministic data, warmups, causal prefix equivalence, previous-session windows, RSI and dashboard preset/watchlist interactions.

## Deploy on Streamlit Community Cloud

1. Push these files to your GitHub repository (including `app.py`, `requirements.txt`, `screener/` and `.streamlit/config.toml`).
2. Sign in at https://share.streamlit.io and choose **Create app**.
3. Select the repository and branch; set **Main file path** to `app.py`.
4. Under advanced settings choose **Python 3.12**, then deploy. No secrets are required.
5. Check build logs, confirm the DEMO banner, switch presets, open stock details and download a CSV.

Do not commit `.env` files or `.streamlit/secrets.toml`; both are ignored. Future credentials belong in Streamlit Cloud Secrets. Watchlist and rule edits are per-session and reset with a new session; export CSVs to keep a record.

## Pending / intentionally outside V1

Real market/fundamental adapters, actual SPY data, exchange-calendar integration, accounting-basis selectors, durable user accounts/watchlists, backtesting and live signal validation are not implemented. Streamlit Community Cloud hosting requires selecting the repository in the user's Cloud account. No brokerage features are planned for this version.
