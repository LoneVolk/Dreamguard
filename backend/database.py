import os
import json
from datetime import date
from dotenv import load_dotenv

import psycopg2
import psycopg2.extras

load_dotenv()

# ─────────────────────────────────────────
#  ПОДКЛЮЧЕНИЕ — Supabase PostgreSQL
# ─────────────────────────────────────────

def get_connection():
    conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sleep_records (
            id                SERIAL PRIMARY KEY,
            user_id           TEXT    NOT NULL DEFAULT 'default',
            date              TEXT    NOT NULL,
            start_time        TEXT    NOT NULL,
            end_time          TEXT    NOT NULL,
            duration_minutes  INTEGER NOT NULL,
            phase_light       INTEGER DEFAULT 0,
            phase_deep        INTEGER DEFAULT 0,
            phase_rem         INTEGER DEFAULT 0,
            phase_awake       INTEGER DEFAULT 0,
            heart_rate_avg    REAL,
            heart_rate_min    REAL,
            heart_rate_max    REAL,
            spo2_avg          REAL,
            spo2_min          REAL,
            sleep_score       INTEGER,
            awakenings_count  INTEGER DEFAULT 0,
            source            TEXT    DEFAULT 'unknown',
            created_at        TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_context (
            id                SERIAL PRIMARY KEY,
            user_id           TEXT    NOT NULL DEFAULT 'default',
            date              TEXT    NOT NULL,
            caffeine_after_15 BOOLEAN DEFAULT FALSE,
            alcohol           BOOLEAN DEFAULT FALSE,
            stress_level      INTEGER DEFAULT 1,
            physical_activity BOOLEAN DEFAULT FALSE,
            screen_before_bed BOOLEAN DEFAULT FALSE,
            late_meal         BOOLEAN DEFAULT FALSE,
            notes             TEXT,
            created_at        TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sleep_anomalies (
            id               SERIAL PRIMARY KEY,
            user_id          TEXT    NOT NULL DEFAULT 'default',
            sleep_record_id  INTEGER,
            date             TEXT    NOT NULL,
            anomaly_type     TEXT    NOT NULL,
            title            TEXT    NOT NULL,
            description      TEXT    NOT NULL,
            severity         TEXT    NOT NULL,
            value            REAL,
            threshold        REAL,
            is_ml_detected   BOOLEAN DEFAULT FALSE,
            created_at       TIMESTAMP DEFAULT NOW()
        )
    """)

    # Индекс ускоряет удаление и выборку аномалий по (user_id, date)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_anomalies_user_date
        ON sleep_anomalies(user_id, date)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id         SERIAL PRIMARY KEY,
            user_id    TEXT NOT NULL DEFAULT 'default',
            date       TEXT NOT NULL,
            category   TEXT NOT NULL,
            title      TEXT NOT NULL,
            text       TEXT NOT NULL,
            based_on   TEXT NOT NULL,
            priority   INTEGER DEFAULT 2,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ База данных инициализирована (Supabase PostgreSQL)")


# ─────────────────────────────────────────
#  SLEEP RECORDS
# ─────────────────────────────────────────

def save_sleep_record(record: dict, user_id: str = "default") -> int:
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO sleep_records (
                user_id, date, start_time, end_time, duration_minutes,
                phase_light, phase_deep, phase_rem, phase_awake,
                heart_rate_avg, heart_rate_min, heart_rate_max,
                spo2_avg, spo2_min, sleep_score, awakenings_count, source
            ) VALUES (
                %(user_id)s, %(date)s, %(start_time)s, %(end_time)s, %(duration_minutes)s,
                %(phase_light)s, %(phase_deep)s, %(phase_rem)s, %(phase_awake)s,
                %(heart_rate_avg)s, %(heart_rate_min)s, %(heart_rate_max)s,
                %(spo2_avg)s, %(spo2_min)s, %(sleep_score)s, %(awakenings_count)s, %(source)s
            )
            ON CONFLICT (user_id, date) DO UPDATE SET
                start_time       = EXCLUDED.start_time,
                end_time         = EXCLUDED.end_time,
                duration_minutes = EXCLUDED.duration_minutes,
                phase_light      = EXCLUDED.phase_light,
                phase_deep       = EXCLUDED.phase_deep,
                phase_rem        = EXCLUDED.phase_rem,
                phase_awake      = EXCLUDED.phase_awake,
                heart_rate_avg   = EXCLUDED.heart_rate_avg,
                heart_rate_min   = EXCLUDED.heart_rate_min,
                heart_rate_max   = EXCLUDED.heart_rate_max,
                spo2_avg         = EXCLUDED.spo2_avg,
                spo2_min         = EXCLUDED.spo2_min,
                sleep_score      = EXCLUDED.sleep_score,
                awakenings_count = EXCLUDED.awakenings_count,
                source           = EXCLUDED.source
            RETURNING id
        """, {**record, "user_id": user_id})
        record_id = cur.fetchone()[0]
        conn.commit()
        return record_id
    finally:
        cur.close()
        conn.close()


def get_sleep_records(user_id: str = "default", limit: int = 90) -> list:
    # Анти-SQLi: явное приведение к int с диапазоном
    limit = max(1, min(int(limit), 365))

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM sleep_records
            WHERE user_id = %s
            ORDER BY date DESC
            LIMIT %s
        """, (user_id, limit))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


# ─────────────────────────────────────────
#  АНОМАЛИИ
# ─────────────────────────────────────────

def save_anomaly(anomaly: dict, user_id: str = "default"):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO sleep_anomalies (
                user_id, sleep_record_id, date, anomaly_type,
                title, description, severity, value, threshold, is_ml_detected
            ) VALUES (
                %(user_id)s, %(sleep_record_id)s, %(date)s, %(anomaly_type)s,
                %(title)s, %(description)s, %(severity)s, %(value)s,
                %(threshold)s, %(is_ml_detected)s
            )
        """, {**anomaly, "user_id": user_id})
        conn.commit()
    finally:
        cur.close()
        conn.close()


