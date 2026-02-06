"""Crawler modules for collecting papers from various sources.

This package contains collectors for:
- OpenAlex (openalex.py) - ML/AI/NLP venues
- ACL Anthology (acl_anthology.py) - NLP conferences
- DBLP (dblp.py) - IR/Legal venues
- OpenReview (openreview.py) - ML conferences (ICLR, NeurIPS, ICML)
- ACM Open (acm_open.py) - ACM conferences (KDD, SIGIR, WWW)
- AAAI OJS (aaai_ojs.py) - AAAI conferences
"""

from src.core.crawler.base import BaseCrawler, classify_paper_type_by_title
from src.core.crawler.openalex import (
    CoreCorpusCollector,
    discover_source_id,
    discover_all_missing_sources,
)
from src.core.crawler.acl_anthology import (
    ACLAnthologyCollector,
    ACL_VENUES,
    get_acl_venues,
    get_acl_venue_info,
)
from src.core.crawler.dblp import (
    DBLPCollector,
    DBLP_VENUES,
    get_dblp_venues,
    get_dblp_venue_info,
)
from src.core.crawler.openreview import (
    OpenReviewCollector,
    OPENREVIEW_VENUES,
    get_openreview_venues,
    get_openreview_venue_info,
)
from src.core.crawler.acm_open import (
    ACMOpenCollector,
    ACM_VENUES as ACM_OPEN_VENUES,
    get_acm_open_venues,
    get_acm_open_venue_info,
)
from src.core.crawler.aaai_ojs import (
    AAOJSCollector,
    AAAI_VENUES,
    get_aaai_venues,
    get_aaai_venue_info,
)

__all__ = [
    # Base
    "BaseCrawler",
    "classify_paper_type_by_title",
    # OpenAlex
    "CoreCorpusCollector",
    "discover_source_id",
    "discover_all_missing_sources",
    # ACL Anthology
    "ACLAnthologyCollector",
    "ACL_VENUES",
    "get_acl_venues",
    "get_acl_venue_info",
    # DBLP
    "DBLPCollector",
    "DBLP_VENUES",
    "get_dblp_venues",
    "get_dblp_venue_info",
    # OpenReview
    "OpenReviewCollector",
    "OPENREVIEW_VENUES",
    "get_openreview_venues",
    "get_openreview_venue_info",
    # ACM Open
    "ACMOpenCollector",
    "ACM_OPEN_VENUES",
    "get_acm_open_venues",
    "get_acm_open_venue_info",
    # AAAI OJS
    "AAOJSCollector",
    "AAAI_VENUES",
    "get_aaai_venues",
    "get_aaai_venue_info",
]
