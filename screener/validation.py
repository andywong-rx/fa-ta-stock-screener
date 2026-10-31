"""Validate external SEC payloads before storing or deriving financial values."""
from datetime import date
import math

class InvalidSECResponse(ValueError):
    def __init__(self):
        super().__init__('SEC data is unavailable or has an unsupported response structure.')

def _require(condition):
    if not condition:
        raise InvalidSECResponse()

def _day(value):
    _require(isinstance(value, str) and len(value) == 10)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidSECResponse() from None

def validate_tickers(data):
    _require(isinstance(data, dict) and bool(data))
    for entry in data.values():
        _require(isinstance(entry, dict))
        _require(type(entry.get('cik_str')) is int and 0 < entry['cik_str'] < 10**10)
        _require(isinstance(entry.get('ticker'), str) and bool(entry['ticker'].strip()))
        _require(isinstance(entry.get('title'), str) and bool(entry['title'].strip()))

def validate_company(data, expected_cik=None):
    _require(isinstance(data, dict))
    _require(type(data.get('cik')) is int and 0 < data['cik'] < 10**10)
    if expected_cik is not None:
        _require(data['cik'] == expected_cik)
    _require(isinstance(data.get('entityName'), str) and bool(data['entityName'].strip()))
    _require(isinstance(data.get('facts'), dict))
    # Empty/unsupported taxonomies are valid responses, but yield UNKNOWN metrics.
    for taxonomy in data['facts'].values():
        _require(isinstance(taxonomy, dict))
        for tag in taxonomy.values():
            _require(isinstance(tag, dict) and isinstance(tag.get('units'), dict))
            for unit, entries in tag['units'].items():
                _require(isinstance(unit, str) and bool(unit) and isinstance(entries, list))
                for fact in entries:
                    _require(isinstance(fact, dict))
                    value = fact.get('val')
                    _require(type(value) in (int, float) and math.isfinite(value))
                    end = _day(fact.get('end'))
                    _day(fact.get('filed'))
                    if 'start' in fact:
                        _require(_day(fact['start']) <= end)
                    for field in ('form', 'accn'):
                        _require(isinstance(fact.get(field), str) and bool(fact[field].strip()))
