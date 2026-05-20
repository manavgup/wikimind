"""SQLModel table classes split into domain-specific modules.

All tables are re-exported here so that ``from wikimind.models.tables import User``
works, and the main ``wikimind.models`` package can star-import everything.
"""

from wikimind.models.tables.auth import (
    MCPAccessToken,
    OAuthAccessToken,
    OAuthAuthorizationCode,
)
from wikimind.models.tables.billing import (
    Plan,
    QueryCount,
    StorageUsage,
    Subscription,
    WebhookEvent,
)
from wikimind.models.tables.capture import CaptureSource, RssFeed
from wikimind.models.tables.compilation import (
    ClaimConcept,
    CompilationDraft,
    CompiledClaim,
    ConceptCluster,
)
from wikimind.models.tables.core import MigrationHistory, User
from wikimind.models.tables.ingest import Source, SourceImage
from wikimind.models.tables.jobs import CostLog, Job, LLMTrace, SyncLog
from wikimind.models.tables.lint import (
    Contradiction,
    ContradictionFinding,
    DismissedFinding,
    LintPairCache,
    LintReport,
    OrphanFinding,
    StructuralFinding,
    _LintFindingBase,
)
from wikimind.models.tables.qa import Conversation, Query
from wikimind.models.tables.sharing import SavedSearch, ShareLink
from wikimind.models.tables.tags import ArticleTag, Tag
from wikimind.models.tables.user_settings import (
    CompilationSchema,
    UserApiKey,
    UserPreference,
)
from wikimind.models.tables.wiki import (
    Article,
    ArticleConcept,
    ArticleSource,
    Backlink,
    Concept,
    ConceptKindDef,
    ReinforcementEvent,
    SourceSpan,
)

__all__ = [
    "Article",
    "ArticleConcept",
    "ArticleSource",
    "ArticleTag",
    "Backlink",
    "CaptureSource",
    "ClaimConcept",
    "CompilationDraft",
    "CompilationSchema",
    "CompiledClaim",
    "Concept",
    "ConceptCluster",
    "ConceptKindDef",
    "Contradiction",
    "ContradictionFinding",
    "Conversation",
    "CostLog",
    "DismissedFinding",
    "Job",
    "LLMTrace",
    "LintPairCache",
    "LintReport",
    "MCPAccessToken",
    "MigrationHistory",
    "OAuthAccessToken",
    "OAuthAuthorizationCode",
    "OrphanFinding",
    "Plan",
    "Query",
    "QueryCount",
    "ReinforcementEvent",
    "RssFeed",
    "SavedSearch",
    "ShareLink",
    "Source",
    "SourceImage",
    "SourceSpan",
    "StorageUsage",
    "StructuralFinding",
    "Subscription",
    "SyncLog",
    "Tag",
    "User",
    "UserApiKey",
    "UserPreference",
    "WebhookEvent",
    "_LintFindingBase",
]
