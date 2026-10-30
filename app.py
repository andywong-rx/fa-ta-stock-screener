"""Streamlit Community Cloud entry point; no network market data or trading."""
from datetime import datetime, timezone
import math
import pandas as pd
import streamlit as st
from screener.providers import DemoProvider, AS_OF
from screener.indicators import Definitions, calculate
from screener.rules import PRESETS, Rule, preset, evaluate
from screener.charts import stock_chart

st.set_page_config(page_title='DEMO | Signal Studio', page_icon='◈', layout='wide')
st.title('◈ Signal Studio · DEMO')
st.caption('US STOCK SCREENER / VERSION 1 / SYNTHETIC DATA ONLY')
st.warning('DEMO — all prices, fundamentals, benchmark values and signals are fictional. No live market data or trading.')
provider = DemoProvider()
with st.sidebar:
    st.header('DEMO strategy desk')
    strategy = st.selectbox('Strategy', PRESETS)
    fa_weight = st.slider('Fundamental weight (%)',0,100,60)
    st.caption(f'Technical weight: {100-fa_weight}%')
    st.caption('Edits persist per preset during this session. Editing the strict preset creates a custom variant.')
    if st.button('Reset selected preset'):
        st.session_state.pop('rules_'+strategy,None)
        st.session_state['revision_'+strategy] = st.session_state.get('revision_'+strategy,0)+1
        st.rerun()
    st.subheader('DEMO watchlist')
    watch = st.multiselect('Saved in this session',provider.symbols(),key='watchlist')
    only_watch = st.checkbox('Show watchlist only')
    st.caption('Watchlist is session-only; export it to retain a copy.')
    st.download_button('Export DEMO watchlist',pd.DataFrame({'DEMO symbol':watch}).to_csv(index=False),'DEMO_watchlist.csv','text/csv')

with st.expander('Edit screening rules',expanded=False):
    st.caption('Percentages use percentage points (50 means 50%). Boolean indicators use 1=true, 0=false. All enabled rules contribute equally to their group score; mandatory rules gate qualification.')
    key = 'rules_'+strategy
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame([vars(r) for r in preset(strategy)])
    edited = st.data_editor(st.session_state[key],hide_index=True,use_container_width=True,
        disabled=['metric','group'],key='editor_'+strategy+str(st.session_state.get('revision_'+strategy,0)),
        column_config={'operator':st.column_config.SelectboxColumn(options=['>=','<=','>','<','between'],required=True),
                       'lower':st.column_config.NumberColumn(required=True),'upper':st.column_config.NumberColumn(required=True)})
    st.session_state[key] = edited.copy()
    rules = [Rule(**row) for row in edited.to_dict('records')]
    if any(r.operator=='between' and r.lower>r.upper for r in rules):
        st.error('Range lower bounds must not exceed upper bounds.'); st.stop()
    if any(not math.isfinite(r.lower) or not math.isfinite(r.upper) for r in rules):
        st.error('Enter finite numeric rule bounds.'); st.stop()
    custom = edited.to_dict('records') != [vars(r) for r in preset(strategy)]
    st.caption('Custom variant' if custom else 'Preset defaults')

with st.expander('Metric definitions & calculation settings'):
    st.markdown('''DEMO fundamentals are supplied synthetic snapshots: revenue/EPS growth = latest fiscal year vs prior year (%); gross margin = gross profit/revenue (%); ROIC = NOPAT/average invested capital (%); P/E = price/TTM diluted EPS; forward P/E = price/next fiscal year estimated diluted EPS; FCF = operating cash flow − capex (USD); debt/equity = total debt/book equity; share count growth = diluted weighted-average shares YoY (%). Future providers must use positive denominators for valuation and return undefined ratios as missing; EPS growth from a nonpositive base is unknown. These are annual definitions, not quarterly growth.''')
    st.caption('Higher highs/lows compares rolling maximum High and minimum Low over two consecutive nonoverlapping windows. This is a causal window definition, not future-confirmed pivots. Relative performance is stock return minus synthetic SPY return. OBV begins at zero; missing volume makes cumulative OBV unknown thereafter. RSI uses Wilder smoothing; MACD uses causal EMAs. SMA50/200, RSI14 and MACD12/26/9 are fixed named definitions.')
    cols=st.columns(2)
    trend=cols[0].number_input('High/low window (sessions)',2,100,20)
    relative=cols[1].number_input('Relative performance window',2,200,63)
    volume=cols[0].number_input('Preceding RVOL sessions',2,100,20)
    breakout=cols[1].number_input('Previous high window',2,100,20)
    obv=cols[0].number_input('OBV SMA window',2,100,10)
    st.caption('Changing windows creates custom metric definitions. Synthetic history uses business weekdays, not an exchange holiday calendar. No interpolation or backfilling is used.')
