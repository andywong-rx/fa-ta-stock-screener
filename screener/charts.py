import plotly.graph_objects as go
from plotly.subplots import make_subplots

def stock_chart(d, symbol):
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.04,
                        row_heights=[.5,.16,.18,.16], subplot_titles=['DEMO price','DEMO RSI(14)','DEMO MACD','DEMO volume'])
    fig.add_trace(go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name='DEMO OHLC'),row=1,col=1)
    for col,color in [('SMA50','#21c7b7'),('SMA200','#eeb75a')]:
        fig.add_trace(go.Scatter(x=d.index,y=d[col],name=col,line=dict(color=color,width=1.5)),row=1,col=1)
    fig.add_trace(go.Scatter(x=d.index,y=d['RSI(14)'],name='RSI'),row=2,col=1)
    for y in [50,70]: fig.add_hline(y=y,line_dash='dot',row=2,col=1)
    for col in ['MACD','Signal']:
        fig.add_trace(go.Scatter(x=d.index,y=d[col],name=col),row=3,col=1)
    fig.add_trace(go.Bar(x=d.index,y=d.MACD-d.Signal,name='Histogram'),row=3,col=1)
    fig.add_trace(go.Bar(x=d.index,y=d.Volume,name='Volume',marker_color='#21c7b7'),row=4,col=1)
    fig.update_layout(title=f'{symbol} · DEMO synthetic history',height=850,template='plotly_dark',
                      xaxis_rangeslider_visible=False,margin=dict(l=10,r=10,t=60,b=10),legend=dict(orientation='h'))
    return fig
