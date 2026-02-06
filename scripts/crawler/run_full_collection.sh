#!/bin/bash
# Full corpus collection script (Orchestrator)
# Calls individual source collection scripts
#
# Sources:
#   1.1 OpenAlex    - ML/AI venues
#   1.2 ACL         - NLP venues
#   1.3 DBLP        - IR/Legal venues
#   1.4 OpenReview  - ML conferences (ICLR, NeurIPS, ICML)
#   1.5 ACM         - ACM conferences
#   1.6 AAAI        - AAAI proceedings

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Default values
SINCE_YEAR=${SINCE_YEAR:-2020}
INCLUDE_WORKSHOPS=${INCLUDE_WORKSHOPS:-false}
SKIP_OPENALEX=${SKIP_OPENALEX:-false}
SKIP_ACL=${SKIP_ACL:-false}
SKIP_DBLP=${SKIP_DBLP:-false}
SKIP_OPENREVIEW=${SKIP_OPENREVIEW:-false}
SKIP_ACM=${SKIP_ACM:-false}
SKIP_AAAI=${SKIP_AAAI:-false}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --since-year)
            SINCE_YEAR="$2"
            shift 2
            ;;
        --include-workshops)
            INCLUDE_WORKSHOPS=true
            shift
            ;;
        --skip-openalex)
            SKIP_OPENALEX=true
            shift
            ;;
        --skip-acl)
            SKIP_ACL=true
            shift
            ;;
        --skip-dblp)
            SKIP_DBLP=true
            shift
            ;;
        --skip-openreview)
            SKIP_OPENREVIEW=true
            shift
            ;;
        --skip-acm)
            SKIP_ACM=true
            shift
            ;;
        --skip-aaai)
            SKIP_AAAI=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Collect papers from all sources"
            echo ""
            echo "Options:"
            echo "  --since-year YEAR    Start year (default: 2020)"
            echo "  --include-workshops  Include ACL workshop papers"
            echo "  --skip-openalex      Skip OpenAlex collection"
            echo "  --skip-acl           Skip ACL Anthology collection"
            echo "  --skip-dblp          Skip DBLP collection"
            echo "  --skip-openreview    Skip OpenReview collection"
            echo "  --skip-acm           Skip ACM collection"
            echo "  --skip-aaai          Skip AAAI collection"
            echo "  --help               Show this help message"
            echo ""
            echo "Individual scripts:"
            echo "  ./scripts/crawler/collect_openalex.sh"
            echo "  ./scripts/crawler/collect_acl.sh"
            echo "  ./scripts/crawler/collect_dblp.sh"
            echo "  ./scripts/crawler/collect_openreview.sh"
            echo "  ./scripts/crawler/collect_acm.sh"
            echo "  ./scripts/crawler/collect_aaai.sh"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Full Corpus Collection"
echo "=========================================="
echo "Start Year: $SINCE_YEAR"
echo "Include Workshops: $INCLUDE_WORKSHOPS"
echo "Skip OpenAlex: $SKIP_OPENALEX"
echo "Skip ACL: $SKIP_ACL"
echo "Skip DBLP: $SKIP_DBLP"
echo "Skip OpenReview: $SKIP_OPENREVIEW"
echo "Skip ACM: $SKIP_ACM"
echo "Skip AAAI: $SKIP_AAAI"
echo "=========================================="
echo ""

# Step 1.1: OpenAlex
if [ "$SKIP_OPENALEX" = false ]; then
    echo "--- [1.1/6] OpenAlex ---"
    "$SCRIPT_DIR/collect_openalex.sh" --since-year "$SINCE_YEAR"
    echo ""
else
    echo "--- [1.1/6] OpenAlex (SKIPPED) ---"
    echo ""
fi

# Step 1.2: ACL Anthology
if [ "$SKIP_ACL" = false ]; then
    echo "--- [1.2/6] ACL Anthology ---"
    CMD="$SCRIPT_DIR/collect_acl.sh --since-year $SINCE_YEAR"
    if [ "$INCLUDE_WORKSHOPS" = true ]; then
        CMD="$CMD --include-workshops"
    fi
    $CMD
    echo ""
else
    echo "--- [1.2/6] ACL Anthology (SKIPPED) ---"
    echo ""
fi

# Step 1.3: DBLP
if [ "$SKIP_DBLP" = false ]; then
    echo "--- [1.3/6] DBLP ---"
    "$SCRIPT_DIR/collect_dblp.sh" --since-year "$SINCE_YEAR"
    echo ""
else
    echo "--- [1.3/6] DBLP (SKIPPED) ---"
    echo ""
fi

# Step 1.4: OpenReview
if [ "$SKIP_OPENREVIEW" = false ]; then
    echo "--- [1.4/6] OpenReview ---"
    "$SCRIPT_DIR/collect_openreview.sh" --since-year "$SINCE_YEAR"
    echo ""
else
    echo "--- [1.4/6] OpenReview (SKIPPED) ---"
    echo ""
fi

# Step 1.5: ACM
if [ "$SKIP_ACM" = false ]; then
    echo "--- [1.5/6] ACM ---"
    "$SCRIPT_DIR/collect_acm.sh" --since-year "$SINCE_YEAR"
    echo ""
else
    echo "--- [1.5/6] ACM (SKIPPED) ---"
    echo ""
fi

# Step 1.6: AAAI
if [ "$SKIP_AAAI" = false ]; then
    echo "--- [1.6/6] AAAI ---"
    "$SCRIPT_DIR/collect_aaai.sh" --since-year "$SINCE_YEAR"
    echo ""
else
    echo "--- [1.6/6] AAAI (SKIPPED) ---"
    echo ""
fi

echo "=========================================="
echo "Collection complete!"
echo "=========================================="
