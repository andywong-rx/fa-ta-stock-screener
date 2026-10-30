# V2A validation record

Development run: 30 October 2026. Python 3.12, pandas 2.2.3, NumPy 2.3.5, Streamlit 1.66.1, yfinance 1.7.0, pytest 8.4.2.

`python -m pytest -q`: **30 passed**. Includes original V1 suite and V2A accounting, cache/SEC HTTP mock integration, ticker mapping, provider-failure retention, split/dated P/E guards, independent scalar-loop technical references and Streamlit DEMO/empty REAL interaction tests. Tests use labeled artificial fixtures, never a REAL-mode data fallback. Causal prefix checks cover history boundaries.

Live access: SEC HTTPS request failed at the managed proxy with `Tunnel connection failed: 403 Forbidden`. The enforced destination list excludes `www.sec.gov`, `data.sec.gov` and Yahoo endpoints. No attempt was made to circumvent that policy. GitHub connector access works; direct Git transport lacks credentials, so remote changes use the GitHub connector.

**Not yet verified:** five-stock SEC filing reconciliation and live Yahoo daily-history integration. AAPL, MSFT, NVDA, AMD and AMZN are the intended validation sample; no figures are claimed verified. `scripts/validate_live.py` collects an audit packet on an appropriately configured network and exits nonzero on provider failure. A person must still compare facts/calculations to the original filing's financial statements and record accession/period/tolerance. Original filing URLs can be constructed from CIK and accession shown in provenance through SEC Archives; do not confuse Company Facts output with independent filing verification.

**Implemented real-data paths:** official SEC mapping/facts, annual financial metrics, conservative trailing EPS bridge, replaceable Yahoo daily provider, all ten causal TA calculations, refresh/cache/status reporting and existing screening/chart/export behavior. Live operation depends on reachable providers and permitted use. **Unavailable by design:** forward P/E estimates, unsupported tags/IFRS/ADR conversions, unreconciled split P/E and non-comparable or missing financial facts. ROIC, narrow debt/equity and rounded EPS bridge are documented approximations.

This is a draft personal-research pilot. No full-market coverage, unrestricted redistribution license, guaranteed availability or production readiness is asserted. Version 1's entry point and engine files are unchanged.
