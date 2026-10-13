"""Database layer for profiles, meal tracking, and weight history."""
import sqlite3
import json
import logging
import re
from contextlib import closing
from datetime import date
from typing import Optional, Dict, Any, List
from config import settings

logger = logging.getLogger(__name__)

def is_postgres() -> bool:
    return bool(settings.DATABASE_URL)


class CursorAdapter:
    """Keep parameter and inserted-ID handling consistent across SQLite and PostgreSQL."""

    def __init__(self, cursor: Any):
        self._cursor = cursor
        self.lastrowid: Optional[int] = None

    def execute(self, query: str, parameters: Any = ()) -> "CursorAdapter":
        if is_postgres():
            query = query.replace("?", "%s")
            query = re.sub(r"(?<!:):([A-Za-z_]\w*)", r"%(\1)s", query)
            if (
                query.lstrip().upper().startswith("INSERT INTO ")
                and "INSERT INTO SCHEMA_MIGRATIONS " not in query.upper()
                and " RETURNING " not in query.upper()
            ):
                query = query.rstrip().rstrip(";") + " RETURNING id"
                self._cursor.execute(query, parameters)
                row = self._cursor.fetchone()
                self.lastrowid = row["id"] if row else None
            else:
                self._cursor.execute(query, parameters)
                self.lastrowid = None
        else:
            self._cursor.execute(query, parameters)
            self.lastrowid = self._cursor.lastrowid
        return self

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> Any:
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


def get_db_connection() -> Any:
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        database_url = settings.DATABASE_URL
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        return psycopg.connect(database_url, row_factory=dict_row)

    settings.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DATABASE_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def get_cursor(conn: Any) -> CursorAdapter:
    return CursorAdapter(conn.cursor())

