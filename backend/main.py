from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import date, datetime, timezone
import json
import csv
import io

import sys
from pathlib import Path

# Добавляем текущую папку в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

from models import (
    SleepRecord, SleepRecordCreate, SleepAnomaly,
    Recommendation, UserContextCreate, SleepSummary, SleepPhases
)
from database import (
    init_db, save_sleep_record, get_sleep_records,
    save_anomaly, delete_anomalies_in_range, get_anomalies,
    save_user_context, get_user_context
)
from analyzer import analyze_sleep, calculate_sleep_score
from recommendations import generate_recommendations

# Нормальный импорт симулятора (вместо importlib.util)
from connectors.simulator import SimulatorConnector

# ─────────────────────────────────────────
#  КОНСТАНТЫ
# ─────────────────────────────────────────

MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 МБ — защита от DoS
MAX_CSV_ROWS = 1000

# ─────────────────────────────────────────
#  ИНИЦИАЛИЗАЦИЯ
# ─────────────────────────────────────────

app = FastAPI(
    title="Sleep Analyzer API",
    description="Анализ сна и выявление аномалий с носимых устройств",
    version="1.0.0"
)

# CORS — разрешаем запросы от React Native / веб
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    init_db()
    print("🚀 Sleep Analyzer API запущен")


# ─────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ
# ─────────────────────────────────────────

