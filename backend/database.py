import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
#  ПОДКЛЮЧЕНИЕ — Supabase Transaction Pooler
# ─────────────────────────────────────────

def get_connection():
    """
    Transaction Pooler (порт 6543) требует:
    1. sslmode в строке подключения, не как отдельный параметр
    2. options=-c statement_timeout=30000 для таймаута
    3. Без prepared statements (они не работают с pooler)
    """
    db_url = os.environ["DATABASE_URL"]

    # Убираем дублирующийся sslmode если есть
    if "sslmode" not in db_url:
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"

    conn = psycopg2.connect(
        db_url,
        # Отключаем prepared statements — обязательно для Transaction Pooler
        options="-c statement_timeout=30000"
    )
    conn.autocommit = False
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sleep_records (
                id                SERIAL PRIMARY KEY,
                user_id           TEXT    NOT NULL DEFAULT 'default',
                date              TEXT    NOT NULL,
                start_time        TEXT    NOT NULL DEFAULT '',
                end_time          TEXT    NOT NULL DEFAULT '',
                duration_minutes  INTEGER NOT NULL DEFAULT 0,
                phase_light       INTEGER DEFAULT 0,
                phase_deep        INTEGER DEFAULT 0,
                phase_rem         INTEGER DEFAULT 0,
                phase_awake       INTEGER DEFAULT 0,
                heart_rate_avg    FLOAT,
                heart_rate_min    FLOAT,
                heart_rate_max    FLOAT,
                spo2_avg          FLOAT,
                spo2_min          FLOAT,
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
                value            FLOAT,
                threshold        FLOAT,
                is_ml_detected   BOOLEAN DEFAULT FALSE,
                created_at       TIMESTAMP DEFAULT NOW()
            )
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
        print("✅ База данных инициализирована (Supabase Transaction Pooler)")
    except Exception as e:
        conn.rollback()
        print(f"❌ Ошибка инициализации БД: {e}")
        raise
    finally:
        cur.close()
        conn.close()


# ─────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────

def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

def _safe_int(v, default=0):
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


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
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s
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
        """, (
            user_id,
            str(record.get("date", "")),
            str(record.get("start_time", "")),
            str(record.get("end_time", "")),
            _safe_int(record.get("duration_minutes")),
            _safe_int(record.get("phase_light")),
            _safe_int(record.get("phase_deep")),
            _safe_int(record.get("phase_rem")),
            _safe_int(record.get("phase_awake")),
            _safe_float(record.get("heart_rate_avg")),
            _safe_float(record.get("heart_rate_min")),
            _safe_float(record.get("heart_rate_max")),
            _safe_float(record.get("spo2_avg")),
            _safe_float(record.get("spo2_min")),
            _safe_int(record.get("sleep_score")) if record.get("sleep_score") is not None else None,
            _safe_int(record.get("awakenings_count")),
            str(record.get("source", "unknown")),
        ))
        record_id = cur.fetchone()[0]
        conn.commit()
        return record_id
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def get_sleep_records(user_id: str = "default", limit: int = 90) -> list:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM sleep_records
            WHERE user_id = %s
            ORDER BY date DESC
            LIMIT %s
        """, (user_id, limit))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            anomaly.get("sleep_record_id"),
            str(anomaly.get("date", "")),
            str(anomaly.get("anomaly_type", "")),
            str(anomaly.get("title", "")),
            str(anomaly.get("description", "")),
            str(anomaly.get("severity", "low")),
            _safe_float(anomaly.get("value")),
            _safe_float(anomaly.get("threshold")),
            bool(anomaly.get("is_ml_detected", False)),
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def get_anomalies(user_id: str = "default", days: int = 30) -> list:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM sleep_anomalies
            WHERE user_id = %s
              AND created_at >= NOW() - INTERVAL '1 day' * %s
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET
                caffeine_after_15 = EXCLUDED.caffeine_after_15,
                alcohol           = EXCLUDED.alcohol,
                stress_level      = EXCLUDED.stress_level,
                physical_activity = EXCLUDED.physical_activity,
                screen_before_bed = EXCLUDED.screen_before_bed,
                late_meal         = EXCLUDED.late_meal,
                notes             = EXCLUDED.notes
        """, (
            user_id,
            str(context.get("date", "")),
            bool(context.get("caffeine_after_15", False)),
            bool(context.get("alcohol", False)),
            _safe_int(context.get("stress_level"), 1),
            bool(context.get("physical_activity", False)),
            bool(context.get("screen_before_bed", False)),
            bool(context.get("late_meal", False)),
            context.get("notes"),
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def get_user_context(user_id: str = "default", days: int = 30) -> list:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM user_context
            WHERE user_id = %s
              AND created_at >= NOW() - INTERVAL '1 day' * %s
            ORDER BY date DESC
        """, (user_id, days))
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()
