"""Repositories: typed, async access to the schema for the rest of the terminal.

Every function takes an ``AsyncSession`` and **never commits** — the caller
owns the transaction (``Database.session()`` commits on success and rolls
back on error), so a unit of work such as "provision ten lab accounts" either
happens completely or not at all.

``catalog``     reference data: venues, instruments, listings, sessions, costs
``strategies``  strategy definitions, instances, versions and promotions
``accounts``    dedicated lab accounts, configuration versions, account state
"""

from kterminal.db.repositories.accounts import (
    AccountNotFoundError,
    AccountProvisioningError,
    AccountState,
    ProvisionedAccount,
    dedicated_account_id,
    dedicated_account_name,
    get_account_state,
    provision_dedicated_account,
)
from kterminal.db.repositories.catalog import (
    CatalogDocumentError,
    CatalogSnapshot,
    StoredCatalogSnapshot,
    apply_catalog,
    latest_catalog_snapshot,
)
from kterminal.db.repositories.strategies import (
    DefinitionRecord,
    InstanceRecord,
    StoredInstance,
    StrategyRepositoryError,
    VersionRecord,
    get_or_create_version,
    list_instances,
    set_instance_status,
    upsert_definition,
    upsert_instance,
    version_id_for,
)

__all__ = [
    "AccountNotFoundError",
    "AccountProvisioningError",
    "AccountState",
    "CatalogDocumentError",
    "CatalogSnapshot",
    "DefinitionRecord",
    "InstanceRecord",
    "ProvisionedAccount",
    "StoredCatalogSnapshot",
    "StoredInstance",
    "StrategyRepositoryError",
    "VersionRecord",
    "apply_catalog",
    "dedicated_account_id",
    "dedicated_account_name",
    "get_account_state",
    "get_or_create_version",
    "latest_catalog_snapshot",
    "list_instances",
    "provision_dedicated_account",
    "set_instance_status",
    "upsert_definition",
    "upsert_instance",
    "version_id_for",
]