def _parse_iso_datetime(value: str) -> datetime:
    """Парсит ISO datetime с учётом timezone. Без tz считаем UTC."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─────────────────────────────────────────
#  SLEEP RECORDS
# ─────────────────────────────────────────

@app.get("/api/sleep", response_model=List[dict])
async def get_sleep(user_id: str = "default", days: int = 30):
    """Возвращает записи сна за последние N дней"""
    records = get_sleep_records(user_id=user_id, limit=days)
    return records


@app.post("/api/sleep", response_model=dict)
async def create_sleep_record(record: SleepRecordCreate, user_id: str = "default"):
    """Создаёт новую запись сна"""
    data = {
        "date": str(record.date),
        "start_time": str(record.start_time),
        "end_time": str(record.end_time),
        "duration_minutes": record.duration_minutes,
        "phase_light": record.phases.light,
        "phase_deep": record.phases.deep,
        "phase_rem": record.phases.rem,
        "phase_awake": record.phases.awake,
        "heart_rate_avg": record.heart_rate_avg,
        "heart_rate_min": record.heart_rate_min,
        "heart_rate_max": record.heart_rate_max,
        "spo2_avg": record.spo2_avg,
        "spo2_min": record.spo2_min,
        "awakenings_count": record.awakenings_count,
        "source": record.source,
        "sleep_score": None
    }

    record_id = save_sleep_record(data, user_id)
    return {"id": record_id, "status": "created"}


@app.get("/api/sleep/summary", response_model=dict)
async def get_summary(user_id: str = "default"):
    """Сводная статистика для дашборда"""
    records = get_sleep_records(user_id=user_id, limit=30)

    if not records:
        return {
            "total_records": 0,
            "avg_duration_minutes": 0,
            "avg_sleep_score": None,
            "avg_deep_percent": 0,
            "avg_rem_percent": 0,
            "anomalies_last_30_days": 0,
            "last_night": None
        }

    durations = [r["duration_minutes"] for r in records]
    scores = [r["sleep_score"] for r in records if r["sleep_score"]]

    deep_percents = []
    rem_percents = []
    for r in records:
        total = r["duration_minutes"]
        if total > 0:
            deep_percents.append((r["phase_deep"] / total) * 100)
            rem_percents.append((r["phase_rem"] / total) * 100)

    anomalies = get_anomalies(user_id=user_id, days=30)

    return {
        "total_records": len(records),
        "avg_duration_minutes": round(sum(durations) / len(durations), 1),
        "avg_sleep_score": round(sum(scores) / len(scores), 1) if scores else None,
        "avg_deep_percent": round(sum(deep_percents) / len(deep_percents), 1) if deep_percents else 0,
        "avg_rem_percent": round(sum(rem_percents) / len(rem_percents), 1) if rem_percents else 0,
        "anomalies_last_30_days": len(anomalies),
        "last_night": records[0] if records else None
    }


# ─────────────────────────────────────────
#  CSV ЗАГРУЗКА (10 МБ, стримово)
# ─────────────────────────────────────────

@app.post("/api/upload/csv")
async def upload_csv(file: UploadFile = File(...), user_id: str = "default"):
    """
    Загружает данные сна из CSV файла.
    Лимит: 10 МБ, 1000 строк (стримовое чтение).
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате CSV")

    # Стримово читаем максимум MAX_CSV_BYTES
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_CSV_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Файл слишком большой (максимум {MAX_CSV_BYTES // (1024 * 1024)} МБ)"
            )
        chunks.append(chunk)
    raw = b"".join(chunks)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []

    saved_count = 0
    errors = []

    is_rich_format = "sleep_start_timestamp" in headers or "date_recorded" in headers

    for i, row in enumerate(reader):
        if saved_count >= MAX_CSV_ROWS:
            break
        try:
            if is_rich_format:
                date_str = row.get("date_recorded", row.get("date", ""))[:10]
                start_time = row.get("sleep_start_timestamp", row.get("start_time", ""))
                end_time = row.get("sleep_end_timestamp", row.get("end_time", ""))
                duration = int(float(row.get("duration_minutes", 0)))
                total = duration if duration > 0 else 1

                deep_pct  = float(row.get("sleep_stage_deep_pct", 0)) / 100
                light_pct = float(row.get("sleep_stage_light_pct", 0)) / 100
                rem_pct   = float(row.get("sleep_stage_rem_pct", 0)) / 100
                awake_pct = float(row.get("sleep_stage_awake_pct", 0)) / 100

                hr_avg  = float(row["heart_rate_mean_bpm"]) if row.get("heart_rate_mean_bpm") else None
                hr_min  = float(row["heart_rate_min_bpm"])  if row.get("heart_rate_min_bpm")  else None
                hr_max  = float(row["heart_rate_max_bpm"])  if row.get("heart_rate_max_bpm")  else None
                spo2    = float(row["spo2_mean_pct"])        if row.get("spo2_mean_pct")        else None
                spo2min = float(row["spo2_min_pct"])         if row.get("spo2_min_pct")         else None
                score   = int(float(row["sleep_score"]))     if row.get("sleep_score")          else None
                awake_c = int(float(row.get("wake_after_sleep_onset_minutes", 0)))

                data = {
                    "date": date_str,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration_minutes": duration,
                    "phase_deep":  int(total * deep_pct),
                    "phase_light": int(total * light_pct),
                    "phase_rem":   int(total * rem_pct),
                    "phase_awake": int(total * awake_pct),
                    "heart_rate_avg": hr_avg,
                    "heart_rate_min": hr_min,
                    "heart_rate_max": hr_max,
                    "spo2_avg": spo2,
                    "spo2_min": spo2min,
                    "awakenings_count": awake_c,
                    "sleep_score": score,
                    "source": "csv",
                }
            else:
                data = {
                    "date": row.get("date", ""),
                    "start_time": row.get("start_time", ""),
                    "end_time": row.get("end_time", ""),
                    "duration_minutes": int(float(row.get("duration_minutes", 0))),
                    "phase_light": int(float(row.get("phase_light", 0))),
                    "phase_deep":  int(float(row.get("phase_deep", 0))),
                    "phase_rem":   int(float(row.get("phase_rem", 0))),
                    "phase_awake": int(float(row.get("phase_awake", 0))),
                    "heart_rate_avg": float(row["heart_rate_avg"]) if row.get("heart_rate_avg") else None,
                    "heart_rate_min": None,
                    "heart_rate_max": None,
                    "spo2_avg": float(row["spo2_avg"]) if row.get("spo2_avg") else None,
                    "spo2_min": None,
                    "awakenings_count": int(float(row.get("awakenings_count", 0))),
                    "sleep_score": None,
                    "source": "csv",
                }

            if not data["date"]:
                continue

            save_sleep_record(data, user_id)
            saved_count += 1

        except Exception as e:
            errors.append(f"Строка {i+2}: {str(e)}")
            if len(errors) > 10:
                break

    return {
        "saved": saved_count,
        "errors": errors[:10],
        "message": f"Загружено {saved_count} записей"
    }


# ─────────────────────────────────────────
#  СИМУЛЯТОР
# ─────────────────────────────────────────

@app.post("/api/simulate")
async def load_simulation(user_id: str = "default", days: int = 30):
    """Загружает симулированные данные для демонстрации"""
    connector = SimulatorConnector(days=days)
    records = connector.fetch()

    saved = 0
    for record in records:
        score = calculate_sleep_score(record)
        data = {
            "date": str(record.date),
            "start_time": str(record.start_time),
            "end_time": str(record.end_time),
            "duration_minutes": record.duration_minutes,
            "phase_light": record.phases.light,
            "phase_deep": record.phases.deep,
            "phase_rem": record.phases.rem,
            "phase_awake": record.phases.awake,
            "heart_rate_avg": record.heart_rate_avg,
            "heart_rate_min": record.heart_rate_min,
            "heart_rate_max": record.heart_rate_max,
            "spo2_avg": record.spo2_avg,
            "spo2_min": record.spo2_min,
            "awakenings_count": record.awakenings_count,
            "source": "simulator",
            "sleep_score": score
        }
        save_sleep_record(data, user_id)
        saved += 1

    return {"saved": saved, "message": f"Загружено {saved} симулированных записей"}


# ─────────────────────────────────────────
#  АНАЛИЗ
# ─────────────────────────────────────────

@app.post("/api/analyze")
async def run_analysis(user_id: str = "default"):
    """
    Запускает полный анализ сна:
    - Пересчитывает Sleep Score
    - Выявляет аномалии (правила + ML)
    - Генерирует рекомендации
    Старые аномалии за период удаляются перед записью новых.
    """
    raw_records = get_sleep_records(user_id=user_id, limit=90)

    if not raw_records:
        raise HTTPException(status_code=404, detail="Нет данных для анализа")

    def _int(v): return int(v) if v is not None else 0
    def _float(v): return float(v) if v is not None else None

    records = []
    for r in raw_records:
        record = SleepRecord(
            id=r["id"],
            user_id=user_id,
            date=r["date"],
            start_time=r["start_time"],
            end_time=r["end_time"],
            duration_minutes=_int(r["duration_minutes"]),
            phases=SleepPhases(
                light=_int(r["phase_light"]),
                deep=_int(r["phase_deep"]),
                rem=_int(r["phase_rem"]),
                awake=_int(r["phase_awake"])
            ),
            heart_rate_avg=_float(r["heart_rate_avg"]),
            heart_rate_min=_float(r["heart_rate_min"]),
            heart_rate_max=_float(r["heart_rate_max"]),
            spo2_avg=_float(r["spo2_avg"]),
            spo2_min=_float(r["spo2_min"]),
            sleep_score=_int(r["sleep_score"]) if r["sleep_score"] is not None else None,
            awakenings_count=_int(r["awakenings_count"]),
            source=r["source"]
        )
        records.append(record)

    # Анализ
    analyzed_records, anomalies = analyze_sleep(records)

    # Удаляем старые аномалии за анализируемый период перед записью новых
    if records:
        dates = [str(r.date) for r in records]
        delete_anomalies_in_range(user_id=user_id, dates=dates)

    # Сохраняем новые аномалии
    for anomaly in anomalies:
        save_anomaly({
            "sleep_record_id": anomaly.sleep_record_id,
            "date": str(anomaly.date),
            "anomaly_type": anomaly.anomaly_type,
            "title": anomaly.title,
            "description": anomaly.description,
            "severity": anomaly.severity,
            "value": anomaly.value,
            "threshold": anomaly.threshold,
            "is_ml_detected": bool(anomaly.is_ml_detected)
        }, user_id)

    # Рекомендации
    context = get_user_context(user_id=user_id, days=30)
    recommendations = generate_recommendations(anomalies, context, analyzed_records)

    return {
        "analyzed": len(analyzed_records),
        "anomalies_found": len(anomalies),
        "recommendations_count": len(recommendations),
        "anomalies": [
            {
                "date": str(a.date),
                "type": a.anomaly_type,
                "title": a.title,
                "severity": a.severity,
                "is_ml": a.is_ml_detected
            }
            for a in anomalies
        ],
        "recommendations": [
            {
                "category": r.category,
                "title": r.title,
                "text": r.text,
                "priority": r.priority
            }
            for r in recommendations
        ]
    }


# ─────────────────────────────────────────
#  АНОМАЛИИ И РЕКОМЕНДАЦИИ
# ─────────────────────────────────────────

@app.get("/api/anomalies")
async def get_anomalies_endpoint(user_id: str = "default", days: int = 30):
    """Возвращает аномалии за последние N дней"""
    return get_anomalies(user_id=user_id, days=days)


# ─────────────────────────────────────────
#  ДНЕВНИК (USER CONTEXT)
# ─────────────────────────────────────────

@app.post("/api/context")
async def create_context(context: UserContextCreate, user_id: str = "default"):
    """Сохраняет запись вечернего дневника"""
    data = {
        "date": str(context.date),
        "caffeine_after_15": bool(context.caffeine_after_15),
        "alcohol": bool(context.alcohol),
        "stress_level": int(context.stress_level),
        "physical_activity": bool(context.physical_activity),
        "screen_before_bed": bool(context.screen_before_bed),
        "late_meal": bool(context.late_meal),
        "notes": context.notes
    }
    save_user_context(data, user_id)
    return {"status": "saved"}


@app.get("/api/context")
async def get_context(user_id: str = "default", days: int = 30):
    """Возвращает записи дневника"""
    return get_user_context(user_id=user_id, days=days)


# ─────────────────────────────────────────
#  HEALTHCHECK
# ─────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "Sleep Analyzer API",
        "version": "1.0.0",
        "status": "running"
    }


