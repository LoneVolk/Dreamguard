import numpy as np
from typing import List, Tuple, Optional
from datetime import date, timedelta
from models import SleepRecord, SleepAnomaly, SleepPhases

# scikit-learn для ML
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("⚠️ scikit-learn не установлен. ML-анализ недоступен.")


# ─────────────────────────────────────────
#  ПОРОГОВЫЕ ЗНАЧЕНИЯ НОРМЫ
# ─────────────────────────────────────────

THRESHOLDS = {
    "min_sleep_hours":      6.0,    # Минимальная норма сна (часов)
    "max_sleep_hours":      10.0,   # Максимальная норма сна (часов)
    "min_deep_percent":     15.0,   # Минимум глубокого сна (%)
    "min_rem_percent":      20.0,   # Минимум REM сна (%)
    "max_awakenings":       5,      # Максимум пробуждений за ночь
    "max_awake_percent":    10.0,   # Максимум времени бодрствования (%)
    "max_hr_night":         70.0,   # Максимальный средний пульс ночью
    "min_spo2":             90.0,   # Минимальный SpO2 (ниже = признак апноэ)
    "max_schedule_variance": 90.0,  # Максимальный разброс времени сна (мин)
}


# ─────────────────────────────────────────
#  SLEEP SCORE
# ─────────────────────────────────────────

def calculate_sleep_score(record: SleepRecord) -> int:
    """
    Вычисляет Sleep Score от 0 до 100.

    Составляющие:
    - Длительность сна      30 баллов
    - Качество фаз          35 баллов
    - Физиологические        20 баллов
    - Стабильность сна       15 баллов
    """
    score = 0
    duration_hours = record.duration_minutes / 60

    # ── 1. Длительность сна (0-30 баллов) ──────────────────────
    if 7.0 <= duration_hours <= 9.0:
        score += 30                         # Идеально
    elif 6.0 <= duration_hours < 7.0:
        score += 20                         # Немного мало
    elif 9.0 < duration_hours <= 10.0:
        score += 22                         # Немного много
    elif 5.0 <= duration_hours < 6.0:
        score += 10                         # Мало
    else:
        score += 0                          # Критически мало/много

    # ── 2. Качество фаз сна (0-35 баллов) ──────────────────────
    total = record.duration_minutes
    if total > 0:
        deep_pct  = (record.phases.deep  / total) * 100
        rem_pct   = (record.phases.rem   / total) * 100
        awake_pct = (record.phases.awake / total) * 100

        # Deep сон (0-15 баллов)
        if deep_pct >= 20:
            score += 15
        elif deep_pct >= 15:
            score += 12
        elif deep_pct >= 10:
            score += 7
        else:
            score += 0

        # REM сон (0-15 баллов)
        if rem_pct >= 25:
            score += 15
        elif rem_pct >= 20:
            score += 12
        elif rem_pct >= 15:
            score += 7
        else:
            score += 0

        # Время бодрствования (0-5 баллов)
        if awake_pct <= 5:
            score += 5
        elif awake_pct <= 10:
            score += 3
        else:
            score += 0

    # ── 3. Физиологические показатели (0-20 баллов) ─────────────
    if record.heart_rate_avg is not None:
        if record.heart_rate_avg <= 60:
            score += 10
        elif record.heart_rate_avg <= 70:
            score += 7
        elif record.heart_rate_avg <= 75:
            score += 3
        else:
            score += 0

    if record.spo2_avg is not None:
        if record.spo2_avg >= 96:
            score += 10
        elif record.spo2_avg >= 93:
            score += 7
        elif record.spo2_avg >= 90:
            score += 3
        else:
            score += 0
    else:
        score += 7  # Нет данных — нейтральный балл

    # ── 4. Стабильность (пробуждения) (0-15 баллов) ─────────────
    if record.awakenings_count == 0:
        score += 15
    elif record.awakenings_count <= 2:
        score += 12
    elif record.awakenings_count <= 4:
        score += 7
    elif record.awakenings_count <= 6:
        score += 3
    else:
        score += 0

    return min(100, max(0, score))


