"""Conservative GaussDB 507 O-mode flags; evidence is in tests/integration.

The postgres dialect selects inherited field mappings, not a compatibility
claim. Native migration execution must use tortoise_gaussdb.migrations.
"""

from tortoise.backends.base.client import Capabilities

gaussdb_capabilities = Capabilities(
    "postgres",
    support_for_update=True,
    support_for_no_key_update=False,
    support_for_posix_regex_queries=True,
    support_json_attributes=False,
    can_rollback_ddl=True,  # test_MIG_01_02_03_04_native_operations
    support_returning=True,  # CRUD and typed insert tests
    support_update_limit_order_by=False,
)
