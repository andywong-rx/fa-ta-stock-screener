"""Offline deployment regressions. Contacts and payloads below are test-only."""
import io
import json
from pathlib import Path
import sqlite3
import urllib.error
import pytest
from streamlit.testing.v1 import AppTest
from screener.config import CONFIG_WARNING, load_sec_user_agent, valid_user_agent
from screener.real import Cache, SEC, refresh, snapshot
from screener.validation import InvalidSECResponse, validate_company, validate_tickers
from test_real import fixture, bars

CONTACT = 'Artificial test app contact@invalid.example'
ROOT = Path(__file__).parents[1]
URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json'

@pytest.mark.parametrize('secrets', [{}, {'sec':{}}, {'sec':None}, {'sec':{'user_agent':None}},
    {'sec':{'user_agent':42}}, {'sec':{'user_agent':'anonymous'}},
    {'sec':{'user_agent':'contact@invalid.example'}},
    {'sec':{'user_agent':CONTACT+'\nInjected: x'}},
    {'sec':{'user_agent':'Artificial test ä contact@invalid.example'}}])
def test_missing_or_malformed_identity(secrets):
    assert load_sec_user_agent(secrets) is None

def test_valid_identity_and_missing_file_are_private(capsys, caplog):
    assert load_sec_user_agent({'sec':{'user_agent':CONTACT}}) == CONTACT
    class BrokenSecrets:
        def __getitem__(self,key): raise ValueError(CONTACT)
    assert load_sec_user_agent(BrokenSecrets()) is None
    assert CONTACT not in capsys.readouterr().out + caplog.text

@pytest.mark.parametrize('data', [None, [], 'error', {}, {'facts':None},
    {'cik':320193,'entityName':'TEST','facts':None},
    {'cik':320193,'entityName':'TEST','facts':{'us-gaap':[]}},
    {'cik':True,'entityName':'TEST','facts':{}},
    {'cik':320193,'entityName':'TEST','facts':{'us-gaap':{'Revenues':{'units':{'USD':[{}]}}}}}])
def test_invalid_sec_schema(data):
    with pytest.raises(InvalidSECResponse): validate_company(data)

@pytest.mark.parametrize('mutation', ['val','end','filed','accn','form','units','cik'])
def test_required_fact_fields(mutation):
    data=fixture()
    tag=data['facts']['us-gaap']['Revenues']
    if mutation=='units': tag['units']=None
    elif mutation=='cik': data['cik']=999
    else: del tag['units']['USD'][0][mutation]
    with pytest.raises(InvalidSECResponse): validate_company(data,320193)

@pytest.mark.parametrize('value', [None,'2025-99-99','nonsense'])
def test_invalid_dates(value):
    data=fixture(); data['facts']['us-gaap']['Revenues']['units']['USD'][0]['end']=value
    with pytest.raises(InvalidSECResponse): validate_company(data)

@pytest.mark.parametrize('value', [None,True,'123',float('nan'),float('inf')])
def test_invalid_financial_values(value):
    data=fixture(); data['facts']['us-gaap']['Revenues']['units']['USD'][0]['val']=value
    with pytest.raises(InvalidSECResponse): validate_company(data)

@pytest.mark.parametrize('payload', [b'{not JSON',b'[]',b'null',b'"error"',b'{}',b'{"facts":null}'])
def test_bad_sec_http_response_never_replaces_last_valid(tmp_path,monkeypatch,payload):
    c=Cache(tmp_path/'cache')
    c.put(URL,fixture(),updated=1000)
    before=c.get(URL)
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:io.BytesIO(payload))
    monkeypatch.setattr('screener.real.time.sleep',lambda s:None)
    with pytest.raises(InvalidSECResponse): SEC(c,CONTACT).get(URL)
    assert c.get(URL)==before

@pytest.mark.parametrize('data', [[],{}, {'0':None}, {'0':{'ticker':'AAPL','cik_str':'320193','title':'TEST'}},
    {'0':{'ticker':'AAPL','cik_str':320193}}])
