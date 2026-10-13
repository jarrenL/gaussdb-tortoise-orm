"""JSON path filters with bound path components, including hostile key names."""

import datetime
import decimal
import operator
from pypika_tortoise.functions import Cast
from pypika_tortoise.terms import Function
from tortoise.contrib.postgres.json_functions import operator_keywords
from tortoise.query_utils import get_json_filter_operator
from tortoise.filters import between_and


def json_filter(field, value):
    keys, value, operation = get_json_filter_operator(value, operator_keywords)
    # Never use upstream's inline ->>'key' path renderer: keys may contain quotes.
    term = Function("jsonb_extract_path_text", field, *(str(key) for key in keys))
    date_operations = {
        operator_keywords[name]
        for name in (
            "year",
            "quarter",
            "month",
            "week",
            "day",
            "hour",
            "minute",
            "second",
            "microsecond",
        )
    }
    if operation in date_operations or isinstance(
        value, (datetime.date, datetime.datetime)
    ):
        term = Cast(term, "timestamp")
    elif operation in {
        operator.gt,
        operator.ge,
        operator.lt,
        operator.le,
        between_and,
    } or type(value) in (int, float, decimal.Decimal):
        term = Cast(term, "numeric")
    elif isinstance(value, bool):
        term = Cast(term, "boolean")
    return operation(term, value)
