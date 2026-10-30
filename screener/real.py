"""Explicit-refresh providers; REAL never falls back to DEMO."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import pandas as pd
from .sec import extract, trailing_eps

UNIVERSE='NVDA AMD AVGO VRT ONDS AAPL MSFT GOOGL AMZN META TSLA INTC MRVL ONTO PLTR ANET MU TSM AMAT LRCX QCOM CRM ORCL PANW CRWD'.split()

def symbols(text):
    result=list(dict.fromkeys(s.upper() for s in re.split(r'[\s,]+',text.strip()) if s))
    if not 1<=len(result)<=50 or any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}',s) for s in result):
        raise ValueError('Enter 1–50 unique ticker symbols (letters, digits, dot or hyphen).')
    return result

class Cache:
    def __init__(self,path=None):
        self.path=Path(path or os.environ.get('SCREENER_CACHE','.cache/v2a.sqlite'))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, updated REAL, body TEXT)')
    def get(self,key,ttl=None):
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT updated,body FROM cache WHERE key=?',(key,)).fetchone()
        return (row[0],json.loads(row[1])) if row and (ttl is None or time.time()-row[0]<ttl) else None
    def put(self,key,value,updated=None):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,time.time() if updated is None else updated,json.dumps(value,allow_nan=False)))

class SEC:
    _lock=threading.Lock()
    _last=0.0
    def __init__(self,cache,user_agent):
        if not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+',user_agent) or len(user_agent)<12:
            raise ValueError('SEC requires an honest app/operator identity and contact email; enter your own User-Agent.')
        self.cache,self.ua=cache,user_agent
    def get(self,url,ttl=86400):
        hit=self.cache.get(url,ttl)
        if hit: return hit[1]
        for attempt in range(4):
            try:
                with SEC._lock:
                    time.sleep(max(0,.25-(time.monotonic()-SEC._last)))
                    SEC._last=time.monotonic()
                    req=urllib.request.Request(url,headers={'User-Agent':self.ua,'Accept':'application/json'})
                    with urllib.request.urlopen(req,timeout=30) as response: data=json.load(response)
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
        target=symbol.replace('.','-')
        cik=next((f['cik_str'] for f in tickers.values() if f['ticker'].upper()==target),None)
        if cik is None: raise ValueError('No SEC ticker-to-CIK mapping (foreign issuers may lack US-GAAP facts)')
        url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010}.json'
        return self.get(url),url

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
        if d[cols].isna().any().any() or (d[cols[:4]]<=0).any().any() or (d.Volume<0).any(): raise ValueError('Invalid or missing OHLCV')
        if ((d.High<d[['Open','Close','Low']].max(axis=1)) | (d.Low>d[['Open','Close','High']].min(axis=1))).any(): raise ValueError('Inconsistent OHLCV')
        # Yahoo historical OHLC is split adjusted, not dividend adjusted; Volume follows Yahoo convention.
        return d

def encode_bars(d):
    return json.loads(d.reset_index(names='Date').to_json(orient='records',date_format='iso'))

def decode_bars(data):
    d=pd.DataFrame(data)
    if d.empty: return pd.DataFrame(columns=['Open','High','Low','Close','Volume'])
    d['Date']=pd.to_datetime(d.Date)
    return d.set_index('Date')

def refresh(universe,ua,cache,prices=None):
    prices=prices or YahooDaily()
    sec=SEC(cache,ua)
    report={}
    # Sequential symbol batches, shared SPY and independent provider failures.
    for symbol in list(dict.fromkeys(['SPY']+universe)):
        status={}
        price_key='prices:'+symbol
        try:
            hit=cache.get(price_key,21600)
            if not hit:
                bars=prices.daily(symbol)
                cache.put(price_key,{'bars':encode_bars(bars),'source':prices.source})
            status['price']='cached' if hit else 'refreshed'
        except Exception as exc: status['price']='FAILED: '+type(exc).__name__+': '+str(exc)[:180]
        if symbol!='SPY':
            try:
                facts,url=sec.facts(symbol)
                # Keep independent successful refresh times and raw provenance; no fabricated fields.
                source_time=cache.get(url)
                body={'facts':facts,'source':url}
                cache.put('facts:'+symbol,body,updated=source_time[0] if source_time else None)
                status['fundamentals']='available (SEC response cache ≤24h)'
            except Exception as exc: status['fundamentals']='FAILED: '+type(exc).__name__+': '+str(exc)[:180]
        report[symbol]=status
    cache.put('status',report)
    return report

def snapshot(cache,symbol):
    price,fact=cache.get('prices:'+symbol),cache.get('facts:'+symbol)
    bars=decode_bars(price[1]['bars']) if price else decode_bars([])
    values,provenance,anchor=extract(fact[1]['facts']) if fact else ({}, {}, None)
    pe_reason='Missing price, SEC EPS or incompatible periods'
    if fact and not bars.empty:
        cutoff=bars.index[-1].date().isoformat()
        # Fundamentals filed after the price candle are excluded from price/EPS calculation.
        eps,eps_facts=trailing_eps(fact[1]['facts'],cutoff)
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
