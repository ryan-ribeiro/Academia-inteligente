#!/bin/sh
set -eu
# Existing production volumes need privileged extension preparation as well.
# Read the existing mounted database secret; never print it or put it in argv.
PGPASSWORD="$(cat /run/secrets/postgres_password)"
export PGPASSWORD
exec psql -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public'