# ─────────────────────────────────────────
#  HEALTH CONNECT (с корректным timezone)
# ─────────────────────────────────────────

@app.post("/api/health-connect")
async def receive_health_connect(payload: dict, user_id: str = "default"):
    """
    Принимает данные сна из Health Connect (Android).
    Корректно обрабатывает timezone — дата сна определяется
    по локальному времени засыпания, а не по UTC.
    """
    sessions = payload.get("sleepSessions", [])
    saved = 0

    for session in sessions:
        try:
            start = session.get("startTime", "")
            end   = session.get("endTime", "")
            if not start or not end:
                continue

            start_dt = _parse_iso_datetime(start)
            end_dt   = _parse_iso_datetime(end)
            duration = int((end_dt - start_dt).total_seconds() / 60)
            if duration <= 0:
                continue

            # Дата сна = локальная дата начала сна (по tz клиента)
            date_str = start_dt.strftime("%Y-%m-%d")

            # Подсчёт фаз из stages
            stages = session.get("stages", [])
            deep = light = rem = awake = 0
            for s in stages:
                stage_type = s.get("stage", 0)
                s_start = _parse_iso_datetime(s["startTime"])
                s_end   = _parse_iso_datetime(s["endTime"])
                mins = max(0, int((s_end - s_start).total_seconds() / 60))
                if stage_type == 4:   deep  += mins
                elif stage_type == 3: light += mins
                elif stage_type == 5: rem   += mins
                elif stage_type == 2: awake += mins

            data = {
                "date": date_str,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "duration_minutes": duration,
                "phase_deep":  deep,
                "phase_light": light,
                "phase_rem":   rem,
                "phase_awake": awake,
                "heart_rate_avg": session.get("heartRateAvg"),
                "heart_rate_min": session.get("heartRateMin"),
                "heart_rate_max": session.get("heartRateMax"),
                "spo2_avg": session.get("spo2Avg"),
                "spo2_min": session.get("spo2Min"),
                "awakenings_count": session.get("awakeningsCount", 0),
                "sleep_score": None,
                "source": "health_connect",
            }

            save_sleep_record(data, user_id)
            saved += 1

        except Exception as e:
            print(f"Health Connect parse error: {e}")

    return {"saved": saved, "message": f"Сохранено {saved} сессий сна из Health Connect"}