def delete_anomalies_in_range(user_id: str, dates: list) -> int:
    """
    Удаляет аномалии пользователя за перечисленные даты.
    Используется перед перезаписью результатов /api/analyze
    чтобы не плодить дубли.
    """
    if not dates:
        return 0

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM sleep_anomalies
            WHERE user_id = %s AND date = ANY(%s)
        """, (user_id, list(dates)))
        deleted = cur.rowcount
        conn.commit()
        return deleted
    finally:
        cur.close()
        conn.close()


def get_anomalies(user_id: str = "default", days: int = 30) -> list:
    # Анти-SQLi: явное приведение к int с диапазоном
    days = max(1, min(int(days), 365))

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM sleep_anomalies
            WHERE user_id = %s
              AND date::date >= CURRENT_DATE - (%s || ' days')::interval
            ORDER BY date DESC
        """, (user_id, days))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


# ─────────────────────────────────────────
#  USER CONTEXT
# ─────────────────────────────────────────

def save_user_context(context: dict, user_id: str = "default"):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO user_context (
                user_id, date, caffeine_after_15, alcohol, stress_level,
                physical_activity, screen_before_bed, late_meal, notes
            ) VALUES (
                %(user_id)s, %(date)s, %(caffeine_after_15)s, %(alcohol)s,
                %(stress_level)s, %(physical_activity)s, %(screen_before_bed)s,
                %(late_meal)s, %(notes)s
            )
            ON CONFLICT (user_id, date) DO UPDATE SET
                caffeine_after_15 = EXCLUDED.caffeine_after_15,
                alcohol           = EXCLUDED.alcohol,
                stress_level      = EXCLUDED.stress_level,
                physical_activity = EXCLUDED.physical_activity,
                screen_before_bed = EXCLUDED.screen_before_bed,
                late_meal         = EXCLUDED.late_meal,
                notes             = EXCLUDED.notes
        """, {**context, "user_id": user_id})
        conn.commit()
    finally:
        cur.close()
        conn.close()


def get_user_context(user_id: str = "default", days: int = 30) -> list:
    days = max(1, min(int(days), 365))

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM user_context
            WHERE user_id = %s
              AND date::date >= CURRENT_DATE - (%s || ' days')::interval
            ORDER BY date DESC
        """, (user_id, days))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()
