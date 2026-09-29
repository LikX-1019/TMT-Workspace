#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")/../.."

: "${POSTGRES_USER:=tmt}"
: "${POSTGRES_DB:=tmt_workspace}"
: "${TMT_TEST_DATABASE_NAME:=tmt_workspace_test}"

database_exists="$(
  docker compose exec -T postgres psql \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    -tAc "SELECT 1 FROM pg_database WHERE datname = '${TMT_TEST_DATABASE_NAME}'"
)"

if [[ "${database_exists}" != "1" ]]; then
  docker compose exec -T postgres createdb -U "${POSTGRES_USER}" "${TMT_TEST_DATABASE_NAME}"
fi

printf '%s\n' "${TMT_TEST_DATABASE_NAME}"
