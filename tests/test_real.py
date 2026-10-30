"""Artificial fixtures only. No fixture can be loaded by the REAL provider."""
import io
import json
from pathlib import Path
import urllib.error
import numpy as np
import pandas as pd
import pytest
from screener.sec import extract, trailing_eps
from screener.real import Cache, SEC, YahooDaily, encode_bars, decode_bars, refresh, snapshot, symbols
from screener.indicators import calculate


def fixture():
    facts={}
    def add(tag,value,year,unit='USD',**extra):
        f=dict(start=f'{year}-01-01',end=f'{year}-12-31',filed=f'{year+1}-02-01',form='10-K',val=value,accn=f'{year}-original',**extra)
        facts.setdefault(tag,{'units':{unit:[]}})['units'][unit].append(f)
    for y,m in [(2023,1),(2024,1.5)]:
        for tag,v in [('Revenues',100*m),('GrossProfit',60*m),('NetCashProvidedByUsedInOperatingActivities',30*m),('PaymentsToAcquirePropertyPlantAndEquipment',10*m),('OperatingIncomeLoss',20*m),('IncomeTaxExpenseBenefit',4*m),('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',20*m)]: add(tag,v,y)
        add('EarningsPerShareDiluted',2*m,y,'USD/shares')
        add('WeightedAverageNumberOfDilutedSharesOutstanding',100*m,y,'shares')
        for tag,v in [('StockholdersEquity',100*m),('CashAndCashEquivalentsAtCarryingValue',20*m),('LongTermDebtCurrent',10*m),('LongTermDebtNoncurrent',30*m)]:
            facts.setdefault(tag,{'units':{'USD':[]}})['units']['USD'].append(dict(end=f'{y}-12-31',filed=f'{y+1}-02-01',form='10-K',val=v,accn='test-accession'))
    return {'cik':320193,'entityName':'ARTIFICIAL TEST COMPANY','facts':{'us-gaap':facts}}

def test_annual_arithmetic_and_roic():
    values,p,a=extract(fixture(),'2025-03-01')
    assert values['Revenue Growth YoY']==50
    assert values['EPS Growth YoY']==50
    assert values['Share Count Growth']==50
    assert values['Gross Margin']==60
    assert values['Free Cash Flow']==30
    assert values['Debt-to-Equity']==.4
    assert values['ROIC']==pytest.approx(100*24/150)
    assert values['Forward P/E'] is None and values['P/E'] is None
    assert a['end']=='2024-12-31'

def test_missing_not_zero_and_negative_denominator():
    f=fixture(); gaap=f['facts']['us-gaap']
    del gaap['PaymentsToAcquirePropertyPlantAndEquipment']
    del gaap['LongTermDebtCurrent']
    gaap['EarningsPerShareDiluted']['units']['USD/shares'][0]['val']=-1
    values,_,_=extract(f,'2025-03-01')
    assert values['Free Cash Flow'] is None
    assert values['Debt-to-Equity'] is None and values['ROIC'] is None
    assert values['EPS Growth YoY'] is None
    assert all(v is None for v in extract({'facts':{}},'2025-03-01')[0].values())

def test_amendment_cutoff_and_nonannual():
    f=fixture(); rr=f['facts']['us-gaap']['Revenues']['units']['USD']
    rr.extend([dict(start='2024-01-01',end='2024-12-31',filed='2025-04-01',form='10-K/A',val=180,accn='amended'),
               dict(start='2025-01-01',end='2025-03-31',filed='2025-05-01',form='10-Q',val=999,accn='test-quarter')])
    assert extract(f,'2025-03-01')[0]['Revenue Growth YoY']==50
    assert extract(f,'2025-05-02')[0]['Revenue Growth YoY']==80
    assert extract(f,'2025-05-02')[1]['revenue']['accn']=='amended'

def test_period_mismatch():
    f=fixture()
    f['facts']['us-gaap']['GrossProfit']['units']['USD'][-1]['start']='2024-02-01'
    assert extract(f,'2025-03-01')[0]['Gross Margin'] is None
    f['facts']['us-gaap']['Revenues']['units']['USD'][0]['end']='2022-12-31'
    assert extract(f,'2025-03-01')[0]['Revenue Growth YoY'] is None