def init_db() -> None:
    """Initialize database tables."""
    conn = get_db_connection()
    cursor = get_cursor(conn)
    auto_id = "BIGSERIAL PRIMARY KEY" if is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    user_id_type = "BIGINT" if is_postgres() else "INTEGER"
    try:
        if is_postgres():
            cursor.execute("SELECT pg_advisory_xact_lock(?)", (6128347594801001,))
            cursor.fetchone()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {auto_id},
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
        cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS user_profile (
        id {auto_id},
        user_id {user_id_type} NOT NULL,
        name TEXT DEFAULT 'Usuario',
        gender TEXT NOT NULL,
        age INTEGER NOT NULL,
        height_cm REAL NOT NULL,
        current_weight_kg REAL NOT NULL,
        target_weight_kg REAL NOT NULL,
        activity_level TEXT NOT NULL,
        goal TEXT NOT NULL,
        target_weeks INTEGER NOT NULL,
        bmr REAL NOT NULL,
        tdee REAL NOT NULL,
        daily_calories REAL NOT NULL,
        protein_g REAL NOT NULL,
        fat_g REAL NOT NULL,
        carbs_g REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
        cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS daily_meals (
        id {auto_id},
        user_id {user_id_type} NOT NULL,
        date_logged DATE NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        meal_type TEXT DEFAULT 'Comida',
        dish_name TEXT NOT NULL,
        total_calories REAL NOT NULL,
        protein_g REAL NOT NULL,
        carbs_g REAL NOT NULL,
        fat_g REAL NOT NULL,
        fiber_g REAL DEFAULT 0.0,
        confidence_score REAL DEFAULT 1.0,
        raw_items_json TEXT,
        image_base64 TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
        cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS weight_logs (
        id {auto_id},
        user_id {user_id_type} NOT NULL,
        date_logged DATE NOT NULL,
        weight_kg REAL NOT NULL,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
        cursor.execute("SELECT MAX(version) AS version FROM schema_migrations")
        schema_version = cursor.fetchone()["version"] or 0
        if schema_version < 1:
            if is_postgres():
                for table in ("user_profile", "daily_meals", "weight_logs"):
                    cursor.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = ?",
                        (table,),
                    )
                    columns = {row["column_name"] for row in cursor.fetchall()}
                    if "user_id" not in columns:
                        cursor.execute(
                            f"ALTER TABLE {table} ADD COLUMN user_id {user_id_type} NOT NULL DEFAULT 1"
                        )
            else:
                for table in ("user_profile", "daily_meals", "weight_logs"):
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = {row["name"] for row in cursor.fetchall()}
                    if "user_id" not in columns:
                        cursor.execute(
                            f"ALTER TABLE {table} ADD COLUMN user_id {user_id_type} NOT NULL DEFAULT 1"
                        )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_meals_user_date "
                "ON daily_meals(user_id, date_logged)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_weight_user_date "
                "ON weight_logs(user_id, date_logged)"
            )
            cursor.execute("INSERT INTO schema_migrations (version) VALUES (?)", (1,))
        conn.commit()
    finally:
        conn.close()

def get_user_profile(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve the profile for the given user_id, or None if not set."""
    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            "SELECT * FROM user_profile WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
    if row:
        return dict(row)
    return None


def save_user_profile(data: Dict[str, Any]) -> int:
    """Insert or update user profile and register initial weight entry."""
    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
        INSERT INTO user_profile (
            user_id, name, gender, age, height_cm, current_weight_kg,
            target_weight_kg, activity_level, goal, target_weeks,
            bmr, tdee, daily_calories, protein_g, fat_g, carbs_g, updated_at
        ) VALUES (
            :user_id, :name, :gender, :age, :height_cm, :current_weight_kg,
            :target_weight_kg, :activity_level, :goal, :target_weeks,
            :bmr, :tdee, :daily_calories, :protein_g, :fat_g, :carbs_g, CURRENT_TIMESTAMP
        )
        """, data)
        profile_id = cursor.lastrowid

        today_str = date.today().isoformat()
        cursor.execute(
            "SELECT id FROM weight_logs WHERE user_id = ? AND date_logged = ?",
            (data["user_id"], today_str),
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                    INSERT INTO weight_logs (user_id, date_logged, weight_kg, notes)
                    VALUES (?, ?, ?, 'Registro de perfil')
                """,
                (data["user_id"], today_str, float(data["current_weight_kg"])),
            )
        else:
            cursor.execute(
                """
                    UPDATE weight_logs SET weight_kg = ? WHERE user_id = ? AND date_logged = ?
                """,
                (float(data["current_weight_kg"]), data["user_id"], today_str),
            )

        conn.commit()
        return profile_id

def log_meal(
    user_id: int,
    dish_name: str,
    total_calories: float,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
    fiber_g: float = 0.0,
    confidence_score: float = 1.0,
    items: Optional[List[Dict[str, Any]]] = None,
    image_base64: Optional[str] = None,
    meal_type: str = "Comida",
    target_date: Optional[str] = None
) -> int:
    """Save a logged meal."""
    if not target_date:
        target_date = date.today().isoformat()

    items_json = json.dumps(items) if items else "[]"

    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
        INSERT INTO daily_meals (
            user_id, date_logged, meal_type, dish_name, total_calories,
            protein_g, carbs_g, fat_g, fiber_g, confidence_score,
            raw_items_json, image_base64
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, target_date, meal_type, dish_name, total_calories,
        protein_g, carbs_g, fat_g, fiber_g, confidence_score,
        items_json, image_base64
        ))
        meal_id = cursor.lastrowid
        conn.commit()
        return meal_id

def update_meal(user_id: int, meal_id: int, dish_name: str, total_calories: float, protein_g: float, carbs_g: float, fat_g: float, fiber_g: float = 0.0, meal_type: str = "Comida") -> bool:
    """Update an existing meal's details for a specific user."""
    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
        UPDATE daily_meals
        SET dish_name = ?,
            total_calories = ?,
            protein_g = ?,
            carbs_g = ?,
            fat_g = ?,
            fiber_g = ?,
            meal_type = ?
        WHERE id = ? AND user_id = ?
    """, (
        dish_name, total_calories, protein_g, carbs_g,
        fat_g, fiber_g, meal_type, meal_id, user_id
        ))
        updated = cursor.rowcount > 0
        conn.commit()
        return updated

def get_meals_for_date(user_id: int, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve meals for a specific date for the given user (defaults to today)."""
    if not target_date:
        target_date = date.today().isoformat()

    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute("""
        SELECT * FROM daily_meals
        WHERE user_id = ? AND date_logged = ?
        ORDER BY timestamp DESC
        """, (user_id, target_date))
        rows = cursor.fetchall()

    meals = []
    for row in rows:
        meal = dict(row)
        try:
            meal["items"] = json.loads(meal["raw_items_json"]) if meal.get("raw_items_json") else []
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Skipping invalid meal items JSON for meal %s: %s", meal["id"], exc)
            meal["items"] = []
        meals.append(meal)
    return meals

def get_daily_summary(user_id: int, target_date: Optional[str] = None) -> Dict[str, float]:
    """Calculate total consumed calories and macros for a date for the given user."""
    meals = get_meals_for_date(user_id, target_date)
    summary = {
        "calories": sum(m["total_calories"] for m in meals),
        "proteins": sum(m["protein_g"] for m in meals),
        "carbs": sum(m["carbs_g"] for m in meals),
        "fats": sum(m["fat_g"] for m in meals),
        "fiber": sum(m.get("fiber_g", 0.0) for m in meals),
        "meal_count": len(meals)
    }
    return summary

def delete_meal(meal_id: int, user_id: int) -> bool:
    """Delete a meal by ID for the given user."""
    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute("DELETE FROM daily_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted

def log_weight(user_id: int, weight_kg: float, target_date: Optional[str] = None, notes: str = "") -> int:
    """Log or update weight measurement for a specific date."""
    if not target_date:
        target_date = date.today().isoformat()
    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            "SELECT id FROM weight_logs WHERE user_id = ? AND date_logged = ?",
            (user_id, target_date),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute("""
            UPDATE weight_logs SET weight_kg = ?, notes = ? WHERE id = ?
            """, (weight_kg, notes, row["id"]))
            log_id = row["id"]
        else:
            cursor.execute("""
            INSERT INTO weight_logs (user_id, date_logged, weight_kg, notes)
            VALUES (?, ?, ?, ?)
            """, (user_id, target_date, weight_kg, notes))
            log_id = cursor.lastrowid

        cursor.execute(
            "SELECT id FROM user_profile WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        p_row = cursor.fetchone()
        if p_row:
            cursor.execute(
                "UPDATE user_profile SET current_weight_kg = ? WHERE id = ? AND user_id = ?",
                (weight_kg, p_row["id"], user_id),
            )

        conn.commit()
        return log_id

def get_weight_history(user_id: int) -> List[Dict[str, Any]]:
    """Get weight logs for a specific user ordered chronologically for charts."""
    with closing(get_db_connection()) as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            "SELECT * FROM weight_logs WHERE user_id = ? ORDER BY date_logged ASC, id ASC",
            (user_id,),
        )
        rows = cursor.fetchall()
    return [dict(r) for r in rows]

def clear_user_data(user_id: int) -> None:
    """Delete profile, meal, and weight data belonging only to one user."""
    conn = get_db_connection()
    cursor = get_cursor(conn)
    try:
        cursor.execute("DELETE FROM daily_meals WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM weight_logs WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
