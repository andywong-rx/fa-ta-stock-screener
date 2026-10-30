"""Explicit-refresh providers; REAL never falls back to DEMO."""
from datetime import datetime, timezone
from typing import Protocol
import json
import re
import threading
import time
import urllib.error
import urllib.request
import pandas as pd
from .sec import extract, trailing_eps
from .cache import Cache
from .config import valid_user_agent
from .validation import InvalidSECResponse, validate_company, validate_tickers
import numpy as np

UNIVERSE='NVDA AMD AVGO VRT ONDS AAPL MSFT GOOGL AMZN META TSLA INTC MRVL ONTO PLTR ANET MU TSM AMAT LRCX QCOM CRM ORCL PANW CRWD'.split()

def symbols(text):
    result=list(dict.fromkeys(s.upper() for s in re.split(r'[\s,]+',text.strip()) if s))
    if not 1<=len(result)<=50 or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}',s) for s in result):
        raise ValueError('Enter 1–50 unique ticker symbols (letters, digits, dot or hyphen).')
    return result

class SEC:
    _lock=threading.Lock()
    _last=0.0
    def __init__(self,cache,user_agent):
        if not valid_user_agent(user_agent):
            raise ValueError('SEC identity configuration is missing or invalid.')
        self.cache,self.ua=cache,user_agent
    def get(self,url,ttl=86400):
        match = re.search(r'/CIK(\d{10})\.json$', url)
        validator = validate_tickers if url.endswith('company_tickers.json') else lambda data: validate_company(data, int(match[1]) if match else None)
        hit=self.cache.get(url,ttl,validator=validator)
        if hit: return hit[1]
        for attempt in range(4):
            try:
                with SEC._lock:
                    time.sleep(max(0,.25-(time.monotonic()-SEC._last)))
                    SEC._last=time.monotonic()
                    req=urllib.request.Request(url,headers={'User-Agent':self.ua,'Accept':'application/json'})
                    with urllib.request.urlopen(req,timeout=30) as response:
                        try:
                            data=json.load(response)
                        except (ValueError, UnicodeError):
                            raise InvalidSECResponse() from None
                validator(data)
                self.cache.put(url,data)
                return data
            except urllib.error.HTTPError as exc:
                if exc.code not in (429,500,502,503,504) or attempt==3: raise
                delay=min(60,max(2**attempt,float(exc.headers.get('Retry-After',0)) if str(exc.headers.get('Retry-After','')).isdigit() else 0))
            except (urllib.error.URLError,TimeoutError):
                if attempt==3: raise
                delay=2**attempt
            time.sleep(delay)
    def facts(self,symbol):
        tickers=self.get('https://www.sec.gov/files/company_tickers.json',604800)
        validate_tickers(tickers)
        target=symbol.replace('.','-')
        cik=next((f['cik_str'] for f in tickers.values() if f['ticker'].upper()==target),None)
        if cik is None: raise ValueError('No SEC ticker-to-CIK mapping (foreign issuers may lack US-GAAP facts)')
        url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010}.json'
        data=self.get(url)
        validate_company(data, int(cik))
        return data,url

class OHLCVProvider(Protocol):
    source: str
    def daily(self,symbol:str)->pd.DataFrame: ...

class YahooDaily:
    source='Yahoo Finance via yfinance · personal research only'
    def daily(self,symbol):
        import yfinance as yf
        time.sleep(.6)
        d=yf.Ticker(symbol.replace('.','-')).history(period='2y',interval='1d',auto_adjust=False,back_adjust=False,actions=True,raise_errors=True)
        if d.empty: raise ValueError('No daily OHLCV returned')
        # Drop the entire current NY calendar date, including after close: conservative completed candles.
        now=pd.Timestamp.now(tz='America/New_York').date()
        d.index=pd.DatetimeIndex([pd.Timestamp(x).date() for x in d.index])
        d=d.loc[d.index.date<now].sort_index()
        if d.index.has_duplicates or d.empty: raise ValueError('Invalid daily timestamps')
        cols=['Open','High','Low','Close','Volume']
        if any(c not in d for c in cols): raise ValueError('Incomplete OHLCV schema')
        if not np.isfinite(d[cols].to_numpy(dtype=float)).all() or (d[cols[:4]]<=0).any().any() or (d.Volume<0).any(): raise ValueError('Invalid or missing OHLCV')
        if ((d.High<d[['Open','Close','Low']].max(axis=1)) | (d.Low>d[['Open','Close','High']].min(axis=1))).any(): raise ValueError('Inconsistent OHLCV')
        # Yahoo historical OHLC is split adjusted, not dividend adjusted; Volume follows Yahoo convention.
        return d

