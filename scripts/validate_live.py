"""Collect a five-stock audit packet; manually reconcile it to original filings."""
import argparse
import json
from pathlib import Path
import sys
import tomllib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from screener.real import Cache, refresh, snapshot
from screener.config import load_sec_user_agent

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--secrets-file',default='.streamlit/secrets.toml')
    p.add_argument('--output',default='work/live-audit.json')
    args=p.parse_args()
    stocks=['AAPL','MSFT','NVDA','AMD','AMZN']
    try:
        with Path(args.secrets_file).open('rb') as handle:
            user_agent=load_sec_user_agent(tomllib.load(handle))
    except Exception:
        user_agent=None
    if user_agent is None:
        sys.exit('SEC identity is missing or invalid. Configure the private local Secrets file.')
    cache=Cache()
    report=refresh(stocks,user_agent,cache)
    packet={'status':report,'cache_warnings':cache.warnings,'verified_against_original_filings':False,'stocks':{}}
    for s in stocks:
        data=snapshot(cache,s)
        packet['stocks'][s]={k:v for k,v in data.items() if k!='bars'}
    dest=Path(args.output); dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(packet,indent=2,default=str))
    print('Audit packet saved; independent filing verification still required.')
    if any('FAILED' in v or 'UNAVAILABLE' in v for status in report.values() for v in status.values()): sys.exit(1)
