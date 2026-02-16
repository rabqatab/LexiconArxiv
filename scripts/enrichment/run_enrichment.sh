#!/bin/bash
# Paper enrichment script (Orchestrator)
# Calls individual enrichment step scripts
#
# Steps:
#   3.1 OpenAlex DOI    - Papers WITH DOIs via OpenAlex
#   3.2 CrossRef        - Additional citations from CrossRef
#   3.3 Title Lookup    - Papers WITHOUT DOIs via title search
#   3.4 Abstracts       - Fill missing abstracts
#   3.6 Resolve Titles  - Resolve TITLE:xxx refs via OpenAlex
#   3.7 Stubs           - Stub paper metadata (optional, expensive)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
PARALLEL=${PARALLEL:-10}
BATCH_SIZE=${BATCH_SIZE:-50}
SKIP_OPENALEX=${SKIP_OPENALEX:-false}
SKIP_CROSSREF=${SKIP_CROSSREF:-false}
SKIP_TITLE=${SKIP_TITLE:-false}
SKIP_ABSTRACTS=${SKIP_ABSTRACTS:-false}
SKIP_PDF=${SKIP_PDF:-false}
SKIP_RESOLVE_TITLES=${SKIP_RESOLVE_TITLES:-false}
ENRICH_STUBS=${ENRICH_STUBS:-false}
RETRY_INCOMPLETE=${RETRY_INCOMPLETE:-false}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --skip-openalex)
            SKIP_OPENALEX=true
            shift
            ;;
        --skip-crossref)
            SKIP_CROSSREF=true
            shift
            ;;
        --skip-title)
            SKIP_TITLE=true
            shift
            ;;
        --skip-abstracts)
            SKIP_ABSTRACTS=true
            shift
            ;;
        --skip-pdf)
            SKIP_PDF=true
            shift
            ;;
        --skip-resolve-titles)
            SKIP_RESOLVE_TITLES=true
            shift
            ;;
        --enrich-stubs)
            ENRICH_STUBS=true
            shift
            ;;
        --retry-incomplete)
            RETRY_INCOMPLETE=true
            shift
            ;;
        --citations-only)
            SKIP_ABSTRACTS=true
            shift
            ;;
        --abstracts-only)
            SKIP_OPENALEX=true
            SKIP_CROSSREF=true
            SKIP_TITLE=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enrich papers with citations and abstracts"
            echo ""
            echo "Options:"
            echo "  --parallel N       Concurrent requests (default: 10)"
            echo "  --batch-size N     Batch size for updates (default: 50)"
            echo "  --skip-openalex    Skip OpenAlex DOI enrichment"
            echo "  --skip-crossref    Skip CrossRef enrichment"
            echo "  --skip-title       Skip title-based enrichment"
            echo "  --skip-abstracts   Skip abstract enrichment"
            echo "  --skip-pdf         Skip PDF/GROBID extraction"
            echo "  --skip-resolve-titles  Skip TITLE:xxx reference resolution"
            echo "  --enrich-stubs     Also enrich stub papers (expensive)"
            echo "  --retry-incomplete Re-process papers still missing data"
            echo "  --citations-only   Only enrich citations (skip abstracts)"
            echo "  --abstracts-only   Only enrich abstracts"
            echo "  --help             Show this help message"
            echo ""
            echo "Individual scripts:"
            echo "  ./scripts/enrichment/enrich_openalex.sh"
            echo "  ./scripts/enrichment/enrich_crossref.sh"
            echo "  ./scripts/enrichment/enrich_by_title.sh"
            echo "  ./scripts/enrichment/enrich_abstracts.sh"
            echo "  ./scripts/enrichment/enrich_pdf.sh"
            echo "  ./scripts/enrichment/resolve_title_refs.sh"
            echo "  ./scripts/enrichment/enrich_stubs.sh"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Calculate total steps (base: 6 steps including PDF and title ref resolution)
TOTAL_STEPS=6
if [ "$ENRICH_STUBS" = true ]; then
    TOTAL_STEPS=7
fi

