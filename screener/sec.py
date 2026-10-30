"""Conservative USD US-GAAP annual fundamentals with auditable fact selection."""
from datetime import date
import math
from .providers import METRICS

TAGS = {
 'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet','RevenueFromContractWithCustomerIncludingAssessedTax'],
 'eps': ['EarningsPerShareDiluted'], 'gross': ['GrossProfit'],
 'cost': ['CostOfRevenue','CostOfGoodsAndServicesSold'],
 'operating': ['OperatingIncomeLoss'], 'tax': ['IncomeTaxExpenseBenefit'],
 'pretax': ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest','IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments'],
 'cashflow': ['NetCashProvidedByUsedInOperatingActivities'],
 'capex': ['PaymentsToAcquirePropertyPlantAndEquipment'],
 'equity': ['StockholdersEquity'], 'cash': ['CashAndCashEquivalentsAtCarryingValue'],
 'debt': ['LongTermDebtCurrent','LongTermDebtNoncurrent'],
 'shares': ['WeightedAverageNumberOfDilutedSharesOutstanding']}

def extract(company, cutoff=None):
    cutoff = str(cutoff or date.today())[:10]
    facts = company.get('facts',{}).get('us-gaap',{})
    provenance = {}
    def rows(key):
        unit = 'USD/shares' if key=='eps' else 'shares' if key=='shares' else 'USD'
        result=[]
        for tag in TAGS[key]:
            for f in facts.get(tag,{}).get('units',{}).get(unit,[]):
                if f.get('form') not in ('10-K','10-K/A','10-Q','10-Q/A'): continue
                if f.get('filed','9999') > cutoff or f.get('end','9999') > cutoff: continue
                try:
                    if not math.isfinite(float(f['val'])): continue
                except (ValueError,TypeError,KeyError): continue
                result.append(dict(f,tag=tag,unit=unit))
        # Latest amendment/restatement known at cutoff wins for the same period and tag.
        unique={}
        for f in sorted(result,key=lambda x:(x['filed'],x.get('accn',''))):
            unique[(f['tag'],f.get('start'),f['end'])]=f
        return list(unique.values())
    def days(f):
        return (date.fromisoformat(f['end'])-date.fromisoformat(f['start'])).days+1 if f.get('start') else 0
    def annuals(key):
        rr=rows(key)
        # Select one coherent tag, never splice historical tag series.
        eligible=[f for f in rr if 350<=days(f)<=380]
        if not eligible: return []
        newest=max(f['end'] for f in eligible)
        for tag in TAGS[key]:
            found=[f for f in eligible if f['tag']==tag]
            if any(f['end']==newest for f in found):
                return sorted(found,key=lambda f:f['end'],reverse=True)
        return []
    revs=annuals('revenue')
    anchor=revs[0] if revs else None
    def annual(key, prior=False):
        if not anchor: return None
        candidates=annuals(key)
        end=date.fromisoformat(anchor['end'])
        for f in candidates:
            gap=(end-date.fromisoformat(f['end'])).days
            if (prior and 350<=gap<=380 or not prior and gap==0) and abs(days(f)-days(anchor))<=8:
                if not prior and f['start']!=anchor['start']: continue
                provenance[key+('_prior' if prior else '')]=f
                return f['val']
        return None
    def instant(key,end):
        rr=[f for f in rows(key) if not f.get('start') and f['end']==end]
        for tag in TAGS[key]:
            ff=[f for f in rr if f['tag']==tag]
            if ff:
                f=max(ff,key=lambda f:f['filed']); provenance[key+'_'+end]=f; return f['val']
        return None
    def ratio(a,b,scale=1):
        return scale*a/b if a is not None and b is not None and b>0 else None
    def growth(key):
        a,b=annual(key),annual(key,True)
        return ratio(a-b,b,100) if a is not None and b is not None else None
    out=dict.fromkeys(METRICS)
    revenue=annual('revenue'); gross=annual('gross')
    if gross is None:
        cost=annual('cost')
        gross=revenue-cost if revenue is not None and cost is not None else None
    out.update({'Revenue Growth YoY':growth('revenue'),'EPS Growth YoY':growth('eps'),
                'Share Count Growth':growth('shares'),'Gross Margin':ratio(gross,revenue,100)})
    cf,capex=annual('cashflow'),annual('capex')
    out['Free Cash Flow']=cf-capex if cf is not None and capex is not None and capex>=0 else None
    # Debt component tags are required individually; absence is never assumed zero.
    def capital(end):
        eq=instant('equity',end); cash=instant('cash',end)
        debt=[]
        for tag in TAGS['debt']:
            ff=[f for f in rows('debt') if f['tag']==tag and not f.get('start') and f['end']==end]
            f=max(ff,key=lambda f:f['filed']) if ff else None
            if f: provenance[tag+'_'+end]=f
            debt.append(f['val'] if f else None)
        total=sum(debt) if all(v is not None and v>=0 for v in debt) else None
        invested=eq+total-cash if eq is not None and eq>0 and total is not None and cash is not None else None
        return eq,total,invested
    if anchor:
        eq,debt,ic=capital(anchor['end'])
        out['Debt-to-Equity']=ratio(debt,eq)
        prior_revs=[f for f in revs if 350<=(date.fromisoformat(anchor['end'])-date.fromisoformat(f['end'])).days<=380]
        prev_ic=capital(prior_revs[0]['end'])[2] if prior_revs else None
        op,tax,pretax=annual('operating'),annual('tax'),annual('pretax')
        rate=ratio(tax,pretax)
        if rate is not None and 0<=rate<=1 and op is not None and ic is not None and ic>0 and prev_ic is not None and prev_ic>0:
            out['ROIC']=100*op*(1-rate)/((ic+prev_ic)/2)
    return out,provenance,anchor