def test_bad_mapping_not_cached(tmp_path,monkeypatch,data):
    c=Cache(tmp_path/'cache')
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:io.BytesIO(json.dumps(data).encode()))
    monkeypatch.setattr('screener.real.time.sleep',lambda s:None)
    url='https://www.sec.gov/files/company_tickers.json'
    with pytest.raises(InvalidSECResponse): SEC(c,CONTACT).get(url)
    assert c.get(url) is None

def test_unsupported_taxonomy_is_unknown_not_malformed():
    validate_company({'cik':320193,'entityName':'TEST','facts':{}})

class TestPrices:
    __test__=False
    source='ARTIFICIAL TEST ONLY'
    def daily(self,symbol): return bars()

def test_malformed_refresh_keeps_original_snapshot_and_hides_errors(tmp_path,monkeypatch,capsys,caplog):
    c=Cache(tmp_path/'cache')
    c.put('facts:AAPL',{'facts':fixture(),'source':URL},updated=1000)
    old=c.get('facts:AAPL')
    monkeypatch.setattr(SEC,'facts',lambda *a:({'facts':None},URL))
    report=refresh(['AAPL'],CONTACT,c,TestPrices())
    assert report['AAPL']['fundamentals'].startswith('FAILED')
    assert c.get('facts:AAPL')==old
    assert snapshot(c,'AAPL')['values']['Revenue Growth YoY']==50
    def fail(*a): raise urllib.error.URLError(CONTACT)
    monkeypatch.setattr(SEC,'facts',fail)
    report=refresh(['AAPL'],CONTACT,c,TestPrices())
    assert CONTACT not in json.dumps(report)+capsys.readouterr().out+caplog.text

def test_no_secret_never_requests_sec(tmp_path,monkeypatch):
    def forbidden(*a): pytest.fail('SEC requested without identity')
    monkeypatch.setattr(SEC,'facts',forbidden)
    report=refresh(['AAPL'],None,Cache(tmp_path/'c'),TestPrices())
    assert report['AAPL']['fundamentals'].startswith('UNAVAILABLE')

def test_corrupt_database_without_backup_recovers(tmp_path):
    path=tmp_path/'cache.sqlite'; path.write_bytes(b'not a database')
    c=Cache(path)
    assert c.get('missing') is None and c.warnings
    assert list(tmp_path.glob('cache.sqlite.corrupt-*'))
    c.put('good',{'value':3})
    assert Cache(path).get('good')[1]=={'value':3}

def test_corrupt_database_recovers_last_successful_backup(tmp_path):
    path=tmp_path/'cache.sqlite'; c=Cache(path)
    c.put('facts:AAPL',{'facts':fixture(),'source':URL},updated=1000)
    c.memory.clear()  # simulate fresh process, independent disk backup required
    path.write_bytes(b'corrupted SQLite')
    recovered=Cache(path)
    assert recovered.get('facts:AAPL')[0]==1000
    assert snapshot(recovered,'AAPL')['values']['Revenue Growth YoY']==50
    assert recovered.warnings

def test_corruption_after_initialization_recovers_on_read(tmp_path):
    c=Cache(tmp_path/'cache'); c.put('good',{'v':4})
    c.path.write_bytes(b'corruption after initialization')
    assert c.get('good')[1]=={'v':4}

def test_corrupt_json_row_uses_backup_and_original_timestamp(tmp_path):
    c=Cache(tmp_path/'cache'); c.put('facts:AAPL',{'facts':fixture(),'source':URL},updated=1000)
    c.memory.clear()
    with sqlite3.connect(c.path) as db:
        db.execute("UPDATE cache SET body='not json' WHERE key='facts:AAPL'")
    recovered=Cache(c.path)
    assert snapshot(recovered,'AAPL')['values']['Revenue Growth YoY']==50
    assert recovered.get('facts:AAPL')[0]==1000
    assert recovered.warnings

def test_both_corrupt_files_are_unknown_then_recoverable(tmp_path):
    c=Cache(tmp_path/'cache'); c.put('good',{'v':1}); c.memory.clear()
    c.path.write_bytes(b'bad'); c.backup.write_bytes(b'also bad')
    recovered=Cache(c.path)
    assert recovered.get('good') is None and recovered.warnings
    recovered.put('new',{'v':2})
    assert Cache(c.path).get('new')[1]=={'v':2}

