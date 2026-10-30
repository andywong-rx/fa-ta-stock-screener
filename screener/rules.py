from dataclasses import dataclass, replace
import math
from .providers import METRICS

@dataclass
class Rule:
    metric: str
    group: str
    operator: str = '>='
    lower: float = 1
    upper: float = 1
    enabled: bool = True
    mandatory: bool = True

PRESETS = ['Quality Growth + Established Uptrend', 'Growth + Breakout',
           'Strong Fundamentals + Awaiting Uptrend', 'Original Strict 19-Filter Strategy']
TECHNICAL = ['Price > SMA50','Price > SMA200','SMA50 > SMA200','Higher highs / higher lows',
             'RSI(14)','MACD > signal','Relative vs SPY','RVOL','Close > previous high','Rising OBV']

def preset(name):
    rules = [Rule(m,'FA',op,val) for m,op,val in zip(METRICS,
        ['>=','>=','>=','>=','<=','<=','>','<=','<='], [50,50,50,12,30,20,0,1,5])]
    rules += [Rule(m,'TA') for m in TECHNICAL]
    for r in rules:
        if r.metric == 'RSI(14)': r.operator,r.lower,r.upper = 'between',50,70
        if r.metric == 'Relative vs SPY': r.operator,r.lower = '>',0
        if r.metric == 'RVOL': r.lower = 1.5
    if name != PRESETS[-1]:
        for r in rules:
            if r.metric in METRICS[:2]: r.lower = 20
            if r.metric == 'Gross Margin': r.lower = 40
            if r.metric in ['RVOL','Close > previous high']: r.mandatory = name == PRESETS[1]
            if name == PRESETS[2] and r.group == 'TA': r.mandatory = False
            if name == PRESETS[1] and r.metric in ['P/E','Forward P/E']: r.mandatory = False
    return rules

def status(value, rule):
    try:
        value = float(value)
        if not math.isfinite(value): return 'unknown'
    except (TypeError, ValueError): return 'unknown'
    passed = {'>=':lambda:value >= rule.lower,'<=':lambda:value <= rule.lower,
              '>':lambda:value > rule.lower,'<':lambda:value < rule.lower,
              'between':lambda:rule.lower <= value <= rule.upper}[rule.operator]()
    return 'pass' if passed else 'fail'

def evaluate(values, rules, fa_weight=.6):
    if not 0 <= fa_weight <= 1: raise ValueError('Invalid FA weight')
    details = []
    groups = {}
    for group in ['FA','TA']:
        active = [r for r in rules if r.enabled and r.group == group]
        states = [(r,status(values.get(r.metric),r)) for r in active]
        score = 100 * sum(s == 'pass' for _,s in states)/len(active) if active else None
        mandatory = [s for r,s in states if r.mandatory]
        # No mandatory rules: require all active score rules for qualification.
        gate = mandatory or [s for _,s in states]
        qualification = 'fail' if 'fail' in gate else 'unknown' if not gate or 'unknown' in gate else 'pass'
        groups[group] = (score,qualification)
        details.extend(dict(metric=r.metric,group=group,value=values.get(r.metric),
                            rule=f'{r.operator} {r.lower:g}'+(f' to {r.upper:g}' if r.operator=='between' else ''),
                            mandatory=r.mandatory,status=s) for r,s in states)
    fa,ta = groups['FA'][1],groups['TA'][1]
    classification = 'unknown' if 'unknown' in (fa,ta) else {('pass','pass'):'fully qualified',
        ('pass','fail'):'FA-only',('fail','pass'):'TA-only',('fail','fail'):'neither'}[(fa,ta)]
    total = None if any(groups[g][0] is None for g in groups) else groups['FA'][0]*fa_weight+groups['TA'][0]*(1-fa_weight)
    return dict(FA=groups['FA'][0],TA=groups['TA'][0],Score=total,Classification=classification),details
