# Crawler Scripts

Shell scripts for running the LexiconArxiv corpus crawlers.

## Scripts Overview

| Script | Description |
|--------|-------------|
| `run_full_collection.sh` | Full corpus collection from all sources |
| `run_incremental.sh` | Incremental updates (for crontab) |
| `count_papers.sh` | Count papers without collecting (dry run) |
| `check_status.sh` | Check collection status and available venues |
| `setup_crontab.sh` | Helper to set up crontab for incremental collection |

## Quick Start

```bash
# Make shell scripts executable
chmod +x scripts/crawler/*.sh

# Count papers first (dry run)
uv run python -m src.cli.core_collect collect --count-only

# Run full collection
./scripts/crawler/run_full_collection.sh

# Check status
./scripts/crawler/check_status.sh
```

## CLI Commands

All crawler functionality is available via the CLI module:

```bash
# Show all available commands
uv run python -m src.cli.core_collect --help

# OpenAlex collection
uv run python -m src.cli.core_collect collect --since-year 2020

# ACL Anthology collection
uv run python -m src.cli.core_collect collect-acl --since-year 2020

# ACL Anthology with workshops
uv run python -m src.cli.core_collect collect-acl --all --include-workshops

# Workshops only
uv run python -m src.cli.core_collect collect-acl --workshops-only --since-year 2024

# OpenReview collection
uv run python -m src.cli.core_collect collect-openreview --since-year 2020

# DBLP collection (includes ACM venues)
uv run python -m src.cli.core_collect collect-dblp --since-year 2020

# ACM venues only (via DBLP)
uv run python -m src.cli.core_collect collect-dblp --all --acm-only --since-year 2020

# AAAI collection
uv run python -m src.cli.core_collect collect-aaai --since-year 2020

# All sources
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020

# All sources with workshops
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020 --include-workshops

# Incremental update
uv run python -m src.cli.core_collect collect-incremental --days 1

# List venues
uv run python -m src.cli.core_collect list-venues
uv run python -m src.cli.core_collect list-acl-venues
uv run python -m src.cli.core_collect list-openreview-venues
uv run python -m src.cli.core_collect list-dblp-venues
uv run python -m src.cli.core_collect list-aaai-venues
```

## Full Collection

### Shell (Recommended)

```bash
# Default: collect from 2020
./scripts/crawler/run_full_collection.sh

# Custom start year
./scripts/crawler/run_full_collection.sh --since-year 2022

# Skip specific sources
./scripts/crawler/run_full_collection.sh --skip-openalex
./scripts/crawler/run_full_collection.sh --skip-acl --skip-dblp
```

### CLI Direct

```bash
# All sources from 2020
uv run python -m src.cli.core_collect collect-all-sources --since-year 2020

# OpenAlex only
uv run python -m src.cli.core_collect collect --since-year 2020 --venue neurips

# ACL Anthology only
uv run python -m src.cli.core_collect collect-acl --venue acl --since-year 2020
```

## Single Venue Collection

Useful for testing or collecting specific venues:

```bash
# OpenAlex venue
uv run python -m src.cli.core_collect collect --venue neurips --since-year 2022

# ACL Anthology venue
uv run python -m src.cli.core_collect collect-acl --venue acl --since-year 2022

# DBLP venue
uv run python -m src.cli.core_collect collect-dblp --venue icail --since-year 2022
```

## Counting Papers (Dry Run)

Check paper counts before starting collection:

```bash
# Count all OpenAlex venues
./scripts/crawler/count_papers.sh

# Count with year range
./scripts/crawler/count_papers.sh --since-year 2022 --to-year 2023

# Via CLI
uv run python -m src.cli.core_collect collect --count-only --since-year 2022
```

## Incremental Collection (Crontab)

For daily updates after initial collection:

### Shell

```bash
./scripts/crawler/run_incremental.sh
./scripts/crawler/run_incremental.sh --days 7
./scripts/crawler/run_incremental.sh --source openalex
```

### CLI Direct

```bash
# Papers from last 24 hours
uv run python -m src.cli.core_collect collect-incremental

# Papers from last 7 days
uv run python -m src.cli.core_collect collect-incremental --days 7
```

### Setting Up Crontab

```bash
# View current crontab
./scripts/crawler/setup_crontab.sh --show

# Install daily cron job (runs at 2 AM)
./scripts/crawler/setup_crontab.sh --install

# Custom schedule (every 6 hours)
CRON_SCHEDULE="0 */6 * * *" ./scripts/crawler/setup_crontab.sh --install

# Remove cron job
./scripts/crawler/setup_crontab.sh --remove
```

### Manual Crontab Setup

```bash
crontab -e
```

Add this line (daily at 2 AM):
```cron
0 2 * * * cd /path/to/LexiconArxiv && uv run python -m src.cli.core_collect collect-incremental >> /var/log/lexicon_crawler.log 2>&1
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SINCE_YEAR` | 2020 | Start year for collection |
| `DAYS_BACK` | 1 | Days to look back (incremental) |
| `SOURCE` | all | Source: all, openalex, acl, dblp |
| `LOG_FILE` | - | Log file path |
| `CRON_SCHEDULE` | `0 2 * * *` | Cron schedule |
| `LOG_DIR` | /var/log | Log directory for crontab |

## Logs

For crontab, logs are written to `/var/log/lexicon_crawler.log` by default.

To use a different location:
```bash
LOG_DIR=$HOME/logs ./scripts/crawler/setup_crontab.sh --install
```

## Source Code

Crawler implementations are in `src/core/crawler/`:

| Module | Description |
|--------|-------------|
| `openalex.py` | OpenAlex API collector (ML/AI/NLP venues) |
| `acl_anthology.py` | ACL Anthology XML collector (NLP conferences + workshops) |
| `openreview.py` | OpenReview API collector (ICLR, NeurIPS, ICML) |
| `acm_open.py` | ACM Digital Library collector (KDD, SIGIR, WWW) |
| `dblp.py` | DBLP Search API collector (IR/Legal venues, auto-retries 5xx) |
| `aaai_ojs.py` | AAAI OJS collector (AAAI 2020-2023) |

## See Also

- [Crawling Guide](../../docs/guides/crawling.md) - Detailed guide
- [CLI Reference](../../docs/reference/cli.md) - Complete CLI command reference
