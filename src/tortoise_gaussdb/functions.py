"""GaussDB expressions with validated options and bound value arguments."""

from pypika_tortoise import analytics, Order
from pypika_tortoise.terms import Function as SQLFunction
from tortoise.expressions import Expression, F, Function, ResolveResult
from tortoise.exceptions import ConfigurationError

PARTS = frozenset(
    {
        "year",
        "quarter",
        "month",
        "week",
        "day",
        "hour",
        "minute",
        "second",
        "microseconds",
        "epoch",
        "dow",
        "doy",
    }
)


class JSONF(F):
    """F-compatible JSON attribute access with bound path components.

    Use JSONF('data__key__0') instead of upstream F for JSON paths.
    """

    def resolve(self, context):
        from pypika_tortoise.terms import JSONAttributeCriterion

        result = super().resolve(context)
        if isinstance(result.term, JSONAttributeCriterion):
            result.term = SQLFunction(
                "jsonb_extract_path_text",
                result.term.json_column,
                *(str(key) for key in result.term.path),
            )
        return result


class Extract(Function):
    def __init__(self, field, part, timezone=None):
        if part not in PARTS:
            raise ConfigurationError("Unsupported datetime part")
        super().__init__(field, part, timezone)

    def _get_function_field(self, field, part, timezone):
        if timezone is not None:
            field = SQLFunction("timezone", timezone, field)
        return SQLFunction("date_part", part, field)


class DateTrunc(Extract):
    def __init__(self, field, part, timezone=None):
        if part not in PARTS - {"epoch", "dow", "doy"}:
            raise ConfigurationError("Unsupported truncation part")
        super().__init__(field, part, timezone)

    def _get_function_field(self, field, part, timezone):
        if timezone is not None:
            field = SQLFunction("timezone", timezone, field)
        return SQLFunction("date_trunc", part, field)


class Window(Expression):
    """Ranking/aggregate window, with explicit ordering and optional ROWS frame.

    Example: Window('row_number', order_by=('id',), partition_by=('category',)).
    rows=(None, 0) means ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW.
    Values <0/>0 indicate PRECEDING/FOLLOWING offsets, None is unbounded.
    """

    FUNCTIONS = {
        "row_number": analytics.RowNumber,
        "rank": analytics.Rank,
        "dense_rank": analytics.DenseRank,
        "sum": analytics.Sum,
        "avg": analytics.Avg,
        "min": analytics.Min,
        "max": analytics.Max,
        "count": analytics.Count,
        "lag": analytics.Lag,
        "lead": analytics.Lead,
    }
    RANKING = {"row_number", "rank", "dense_rank"}

    def __init__(
        self, function, field=None, *, partition_by=(), order_by=(), rows=None
    ):
        if function not in self.FUNCTIONS or not order_by:
            raise ConfigurationError(
                "Window requires a supported function and explicit order_by"
            )
        if (function in self.RANKING) != (field is None):
            raise ConfigurationError(
                "Window aggregate/offset functions require a field; rankings do not"
            )
        if rows is not None:
            if function in self.RANKING | {"lag", "lead"} or len(rows) != 2:
                raise ConfigurationError("ROWS frames apply to aggregate windows only")
            if any(
                x is not None and (isinstance(x, bool) or not isinstance(x, int))
                for x in rows
            ):
                raise ConfigurationError("Frame offsets must be integers or None")
            if rows[0] is not None and rows[1] is not None and rows[0] > rows[1]:
                raise ConfigurationError("Frame start must not exceed end")
        self.function, self.field, self.partitions, self.ordering, self.rows = (
            function,
            field,
            partition_by,
            order_by,
            rows,
        )

    def resolve(self, context):
        joins = []

        def resolve_field(name):
            result = F(name).resolve(context)
            joins.extend(result.joins)
            return result.term

        args = [] if self.field is None else [resolve_field(self.field)]
        term = self.FUNCTIONS[self.function](*args)
        if self.partitions:
            term = term.over(*(resolve_field(x) for x in self.partitions))
        for name in self.ordering:
            descending = name.startswith("-")
            term = term.orderby(
                resolve_field(name[1:] if descending else name),
                order=Order.desc if descending else Order.asc,
            )
        if self.rows is not None:

            def edge(value, start):
                if value is None:
                    return analytics.Preceding() if start else analytics.Following()
                if value == 0:
                    return analytics.CURRENT_ROW
                return (
                    analytics.Preceding(-value)
                    if value < 0
                    else analytics.Following(value)
                )

            term = term.rows(edge(self.rows[0], True), edge(self.rows[1], False))
        return ResolveResult(term=term, joins=list(set(joins)))


class JSONExtract(Function):
    """Extract a JSON path using bound keys; use text=False to preserve JSON types."""

    def __init__(self, field, *path, text=True):
        if not path or any(
            not isinstance(key, (str, int)) or isinstance(key, bool) for key in path
        ):
            raise ConfigurationError("JSONExtract needs string/integer path components")
        self.as_text = text
        super().__init__(field, *(str(key) for key in path))

    def _get_function_field(self, field, *path):
        return SQLFunction(
            "jsonb_extract_path_text" if self.as_text else "jsonb_extract_path",
            field,
            *path,
        )


class JSONObject(Expression):
    """Build JSON from keyword values; use F('field') to reference a column."""

    def __init__(self, **values):
        self.values = values

    def resolve(self, context):
        import json
        from pypika_tortoise.functions import Cast
        from pypika_tortoise.terms import ValueWrapper

        args = []
        joins = []
        for key, value in self.values.items():
            if isinstance(value, Expression):
                result = value.resolve(context)
                term = result.term
                joins.extend(result.joins)
            else:
                term = Cast(
                    ValueWrapper(json.dumps(value, ensure_ascii=False)), "jsonb"
                )
            args.extend([Cast(ValueWrapper(key), "text"), term])
        return ResolveResult(
            term=SQLFunction("jsonb_build_object", *args), joins=list(set(joins))
        )
