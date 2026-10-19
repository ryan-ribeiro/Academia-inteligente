#!/bin/sh
set -eu
# The development database and the least-privileged production application's
# database need the extension installed by the database owner during first init.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public'
if [ "$POSTGRES_DB" != academia ] && \
   [ "$(psql --username "$POSTGRES_USER" --dbname postgres -Atc "SELECT 1 FROM pg_database WHERE datname = 'academia'")" = 1 ]; then
  psql --username "$POSTGRES_USER" --dbname academia -v ON_ERROR_STOP=1 \
    -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public'
fi