definitions=Definitions(trend,relative,volume,breakout,obv)
strict_defaults = strategy==PRESETS[-1] and not custom and definitions==Definitions()
st.info(('Original Strict · all 19 rules mandatory' if strict_defaults else strategy+(' · CUSTOM' if custom or definitions!=Definitions() else ''))+' · DEMO')
benchmark=provider.snapshot('SPY')
rows, histories, details = [], {}, {}
for symbol in provider.symbols():
    snapshot=provider.snapshot(symbol)
    history=calculate(snapshot.bars,benchmark.bars,definitions)
    histories[symbol]=history
    values={**snapshot.fundamentals,**history.iloc[-1].to_dict()}
    result,detail=evaluate(values,rules,fa_weight/100)
    rows.append({'Symbol':symbol,**result,'Price (DEMO USD)':history.Close.iloc[-1],
        'Data source':'DEMO synthetic','Price as of UTC':snapshot.as_of.isoformat(),
        'Fundamentals as of UTC':snapshot.fundamental_as_of.isoformat()})
    details[symbol]=detail
results=pd.DataFrame(rows).sort_values(['Score','Symbol'],ascending=[False,True],na_position='last')
filtered=results[results.Symbol.isin(watch)] if only_watch else results
st.caption(f'DEMO snapshot: {AS_OF.isoformat()} · Evaluated: {datetime.now(timezone.utc).isoformat(timespec="seconds")} · Fixed demo vintage, never live')
cols=st.columns(3)
cols[0].metric('DEMO universe',len(filtered))
cols[1].metric('DEMO fully qualified',int((filtered.Classification=='fully qualified').sum()))
cols[2].metric('DEMO unknown',int((filtered.Classification=='unknown').sum()))
rank_tab,inspect_tab,method_tab=st.tabs(['DEMO ranked results','DEMO stock detail','Scoring guide'])
with rank_tab:
    selected_classes=st.multiselect('Classification filter',results.Classification.unique().tolist(),default=results.Classification.unique().tolist())
    shown=filtered[filtered.Classification.isin(selected_classes)]
    st.dataframe(shown,hide_index=True,use_container_width=True,column_config={c:st.column_config.NumberColumn(format='%.2f') for c in ['FA','TA','Score','Price (DEMO USD)']})
    export=shown.copy()
    export['Strategy']=strategy+(' CUSTOM' if custom else '')
    export['FA weight']=fa_weight/100
    export['Metric definitions']=str(vars(definitions))
    export['Rules']=str([vars(r) for r in rules])
    st.download_button('Download DEMO results CSV',export.to_csv(index=False),'DEMO_screen_results.csv','text/csv')
with inspect_tab:
    symbol=st.selectbox('DEMO symbol to inspect',provider.symbols())
    st.caption('DEMO values only · unknown means missing or insufficient history · disabled rules omitted')
    st.dataframe(pd.DataFrame(details[symbol]),hide_index=True,use_container_width=True)
    st.plotly_chart(stock_chart(histories[symbol].tail(220),symbol),use_container_width=True)
    st.download_button('Download DEMO rule details',pd.DataFrame(details[symbol]).assign(Source='DEMO synthetic',Symbol=symbol,As_of_UTC=AS_OF.isoformat()).to_csv(index=False),f'DEMO_{symbol}_details.csv','text/csv')
with method_tab:
    st.markdown('''Each group score is 100 × passing enabled rules / enabled rules. Missing metrics receive zero credit and remain in the denominator. Disabled rules do not contribute. Combined score = FA × fundamental weight + TA × technical weight (default 60/40).

Qualification requires every enabled mandatory rule in its group to pass. Score-only rules affect ranking but cannot override a mandatory failure. If a group has no mandatory rules, all its enabled rules determine qualification; no enabled rules means unknown. A known failure takes precedence over unknown within a group. Any unknown group yields an unknown overall classification; otherwise the two group outcomes yield fully qualified, FA-only, TA-only, or neither. Scores measure rule matches, not investment quality or return forecasts.

DEMO12 deliberately contains missing ROIC and current volume to demonstrate unknown handling. Presets and watchlists persist only for this browser session. The Original Strict default has all nine fundamental and ten technical rules enabled and mandatory; edited variants are labeled CUSTOM. No brokerage integration or order execution exists.''')