echo "=========================================="
echo "LexiconArxiv Paper Enrichment"
echo "=========================================="
echo "Parallel: $PARALLEL"
echo "Batch Size: $BATCH_SIZE"
echo "Skip OpenAlex: $SKIP_OPENALEX"
echo "Skip CrossRef: $SKIP_CROSSREF"
echo "Skip Title Lookup: $SKIP_TITLE"
echo "Skip Abstracts: $SKIP_ABSTRACTS"
echo "Skip PDF/GROBID: $SKIP_PDF"
echo "Skip Resolve Titles: $SKIP_RESOLVE_TITLES"
echo "Enrich Stubs: $ENRICH_STUBS"
echo "Retry Incomplete: $RETRY_INCOMPLETE"
echo "=========================================="
echo ""

# Step 3.1: OpenAlex DOI-based enrichment
if [ "$SKIP_OPENALEX" = false ]; then
    echo "--- [3.1/$TOTAL_STEPS] OpenAlex (DOI) ---"
    CMD="$SCRIPT_DIR/enrich_openalex.sh --parallel $PARALLEL --batch-size $BATCH_SIZE"
    [ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
    $CMD
    echo ""
else
    echo "--- [3.1/$TOTAL_STEPS] OpenAlex (SKIPPED) ---"
    echo ""
fi

# Step 3.2: CrossRef enrichment
if [ "$SKIP_CROSSREF" = false ]; then
    echo "--- [3.2/$TOTAL_STEPS] CrossRef ---"
    CMD="$SCRIPT_DIR/enrich_crossref.sh --parallel 5 --batch-size $BATCH_SIZE"
    [ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
    $CMD
    echo ""
else
    echo "--- [3.2/$TOTAL_STEPS] CrossRef (SKIPPED) ---"
    echo ""
fi

# Step 3.3: Title-based enrichment (parallel auto-detected: 5 for API key, 1 for email)
if [ "$SKIP_TITLE" = false ]; then
    echo "--- [3.3/$TOTAL_STEPS] Title Lookup ---"
    CMD="$SCRIPT_DIR/enrich_by_title.sh"
    [ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
    $CMD
    echo ""
else
    echo "--- [3.3/$TOTAL_STEPS] Title Lookup (SKIPPED) ---"
    echo ""
fi

# Step 3.4: Abstract enrichment
if [ "$SKIP_ABSTRACTS" = false ]; then
    echo "--- [3.4/$TOTAL_STEPS] Abstracts ---"
    CMD="$SCRIPT_DIR/enrich_abstracts.sh --parallel $PARALLEL --batch-size $BATCH_SIZE"
    [ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
    $CMD
    echo ""
else
    echo "--- [3.4/$TOTAL_STEPS] Abstracts (SKIPPED) ---"
    echo ""
fi

# Step 3.5: PDF/GROBID extraction (last-resort fallback)
if [ "$SKIP_PDF" = false ]; then
    echo "--- [3.5/$TOTAL_STEPS] PDF/GROBID ---"
    "$SCRIPT_DIR/enrich_pdf.sh" --parallel 2 --batch-size 10
    echo ""
else
    echo "--- [3.5/$TOTAL_STEPS] PDF/GROBID (SKIPPED) ---"
    echo ""
fi

# Step 3.6: Resolve TITLE:xxx references via OpenAlex
if [ "$SKIP_RESOLVE_TITLES" = false ]; then
    echo "--- [3.6/$TOTAL_STEPS] Resolve Title Refs ---"
    CMD="$SCRIPT_DIR/resolve_title_refs.sh --parallel 3 --batch-size 100"
    [ "$RETRY_INCOMPLETE" = true ] && CMD="$CMD --retry-incomplete"
    $CMD
    echo ""
else
    echo "--- [3.6/$TOTAL_STEPS] Resolve Title Refs (SKIPPED) ---"
    echo ""
fi

# Step 3.7: Stub enrichment (optional)
if [ "$ENRICH_STUBS" = true ]; then
    echo "--- [3.7/$TOTAL_STEPS] Stubs ---"
    "$SCRIPT_DIR/enrich_stubs.sh" --parallel 5
    echo ""
fi

echo "=========================================="
echo "Enrichment complete!"
echo "=========================================="

# Show data quality stats
echo ""
echo "Data Quality Summary:"
uv run python -m src.cli.core_collect status