def score_to_label(score: int) -> str:
    """Текстовая метка для Sleep Score"""
    if score >= 85:
        return "Отличный"
    elif score >= 70:
        return "Хороший"
    elif score >= 55:
        return "Удовлетворительный"
    elif score >= 40:
        return "Плохой"
    else:
        return "Критический"


# ─────────────────────────────────────────
#  АНАЛИЗ АНОМАЛИЙ — ПРАВИЛА
# ─────────────────────────────────────────

def detect_rule_based_anomalies(record: SleepRecord) -> List[SleepAnomaly]:
    """
    Выявляет аномалии на основе медицинских пороговых значений.
    Работает даже при малом количестве данных.
    """
    anomalies = []
    total = record.duration_minutes

    # ── 1. Короткий сон ─────────────────────────────────────────
    duration_hours = total / 60
    if duration_hours < THRESHOLDS["min_sleep_hours"]:
        severity = "high" if duration_hours < 5 else "medium"
        anomalies.append(SleepAnomaly(
            user_id=record.user_id,
            sleep_record_id=record.id,
            date=record.date,
            anomaly_type="short_sleep",
            title="Недостаточная продолжительность сна",
            description=f"Вы спали {duration_hours:.1f} ч. Рекомендуемая норма — 7-9 часов.",
            severity=severity,
            value=round(duration_hours, 1),
            threshold=THRESHOLDS["min_sleep_hours"]
        ))

    # ── 2. Избыточный сон ───────────────────────────────────────
    if duration_hours > THRESHOLDS["max_sleep_hours"]:
        anomalies.append(SleepAnomaly(
            user_id=record.user_id,
            sleep_record_id=record.id,
            date=record.date,
            anomaly_type="long_sleep",
            title="Избыточная продолжительность сна",
            description=f"Вы спали {duration_hours:.1f} ч. Сон более 10 часов может указывать на гиперсомнию.",
            severity="low",
            value=round(duration_hours, 1),
            threshold=THRESHOLDS["max_sleep_hours"]
        ))

    # ── 3. Мало глубокого сна ───────────────────────────────────
    if total > 0:
        deep_pct = (record.phases.deep / total) * 100
        if deep_pct < THRESHOLDS["min_deep_percent"]:
            severity = "high" if deep_pct < 8 else "medium"
            anomalies.append(SleepAnomaly(
                user_id=record.user_id,
                sleep_record_id=record.id,
                date=record.date,
                anomaly_type="low_deep_sleep",
                title="Недостаток глубокого сна",
                description=f"Глубокий сон составил {deep_pct:.1f}% (норма ≥15%). Организм не восстанавливается полноценно.",
                severity=severity,
                value=round(deep_pct, 1),
                threshold=THRESHOLDS["min_deep_percent"]
            ))

    # ── 4. Мало REM сна ─────────────────────────────────────────
        rem_pct = (record.phases.rem / total) * 100
        if rem_pct < THRESHOLDS["min_rem_percent"]:
            anomalies.append(SleepAnomaly(
                user_id=record.user_id,
                sleep_record_id=record.id,
                date=record.date,
                anomaly_type="low_rem_sleep",
                title="Недостаток REM сна",
                description=f"REM сон составил {rem_pct:.1f}% (норма ≥20%). Возможны проблемы с памятью и эмоциональным восстановлением.",
                severity="medium",
                value=round(rem_pct, 1),
                threshold=THRESHOLDS["min_rem_percent"]
            ))

    # ── 5. Частые пробуждения ───────────────────────────────────
    if record.awakenings_count > THRESHOLDS["max_awakenings"]:
        severity = "high" if record.awakenings_count > 8 else "medium"
        anomalies.append(SleepAnomaly(
            user_id=record.user_id,
            sleep_record_id=record.id,
            date=record.date,
            anomaly_type="frequent_awakenings",
            title="Частые пробуждения",
            description=f"За ночь зафиксировано {record.awakenings_count} пробуждений (норма ≤5). Сон фрагментирован.",
            severity=severity,
            value=float(record.awakenings_count),
            threshold=float(THRESHOLDS["max_awakenings"])
        ))

    # ── 6. Высокий ночной пульс ─────────────────────────────────
    if record.heart_rate_avg and record.heart_rate_avg > THRESHOLDS["max_hr_night"]:
        severity = "high" if record.heart_rate_avg > 80 else "medium"
        anomalies.append(SleepAnomaly(
            user_id=record.user_id,
            sleep_record_id=record.id,
            date=record.date,
            anomaly_type="high_heart_rate",
            title="Повышенный ночной пульс",
            description=f"Средний пульс за ночь: {record.heart_rate_avg:.0f} уд/мин (норма ≤70). Возможен стресс или болезнь.",
            severity=severity,
            value=record.heart_rate_avg,
            threshold=THRESHOLDS["max_hr_night"]
        ))

    # ── 7. Низкий SpO2 (признак апноэ) ─────────────────────────
    if record.spo2_min and record.spo2_min < THRESHOLDS["min_spo2"]:
        severity = "high" if record.spo2_min < 85 else "medium"
        anomalies.append(SleepAnomaly(
            user_id=record.user_id,
            sleep_record_id=record.id,
            date=record.date,
            anomaly_type="low_spo2",
            title="Снижение уровня кислорода (возможное апноэ)",
            description=f"Минимальный SpO2 за ночь: {record.spo2_min:.1f}% (норма ≥90%). Рекомендуется консультация врача.",
            severity=severity,
            value=record.spo2_min,
            threshold=THRESHOLDS["min_spo2"],
            is_ml_detected=False
        ))

    return anomalies


