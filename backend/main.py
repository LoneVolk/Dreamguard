from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import date
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
    save_anomaly, get_anomalies,
    save_user_context, get_user_context
)
from analyzer import analyze_sleep, calculate_sleep_score
from recommendations import generate_recommendations

# Импортируем симулятор
import importlib.util
spec = importlib.util.spec_from_file_location("simulator", Path(__file__).parent / "connectors" / "simulator.py")
simulator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulator_module)
SimulatorConnector = simulator_module.SimulatorConnector

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
#  GADGETBRIDGE — HTTP ХУКИ
# ─────────────────────────────────────────

@app.post("/api/gadgetbridge/webhook")
async def gadgetbridge_webhook(payload: dict):
    """
    Принимает данные напрямую от Gadgetbridge.
    Настройте URL в Gadgetbridge: http://ВАШ_IP:8000/api/gadgetbridge/webhook
    """
    try:
        # Gadgetbridge шлёт данные активности — парсим сон
        sleep_data = _parse_gadgetbridge_payload(payload)
        if sleep_data:
            save_sleep_record(sleep_data)
            return {"status": "ok", "message": "Данные сна сохранены"}
        return {"status": "ok", "message": "Данные активности получены (не сон)"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _parse_gadgetbridge_payload(payload: dict) -> Optional[dict]:
    """Парсит webhook от Gadgetbridge в универсальный формат"""
    # Gadgetbridge шлёт данные в формате activity samples
    # Фильтруем только ночные данные (raw_kind = 112 для Huami/Amazfit)
    if "sleep" not in payload and "activity" not in payload:
        return None

    sleep = payload.get("sleep", {})
    if not sleep:
        return None

    return {
        "date": sleep.get("date", str(date.today())),
        "start_time": sleep.get("start", ""),
        "end_time": sleep.get("end", ""),
        "duration_minutes": sleep.get("duration", 0),
        "phase_light": sleep.get("lightSleepDuration", 0),
        "phase_deep": sleep.get("deepSleepDuration", 0),
        "phase_rem": sleep.get("remSleepDuration", 0),
        "phase_awake": sleep.get("awakeDuration", 0),
        "heart_rate_avg": sleep.get("heartRateAverage"),
        "heart_rate_min": sleep.get("heartRateMin"),
        "heart_rate_max": sleep.get("heartRateMax"),
        "spo2_avg": sleep.get("spo2Average"),
        "spo2_min": sleep.get("spo2Min"),
        "awakenings_count": sleep.get("wakeupCount", 0),
        "source": "gadgetbridge",
        "sleep_score": None
    }


# ─────────────────────────────────────────
#  CSV ЗАГРУЗКА
# ─────────────────────────────────────────

@app.post("/api/upload/csv")
async def upload_csv(file: UploadFile = File(...), user_id: str = "default"):
    """
    Загружает данные сна из CSV файла.
    Поддерживает экспорт из Zepp/Mi Fitness и стандартный формат.

    Ожидаемые колонки CSV:
    date, start_time, end_time, duration_minutes,
    phase_light, phase_deep, phase_rem, phase_awake,
    heart_rate_avg, spo2_avg, awakenings_count
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате CSV")

    content = await file.read()
    text = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))

    saved_count = 0
    errors = []

    for i, row in enumerate(reader):
        try:
            data = {
                "date": row["date"],
                "start_time": row.get("start_time", ""),
                "end_time": row.get("end_time", ""),
                "duration_minutes": int(row.get("duration_minutes", 0)),
                "phase_light": int(row.get("phase_light", 0)),
                "phase_deep": int(row.get("phase_deep", 0)),
                "phase_rem": int(row.get("phase_rem", 0)),
                "phase_awake": int(row.get("phase_awake", 0)),
                "heart_rate_avg": float(row["heart_rate_avg"]) if row.get("heart_rate_avg") else None,
                "heart_rate_min": None,
                "heart_rate_max": None,
                "spo2_avg": float(row["spo2_avg"]) if row.get("spo2_avg") else None,
                "spo2_min": None,
                "awakenings_count": int(row.get("awakenings_count", 0)),
                "source": "csv",
                "sleep_score": None
            }
            save_sleep_record(data, user_id)
            saved_count += 1
        except Exception as e:
            errors.append(f"Строка {i+2}: {str(e)}")

    return {
        "saved": saved_count,
        "errors": errors,
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
    """
    raw_records = get_sleep_records(user_id=user_id, limit=90)

    if not raw_records:
        raise HTTPException(status_code=404, detail="Нет данных для анализа")

    # Конвертируем в SleepRecord (приводим типы — SQLite возвращает строки)
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

    # Сохраняем аномалии
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
            "is_ml_detected": int(anomaly.is_ml_detected)
        }, user_id)

    # Рекомендации
    context = get_user_context(user_id=user_id, days=30)
    recommendations = generate_recommendations(anomalies, context, analyzed_records)

    return {
        "analyzed": len(analyzed_records),
        "anomalies_found": len(anomalies),
        "recommendations": len(recommendations),
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
        "caffeine_after_15": int(context.caffeine_after_15),
        "alcohol": int(context.alcohol),
        "stress_level": context.stress_level,
        "physical_activity": int(context.physical_activity),
        "screen_before_bed": int(context.screen_before_bed),
        "late_meal": int(context.late_meal),
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