# ─────────────────────────────────────────
#  GADGETBRIDGE — единственный webhook
#  (deep больше НЕ fallback'ит на light)
# ─────────────────────────────────────────

@app.post("/api/gadgetbridge/webhook")
async def gadgetbridge_webhook(payload: dict, user_id: str = "default"):
    """
    Принимает данные от Gadgetbridge через HTTP.
    Настройка в Gadgetbridge:
    Настройки → Управление устройством → HTTP Reporter → URL сервера:
    https://ВАШ-ПРОЕКТ.up.railway.app/api/gadgetbridge/webhook
    """
    try:
        sleep = payload.get("sleep") or payload.get("Sleep") or {}

        if not sleep:
            return {"status": "ok", "message": "Нет данных сна в payload"}

        start_ts = sleep.get("start", sleep.get("startTime", 0))
        end_ts   = sleep.get("end",   sleep.get("endTime", 0))

        if isinstance(start_ts, (int, float)) and start_ts > 1000000000:
            start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            end_dt   = datetime.fromtimestamp(end_ts,   tz=timezone.utc)
        else:
            start_dt = _parse_iso_datetime(str(start_ts))
            end_dt   = _parse_iso_datetime(str(end_ts))

        duration = int((end_dt - start_dt).total_seconds() / 60)
        if duration <= 0:
            raise HTTPException(status_code=400, detail="Некорректная длительность сна")

        # ВАЖНО: deep НЕ fallback'ит на light — это разные фазы
        deep  = int(sleep.get("deepSleepDuration", 0) or 0)
        light = int(sleep.get("lightSleepDuration", 0) or 0)
        rem   = int(sleep.get("remSleepDuration", 0) or 0)
        awake = int(sleep.get("awakeDuration", 0) or 0)

        data = {
            "date": start_dt.strftime("%Y-%m-%d"),
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "duration_minutes": duration,
            "phase_deep":  deep,
            "phase_light": light,
            "phase_rem":   rem,
            "phase_awake": awake,
            "heart_rate_avg": sleep.get("heartRateAverage", sleep.get("heartRate")),
            "heart_rate_min": sleep.get("heartRateMin"),
            "heart_rate_max": sleep.get("heartRateMax"),
            "spo2_avg": sleep.get("spo2Average", sleep.get("spo2")),
            "spo2_min": sleep.get("spo2Min"),
            "awakenings_count": int(sleep.get("wakeupCount", 0) or 0),
            "sleep_score": None,
            "source": "gadgetbridge",
        }

        save_sleep_record(data, user_id)
        return {"status": "ok", "message": "Данные сна сохранены", "date": data["date"]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка парсинга: {str(e)}")
