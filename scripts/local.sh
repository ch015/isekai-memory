#!/usr/bin/env bash
# Local Memory stack only. Never prunes images, removes volumes, or deploys to AWS.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: scripts/local.sh COMMAND' \
    '  up                          Build, migrate, start DB + server, wait for readiness' \
    '  build                       Build the shared local server/migration image' \
    '  down                        Remove stack containers/network; KEEP database volume' \
    '  status                      Show this stack (including completed migration)' \
    '  logs [memory|db|migrate]     Follow recent logs (all services by default)' \
    '  check                       Verify server + schema readiness inside the container' \
    '  token PROJECT USER [SCOPES] Issue a token explicitly (default read,write; admin allowed)' \
    '  revoke TOKEN_ID             Revoke that token explicitly' \
    '  help                        Show this help' \
    'Optional settings: repository .env, COMPOSE_PROJECT_NAME, ISEKAI_LOCAL_PORT.' \
    'No token is issued and no client configuration is changed by up.'
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 2
}

LOCAL_ACTION="${1:-help}"
if (( $# )); then shift; fi
case "$LOCAL_ACTION" in
  help|-h|--help) usage; exit 0 ;;
  up|build|down|status|check) (( $# == 0 )) || fail "$LOCAL_ACTION takes no arguments" ;;
  logs)
    (( $# <= 1 )) || fail 'logs accepts at most one service'
    case "${1:-memory}" in memory|db|migrate) ;; *) fail 'unknown log service' ;; esac
    ;;
  token) (( $# >= 2 && $# <= 3 )) || fail 'token requires PROJECT USER [SCOPES]' ;;
  revoke) (( $# == 1 )) || fail 'revoke requires TOKEN_ID' ;;
  *) usage >&2; fail "unknown command: $LOCAL_ACTION" ;;
esac

command -v docker >/dev/null 2>&1 || fail 'Docker is required. Start Docker Desktop / Docker Engine first.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is required.'

LOCAL_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Never source .env as shell code. Compose reads it from this fixed project directory.
cd "$LOCAL_ROOT"
compose() {
  docker compose --project-directory "$LOCAL_ROOT" -f "$LOCAL_ROOT/compose.yaml" "$@"
}

check() {
  compose exec -T memory python -c \
    "import json, urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8100/ready', timeout=5))))"
}

case "$LOCAL_ACTION" in
  up)
    compose up --build --detach --wait --wait-timeout 120
    check
    compose ps --all
    printf 'Memory host address (append /mcp for clients):\n'
    compose port memory 8100
    ;;
  build) compose build migrate ;;
  down)
    compose down
    printf 'Stopped. PostgreSQL volume and data were preserved.\n'
    ;;
  status) compose ps --all ;;
  logs) compose logs --follow --tail 100 "$@" ;;
  check) check ;;
  token)
    printf 'The next JSON includes a newly issued secret. Store it privately; do not commit it.\n' >&2
    compose exec -T memory isekai-memory --issue-token --project-id="$1" --user-id="$2" --scopes="${3:-read,write}"
    ;;
  revoke) compose exec -T memory isekai-memory --revoke-token="$1" ;;
esac
