"""Cravatar integration contracts; no production connector is enabled."""

from .adapter import CravatarAction, CravatarAdapter
from .shadow import CravatarShadowConnector, ShadowRecord
from .backlog import (
    CravatarBacklog,
    CravatarBacklogRecord,
    import_cravatar_backlog,
    submit_cravatar_backlog,
)
from .incremental import (
    CravatarCursorStore,
    CravatarIncrementalImporter,
    IncrementalOutcome,
    IncrementalRun,
    WatermarkSummary,
)
from .registry import (
    InvalidRegistryRecord,
    RegistryExportPage,
    RegistryLedger,
    RegistryRecord,
    collect_registry_export,
    read_registry_export,
)

__all__ = [
    "CravatarAction", "CravatarAdapter", "CravatarBacklog", "CravatarBacklogRecord",
    "CravatarShadowConnector", "ShadowRecord", "import_cravatar_backlog",
    "submit_cravatar_backlog", "CravatarCursorStore", "CravatarIncrementalImporter",
    "IncrementalOutcome", "IncrementalRun", "WatermarkSummary",
    "InvalidRegistryRecord", "RegistryExportPage", "RegistryLedger", "RegistryRecord",
    "collect_registry_export", "read_registry_export",
]
