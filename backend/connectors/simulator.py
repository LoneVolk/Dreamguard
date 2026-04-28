import random
from datetime import datetime, date, timedelta
from typing import List
from models import SleepRecord, SleepPhases

# BaseConnector не требуется для симулятора


class SimulatorConnector:
    """
    Генерирует реалистичные тестовые данные сна.
    Используется для демонстрации без реального устройства.
    Включает намеренно аномальные ночи для демонстрации алгоритма.
    """

    def __init__(self, days: int = 30, seed: int = 42):
        self.days = days
        random.seed(seed)

    def validate_connection(self) -> bool:
        return True  # Симулятор всегда доступен

    def fetch(self) -> List[SleepRecord]:
        records = []
        today = date.today()

        for i in range(self.days, 0, -1):
            night_date = today - timedelta(days=i)
            record = self._generate_night(night_date, i)
            records.append(record)

        return records

    def _generate_night(self, night_date: date, day_index: int) -> SleepRecord:
        """Генерирует одну ночь сна с реалистичными значениями"""

        # Базовое время отхода ко сну ~23:00 с вариацией
        bedtime_hour = 23
        bedtime_minute = random.randint(-60, 90)  # ±1 час вариация
        actual_bedtime_minute = bedtime_hour * 60 + bedtime_minute

        start_hour = actual_bedtime_minute // 60
        start_min = actual_bedtime_minute % 60

        start_time = datetime(
            night_date.year, night_date.month, night_date.day,
            max(21, min(2, start_hour)), start_min
        )

        # Базовая длительность ~7.5 часов с вариацией
        is_anomaly = self._should_be_anomaly(day_index)
        duration = self._get_duration(is_anomaly)

        end_time = start_time + timedelta(minutes=duration)

        # Фазы сна
        phases = self._get_phases(duration, is_anomaly)

        # Пульс
        hr_avg = self._get_heart_rate(is_anomaly)
        hr_min = hr_avg - random.uniform(5, 15)
        hr_max = hr_avg + random.uniform(10, 25)

        # SpO2
        spo2_avg = self._get_spo2(is_anomaly)
        spo2_min = spo2_avg - random.uniform(1, 4)

        # Пробуждения
        awakenings = self._get_awakenings(is_anomaly)

        return SleepRecord(
            user_id="default",
            date=night_date,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration,
            phases=phases,
            heart_rate_avg=round(hr_avg, 1),
            heart_rate_min=round(hr_min, 1),
            heart_rate_max=round(hr_max, 1),
            spo2_avg=round(spo2_avg, 1),
            spo2_min=round(spo2_min, 1),
            awakenings_count=awakenings,
            source="simulator"
        )

    def _should_be_anomaly(self, day_index: int) -> str | None:
        """Определяет тип аномалии для конкретного дня"""
        # Вставляем конкретные аномалии в определённые дни
        anomaly_days = {
            5:  "short_sleep",      # Мало спал
            10: "low_deep",         # Мало глубокого сна
            15: "high_hr",          # Высокий пульс
            20: "low_spo2",         # Низкий SpO2
            25: "many_awakenings",  # Много пробуждений
        }
        return anomaly_days.get(day_index, None)

    def _get_duration(self, anomaly_type: str | None) -> int:
        if anomaly_type == "short_sleep":
            return random.randint(200, 280)   # 3-4.5 часа
        return random.randint(380, 520)        # 6.5-8.5 часов (норма)

    def _get_phases(self, duration: int, anomaly_type: str | None) -> SleepPhases:
        if anomaly_type == "low_deep":
            # Почти нет глубокого сна
            deep = int(duration * random.uniform(0.03, 0.08))
            rem = int(duration * random.uniform(0.18, 0.22))
        else:
            # Нормальное распределение фаз
            deep = int(duration * random.uniform(0.15, 0.23))
            rem = int(duration * random.uniform(0.20, 0.25))

        awake = int(duration * random.uniform(0.03, 0.08))
        light = duration - deep - rem - awake

        return SleepPhases(
            light=max(0, light),
            deep=max(0, deep),
            rem=max(0, rem),
            awake=max(0, awake)
        )

    def _get_heart_rate(self, anomaly_type: str | None) -> float:
        if anomaly_type == "high_hr":
            return random.uniform(72, 85)   # Аномально высокий
        return random.uniform(52, 65)        # Норма ночью

    def _get_spo2(self, anomaly_type: str | None) -> float:
        if anomaly_type == "low_spo2":
            return random.uniform(87, 92)   # Низкий — признак апноэ
        return random.uniform(95, 99)        # Норма

    def _get_awakenings(self, anomaly_type: str | None) -> int:
        if anomaly_type == "many_awakenings":
            return random.randint(7, 12)    # Много пробуждений
        return random.randint(0, 3)          # Норма
