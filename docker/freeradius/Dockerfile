# ─────────────────────────────────────────────────────────────────────────────
# NetSuite-ISP  —  FreeRADIUS + PostgreSQL support
# Uses Ubuntu base so apt-get works cleanly.
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        freeradius \
        freeradius-postgresql \
        freeradius-utils \
        libpq-dev \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy our config overrides
COPY config/ /etc/freeradius/3.0/

EXPOSE 1812/udp 1813/udp

CMD ["freeradius", "-f", "-l", "stdout"]
