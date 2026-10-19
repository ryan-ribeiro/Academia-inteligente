# Keep the canonical PostgreSQL patch version and add the reviewed pgvector extension.
FROM postgres:18.6-bookworm

# Fetch the pinned source archive without BuildKit's remote Git/HTTP2 transport.
ADD --checksum=sha256:a9094dfb85ccdde3cbb295f1086d4c71a20db1d26bf1d6c39f07a7d164033eb4 \
    https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v0.8.1 /tmp/pgvector.tar.gz
RUN apt-get update \
    && apt-mark hold locales \
    && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-18 \
    && mkdir -p /tmp/pgvector \
    && tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1 \
    && make -C /tmp/pgvector OPTFLAGS="" \
    && make -C /tmp/pgvector install \
    && mkdir -p /usr/share/doc/pgvector \
    && cp /tmp/pgvector/LICENSE /usr/share/doc/pgvector/ \
    && rm -rf /tmp/pgvector /tmp/pgvector.tar.gz \
    && apt-get remove -y build-essential postgresql-server-dev-18 \
    && apt-get autoremove -y \
    && apt-mark unhold locales \
    && rm -rf /var/lib/apt/lists/*
COPY 02-knowledge-extension.sh /docker-entrypoint-initdb.d/02-knowledge-extension.sh
COPY ensure-knowledge-extension.sh /usr/local/bin/ensure-knowledge-extension.sh
