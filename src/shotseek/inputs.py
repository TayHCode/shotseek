"""Strict primitives for user-authored structured inputs."""
import json
import math

# Seconds stay well inside exact millisecond arithmetic and stored integer ranges.
MAX_SECONDS = 10_000_000


def seconds(value, field):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= MAX_SECONDS
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(field + f" must be a finite number from 0 to {MAX_SECONDS} seconds")
    return value


def text(value, field, nonempty=True):
    if not isinstance(value, str) or nonempty and not value.strip():
        raise ValueError(field + " must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError(field + " must contain valid Unicode") from None
    return value


def times(start, end, field):
    if start is None and end is None:
        return
    seconds(start, field + ".start")
    seconds(end, field + ".end")
    if start > end:
        raise ValueError(field + " times must have 0 <= start <= end")


def json_document(value):
    def constant(unused):
        raise ValueError("JSON numbers must be finite")
    def pairs(values):
        result = {}
        for key, item in values:
            if key in result:
                raise ValueError("JSON object keys must be unique")
            result[key] = item
        return result
    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("JSON numbers must be finite")
        return number
    try:
        return json.loads(value, parse_constant=constant, parse_float=floating, object_pairs_hook=pairs)
    except RecursionError:
        raise ValueError("JSON nesting exceeds the supported depth") from None
