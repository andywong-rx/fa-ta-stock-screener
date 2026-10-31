"""REAL result presentation only; no provider values, rules or scores are changed."""
import math

RANKINGS = {'Combined Score': 'Score', 'FA Score': 'FA', 'TA Score': 'TA'}
LIMITS = {'Top 10': 10, 'Top 20': 20, 'All': None}


def rank_results(results, classifications=(), ranking='Combined Score', limit='All'):
    """Filter, sort descending (UNKNOWN last, symbol tie-break), then limit.

    An empty classification selection means every classification. The caller
    applies its watchlist restriction first; inputs are never mutated.
    """
    column, count = RANKINGS[ranking], LIMITS[limit]
    selected = results[results.Classification.isin(classifications)] if classifications else results
    selected = selected.sort_values([column, 'Symbol'], ascending=[False, True],
                                    na_position='last', kind='stable')
    return (selected.head(count) if count is not None else selected).copy()


def _number(value):
    try:
        number = float(value)
        if math.isfinite(number):
            return str(int(number)) if number.is_integer() else repr(number)
    except (ValueError, TypeError):
        pass
    return 'UNKNOWN'


def explain_rules(details, rules):
    """Explain the evaluated rules using their actual, unrounded edited bounds."""
    thresholds = {(r.group, r.metric): r for r in rules if r.enabled}
    groups_with_mandatory = {d['group'] for d in details if d['mandatory']}
    explained = []
    for detail in details:
        row = dict(detail)
        rule = thresholds[(row['group'], row['metric'])]
        threshold = f'{rule.operator} {_number(rule.lower)}'
        if rule.operator == 'between':
            threshold = f'between {_number(rule.lower)} and {_number(rule.upper)} (inclusive)'
        actual = _number(row['value'])
        state = row['status'].upper()
        if state == 'UNKNOWN':
            message = f'UNKNOWN: actual value is unavailable or non-comparable; threshold {threshold} cannot be evaluated.'
        elif state == 'FAIL':
            message = f'FAIL: actual {actual} does not meet threshold {threshold}.'
        else:
            message = f'PASS: actual {actual} meets threshold {threshold}.'
        role = ('Mandatory' if row['mandatory'] else
                'Qualification fallback (no mandatory rules)' if row['group'] not in groups_with_mandatory
                else 'Optional (score only)')
        row.update(status=state, rule=threshold, actual=actual, role=role, explanation=message)
        explained.append(row)
    return explained


def qualification_summary(details):
    """Report FAIL and UNKNOWN separately, respecting the existing group gates."""
    summary = {}
    for group in ('FA', 'TA'):
        active = [d for d in details if d['group'] == group]
        mandatory = [d for d in active if d['mandatory']]
        gate = mandatory or active
        states = {d['status'] for d in gate}
        summary[f'{group} qualification'] = ('FAIL' if 'FAIL' in states else
                                            'UNKNOWN' if not gate or 'UNKNOWN' in states else 'PASS')
        for state in ('FAIL', 'UNKNOWN'):
            reasons = [f"{d['role']} · {d['metric']} · {d['explanation']}" for d in gate if d['status'] == state]
            if not gate and state == 'UNKNOWN':
                reasons = ['No enabled rules; qualification is unavailable.']
            summary[f'{group} {state} reasons'] = ' | '.join(reasons) or 'None'
    return summary