def validate_bars(d):
    cols=['Open','High','Low','Close','Volume']
    if not isinstance(d, pd.DataFrame) or d.empty or any(c not in d for c in cols):
        raise ValueError('Invalid OHLCV response')
    if not isinstance(d.index, pd.DatetimeIndex) or d.index.hasnans or d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError('Invalid OHLCV timestamps')
    if d.index.tz is not None or not (d.index == d.index.normalize()).all():
        raise ValueError('OHLCV must use daily dates')
    if not np.isfinite(d[cols].to_numpy(dtype=float)).all() or (d[cols[:4]]<=0).any().any() or (d.Volume<0).any():
        raise ValueError('Invalid OHLCV values')
    if ((d.High<d[['Open','Close','Low']].max(axis=1)) | (d.Low>d[['Open','Close','High']].min(axis=1))).any():
        raise ValueError('Inconsistent OHLCV values')

def validate_price_record(data):
    if not isinstance(data,dict) or not isinstance(data.get('source'),str) or not isinstance(data.get('bars'),list):
        raise ValueError('Invalid cached prices')
    validate_bars(decode_bars(data['bars']))

def validate_fact_record(data):
    if not isinstance(data,dict) or not isinstance(data.get('source'),str):
        raise InvalidSECResponse()
    validate_company(data.get('facts'))

def encode_bars(d):
    validate_bars(d)
    return json.loads(d.reset_index(names='Date').to_json(orient='records',date_format='iso'))

def decode_bars(data):
    d=pd.DataFrame(data)
    if d.empty: return pd.DataFrame(columns=['Open','High','Low','Close','Volume'])
    d['Date']=pd.to_datetime(d.Date)
    return d.set_index('Date')

def refresh(universe,ua,cache,prices=None):
    prices=prices or YahooDaily()
    sec=SEC(cache,ua) if valid_user_agent(ua) else None
    report={}
    # Sequential symbol batches, shared SPY and independent provider failures.
    for symbol in list(dict.fromkeys(['SPY']+universe)):
        status={}
        price_key='prices:'+symbol
        try:
            hit=cache.get(price_key,21600,validator=validate_price_record)
            if not hit:
                bars=prices.daily(symbol)
                cache.put(price_key,{'bars':encode_bars(bars),'source':prices.source})
            status['price']='cached' if hit else 'refreshed'
        except Exception: status['price']='FAILED: daily prices unavailable; last valid data retained where possible'
        if symbol!='SPY' and sec is None:
            status['fundamentals']='UNAVAILABLE: SEC identity is not configured'
        elif symbol!='SPY':
            try:
                facts,url=sec.facts(symbol)
                validate_company(facts)
                # Keep independent successful refresh times and raw provenance; no fabricated fields.
                source_time=cache.get(url)
                body={'facts':facts,'source':url}
                cache.put('facts:'+symbol,body,updated=source_time[0] if source_time else None)
                status['fundamentals']='valid SEC response (≤24h cache); unsupported metrics remain UNKNOWN'
            except Exception: status['fundamentals']='FAILED: SEC data unavailable or invalid; last valid data retained where possible'
        report[symbol]=status
    cache.put('status',report)
    return report

def snapshot(cache,symbol):
    price=cache.get('prices:'+symbol,validator=validate_price_record)
    fact=cache.get('facts:'+symbol,validator=validate_fact_record)
    bars=decode_bars(price[1]['bars']) if price else decode_bars([])
    try:
        values,provenance,anchor=extract(fact[1]['facts']) if fact else ({}, {}, None)
    except Exception:
        cache._note('Cached fundamentals could not be calculated. Values remain UNKNOWN; refresh is required.')
        values,provenance,anchor={}, {}, None
        fact=None
    pe_reason='Missing price, SEC EPS or incompatible periods'
    if fact and not bars.empty:
        cutoff=bars.index[-1].date().isoformat()
        # Fundamentals filed after the price candle are excluded from price/EPS calculation.
        try:
            eps,eps_facts=trailing_eps(fact[1]['facts'],cutoff)
        except Exception:
            eps,eps_facts=None,[]
            cache._note('Trailing EPS is unavailable. P/E remains UNKNOWN.')
        start=min((f['start'] for f in eps_facts),default=cutoff)
        split=bars.loc[bars.index>=pd.Timestamp(start),'Stock Splits'] if 'Stock Splits' in bars else pd.Series(dtype=float)
        # Do not guess how historical EPS was restated for a split.
        safe=not split.ne(0).any()
        if eps is not None and eps>0 and safe:
            values['P/E']=float(bars.Close.iloc[-1])/eps
            provenance['trailing_eps']={'val':eps,'facts':eps_facts,'price_date':cutoff}
            pe_reason='Trailing reported diluted EPS; annual + comparable YTD bridge (rounding approximation)'
        elif not safe: pe_reason='UNKNOWN: split in EPS lookback; split restatement not reconciled'
    return {'bars':bars,'values':values,'provenance':provenance,'period':anchor['end'] if anchor else 'UNKNOWN',
        'pe_note':pe_reason,'price_refresh':datetime.fromtimestamp(price[0],timezone.utc).isoformat() if price else 'Never',
        'fundamentals_refresh':datetime.fromtimestamp(fact[0],timezone.utc).isoformat() if fact else 'Never',
        'fundamental_source':fact[1]['source'] if fact else 'UNKNOWN',
        'price_source':price[1]['source'] if price else 'UNKNOWN'}
