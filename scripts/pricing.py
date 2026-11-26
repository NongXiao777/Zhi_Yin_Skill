"""Quote a selling price from explicit local costs and a profit or margin target."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import json
from pathlib import Path
import re

from collected_products import channel_price
from erp_products import ProductError


COST_FIELDS = ('unit_cost', 'shipping_cost', 'packaging_cost', 'other_cost')
FILE_LIMIT = 65536


def _decimal(value, field):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ProductError(f'{field} must be a finite nonnegative decimal.')
    raw = str(value).strip()
    if len(raw) > 80:
        raise ProductError(f'{field} exceeds the supported decimal size.')
    try:
        number = Decimal(raw)
        if not number.is_finite() or number < 0:
            raise ValueError()
        # Bound arithmetic size while retaining fractional monetary and rate inputs.
        if (number > Decimal('1000000000000') or number.as_tuple().exponent < -18
                or number.as_tuple().exponent > 12):
            raise ProductError(f'{field} supports amounts up to 1 trillion and 18 decimal places.')
        return number
    except (InvalidOperation, ValueError):
        raise ProductError(f'{field} must be a finite nonnegative decimal.') from None


def _text(number):
    return format(number, 'f')


def quote_spec(spec):
    if not isinstance(spec, dict):
        raise ProductError('Pricing input must be a JSON object.')
    currency = spec.get('currency')
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Za-z]{3}', currency):
        raise ProductError('Use a three-letter currency code for every amount in the quote.')
    missing = [field for field in (*COST_FIELDS, 'platform_fee_rate') if field not in spec]
    if missing:
        raise ProductError('Pricing input is missing: ' + ', '.join(missing))
    targets = [field for field in ('target_profit', 'target_margin') if field in spec]
    if len(targets) != 1:
        raise ProductError('Supply exactly one target_profit amount or target_margin fraction.')
    costs = {field: _decimal(spec[field], field) for field in COST_FIELDS}
    fee = _decimal(spec['platform_fee_rate'], 'platform_fee_rate')
    target_field = targets[0]
    target = _decimal(spec[target_field], target_field)
    if fee >= 1:
        raise ProductError('platform_fee_rate must be a fraction from 0 up to, but excluding, 1.')
    with localcontext() as context:
        context.prec = 64
        context.rounding = ROUND_CEILING
        total_cost = sum(costs.values(), Decimal(0))
        if target_field == 'target_profit':
            minimum = (total_cost + target) / (1 - fee)
            formula = '(total_cost + target_profit) / (1 - platform_fee_rate)'
        else:
            if target >= 1 or fee + target >= 1:
                raise ProductError('target_margin must be a fraction with platform_fee_rate + target_margin < 1.')
            minimum = total_cost / (1 - fee - target)
            formula = 'total_cost / (1 - platform_fee_rate - target_margin)'
        price = channel_price(minimum)
        platform_fee = price * fee
        net_profit = price - platform_fee - total_cost
        net_margin = net_profit / price
        target_met = net_profit >= target if target_field == 'target_profit' else net_profit >= price * target
        result = {
            'ok': True, 'mode': 'local_pricing_quote', 'currency': currency.upper(),
            'costs': {field: _text(value) for field, value in costs.items()},
            'total_cost': _text(total_cost), 'platform_fee_rate': _text(fee),
            target_field: _text(target), 'formula': formula,
            'required_price': _text(minimum), 'quoted_price': _text(price),
            'price_endings': ['.49', '.89', '.99'],
            'projected_platform_fee': _text(platform_fee), 'projected_net_profit': _text(net_profit),
            'projected_net_margin': _text(net_margin), 'target_met': target_met,
            'business_requests_sent': 0, 'erp_surcharge_inferred': False,
        }
        # These are external comparison values, never evidence that ERP money is
        # a difference between a channel price and a supplied baseline.
        comparison = {}
        if 'channel_base_price' in spec:
            base = _decimal(spec['channel_base_price'], 'channel_base_price')
            comparison.update(channel_base_price=_text(base), quoted_price_delta=_text(price - base))
        if 'current_surcharge' in spec:
            comparison['reported_current_surcharge'] = _text(_decimal(spec['current_surcharge'], 'current_surcharge'))
        if comparison:
            result['comparison'] = {**comparison, 'comparison_only': True}
        return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProductError('Pricing input contains a duplicate JSON field.')
        result[key] = value
    return result


def pricing_quote(file):
    path = Path(file)
    try:
        if path.stat().st_size > FILE_LIMIT:
            raise ProductError('Pricing input exceeds the 64 KB size limit.')
        spec = json.loads(path.read_text(encoding='utf-8-sig'), parse_float=Decimal,
                          parse_constant=Decimal, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ProductError('Could not read the local pricing JSON file.') from None
    return quote_spec(spec)
