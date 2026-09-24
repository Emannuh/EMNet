# ─────────────────────────────────────────────────────────────────────────────
# NetSuite-ISP  —  FreeRADIUS + PostgreSQL
# Strategy: use FreeRADIUS's own complete radiusd.conf (it works out of box),
# only inject our SQL module config and clients.conf as additions.
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        freeradius \
        freeradius-postgresql \
        freeradius-utils \
        libpq-dev \
        postgresql-client \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Inject our SQL module config (overwrites the stock sql module which uses sqlite)
COPY config/mods-available/sql /etc/freeradius/3.0/mods-available/sql

# Enable the SQL module by creating a symlink in mods-enabled
RUN ln -sf /etc/freeradius/3.0/mods-available/sql \
           /etc/freeradius/3.0/mods-enabled/sql

# Inject our clients.conf (adds localhost NAS for testing)
COPY config/clients.conf /etc/freeradius/3.0/clients.conf

# Entrypoint substitutes env vars then starts FreeRADIUS
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 1812/udp 1813/udp

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["freeradius", "-f", "-l", "stdout"]
