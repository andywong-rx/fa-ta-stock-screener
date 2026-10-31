"""Presentation tests use artificial inputs only, never REAL provider fallbacks."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from screener.ranking import rank_results, explain_rules, qualification_summary
from screener.rules import Rule, evaluate


def results():
    return pd.DataFrame([
        dict(Symbol='CCC',Score=80.,FA=20.,TA=90.,Classification='TA-only'),
        dict(Symbol='BBB',Score=90.,FA=50.,TA=30.,Classification='neither'),
        dict(Symbol='AAA',Score=90.,FA=99.,TA=10.,Classification='FA-only'),
        dict(Symbol='DDD',Score=None,FA=None,TA=None,Classification='unknown')])


def test_empty_classification_means_all_and_default_combined_descending():
    source=results(); original=source.copy(deep=True)
    shown=rank_results(source,[])
    assert shown.Symbol.tolist()==['AAA','BBB','CCC','DDD']
    pd.testing.assert_frame_equal(source,original)
    assert pd.isna(shown.iloc[-1].Score)


@pytest.mark.parametrize('classes,expected', [(['unknown'],['DDD']),
    (['FA-only','TA-only'],['AAA','CCC']),(['fully qualified'],[])])
def test_classifications(classes,expected):
    assert rank_results(results(),classes).Symbol.tolist()==expected


@pytest.mark.parametrize('ranking,expected',[('Combined Score',['AAA','BBB','CCC','DDD']),
    ('FA Score',['AAA','BBB','CCC','DDD']),('TA Score',['CCC','BBB','AAA','DDD'])])
def test_each_score_descending_and_unknown_last(ranking,expected):
    assert rank_results(results(),ranking=ranking).Symbol.tolist()==expected


@pytest.mark.parametrize('limit,size',[('Top 10',10),('Top 20',20),('All',25)])
def test_ranking_limits_follow_sorting(limit,size):
    d=pd.DataFrame([dict(Symbol=f'T{i:02}',Score=i,FA=25-i,TA=i,Classification='neither') for i in range(25)])
    shown=rank_results(d,limit=limit)
    assert len(shown)==size
    assert shown.Symbol.tolist()==[f'T{i:02}' for i in range(24,24-size,-1)]


def test_filter_precedes_limit_and_never_expands_watchlist():
    d=pd.DataFrame([dict(Symbol=f'T{i:02}',Score=i,FA=i,TA=i,
        Classification='FA-only' if i%2 else 'neither') for i in range(40)])
    watch=d[d.Symbol.isin(['T01','T03','T10'])]
    assert rank_results(watch,['FA-only'],limit='Top 10').Symbol.tolist()==['T03','T01']
    assert len(rank_results(d,['FA-only'],limit='Top 10'))==10
    assert len(rank_results(d.iloc[:0],limit='All'))==0


def explained(values,rules):
    result,details=evaluate(values,rules)
    return result,explain_rules(details,rules)


def test_fail_and_unknown_have_separate_actual_values_and_thresholds():
    rules=[Rule('Revenue Growth YoY','FA','>=',20),Rule('Forward P/E','FA','<=',30),
        Rule('RSI(14)','TA','between',50,70)]
    _,details=explained({'Revenue Growth YoY':12.5,'Forward P/E':None,'RSI(14)':74},rules)
    summary=qualification_summary(details)
    assert summary['FA qualification']=='FAIL'
    assert summary['TA qualification']=='FAIL'
    assert 'actual 12.5' in summary['FA FAIL reasons'] and '>= 20' in summary['FA FAIL reasons']
    assert 'Forward P/E' not in summary['FA FAIL reasons']
    assert 'Forward P/E' in summary['FA UNKNOWN reasons']
    assert 'cannot be evaluated' in summary['FA UNKNOWN reasons']
    assert 'FAIL' not in summary['FA UNKNOWN reasons']
    assert 'actual 74' in summary['TA FAIL reasons'] and 'between 50 and 70 (inclusive)' in summary['TA FAIL reasons']


@pytest.mark.parametrize('value',[None,np.nan,np.inf,-np.inf])
def test_unavailable_is_not_financial_failure(value):
    _,details=explained({'x':value},[Rule('x','FA')])
    summary=qualification_summary(details)
    assert details[0]['actual']=='UNKNOWN' and details[0]['status']=='UNKNOWN'
    assert summary['FA qualification']=='UNKNOWN' and summary['FA FAIL reasons']=='None'


def test_optional_and_disabled_rules_are_not_mandatory_failures():
    rules=[Rule('required','FA'),Rule('optional','FA',mandatory=False),Rule('disabled','FA',enabled=False)]
    result,details=explained({'required':1,'optional':0,'disabled':0},rules)
    summary=qualification_summary(details)
    assert result['FA']==50  # existing scoring behavior stays intact
    assert summary['FA qualification']=='PASS'
    assert summary['FA FAIL reasons']=='None'
    assert len(details)==2
    assert details[1]['role']=='Optional (score only)' and details[1]['status']=='FAIL'


def test_no_mandatory_fallback_and_no_enabled_rules_are_explained():
    _,details=explained({'optional':0},[Rule('optional','TA',mandatory=False)])
    summary=qualification_summary(details)
    assert summary['TA qualification']=='FAIL'
    assert 'Qualification fallback (no mandatory rules)' in summary['TA FAIL reasons']
    assert summary['FA qualification']=='UNKNOWN'
    assert summary['FA FAIL reasons']=='None'
    assert 'No enabled rules' in summary['FA UNKNOWN reasons']


def test_edited_threshold_precision_and_passing_boundary():
    bound=0.123456789123
    _,details=explained({'metric':bound},[Rule('metric','FA','>=',bound)])
    assert details[0]['status']=='PASS'
    assert details[0]['actual']==repr(bound)
    assert details[0]['rule']=='>= '+repr(bound)


def test_known_boolean_failure_is_not_missing_data():
    _,details=explained({'Price > SMA50':0},[Rule('Price > SMA50','TA')])
    assert details[0]['status']=='FAIL' and details[0]['actual']=='0'
    assert 'actual 0' in details[0]['explanation']


def test_real_ranking_controls_and_watchlist(tmp_path,monkeypatch):
    from screener.real import UNIVERSE
    from test_real import bars
    def artificial_snapshot(cache,symbol):
        i=UNIVERSE.index(symbol) if symbol in UNIVERSE else 0
        return dict(bars=bars(),values={'Revenue Growth YoY':i*5.,'EPS Growth YoY':50.,
            'Gross Margin':60.,'ROIC':15.,'P/E':15.,'Forward P/E':None,
            'Free Cash Flow':1000000.,'Debt-to-Equity':.5,'Share Count Growth':2.},
            provenance={},period='2024-12-31',pe_note='ARTIFICIAL TEST ONLY',
            price_refresh='TEST',fundamentals_refresh='TEST',price_source='TEST',fundamental_source='TEST')
    monkeypatch.setattr('screener.real.snapshot',artificial_snapshot)
    monkeypatch.setenv('SCREENER_CACHE',str(tmp_path/'cache'))
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app_v2a.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('REAL').run(timeout=30)
    assert not app.exception
    def table():
        return next(df.value for df in app.dataframe if 'Symbol' in df.value.columns)
    classification=app.multiselect(key='real_classifications')
    assert classification.value==[]
    initial=table()
    assert len(initial)==25
    assert initial.Symbol.tolist()==initial.sort_values(['Score','Symbol'],ascending=[False,True]).Symbol.tolist()
    assert 'FA FAIL reasons' in initial and 'FA UNKNOWN reasons' in initial
    assert all('Forward P/E' not in text for text in initial['FA FAIL reasons'])
    assert any('Forward P/E' in text for text in initial['FA UNKNOWN reasons'])
    app.selectbox(key='real_limit').select('Top 10').run(timeout=30)
    assert len(table())==10
    app.selectbox(key='real_limit').select('Top 20').run(timeout=30)
    assert len(table())==20
    app.selectbox(key='real_limit').select('All').run(timeout=30)
    for ranking,column in [('FA Score','FA'),('TA Score','TA'),('Combined Score','Score')]:
        app.selectbox(key='real_ranking').select(ranking).run(timeout=30)
        assert table().Symbol.tolist()==initial.sort_values([column,'Symbol'],ascending=[False,True]).Symbol.tolist()
    chosen=initial.Classification.iloc[0]
    app.multiselect(key='real_classifications').set_value([chosen]).run(timeout=30)
    assert len(table())==int((initial.Classification==chosen).sum())
    app.multiselect(key='real_classifications').set_value([]).run(timeout=30)
    assert len(table())==25
    app.sidebar.multiselect[0].set_value(['AAPL','MSFT']).run(timeout=30)
    next(c for c in app.sidebar.checkbox if c.label=='Show REAL watchlist only').check().run(timeout=30)
    assert set(table().Symbol)=={'AAPL','MSFT'}
    assert not app.exception
