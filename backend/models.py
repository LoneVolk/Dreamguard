from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date


# ─────────────────────────────────────────
#  ФАЗЫ СНА
# ─────────────────────────────────────────

class SleepPhases(BaseModel):
    """Длительность каждой фазы сна в минутах"""
    light: int = 0       # Лёгкий сон
    deep: int = 0        # Глубокий сон
    rem: int = 0         # REM (быстрый) сон
    awake: int = 0       # Пробуждения


# ─────────────────────────────────────────
#  УНИВЕРСАЛЬНАЯ ЗАПИСЬ СНА
#  Единый формат для всех источников данных
# ─────────────────────────────────────────

class SleepRecord(BaseModel):
    """
    Универсальная модель записи сна.
    Все коннекторы (Fitbit, Gadgetbridge, CSV и др.)
    трансформируют свои данные в этот формат.
    """
    id: Optional[int] = None
    user_id: str = "default"

    # Время сна
    date: date                              # Дата ночи (дата начала)
    start_time: datetime                    # Время засыпания
    end_time: datetime                      # Время пробуждения
    duration_minutes: int                   # Общая длительность сна

    # Фазы сна
    phases: SleepPhases = Field(default_factory=SleepPhases)

    # Физиологические показатели
    heart_rate_avg: Optional[float] = None  # Средний пульс за ночь
    heart_rate_min: Optional[float] = None  # Минимальный пульс
    heart_rate_max: Optional[float] = None  # Максимальный пульс
    spo2_avg: Optional[float] = None        # Среднее насыщение крови О2
    spo2_min: Optional[float] = None        # Минимальное SpO2

    # Метрики качества
    sleep_score: Optional[int] = None       # Sleep Score 0-100 (считается позже)
    awakenings_count: int = 0               # Количество пробуждений

    # Источник данных
    source: str = "unknown"  # "fitbit" | "gadgetbridge" | "csv" | "simulator"

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat()
        }


# ─────────────────────────────────────────
#  ПОЛЬЗОВАТЕЛЬСКИЙ КОНТЕКСТ (ДНЕВНИК)
# ─────────────────────────────────────────

class UserContext(BaseModel):
    """
    Вечерний дневник пользователя.
    Заполняется перед сном для корреляционного анализа.
    """
    id: Optional[int] = None
    user_id: str = "default"
    date: date                                      # Дата записи

    # Факторы влияющие на сон
    caffeine_after_15: bool = False                 # Кофеин после 15:00
    alcohol: bool = False                           # Алкоголь
    stress_level: int = Field(default=1, ge=1, le=5)  # Стресс 1-5
    physical_activity: bool = False                 # Физическая активность
    screen_before_bed: bool = False                 # Экран перед сном
    late_meal: bool = False                         # Поздний ужин (после 21:00)
    notes: Optional[str] = None                     # Свободный комментарий


# ─────────────────────────────────────────
#  АНОМАЛИЯ СНА
# ─────────────────────────────────────────

class SleepAnomaly(BaseModel):
    """Выявленная аномалия сна"""
    id: Optional[int] = None
    user_id: str = "default"
    sleep_record_id: Optional[int] = None

    date: date                          # Дата аномалии
    anomaly_type: str                   # Тип аномалии (код)
    title: str                          # Название для UI
    description: str                    # Описание аномалии
    severity: str                       # "low" | "medium" | "high"
    value: Optional[float] = None       # Фактическое значение
    threshold: Optional[float] = None   # Пороговое значение нормы
    is_ml_detected: bool = False        # Обнаружена ML или правилами


# ─────────────────────────────────────────
#  РЕКОМЕНДАЦИЯ
# ─────────────────────────────────────────

class Recommendation(BaseModel):
    """Персональная рекомендация пользователю"""
    id: Optional[int] = None
    user_id: str = "default"

    date: date                          # Дата генерации
    category: str                       # "schedule" | "lifestyle" | "environment"
    title: str                          # Короткий заголовок
    text: str                           # Полный текст рекомендации
    based_on: str                       # На чём основана рекомендация
    priority: int = Field(default=1, ge=1, le=3)  # 1=высокий, 2=средний, 3=низкий


# ─────────────────────────────────────────
#  API СХЕМЫ (запросы и ответы)
# ─────────────────────────────────────────

class SleepRecordCreate(BaseModel):
    """Схема для создания записи сна через API"""
    date: date
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    phases: SleepPhases = Field(default_factory=SleepPhases)
    heart_rate_avg: Optional[float] = None
    heart_rate_min: Optional[float] = None
    heart_rate_max: Optional[float] = None
    spo2_avg: Optional[float] = None
    spo2_min: Optional[float] = None
    awakenings_count: int = 0
    source: str = "unknown"


class UserContextCreate(BaseModel):
    """Схема для создания записи дневника через API"""
    date: date
    caffeine_after_15: bool = False
    alcohol: bool = False
    stress_level: int = Field(default=1, ge=1, le=5)
    physical_activity: bool = False
    screen_before_bed: bool = False
    late_meal: bool = False
    notes: Optional[str] = None


class SleepSummary(BaseModel):
    """Краткая сводка сна для дашборда"""
    total_records: int
    avg_duration_minutes: float
    avg_sleep_score: Optional[float]
    avg_deep_percent: float
    avg_rem_percent: float
    anomalies_last_30_days: int
    last_night: Optional[SleepRecord] = None