# ─────────────────────────────────────────
#  АНАЛИЗ АНОМАЛИЙ — ПАТТЕРНЫ (несколько ночей)
# ─────────────────────────────────────────

def detect_pattern_anomalies(records: List[SleepRecord]) -> List[SleepAnomaly]:
    """
    Выявляет паттерновые аномалии по нескольким ночам.
    Требует минимум 7 записей.
    """
    anomalies = []
    if len(records) < 7:
        return anomalies

    # Сортируем по дате
    sorted_records = sorted(records, key=lambda r: r.date)
    latest = sorted_records[-1]

    # ── Социальный джетлаг ──────────────────────────────────────
    # Разница режима будни vs выходные > 2 часов
    weekday_starts = []
    weekend_starts = []

    for r in sorted_records[-14:]:  # Последние 2 недели
        hour = r.start_time.hour + r.start_time.minute / 60
        if r.date.weekday() < 5:
            weekday_starts.append(hour)
        else:
            weekend_starts.append(hour)

    if weekday_starts and weekend_starts:
        jetlag = abs(np.mean(weekend_starts) - np.mean(weekday_starts))
        if jetlag > 2.0:
            anomalies.append(SleepAnomaly(
                user_id=latest.user_id,
                date=latest.date,
                anomaly_type="social_jetlag",
                title="Социальный джетлаг",
                description=f"Разница времени сна в будни и выходные: {jetlag:.1f} ч. Это нарушает циркадные ритмы.",
                severity="medium" if jetlag < 3 else "high",
                value=round(jetlag, 1),
                threshold=2.0
            ))

    # ── Нестабильный режим ──────────────────────────────────────
    recent_starts = [
        r.start_time.hour * 60 + r.start_time.minute
        for r in sorted_records[-7:]
    ]
    schedule_variance = np.std(recent_starts)

    if schedule_variance > THRESHOLDS["max_schedule_variance"]:
        anomalies.append(SleepAnomaly(
            user_id=latest.user_id,
            date=latest.date,
            anomaly_type="irregular_schedule",
            title="Нестабильный режим сна",
            description=f"Разброс времени отхода ко сну за неделю: {schedule_variance:.0f} мин. Старайтесь ложиться в одно время.",
            severity="medium",
            value=round(schedule_variance, 0),
            threshold=THRESHOLDS["max_schedule_variance"]
        ))

    # ── Устойчивый недосып (3+ ночи подряд) ────────────────────
    consecutive_short = 0
    for r in reversed(sorted_records):
        if r.duration_minutes / 60 < THRESHOLDS["min_sleep_hours"]:
            consecutive_short += 1
        else:
            break

    if consecutive_short >= 3:
        anomalies.append(SleepAnomaly(
            user_id=latest.user_id,
            date=latest.date,
            anomaly_type="chronic_sleep_deprivation",
            title="Хронический недосып",
            description=f"{consecutive_short} ночей подряд с продолжительностью менее 6 часов. Накапливается долг сна.",
            severity="high",
            value=float(consecutive_short),
            threshold=3.0
        ))

    return anomalies


