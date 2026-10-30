import numpy as np
import pandas as pd
import pytest
from screener.providers import DemoProvider
from screener.indicators import calculate, Definitions
from screener.rules import preset, PRESETS, evaluate, Rule, status


def test_strict_contract():
    rules=preset(PRESETS[-1])
    assert len(rules)==19 and all(r.enabled and r.mandatory for r in rules)
    assert [r.lower for r in rules[:9]]==[50,50,50,12,30,20,0,1,5]
    assert (rules[13].lower,rules[13].upper)==(50,70)
    for r in rules:
        assert status(None,r)=='unknown'
    values={r.metric:r.lower for r in rules}
    values.update({'Free Cash Flow':1,'Relative vs SPY':.01})
    result,_=evaluate(values,rules)
    assert result['Classification']=='fully qualified'
    for r in rules:
        incomplete=values.copy(); incomplete[r.metric]=None
        assert evaluate(incomplete,rules)[0]['Classification']!='fully qualified'

@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),-float('inf'),'bad'])
def test_missing(value):
    assert status(value,Rule('x','FA'))=='unknown'

def test_scoring_and_gates():
    rules=[Rule('a','FA'),Rule('b','FA',mandatory=False),Rule('c','TA')]
    result,_=evaluate({'a':1,'b':None,'c':0},rules)
    assert result==dict(FA=50,TA=0,Score=30,Classification='FA-only')
    rules[1].enabled=False
    assert evaluate({'a':1,'c':1},rules)[0]['Score']==100
    rules[0].enabled=False
    assert evaluate({'c':1},rules)[0]['Classification']=='unknown'

def test_classifications():
    rules=[Rule('a','FA'),Rule('b','TA')]
    for a,b,label in [(1,1,'fully qualified'),(1,0,'FA-only'),(0,1,'TA-only'),(0,0,'neither'),(None,1,'unknown')]:
        assert evaluate({'a':a,'b':b},rules)[0]['Classification']==label

def test_provider_deterministic():
    p=DemoProvider()
    pd.testing.assert_frame_equal(p.snapshot('DEMO01').bars,p.snapshot('DEMO01').bars)
    assert p.snapshot('DEMO01').fundamentals==p.snapshot('DEMO01').fundamentals
    assert p.snapshot('DEMO12').fundamentals['ROIC'] is None

def test_no_lookahead_and_reference_windows():
    p=DemoProvider(); bars=p.snapshot('DEMO01').bars; spy=p.snapshot('SPY').bars
    full=calculate(bars,spy)
    for n in [10,50,200,280]:
        pd.testing.assert_frame_equal(full.iloc[:n],calculate(bars.iloc[:n],spy.iloc[:n]))
    assert full.RVOL.iloc[-1]==pytest.approx(bars.Volume.iloc[-1]/bars.Volume.iloc[-21:-1].mean())
    assert full['Previous high'].iloc[-1]==bars.High.iloc[-21:-1].max()
    assert full['Relative vs SPY'].iloc[-1]==pytest.approx(bars.Close.iloc[-1]/bars.Close.iloc[-64]-spy.Close.iloc[-1]/spy.Close.iloc[-64])
    assert full.SMA200.iloc[:199].isna().all()

def test_rsi_and_missing_volume():
    p=DemoProvider(); bars=p.snapshot('DEMO01').bars.copy(); bars['Close']=np.arange(len(bars))+10.
    result=calculate(bars,p.snapshot('SPY').bars)
    assert result['RSI(14)'].iloc[-1]==100
    missing=calculate(p.snapshot('DEMO12').bars,p.snapshot('SPY').bars)
    assert pd.isna(missing.RVOL.iloc[-1]) and pd.isna(missing['Rising OBV'].iloc[-1])

def test_threshold_boundaries():
    assert status(0,Rule('FCF','FA','>',0))=='fail'
    assert status(70,Rule('RSI','TA','between',50,70))=='pass'
    assert status(70.1,Rule('RSI','TA','between',50,70))=='fail'
    assert status(1.5,Rule('RVOL','TA','>=',1.5))=='pass'

def test_missing_current_close_never_reuses_macd():
    p=DemoProvider(); bars=p.snapshot('DEMO01').bars.copy()
    bars.loc[bars.index[-1],'Close']=np.nan
    out=calculate(bars,p.snapshot('SPY').bars)
    for metric in ['MACD > signal','Price > SMA50','Price > SMA200','RSI(14)','Relative vs SPY','Rising OBV']:
        assert pd.isna(out[metric].iloc[-1])