def trailing_eps(company, cutoff):
    """Annual EPS + subsequent YTD EPS - comparable prior YTD EPS; no annualization."""
    _,p,anchor=extract(company,cutoff)
    if not anchor: return None,[]
    rows=company.get('facts',{}).get('us-gaap',{}).get('EarningsPerShareDiluted',{}).get('units',{}).get('USD/shares',[])
    rows=[f for f in rows if f.get('form') in ('10-K','10-K/A','10-Q','10-Q/A') and f.get('filed','9999')<=str(cutoff)[:10] and f.get('start')]
    dedup={}
    for f in sorted(rows,key=lambda x:(x['filed'],x.get('accn',''))): dedup[(f['start'],f['end'])]=f
    rows=list(dedup.values())
    annual=p.get('eps')
    if not annual: return None,[]
    end=date.fromisoformat(annual['end'])
    later=[f for f in rows if date.fromisoformat(f['start'])==end.fromordinal(end.toordinal()+1) and f['end']<=str(cutoff)[:10] and 60<=(date.fromisoformat(f['end'])-end).days<=300]
    if not later:
        # A later filing without a compatible YTD EPS fact must not silently yield stale annual EPS.
        if any(f['end']>annual['end'] for f in rows): return None,[]
        if (date.fromisoformat(str(cutoff)[:10])-end).days>150: return None,[]
        return annual['val'],[annual]
    ytd=max(later,key=lambda f:f['end'])
    if (date.fromisoformat(str(cutoff)[:10])-date.fromisoformat(ytd['end'])).days>150: return None,[]
    duration=(date.fromisoformat(ytd['end'])-date.fromisoformat(ytd['start'])).days
    prior=[f for f in rows if 350<=(date.fromisoformat(ytd['end'])-date.fromisoformat(f['end'])).days<=380 and abs((date.fromisoformat(f['end'])-date.fromisoformat(f['start'])).days-duration)<=8]
    if not prior: return None,[]
    old=max(prior,key=lambda f:f['filed'])
    value=annual['val']+ytd['val']-old['val']
    return value,[annual,ytd,old]