def test_unavailable_disk_uses_process_memory(tmp_path):
    c=Cache(tmp_path)  # directory cannot be used as a SQLite file
    assert not c.available and c.warnings
    c.put('current',{'v':1})
    assert c.get('current')[1]=={'v':1}

@pytest.mark.parametrize('secret', [None,'anonymous',CONTACT])
def test_secrets_ui_and_single_page_configuration(tmp_path,monkeypatch,secret):
    import streamlit as st
    calls=[]
    original=st.set_page_config
    def configured(*args,**kwargs):
        calls.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(st,'set_page_config',configured)
    monkeypatch.setenv('SCREENER_CACHE',str(tmp_path/'cache'))
    app=AppTest.from_file(str(ROOT/'app_v2a.py'))
    if secret is not None: app.secrets['sec']={'user_agent':secret}
    app.run(timeout=30)
    assert not app.exception and len(calls)==1
    calls.clear()
    app.sidebar.radio[0].set_value('REAL').run(timeout=30)
    assert not app.exception and len(calls)==1
    app.sidebar.checkbox[0].check().run(timeout=30)
    refresh_button=next(b for b in app.sidebar.button if b.label=='Refresh REAL data')
    assert refresh_button.disabled == (secret!=CONTACT)
    visible=' '.join(str(e.value) for kind in ('caption','warning','text_input','error','text') for e in getattr(app,kind))
    assert CONTACT not in visible
    if secret!=CONTACT: assert CONFIG_WARNING in visible
    assert not app.sidebar.text_input

