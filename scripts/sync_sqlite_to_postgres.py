#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot migration SQLite -> PostgreSQL")
    parser.add_argument("--sqlite", default="data/db/anpr.db")
    parser.add_argument("--postgres-dsn", required=True)
    args = parser.parse_args()

    import psycopg  # type: ignore

    source = sqlite3.connect(args.sqlite)
    source.row_factory = sqlite3.Row

    query = "SELECT timestamp, channel, plate, country, confidence, source, frame_path, plate_path, direction FROM events"
    rows = source.execute(query).fetchall()

    with psycopg.connect(args.postgres_dsn) as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO events (timestamp, channel, plate, country, confidence, source, frame_path, plate_path, direction)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["timestamp"],
                        row["channel"],
                        row["plate"],
                        row["country"],
                        row["confidence"],
                        row["source"],
                        row["frame_path"],
                        row["plate_path"],
                        row["direction"],
                    ),
                )
        conn.commit()

    print(f"migrated rows: {len(rows)}")


if __name__ == "__main__":
    main()
