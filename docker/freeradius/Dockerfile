# ─────────────────────────────────────────────────────────────────────────────
# NetSuite-ISP  —  FreeRADIUS Dockerfile
# Extends the official image with PostgreSQL SQL schema support.
# ─────────────────────────────────────────────────────────────────────────────
FROM freeradius/freeradius-server:3.2

# Install Postgres client libs for rlm_sql_postgresql
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        freeradius-postgresql \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy our custom config (clients.conf, sql.conf overrides)
COPY config/ /etc/freeradius/3.0/

EXPOSE 1812/udp 1813/udp

CMD ["freeradius", "-f", "-l", "stdout"]
