"""Custom exception hierarchy for LexiconArxiv."""


class LexiconArxivError(Exception):
    """Base exception for all LexiconArxiv errors."""


class StorageError(LexiconArxivError):
    """Qdrant storage operation failed."""


class CollectionNotFoundError(StorageError):
    """Qdrant collection does not exist."""


class PaperNotFoundError(StorageError):
    """Paper with given ID not found."""


class EnrichmentError(LexiconArxivError):
    """Enrichment pipeline error."""


class APIRateLimitError(EnrichmentError):
    """External API rate limit hit."""


class ResolutionError(LexiconArxivError):
    """Reference resolution failed."""


class CheckpointError(LexiconArxivError):
    """Checkpoint read/write error."""


class CrawlerError(LexiconArxivError):
    """Data source crawler error."""


class ConfigurationError(LexiconArxivError):
    """Missing or invalid configuration."""