def test_ttm_bridge_and_missing_comparison():
    f=fixture(); rr=f['facts']['us-gaap']['EarningsPerShareDiluted']['units']['USD/shares']
    rr.extend([dict(start='2025-01-01',end='2025-06-30',filed='2025-08-01',form='10-Q',val=2,accn='test-ytd'),
               dict(start='2024-01-01',end='2024-06-30',filed='2025-08-01',form='10-Q',val=1,accn='test-prior-ytd')])
    assert trailing_eps(f,'2025-03-01')[0]==3
    assert trailing_eps(f,'2025-07-31')[0] is None  # stale annual, future YTD not yet filed
    assert trailing_eps(f,'2025-08-02')[0]==4
    rr.pop()
    assert trailing_eps(f,'2025-08-02')[0] is None

def test_cache_expiration_and_roundtrip(tmp_path):
    c=Cache(tmp_path/'cache.sqlite')
    c.put('x',{'a':1})
    assert c.get('x')[1]=={'a':1}
    assert c.get('x',-1) is None
    d=bars()
    pd.testing.assert_frame_equal(d,decode_bars(encode_bars(d)),check_freq=False,check_dtype=False,check_names=False)

def bars(n=260):
    x=np.arange(n)
    close=100+x*.1+np.sin(x/3)
    return pd.DataFrame({'Open':close-.2,'High':close+1,'Low':close-1,'Close':close,'Volume':1000+x},index=pd.bdate_range(end='2025-01-02',periods=n))

def test_refresh_integration_no_demo_and_independent_failures(tmp_path,monkeypatch):
    c=Cache(tmp_path/'c.sqlite')
    class Prices:
        source='TEST ONLY'
        def daily(self,s):
            if s=='BAD': raise ValueError('Unavailable')
            return bars()
    monkeypatch.setattr(SEC,'facts',lambda self,s:(fixture(),'https://data.sec.gov/test'))
    monkeypatch.setattr('screener.real.time.sleep',lambda s:None)
    report=refresh(['AAPL','BAD'],'Test test@example.com',c,Prices())
    assert report['BAD']['price'].startswith('FAILED')
    assert not snapshot(c,'AAPL')['bars'].empty
    assert snapshot(c,'BAD')['bars'].empty
    assert snapshot(c,'BAD')['values']['P/E'] is None
    original=c.get('prices:AAPL')
    class Fail:
        source='TEST ONLY'
        def daily(self,s): raise RuntimeError('offline')
    # fresh cache reused without fetching on manual refresh
    refresh(['AAPL'],'Test test@example.com',c,Fail())
    assert c.get('prices:AAPL')==original

def test_sec_throttle_retry_cache_and_identity(tmp_path,monkeypatch):
    with pytest.raises(ValueError): SEC(Cache(tmp_path/'c'), 'anonymous')
    client=SEC(Cache(tmp_path/'d'),'Unit test test@example.com')
    calls=[]; sleeps=[]
    def open_(req,timeout):
        calls.append(req)
        if len(calls)==1: raise urllib.error.HTTPError(req.full_url,429,'limit',{'Retry-After':'2'},None)
        return io.BytesIO(json.dumps(fixture()).encode())
    monkeypatch.setattr('urllib.request.urlopen',open_)
    monkeypatch.setattr('screener.real.time.sleep',sleeps.append)
    assert client.get('https://data.sec.gov/test')==fixture()
    assert len(calls)==2 and calls[0].get_header('User-agent')=='Unit test test@example.com'
    assert 2 in sleeps
    client.get('https://data.sec.gov/test')
    assert len(calls)==2

def test_yahoo_completed_only_and_options(monkeypatch):
    import yfinance
    d=bars(10)
    today=pd.Timestamp.now(tz='America/New_York').date()
    d.index=pd.bdate_range(end=pd.Timestamp(today),periods=10)
    # append today's bar even if today happens to be a weekend
    d.loc[pd.Timestamp(today)]=d.iloc[-1]
    class T:
        def history(self,**kwargs):
            assert kwargs['auto_adjust'] is False and kwargs['back_adjust'] is False
            return d
    monkeypatch.setattr(yfinance,'Ticker',lambda s:T())
    monkeypatch.setattr('screener.real.time.sleep',lambda s:None)
    out=YahooDaily().daily('AAPL')
    assert all(t.date()<today for t in out.index)
    d.iloc[0,d.columns.get_loc('High')]=0
    with pytest.raises(ValueError): YahooDaily().daily('AAPL')

def test_ticker_validation():
    assert symbols('aapl, MSFT AAPL brk.b')==['AAPL','MSFT','BRK.B']
    for s in ['', '../evil',','.join(f'A{i}' for i in range(51))]:
        with pytest.raises(ValueError): symbols(s)

