from src.literature_review.discovery.deduplication import (
    AmbiguousMatch,
    deduplicate_papers,
)
from src.literature_review.discovery.approval import ApprovalService
from src.literature_review.discovery.normalization import (
    normalize_arxiv_id,
    normalize_author,
    normalize_doi,
    normalize_space,
    normalize_title_key,
)
from src.literature_review.discovery.planner import QueryPlanner
from src.literature_review.discovery.screening import (
    ScreeningResult,
    screen_candidate,
)
from src.literature_review.discovery.service import (
    AllProvidersFailedError,
    DiscoveryOutcome,
    DiscoveryService,
)

__all__ = [
    "AmbiguousMatch",
    "AllProvidersFailedError",
    "ApprovalService",
    "DiscoveryOutcome",
    "DiscoveryService",
    "QueryPlanner",
    "ScreeningResult",
    "deduplicate_papers",
    "normalize_arxiv_id",
    "normalize_author",
    "normalize_doi",
    "normalize_space",
    "normalize_title_key",
    "screen_candidate",
]
