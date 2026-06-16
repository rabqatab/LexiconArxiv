from dagster import Definitions

from src.orchestration.assets.collection import collect_papers
from src.orchestration.assets.enrichment import enrich_abstracts
from src.orchestration.assets.embedding import embed_papers

defs = Definitions(
    assets=[collect_papers, enrich_abstracts, embed_papers],
)
