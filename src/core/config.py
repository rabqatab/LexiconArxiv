"""Venue configuration for Core Corpus collection.

Contains Source IDs for Tier 0 and Tier 1 AI/NLP venues from OpenAlex.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VenueConfig:
    """Configuration for a venue in the core corpus."""

    name: str  # Short venue name (e.g., "NeurIPS")
    full_name: str  # Full venue name
    source_id: str | None  # Primary OpenAlex Source ID (e.g., "S4306420609")
    tier: int  # 0 = top tier, 1 = second tier, 2 = specialized/legal
    venue_type: str = "conference"  # conference, journal, workshop
    domain: str = "ai"  # Domain: "ai" (default), "legal", etc.
    # Some venues have per-year Source IDs in OpenAlex (fragmented)
    alt_source_ids: tuple[str, ...] = ()  # Additional per-year Source IDs

    @property
    def all_source_ids(self) -> list[str]:
        """Return all Source IDs (primary + alternates)."""
        ids = []
        if self.source_id:
            ids.append(self.source_id)
        ids.extend(self.alt_source_ids)
        return ids

    @property
    def openalex_source_url(self) -> str | None:
        """Return the full OpenAlex source URL for primary source."""
        if self.source_id:
            return f"https://openalex.org/{self.source_id}"
        return None

    @property
    def openalex_source_urls(self) -> list[str]:
        """Return all OpenAlex source URLs."""
        return [f"https://openalex.org/{sid}" for sid in self.all_source_ids]

    @property
    def is_discovered(self) -> bool:
        """Return True if at least one Source ID has been discovered."""
        return self.source_id is not None or len(self.alt_source_ids) > 0


# Tier 0: Top AI/ML/NLP venues (10 venues)
TIER_0_VENUES = [
    VenueConfig(
        name="NeurIPS",
        full_name="Neural Information Processing Systems",
        source_id="S4306420609",
        tier=0,
        venue_type="conference",
    ),
    VenueConfig(
        name="ICML",
        full_name="International Conference on Machine Learning",
        source_id="S4306419644",
        tier=0,
        venue_type="conference",
    ),
    VenueConfig(
        name="ICLR",
        full_name="International Conference on Learning Representations",
        source_id="S4306419637",
        tier=0,
        venue_type="conference",
    ),
    VenueConfig(
        name="AAAI",
        full_name="AAAI Conference on Artificial Intelligence",
        source_id="S4210191458",
        tier=0,
        venue_type="conference",
    ),
    VenueConfig(
        name="IJCAI",
        full_name="International Joint Conference on Artificial Intelligence",
        source_id="S4306419999",
        tier=0,
        venue_type="conference",
        alt_source_ids=(
            "S4363608755",  # IJCAI 31st (863 works)
        ),
    ),
    VenueConfig(
        name="ACL",
        full_name="Annual Meeting of the Association for Computational Linguistics",
        source_id="S4306420508",
        tier=0,
        venue_type="conference",
        alt_source_ids=(
            "S4363608652",  # ACL 60th/2022 (603 works)
        ),
    ),
    VenueConfig(
        name="EMNLP",
        full_name="Conference on Empirical Methods in Natural Language Processing",
        source_id="S4306418267",
        tier=0,
        venue_type="conference",
        alt_source_ids=(
            "S4363608991",  # EMNLP 2021 (847 works)
        ),
    ),
    VenueConfig(
        name="SIGIR",
        full_name="ACM SIGIR Conference on Research and Development in Information Retrieval",
        source_id="S4306418959",
        tier=0,
        venue_type="conference",
        alt_source_ids=(
            "S4363608773",  # SIGIR 45th (444 works)
        ),
    ),
    VenueConfig(
        name="KDD",
        full_name="ACM SIGKDD Conference on Knowledge Discovery and Data Mining",
        source_id="S4306420424",
        tier=0,
        venue_type="conference",
        alt_source_ids=(
            "S4363608767",  # KDD 28th (534 works)
        ),
    ),
    VenueConfig(
        name="JMLR",
        full_name="Journal of Machine Learning Research",
        source_id="S118988714",
        tier=0,
        venue_type="journal",
    ),
    VenueConfig(
        name="WWW",
        full_name="The Web Conference",
        source_id="S4363608783",  # ACM Web Conference 2022 (367 works)
        tier=0,
        venue_type="conference",
        alt_source_ids=(
            "S4306421067",  # The Web Conference (315 works)
            "S4363608846",  # Companion Proceedings 2022 (224 works)
        ),
    ),
]

# Tier 1: Strong AI/NLP venues (7 venues)
TIER_1_VENUES = [
    VenueConfig(
        name="NAACL",
        full_name="North American Chapter of the Association for Computational Linguistics",
        source_id="S4306420633",
        tier=1,
        venue_type="conference",
        alt_source_ids=(
            "S4363608774",  # NAACL 2022 (442 works)
        ),
    ),
    VenueConfig(
        name="EACL",
        full_name="European Chapter of the Association for Computational Linguistics",
        source_id="S4306418011",
        tier=1,
        venue_type="conference",
    ),
    VenueConfig(
        name="COLING",
        full_name="International Conference on Computational Linguistics",
        source_id="S4306419219",
        tier=1,
        venue_type="conference",
    ),
    VenueConfig(
        name="Findings",
        full_name="Findings of the Association for Computational Linguistics",
        source_id="S4363605144",  # Findings ACL (331 works)
        tier=1,
        venue_type="conference",
        alt_source_ids=(
            "S4363605604",  # Findings EMNLP (209 works)
        ),
    ),
    VenueConfig(
        name="TACL",
        full_name="Transactions of the Association for Computational Linguistics",
        source_id="S2729999759",
        tier=1,
        venue_type="journal",
    ),
    VenueConfig(
        name="TOIS",
        full_name="ACM Transactions on Information Systems",
        source_id="S4394735545",
        tier=1,
        venue_type="journal",
    ),
    VenueConfig(
        name="ESWA",
        full_name="Expert Systems with Applications",
        source_id="S13144211",
        tier=1,
        venue_type="journal",
    ),
    VenueConfig(
        name="WSDM",
        full_name="ACM International Conference on Web Search and Data Mining",
        source_id="S4363608885",  # WSDM 2022 (15th, 210 works)
        tier=1,
        venue_type="conference",
        # Note: OpenAlex has limited/fragmented coverage for WSDM
    ),
    VenueConfig(
        name="CIKM",
        full_name="ACM International Conference on Information and Knowledge Management",
        source_id="S4363608762",  # CIKM 2022 (31st, 662 works)
        tier=1,
        venue_type="conference",
        # Note: OpenAlex has limited/fragmented coverage for CIKM
    ),
    VenueConfig(
        name="ICDM",
        full_name="IEEE International Conference on Data Mining",
        source_id="S4363608061",  # ICDM 2021 (208 works)
        tier=1,
        venue_type="conference",
        alt_source_ids=(
            "S4363608104",  # ICDM 2022 (181 works)
        ),
    ),
    VenueConfig(
        name="ECIR",
        full_name="European Conference on Information Retrieval",
        source_id="S4306418323",
        tier=1,
        venue_type="conference",
    ),
    VenueConfig(
        name="CoNLL",
        full_name="Conference on Computational Natural Language Learning",
        source_id="S4306418031",
        tier=1,
        venue_type="conference",
    ),
    VenueConfig(
        name="LREC",
        full_name="Language Resources and Evaluation Conference",
        source_id="S4306424877",  # Journal/proceedings hybrid
        tier=1,
        venue_type="conference",
    ),
    VenueConfig(
        name="RecSys",
        full_name="ACM Conference on Recommender Systems",
        source_id="S4306418092",
        tier=1,
        venue_type="conference",
    ),
]

# Tier 2: Legal AI domain venues
TIER_2_VENUES = [
    VenueConfig(
        name="AILaw",
        full_name="Artificial Intelligence and Law",
        source_id="S96609033",
        tier=2,
        venue_type="journal",
        domain="legal",
    ),
    VenueConfig(
        name="ICAIL",
        full_name="International Conference on Artificial Intelligence and Law",
        source_id="S4306419144",  # Limited OpenAlex coverage
        tier=2,
        venue_type="conference",
        domain="legal",
    ),
    VenueConfig(
        name="JURIX",
        full_name="International Conference on Legal Knowledge and Information Systems",
        source_id="S4306419638",  # Limited OpenAlex coverage
        tier=2,
        venue_type="conference",
        domain="legal",
    ),
    VenueConfig(
        name="NLLP",
        full_name="Natural Legal Language Processing Workshop",
        source_id=None,  # No stable OpenAlex source; collected via ACL/EMNLP workshops
        tier=2,
        venue_type="workshop",
        domain="legal",
    ),
    VenueConfig(
        name="LREC-Legal",
        full_name="Workshop on Language Resources and Technologies for the Legal Knowledge Graph",
        source_id=None,  # Collected via LREC workshops
        tier=2,
        venue_type="workshop",
        domain="legal",
    ),
]

# Combined list of all venues
VENUES: list[VenueConfig] = TIER_0_VENUES + TIER_1_VENUES + TIER_2_VENUES


def get_venue_by_name(name: str) -> VenueConfig | None:
    """Get venue configuration by short name (case-insensitive)."""
    name_lower = name.lower()
    for venue in VENUES:
        if venue.name.lower() == name_lower:
            return venue
    return None


def get_tier_venues(tier: int) -> list[VenueConfig]:
    """Get all venues for a specific tier."""
    return [v for v in VENUES if v.tier == tier]


def get_discovered_venues() -> list[VenueConfig]:
    """Get all venues with discovered Source IDs."""
    return [v for v in VENUES if v.is_discovered]


def get_undiscovered_venues() -> list[VenueConfig]:
    """Get all venues that need Source ID discovery."""
    return [v for v in VENUES if not v.is_discovered]


def get_venues_by_domain(domain: str) -> list[VenueConfig]:
    """Get all venues for a specific domain (e.g., 'legal', 'ai')."""
    return [v for v in VENUES if v.domain == domain]


# Domain constants
DOMAIN_AI = "ai"
DOMAIN_LEGAL = "legal"