def test_independent_technical_reference():
    d=bars(); out=calculate(d,d)
    close=d.Close.to_numpy(); vol=d.Volume.to_numpy()
    assert out.SMA50.iloc[-1]==pytest.approx(sum(close[-50:])/50)
    assert out.SMA200.iloc[-1]==pytest.approx(sum(close[-200:])/200)
    changes=np.diff(close)
    gain=sum(max(v,0) for v in changes[:14])/14
    loss=sum(max(-v,0) for v in changes[:14])/14
    for v in changes[14:]: gain=(13*gain+max(v,0))/14; loss=(13*loss+max(-v,0))/14
    assert out['RSI(14)'].iloc[-1]==pytest.approx(100-100/(1+gain/loss))
    def ema(vals,span):
        result=[vals[0]]
        for value in vals[1:]: result.append(result[-1]+2/(span+1)*(value-result[-1]))
        return np.array(result)
    macd=ema(close,12)-ema(close,26)
    signal=ema(macd[25:],9)
    assert out.MACD.iloc[-1]==pytest.approx(macd[-1])
    assert out.Signal.iloc[-1]==pytest.approx(signal[-1])
    obv=[0]
    for i in range(1,len(close)): obv.append(obv[-1]+np.sign(close[i]-close[i-1])*vol[i])
    assert out.OBV.iloc[-1]==obv[-1]
    assert out['OBV SMA'].iloc[-1]==pytest.approx(sum(obv[-10:])/10)
    assert out.RVOL.iloc[-1]==pytest.approx(vol[-1]/(sum(vol[-21:-1])/20))
    assert out['Close > previous high'].iloc[-1]==float(close[-1]>max(d.High.iloc[-21:-1]))
    assert out['Relative vs SPY'].iloc[-1]==0
    assert out['Higher highs / higher lows'].iloc[-1]==float(max(d.High.iloc[-20:])>max(d.High.iloc[-40:-20]) and min(d.Low.iloc[-20:])>min(d.Low.iloc[-40:-20]))

def test_mapping_and_unknown_cik(tmp_path,monkeypatch):
    client=SEC(Cache(tmp_path/'c'),'Mapping test test@example.com')
    calls=[]
    def get(url,ttl=86400):
        calls.append(url)
        return {'0':{'ticker':'BRK-B','cik_str':320193,'title':'ARTIFICIAL TEST COMPANY'}} if url.endswith('company_tickers.json') else fixture()
    monkeypatch.setattr(client,'get',get)
    f,url=client.facts('BRK.B')
    assert url.endswith('CIK0000320193.json')
    with pytest.raises(ValueError): client.facts('MISSING')

def test_pe_dated_and_split_guard(tmp_path):
    c=Cache(tmp_path/'c'); d=bars()
    d.index=pd.bdate_range(end='2025-03-03',periods=len(d))
    c.put('facts:AAPL',{'facts':fixture(),'source':'SEC TEST'})
    c.put('prices:AAPL',{'bars':encode_bars(d),'source':'TEST'})
    snap=snapshot(c,'AAPL')
    assert snap['values']['P/E']==pytest.approx(d.Close.iloc[-1]/3)
    assert snap['provenance']['trailing_eps']['price_date']=='2025-03-03'
    d['Stock Splits']=0.
    d.iloc[-20,d.columns.get_loc('Stock Splits')]=2
    c.put('prices:AAPL',{'bars':encode_bars(d),'source':'TEST'})
    assert snapshot(c,'AAPL')['values']['P/E'] is None

def test_failed_refresh_keeps_original_data_and_time(tmp_path,monkeypatch):
    c=Cache(tmp_path/'c')
    c.put('prices:AAPL',{'bars':encode_bars(bars()),'source':'TEST'},updated=1000)
    original=c.get('prices:AAPL')
    class Broken:
        source='TEST'
        def daily(self,s): raise ValueError('offline')
    def fail(self,s): raise ValueError('offline')
    monkeypatch.setattr(SEC,'facts',fail)
    report=refresh(['AAPL'],'Test test@example.com',c,Broken())
    assert 'FAILED' in report['AAPL']['price']
    assert c.get('prices:AAPL')==original
    assert snapshot(c,'AAPL')['fundamentals_refresh']=='Never'

def test_revenue_tag_transition_not_stale():
    f=fixture(); facts=f['facts']['us-gaap']
    facts['RevenueFromContractWithCustomerExcludingAssessedTax']={'units':{'USD':[dict(start='2022-01-01',end='2022-12-31',filed='2023-02-01',form='10-K',val=90)]}}
    assert extract(f,'2025-03-01')[2]['end']=='2024-12-31'
