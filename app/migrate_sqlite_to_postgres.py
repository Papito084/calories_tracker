"""Copy the local SQLite dataset into an initialized PostgreSQL database."""

import argparse
import os
import secrets
import sqlite3
from pathlib import Path


TABLES = ("users", "user_profile", "daily_meals", "weight_logs")
TARGET_COLUMNS = {
    "users": (
        "id", "username", "password_hash", "created_at", "google_sub", "email",
        "first_name", "last_name", "nickname",
    ),
    "user_profile": (
        "id", "user_id", "name", "gender", "age", "height_cm",
        "current_weight_kg", "target_weight_kg", "activity_level", "goal",
        "target_weeks", "bmr", "tdee", "daily_calories", "protein_g",
        "fat_g", "carbs_g", "created_at", "updated_at",
    ),
    "daily_meals": (
        "id", "user_id", "date_logged", "timestamp", "meal_type", "dish_name",
        "total_calories", "protein_g", "carbs_g", "fat_g", "fiber_g",
        "confidence_score", "raw_items_json", "image_base64",
    ),
    "weight_logs": (
        "id", "user_id", "date_logged", "weight_kg", "notes", "created_at",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "cal_ai.db",
        help="SQLite database file to copy",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection string (defaults to DATABASE_URL)",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("Set DATABASE_URL or pass --database-url")
    if not args.source.is_file():
        parser.error(f"SQLite database does not exist: {args.source}")

    database_url = args.database_url
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
    from app import database
    import psycopg

    database.init_db()
    source = sqlite3.connect(args.source)
    source.row_factory = sqlite3.Row
    try:
        with psycopg.connect(database_url) as target:
            with target.cursor() as cursor:
                for table in TABLES:
                    source_columns = {
                        row["name"]
                        for row in source.execute(f"PRAGMA table_info({table})")
                    }
                    if not source_columns:
                        raise RuntimeError(f"Missing source table: {table}")
                    rows = source.execute(f"SELECT * FROM {table}").fetchall()
                    for source_row in rows:
                        row = dict(source_row)
                        if table in {"user_profile", "daily_meals", "weight_logs"} and "user_id" not in row:
                            row["user_id"] = 1
                        columns = [
                            column for column in TARGET_COLUMNS[table]
                            if column in row
                        ]
                        placeholders = ", ".join(["%s"] * len(columns))
                        names = ", ".join(columns)
                        cursor.execute(
                            f"INSERT INTO {table} ({names}) VALUES ({placeholders}) "
                            "ON CONFLICT (id) DO NOTHING",
                            [row[column] for column in columns],
                        )
                    cursor.execute(
                        "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                        "COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) "
                        f"FROM {table}",
                        (table,),
                    )
                    print(f"{table}: processed {len(rows)} source rows")
    finally:
        source.close()


if __name__ == "__main__":
    main()
