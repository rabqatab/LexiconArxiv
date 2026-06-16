# shellcheck shell=bash
# =============================================================================
# ensure_grobid.sh — shared helper for GROBID-dependent enrichment scripts
# =============================================================================
# Ensures a GROBID server is reachable before PDF-based enrichment runs,
# auto-starting a container if needed. If (and only if) this helper started
# the container, it is stopped automatically when the calling script exits.
#
# A GROBID server that was already running (started manually or elsewhere) is
# left untouched — we never stop something we did not start.
#
# Usage (source it, then call ensure_grobid before the enrich-5/enrich-11 step):
#
#     source "$SCRIPT_DIR/../lib/ensure_grobid.sh"
#     ensure_grobid            # blocks until GROBID answers /api/isalive
#     ... run enrich-5-refs-by-pdf-via-grobid / enrich-11-code-repos-via-grobid ...
#     # container is stopped automatically on EXIT if we started it
#
# NOTE: ensure_grobid installs EXIT/INT/TERM traps. Callers should not install
# their own EXIT trap after sourcing (none of the current callers do).
#
# Honored environment variables:
#   GROBID_URL        default http://localhost:8070
#   GROBID_IMAGE      default: arch-detected — grobid-arm64 on aarch64/arm64,
#                     lfoppiano/grobid:0.8.0 otherwise
#   GROBID_CONTAINER  default "grobid"
#   GROBID_WAIT_SECS  default 120 (cold start / model load can take a while)
#   GROBID_KEEP       set to 1 to skip auto-teardown even if we started it
# =============================================================================

GROBID_URL="${GROBID_URL:-http://localhost:8070}"
GROBID_CONTAINER="${GROBID_CONTAINER:-grobid}"
GROBID_WAIT_SECS="${GROBID_WAIT_SECS:-120}"

# Internal: 1 only if *this* process started the container (gates teardown).
_GROBID_STARTED_BY_US=0

_grobid_alive() {
    # GROBID's /api/isalive returns the literal text "true" when ready.
    curl -sf --connect-timeout 3 "$GROBID_URL/api/isalive" 2>/dev/null | grep -qi true
}

_grobid_image() {
    if [[ -n "${GROBID_IMAGE:-}" ]]; then
        printf '%s' "$GROBID_IMAGE"
    else
        case "$(uname -m)" in
            aarch64|arm64) printf 'grobid-arm64' ;;
            *)             printf 'lfoppiano/grobid:0.8.0' ;;
        esac
    fi
}

stop_grobid_if_started() {
    if [[ "$_GROBID_STARTED_BY_US" == "1" && "${GROBID_KEEP:-0}" != "1" ]]; then
        echo "[ensure_grobid] Stopping GROBID container we started ($GROBID_CONTAINER)..."
        docker stop "$GROBID_CONTAINER" >/dev/null 2>&1 || true
        _GROBID_STARTED_BY_US=0
    fi
}

ensure_grobid() {
    if _grobid_alive; then
        echo "[ensure_grobid] GROBID already up at $GROBID_URL — leaving it as-is."
        return 0
    fi

    local image
    image="$(_grobid_image)"
    echo "[ensure_grobid] GROBID not responding at $GROBID_URL — starting '$image'..."

    # Fail clearly instead of hanging on an implicit pull of a missing image
    # (the arm64 build is local-only and won't exist in a registry).
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        echo "[ensure_grobid] ERROR: docker image '$image' not found locally." >&2
        if [[ "$image" == "grobid-arm64" ]]; then
            echo "[ensure_grobid]   Build it: docker build --no-cache -t grobid-arm64 ./docker/grobid-arm64" >&2
        else
            echo "[ensure_grobid]   Pull it:  docker pull $image" >&2
        fi
        return 1
    fi

    # Clear any stale container holding the name (e.g. a crashed run).
    if docker ps -aq -f "name=^${GROBID_CONTAINER}$" | grep -q .; then
        docker rm -f "$GROBID_CONTAINER" >/dev/null 2>&1 || true
    fi

    docker run -d --rm --name "$GROBID_CONTAINER" -p 8070:8070 "$image" >/dev/null
    _GROBID_STARTED_BY_US=1
    # Tear down on any exit path (normal, set -e failure, or interrupt).
    trap stop_grobid_if_started EXIT
    trap 'stop_grobid_if_started; exit 130' INT TERM

    echo "[ensure_grobid] Waiting up to ${GROBID_WAIT_SECS}s for GROBID to become healthy..."
    local waited=0
    while ! _grobid_alive; do
        sleep 3
        waited=$((waited + 3))
        if (( waited >= GROBID_WAIT_SECS )); then
            echo "[ensure_grobid] ERROR: GROBID did not become healthy within ${GROBID_WAIT_SECS}s." >&2
            return 1
        fi
    done
    echo "[ensure_grobid] GROBID healthy after ~${waited}s."
}
