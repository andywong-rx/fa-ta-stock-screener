from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_dashboard_and_presets():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py')).run(timeout=30)
    assert not app.exception
    assert len(app.dataframe)>=2
    for strategy in app.sidebar.selectbox[0].options:
        app.sidebar.selectbox[0].select(strategy).run(timeout=30)
        assert not app.exception
    app.sidebar.multiselect[0].set_value(['DEMO01']).run()
    app.sidebar.checkbox[0].check().run()
    assert not app.exception
    assert app.metric[0].value=='1'


def test_v2a_modes_empty_real_and_rules(tmp_path,monkeypatch):
    monkeypatch.setenv('SCREENER_CACHE',str(tmp_path/'cache.sqlite'))
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app_v2a.py')).run(timeout=30)
    assert not app.exception
    app.sidebar.radio[0].set_value('REAL').run(timeout=30)
    assert not app.exception
    assert any('UNKNOWN' in str(df.value) for df in app.dataframe)
    app.sidebar.text_area[0].set_value('AAPL,MSFT').run(timeout=30)
    assert not app.exception
    app.sidebar.selectbox[0].select('Growth + Breakout').run(timeout=30)
    assert not app.exception
    app.sidebar.radio[0].set_value('DEMO').run(timeout=30)
    assert not app.exception
