"""
Convert network_bandwidthsnapshot to a TimescaleDB hypertable.

TimescaleDB requires the partitioning column (timestamp) to be part of
the primary key. We replace the integer serial PK with a composite PK
of (id, timestamp) before calling create_hypertable().
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("network", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Step 1: Drop the existing plain primary key
            ALTER TABLE network_bandwidthsnapshot DROP CONSTRAINT IF EXISTS network_bandwidthsnapshot_pkey;

            -- Step 2: Add composite primary key that includes timestamp
            ALTER TABLE network_bandwidthsnapshot
                ADD PRIMARY KEY (id, timestamp);

            -- Step 3: Convert to TimescaleDB hypertable partitioned by timestamp
            SELECT create_hypertable(
                'network_bandwidthsnapshot',
                'timestamp',
                chunk_time_interval => INTERVAL '1 day',
                if_not_exists       => TRUE,
                migrate_data        => TRUE
            );
            """,
            reverse_sql="""
            -- Reversing a hypertable conversion is destructive — not supported.
            SELECT 1;
            """,
        ),
    ]