@pytest.mark.parametrize('fault', ['database','facts','prices','status','calculation'])
def test_real_rendering_survives_data_and_storage_faults(tmp_path,monkeypatch,fault):
    path=tmp_path/'cache'
    c=Cache(path)
    if fault=='database': path.write_bytes(b'not SQLite')
    elif fault=='facts': c.put('facts:AAPL',{'facts':{'facts':None},'source':URL})
    elif fault=='prices': c.put('prices:AAPL',{'bars':[{'Date':'invalid'}],'source':'TEST'})
    elif fault=='status': c.put('status',{'AAPL':None})
    else:
        c.put('prices:AAPL',{'bars':json.loads(bars().reset_index(names='Date').to_json(orient='records',date_format='iso')),'source':'TEST'})
        def broken(*a,**k): raise ValueError('artificial calculation fault')
        monkeypatch.setattr('screener.indicators.calculate',broken)
    monkeypatch.setenv('SCREENER_CACHE',str(path))
    app=AppTest.from_file(str(ROOT/'app_v2a.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('REAL').run(timeout=30)
    assert not app.exception
    assert any('UNKNOWN' in str(df.value) for df in app.dataframe)
    assert app.warning

def test_bad_local_toml_is_private(tmp_path,capsys,caplog,monkeypatch):
    from streamlit.runtime.secrets import Secrets
    path=tmp_path/'secrets.toml'; path.write_text('[sec\nuser_agent = "'+CONTACT+'"')
    original=__import__('streamlit').config.get_option
    monkeypatch.setattr('streamlit.runtime.secrets.config.get_option',lambda name:[str(path)] if name=='secrets.files' else original(name))
    monkeypatch.setattr(Secrets,'_maybe_install_file_watchers',lambda self:None)
    assert load_sec_user_agent(Secrets()) is None
    captured=capsys.readouterr()
    assert CONTACT not in captured.out+captured.err+caplog.text

def test_valid_local_toml(tmp_path,monkeypatch):
    from streamlit.runtime.secrets import Secrets
    path=tmp_path/'secrets.toml'; path.write_text('[sec]\nuser_agent = "'+CONTACT+'"')
    original=__import__('streamlit').config.get_option
    monkeypatch.setattr('streamlit.runtime.secrets.config.get_option',lambda name:[str(path)] if name=='secrets.files' else original(name))
    monkeypatch.setattr(Secrets,'_maybe_install_file_watchers',lambda self:None)
    assert load_sec_user_agent(Secrets())==CONTACT

def test_refresh_ui_never_exposes_backend_exception(tmp_path,monkeypatch,capsys,caplog):
    monkeypatch.setenv('SCREENER_CACHE',str(tmp_path/'cache'))
    def fail(*a,**k): raise RuntimeError(CONTACT)
    monkeypatch.setattr('screener.real.refresh',fail)
    app=AppTest.from_file(str(ROOT/'app_v2a.py'))
    app.secrets['sec']={'user_agent':CONTACT}
    app.run(timeout=30)
    app.sidebar.radio[0].set_value('REAL').run(timeout=30)
    app.sidebar.checkbox[0].check().run(timeout=30)
    next(b for b in app.sidebar.button if b.label=='Refresh REAL data').click().run(timeout=30)
    assert not app.exception and app.error
    visible=' '.join(str(e.value) for kind in ('caption','warning','error','text') for e in getattr(app,kind))
    captured=capsys.readouterr()
    assert CONTACT not in visible+captured.out+captured.err+caplog.text

def test_chart_error_keeps_real_screen_available(tmp_path,monkeypatch):
    from screener.real import encode_bars
    path=tmp_path/'cache'; c=Cache(path)
    c.put('prices:AAPL',{'bars':encode_bars(bars()),'source':'TEST'})
    def fail(*a,**k): raise ValueError('artificial chart failure')
    monkeypatch.setattr('screener.charts.stock_chart',fail)
    monkeypatch.setenv('SCREENER_CACHE',str(path))
    app=AppTest.from_file(str(ROOT/'app_v2a.py')).run(timeout=30)
    app.sidebar.radio[0].set_value('REAL').run(timeout=30)
    app.sidebar.text_area[0].set_value('AAPL').run(timeout=30)
    assert not app.exception
    assert any('Chart unavailable' in i.value for i in app.info)

def test_invalid_timestamp_uses_backup(tmp_path):
    c=Cache(tmp_path/'cache'); c.put('good',{'v':1},updated=1000); c.memory.clear()
    with sqlite3.connect(c.path) as db:
        db.execute('UPDATE cache SET updated=1e30')
    assert Cache(c.path).get('good')==(1000,{'v':1})

@pytest.mark.parametrize('address', ['x@a..com','x@-domain.com','x@domain-.com','x@domain','a..b@domain.com','a@domain.com@other.com'])
def test_malformed_email_is_rejected(address):
    assert not valid_user_agent('Artificial test app '+address)

def test_missing_primary_database_restores_backup(tmp_path):
    c=Cache(tmp_path/'cache'); c.put('good',{'v':2},updated=1000); c.memory.clear()
    c.path.unlink()
    restored=Cache(c.path)
    assert restored.get('good')==(1000,{'v':2})

def test_corruption_on_write_preserves_previous_and_new_values(tmp_path):
    c=Cache(tmp_path/'cache'); c.put('earlier',{'v':1},updated=1000)
    c.memory.clear(); c.path.write_bytes(b'corrupt before write')
    c.put('current',{'v':2})
    assert Cache(c.path).get('earlier')==(1000,{'v':1})
    assert Cache(c.path).get('current')[1]=={'v':2}

def test_audit_script_missing_identity_is_generic(tmp_path):
    import subprocess,sys
    path=tmp_path/'secrets.toml'; path.write_text('[sec\nuser_agent="'+CONTACT+'"')
    result=subprocess.run([sys.executable,str(ROOT/'scripts/validate_live.py'),'--secrets-file',str(path)],capture_output=True,text=True)
    assert result.returncode!=0
    assert CONTACT not in result.stdout+result.stderr
    assert 'SEC identity is missing or invalid' in result.stderr

def test_locked_database_is_not_quarantined_or_overwritten(tmp_path,monkeypatch):
    c=Cache(tmp_path/'cache'); c.put('earlier',{'v':1})
    monkeypatch.setattr(Cache,'_connect',lambda self:sqlite3.connect(self.path,timeout=.01))
    with sqlite3.connect(c.path) as locked:
        locked.execute('BEGIN EXCLUSIVE')
        c.put('current',{'v':2})
        assert c.get('current')[1]=={'v':2}
        assert c.warnings
        assert not list(tmp_path.glob('cache.corrupt-*'))
        locked.rollback()
    with sqlite3.connect(c.path) as db:
        assert json.loads(db.execute("SELECT body FROM cache WHERE key='earlier'").fetchone()[0])=={'v':1}
