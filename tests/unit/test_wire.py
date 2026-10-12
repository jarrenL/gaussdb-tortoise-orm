import datetime
import struct
import pytest
from tortoise_gaussdb.wire_adapters import (
    GaussDBDateBinaryDumper,
    GaussDBDateLoader,
    GaussDBTimestampAsDateLoader,
)


@pytest.mark.parametrize(
    "value",
    [
        datetime.date(1, 1, 1),
        datetime.date(2000, 1, 1),
        datetime.date(2024, 2, 29),
        datetime.date(9999, 12, 31),
    ],
)
def test_date_binary_boundaries(value):
    dump = GaussDBDateBinaryDumper(datetime.date).dump(value)
    assert (
        struct.unpack("!q", dump)[0]
        == (value - datetime.date(2000, 1, 1)).days * 86400000000
    )


@pytest.mark.parametrize("cls", [GaussDBDateLoader, GaussDBTimestampAsDateLoader])
def test_BC_not_silently_AD(cls):
    with pytest.raises(ValueError, match="BC"):
        cls(1116).load(b"0001-01-01 00:00:00 BC")


def test_microseconds_exact():
    result = GaussDBTimestampAsDateLoader(1116).load(b"2024-02-29 12:13:14.123456")
    assert result == datetime.datetime(2024, 2, 29, 12, 13, 14, 123456)
