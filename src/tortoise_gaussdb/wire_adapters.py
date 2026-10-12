"""GaussDB 507 wire-format adaptations for the gaussdb driver.

Each class fixes a server/driver mismatch pinned by probe evidence:

Dumpers (Python -> server):

GaussDBDateBinaryDumper
    GaussDB 507's date_recv expects an 8-byte microsecond value (same wire
    format as timestamp), NOT PostgreSQL's 4-byte days-since-2000. The stock
    psycopg-lineage dumper sends 4 bytes and the server rejects it with
    "Insufficient data left in message".
    Evidence: scripts/date_adapter_probe.py, 2026-10-08, C507-O
    (int8-micros -> stored '29-FEB-24' == 2024-02-29; int4 rejected).

Loaders (server -> Python):

GaussDBDateLoader
    In O mode a DATE column (oid 1082) comes back over the wire as a text
    like b'2024-02-29 00:00:00 AD' — i.e. timestamp-shaped text with an
    optional ' AD'/' BC' era suffix — and NOT in the b'2024-02-29' form the
    stock DateLoader parses. The stock loader raises "can't parse date".
    Evidence: date_wire probe on C507-O 2026-10-08: SELECT d FROM t ->
    '2024-02-29 00:00:00 AD'; d::text -> '29-FEB-24' (Oracle DD-MON-RR).

    This loader accepts the timestamp-shaped form (stripping the era suffix),
    the stock ISO date form, and falls back to DD-MON-RR parsing, always
    returning a datetime.date.
"""

from __future__ import annotations

import datetime
import re
import struct

from gaussdb import pq
from gaussdb.types.datetime import DateBinaryDumper

_EPOCH = datetime.datetime(2000, 1, 1)

# '2024-02-29 00:00:00 AD' / '2024-02-29' / '29-FEB-24'
_TS_SHAPE = re.compile(rb"^(\d{4})-(\d{2})-(\d{2})")
_DMY_SHAPE = re.compile(rb"^(\d{1,2})-([A-Z]{3})-(\d{2,4})")
_MONTHS = {
    b"JAN": 1,
    b"FEB": 2,
    b"MAR": 3,
    b"APR": 4,
    b"MAY": 5,
    b"JUN": 6,
    b"JUL": 7,
    b"AUG": 8,
    b"SEP": 9,
    b"OCT": 10,
    b"NOV": 11,
    b"DEC": 12,
}


class GaussDBDateBinaryDumper(DateBinaryDumper):
    """date -> int64 micros since 2000-01-01 (GaussDB 507 wire format)."""

    def dump(self, obj: datetime.date) -> bytes:
        micros = (obj - _EPOCH.date()).days * 86_400_000_000
        return struct.pack("!q", micros)


class GaussDBDateLoader:
    """Parse GaussDB 507 O-mode DATE wire text into datetime.date.

    Wire evidence (C507-O, 2026-10-08, scripts/ts_vs_date_probe.py):

    - a DATE column arrives with oid **1116** (not PG's 1082) and text
      'YYYY-MM-DD 00:00:00 AD' — the ' AD' era suffix is the reliable
      discriminator vs. a true timestamp (oid 1114, no suffix).
    - d::text renders Oracle-style '29-FEB-24' (DD-MON-RR).

    So: registered on BOTH 1082 and 1116. For 1116 the loader only
    rewrites values ending in ' AD'/' BC' (era-suffixed midnight values =
    DATE columns); anything else (a real timestamp slipping through with
    the same oid) is returned as-is for the timestamp loaders to handle.
    """

    format = pq.Format.TEXT

    def __init__(self, oid: int, context=None) -> None:
        self.oid = oid

    def load(self, data):
        if isinstance(data, memoryview):
            data = bytes(data)
        if isinstance(data, str):
            data = data.encode("ascii", "replace")
        if data.rstrip().endswith(b" BC"):
            raise ValueError("BC dates cannot be represented by datetime.date")
        m = _TS_SHAPE.match(data)
        if m:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DMY_SHAPE.match(data)
        if m:
            day = int(m.group(1))
            month = _MONTHS.get(m.group(2).upper())
            year = int(m.group(3))
            if year < 100:  # RR style: 00-49 -> 2000s, 50-99 -> 1900s
                year += 2000 if year < 50 else 1900
            if month is not None:
                return datetime.date(year, month, day)
        raise ValueError(f"can't parse GaussDB date {data!r}")


class GaussDBTimestampAsDateLoader(GaussDBDateLoader):
    """Loader for oid 1116 values that carry the era suffix.

    Non-era values (true timestamps rendered '2024-02-29 15:30:45') are
    returned as datetime so DatetimeField keeps working."""

    _TS_FULL = re.compile(
        rb"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(\.\d+)?\s*(AD|BC)?$"
    )

    def load(self, data):
        if isinstance(data, memoryview):
            data = bytes(data)
        if isinstance(data, str):
            data = data.encode("ascii", "replace")
        if data.rstrip().endswith(b" BC"):
            raise ValueError("BC dates cannot be represented by datetime.date")
        m = self._TS_FULL.match(data)
        if not m:
            return super().load(data)
        if m.group(8) is None:
            # true timestamp (no era suffix): keep datetime semantics
            micro = int((m.group(7)[1:] + b"000000")[:6]) if m.group(7) else 0
            return datetime.datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5)),
                int(m.group(6)),
                micro,
            )
        # era-suffixed: this is really a DATE column -> date
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def register(conn) -> None:
    """Register all GaussDB wire-format adapter fixes on a connection (or
    the gaussdb module for global registration). Safe to call multiple times."""
    conn.adapters.register_dumper(datetime.date, GaussDBDateBinaryDumper)
    conn.adapters.register_loader(1082, GaussDBDateLoader)  # PG-standard date oid
    conn.adapters.register_loader(1116, GaussDBTimestampAsDateLoader)  # O-mode DATE oid


async def aregister(conn) -> None:
    """Async variant for gaussdb_pool's ``configure`` hook.

    The fork's AsyncConnectionPool awaits the configure callback's return
    value ("object NoneType can't be used in 'await' expression" with the
    sync version), so the hook must be a coroutine function.
    """
    register(conn)
