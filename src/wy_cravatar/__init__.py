"""Cravatar integration contracts; no production connector is enabled."""

from .adapter import CravatarAction, CravatarAdapter
from .shadow import CravatarShadowConnector, ShadowRecord
from .backlog import (
    CravatarBacklog,
    CravatarBacklogRecord,
    import_cravatar_backlog,
    submit_cravatar_backlog,
)

__all__ = [
    "CravatarAction", "CravatarAdapter", "CravatarBacklog", "CravatarBacklogRecord",
    "CravatarShadowConnector", "ShadowRecord", "import_cravatar_backlog",
    "submit_cravatar_backlog",
]
