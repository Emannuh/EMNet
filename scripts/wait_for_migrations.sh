#!/bin/sh
# Waits until Django migrations have run by polling for a known table.
# Used by celery_beat so it never starts before the DB schema is ready.

set -e

echo "Waiting for Django migrations to complete..."

until python - <<'EOF'
import django, os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = 'django_celery_beat_periodictask'
        )
    """)
    exists = c.fetchone()[0]
sys.exit(0 if exists else 1)
EOF
do
    echo "Migrations not done yet — retrying in 3s..."
    sleep 3
done

echo "Migrations complete. Starting celery beat..."
exec "$@"
