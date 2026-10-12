# Tortoise-GaussDB driver test image (Linux arm64)
# Base: psycopg2-gaussdb:cp312-arm64 which carries:
#   - Python 3.12
#   - GaussDB 507-matched libpq at /opt/gaussdb_libpq/ (from the official
#     GaussDB-Kernel-V500R002C10 Libpq package)
# Driver: the locally-built gaussdb 1.0.4 wheel from the verified fork
#   separately supplied gaussdb-python fork (15 files differ from PyPI 1.0.4;
#   critical fix: errors.finish_pgconn no longer reflects over pgconn
#   attributes — PyPI's version calls PQpass() on a failed connection and
#   GaussDB 507 libpq returns NULL there, which segfaults ctypes).
#   Provenance and verification boundary: docs/DRIVER_PROVENANCE.md.
FROM psycopg2-gaussdb:cp312-arm64

ENV LD_LIBRARY_PATH=/opt/gaussdb_libpq \
    GAUSSDB_LIBPQ_PATH=/opt/gaussdb_libpq/libpq.so.5 \
    PYTHONUNBUFFERED=1

WORKDIR /work

RUN pip install --no-cache-dir --upgrade pip 2>/dev/null || true

# fork driver wheel first (must not be overwritten by the PyPI dep later)
COPY gaussdb-1.0.4-py3-none-any.whl /tmp/driver/
RUN pip install --no-cache-dir /tmp/driver/gaussdb-1.0.4-py3-none-any.whl && \
    rm -rf /tmp/driver

RUN pip install --no-cache-dir \
    "gaussdb-pool==1.0.4" \
    "tortoise-orm==1.1.8" \
    "pytest>=8.0" \
    "pytest-asyncio>=0.24" \
    "httpx" \
    "asgi-lifespan" \
    "fastapi>=0.110"

CMD ["python3", "-c", "import gaussdb, gaussdb_pool, tortoise; print('gaussdb', gaussdb.__version__, '| tortoise', tortoise.__version__)"]