# ─────────────────────────────────────────
#  ML АНАЛИЗ — ISOLATION FOREST
# ─────────────────────────────────────────

def detect_ml_anomalies(records: List[SleepRecord]) -> List[SleepAnomaly]:
    """
    Isolation Forest — обнаруживает комплексные аномалии,
    которые не видны по отдельным правилам.
    Требует минимум 14 записей для надёжного результата.
    """
    if not ML_AVAILABLE:
        return []

    if len(records) < 14:
        return []

    # Формируем матрицу признаков
    features = []
    for r in records:
        total = r.duration_minutes if r.duration_minutes > 0 else 1
        features.append([
            r.duration_minutes,
            (r.phases.deep / total) * 100,
            (r.phases.rem / total) * 100,
            (r.phases.awake / total) * 100,
            r.heart_rate_avg or 60,
            r.spo2_avg or 97,
            r.awakenings_count,
        ])

    X = np.array(features)

    # Нормализация
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Isolation Forest
    # contamination — ожидаемая доля аномалий (10%)
    model = IsolationForest(
        n_estimators=100,
        contamination=0.1,
        random_state=42
    )
    predictions = model.fit_predict(X_scaled)
    scores = model.score_samples(X_scaled)

    anomalies = []
    for i, (record, pred, score) in enumerate(zip(records, predictions, scores)):
        if pred == -1:  # -1 = аномалия
            # Нормализуем score в понятный процент аномальности
            anomaly_degree = min(100, int(abs(score) * 50))

            anomalies.append(SleepAnomaly(
                user_id=record.user_id,
                sleep_record_id=record.id,
                date=record.date,
                anomaly_type="ml_complex_anomaly",
                title="Комплексная аномалия сна (ML)",
                description=(
                    f"Алгоритм машинного обучения выявил нетипичный паттерн сна. "
                    f"Степень аномальности: {anomaly_degree}%. "
                    f"Один или несколько показателей значительно отклоняются от вашей нормы."
                ),
                severity="high" if anomaly_degree > 70 else "medium",
                value=float(anomaly_degree),
                threshold=50.0,
                is_ml_detected=True
            ))

    return anomalies


# ─────────────────────────────────────────
#  ГЛАВНАЯ ФУНКЦИЯ АНАЛИЗА
# ─────────────────────────────────────────

def analyze_sleep(records: List[SleepRecord]) -> Tuple[List[SleepRecord], List[SleepAnomaly]]:
    """
    Полный анализ сна:
    1. Считает Sleep Score для каждой записи
    2. Выявляет аномалии по правилам
    3. Выявляет паттерновые аномалии
    4. Запускает ML анализ (Isolation Forest)

    Возвращает обновлённые записи и список всех аномалий.
    """
    all_anomalies = []

    # Шаг 1 — Sleep Score для каждой ночи
    for record in records:
        record.sleep_score = calculate_sleep_score(record)

    # Шаг 2 — Правила для каждой ночи
    for record in records:
        rule_anomalies = detect_rule_based_anomalies(record)
        all_anomalies.extend(rule_anomalies)

    # Шаг 3 — Паттерновые аномалии (по всем записям)
    pattern_anomalies = detect_pattern_anomalies(records)
    all_anomalies.extend(pattern_anomalies)

    # Шаг 4 — ML анализ
    ml_anomalies = detect_ml_anomalies(records)
    all_anomalies.extend(ml_anomalies)

    print(f"✅ Проанализировано {len(records)} записей. Найдено {len(all_anomalies)} аномалий.")
    return records, all_anomalies
