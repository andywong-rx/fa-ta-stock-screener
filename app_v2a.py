"""Opt-in V2A pilot. app.py remains the unchanged Version 1 DEMO application."""
import math
from pathlib import Path
import pandas as pd
import streamlit as st
from screener.real import Cache, UNIVERSE, symbols, refresh, snapshot
from screener.indicators import calculate
from screener.rules import PRESETS, Rule, preset, evaluate
from screener.charts import stock_chart

st.set_page_config(page_title='Signal Studio · V2A',layout='wide')
mode=st.sidebar.radio('Data mode',['DEMO','REAL'],key='v2a_mode')
if mode=='DEMO':
    exec(compile(Path(__file__).with_name('app.py').read_text(),'app.py','exec'))
    st.stop()
st.title('◈ Signal Studio · REAL · Version 2A')
st.warning('Limited US stock research pilot · SEC + Yahoo via yfinance · no guaranteed availability or redistribution license. No paid services or API keys.')
cache=Cache()
with st.sidebar:
    strategy=st.selectbox('REAL strategy',PRESETS)
    weight=st.slider('REAL fundamental weight (%)',0,100,60)
    ticker_text=st.text_area('REAL tickers (1–50)',','.join(UNIVERSE),key='real_tickers')
    try: universe=symbols(ticker_text)
    except ValueError as exc: st.error(str(exc)); st.stop()
    ua=st.text_input('SEC User-Agent: app/operator and contact email',placeholder='My research screener Jane jane@example.com')
    st.caption('Contact identity is required by SEC, not an API key. It is sent only as an HTTP header and is not saved in the data cache.')
    consent=st.checkbox('I have reviewed Yahoo terms and use this provider for permitted personal research')
    if st.button('Refresh REAL data',disabled=not consent):
        try:
            with st.spinner('Sequentially refreshing prices and SEC facts; cached responses reused…'):
                refresh(universe,ua,cache)
        except ValueError as exc: st.error(str(exc))
    watch=st.multiselect('REAL session watchlist',universe,key='real_watch')
    only=st.checkbox('Show REAL watchlist only')
    st.download_button('Export REAL watchlist',pd.DataFrame({'Symbol':watch}).to_csv(index=False),'REAL_watchlist.csv')
    st.caption('Refresh explicitly. Reruns read local SQLite only. Prices cached 6h; SEC facts 24h; ticker mapping 7d. Local files may disappear on Community Cloud restart/redeploy. Watchlist is session-only.')
with st.expander('Edit REAL screening rules'):
    k='real_rules_'+strategy
    if k not in st.session_state: st.session_state[k]=pd.DataFrame([vars(r) for r in preset(strategy)])
    edited=st.data_editor(st.session_state[k],disabled=['metric','group'],hide_index=True,
        column_config={'operator':st.column_config.SelectboxColumn(options=['>=','<=','>','<','between'],required=True),
        'lower':st.column_config.NumberColumn(required=True),'upper':st.column_config.NumberColumn(required=True)},key='real_editor_'+strategy)
    st.session_state[k]=edited.copy()
    rules=[Rule(**r) for r in edited.to_dict('records')]
    if any(not math.isfinite(r.lower) or not math.isfinite(r.upper) or r.operator=='between' and r.lower>r.upper for r in rules):
        st.error('Enter finite bounds and ordered ranges.'); st.stop()
    st.caption('CUSTOM' if edited.to_dict('records')!=[vars(r) for r in preset(strategy)] else 'Preset defaults')
status=cache.get('status')
with st.expander('Provider status / failed symbols',expanded=True):
    st.caption('Last refresh attempt: '+(pd.Timestamp(status[0],unit='s',tz='UTC').isoformat() if status else 'Never'))
    if status: st.dataframe(pd.DataFrame(status[1]).T,use_container_width=True)
    st.caption('A failed refresh retains the last successful payload and its original timestamp. Unavailable fields remain UNKNOWN. Old prices are explicitly flagged; stale data is not current market data.')
spy=snapshot(cache,'SPY')['bars']
rows=[]; histories={}; detail={}; snapshots={}
for symbol in universe:
    snap=snapshot(cache,symbol); snapshots[symbol]=snap
    bars=snap['bars']
    history=calculate(bars,spy) if not bars.empty else bars
    histories[symbol]=history
    values={**snap['values'],**(history.iloc[-1].to_dict() if not history.empty else {})}
    result,dd=evaluate(values,rules,weight/100)
    missing=[r.metric for r in rules if r.enabled and (values.get(r.metric) is None or pd.isna(values.get(r.metric)))]
    detail[symbol]=dd
    last=bars.index[-1].date().isoformat() if not bars.empty else 'UNKNOWN'
    stale=not bars.empty and (pd.Timestamp.now(tz='UTC').date()-bars.index[-1].date()).days>4
    rows.append({'Symbol':symbol,**result,'Close USD':float(bars.Close.iloc[-1]) if not bars.empty else None,
        'Missing data':' | '.join(missing),'Price date':last,'Stale price (>4 calendar days)':stale,
        'Fiscal year end':snap['period'],'Price refresh UTC':snap['price_refresh'],
        'Fundamentals payload refresh UTC':snap['fundamentals_refresh'],
        'Price source':snap['price_source'],'Fundamental source':snap['fundamental_source']})
results=pd.DataFrame(rows).sort_values(['Score','Symbol'],ascending=[False,True])
if only: results=results[results.Symbol.isin(watch)]
rank,inspect,methods=st.tabs(['REAL ranked results','REAL stock detail','Methods and limitations'])
with rank:
    classes=st.multiselect('Classification',results.Classification.unique(),default=list(results.Classification.unique()))
    shown=results[results.Classification.isin(classes)]
    st.dataframe(shown,hide_index=True,use_container_width=True)
    export=shown.assign(Mode='REAL',Strategy=strategy,FA_weight=weight/100,Rules=str([vars(r) for r in rules]))
    st.download_button('Download REAL results CSV',export.to_csv(index=False,na_rep='UNKNOWN'),'REAL_screen_results.csv','text/csv')
with inspect:
    symbol=st.selectbox('REAL symbol to inspect',universe)
    snap=snapshots[symbol]
    st.caption(f"Price refresh: {snap['price_refresh']} · Fundamentals payload refresh: {snap['fundamentals_refresh']} · Report period: {snap['period']}")
    st.caption('ROIC and Debt-to-Equity use approximate definitions; see Methods. Forward P/E is UNKNOWN.')
    st.caption(snap['pe_note'])
    st.dataframe(pd.DataFrame(detail[symbol]).fillna('UNKNOWN'),hide_index=True,use_container_width=True)
    if not histories[symbol].empty: st.plotly_chart(stock_chart(histories[symbol].tail(220),symbol),use_container_width=True)
    else: st.info('No successful daily price response. Use Refresh REAL data.')
    st.download_button('Download REAL rule details',pd.DataFrame(detail[symbol]).assign(Mode='REAL',Symbol=symbol,Price_date=rows[universe.index(symbol)]['Price date'],Fiscal_year_end=snap['period']).to_csv(index=False,na_rep='UNKNOWN'),f'REAL_{symbol}_details.csv')
    with st.expander('SEC fact provenance (reported values, periods, filing dates and accession IDs)'):
        st.json(snap['provenance'])
with methods:
    st.markdown(Path('V2A.md').read_text())
