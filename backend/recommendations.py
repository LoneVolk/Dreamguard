from typing import List, Optional
from datetime import date
from models import SleepRecord, SleepAnomaly, Recommendation, UserContext


# ─────────────────────────────────────────
#  БАЗА РЕКОМЕНДАЦИЙ
# ─────────────────────────────────────────

RECOMMENDATIONS_DB = {

    "short_sleep": Recommendation(
        date=date.today(),
        category="schedule",
        title="Увеличьте продолжительность сна",
        text=(
            "Вы регулярно спите меньше рекомендованной нормы. "
            "Попробуйте ложиться на 30-60 минут раньше в течение недели — "
            "резкое изменение режима хуже, чем постепенное. "
            "Установите напоминание о подготовке ко сну за час до нужного времени."
        ),
        based_on="Недостаточная продолжительность сна",
        priority=1
    ),

    "low_deep_sleep": Recommendation(
        date=date.today(),
        category="lifestyle",
        title="Улучшите качество глубокого сна",
        text=(
            "Глубокий сон — фаза физического восстановления организма. "
            "Для его улучшения: избегайте алкоголя (он подавляет Deep сон), "
            "поддерживайте прохладу в спальне (18-20°C), "
            "и избегайте интенсивных тренировок за 3 часа до сна."
        ),
        based_on="Недостаток глубокого сна",
        priority=1
    ),

    "low_rem_sleep": Recommendation(
        date=date.today(),
        category="lifestyle",
        title="Улучшите REM сон",
        text=(
            "REM сон важен для памяти и эмоционального восстановления. "
            "Он преобладает в последних циклах ночи, поэтому главное — "
            "не сокращать сон утром. Также REM подавляют некоторые лекарства "
            "и алкоголь — проконсультируйтесь с врачом если принимаете препараты."
        ),
        based_on="Недостаток REM сна",
        priority=2
    ),

    "frequent_awakenings": Recommendation(
        date=date.today(),
        category="environment",
        title="Устраните причины ночных пробуждений",
        text=(
            "Частые пробуждения фрагментируют сон и снижают его восстановительный эффект. "
            "Проверьте: шум (беруши или белый шум), свет (плотные шторы), "
            "температуру (оптимально 18-20°C) и потребление жидкости вечером. "
            "Если проблема сохраняется — возможно апноэ сна, стоит обратиться к врачу."
        ),
        based_on="Частые пробуждения",
        priority=1
    ),

    "high_heart_rate": Recommendation(
        date=date.today(),
        category="lifestyle",
        title="Снизьте ночной пульс",
        text=(
            "Повышенный пульс ночью может указывать на стресс, перетренированность или начало болезни. "
            "Попробуйте вечернюю медитацию или дыхательные упражнения (4-7-8: вдох 4с, задержка 7с, выдох 8с). "
            "Если высокий пульс сохраняется несколько ночей — обратитесь к врачу."
        ),
        based_on="Повышенный ночной пульс",
        priority=1
    ),

    "low_spo2": Recommendation(
        date=date.today(),
        category="health",
        title="Обратитесь к врачу — возможное апноэ",
        text=(
            "Снижение уровня кислорода во сне (SpO2 < 90%) — серьёзный симптом, "
            "который может указывать на синдром обструктивного апноэ сна. "
            "Это состояние требует медицинской диагностики (полисомнография). "
            "Рекомендуем обратиться к врачу-сомнологу."
        ),
        based_on="Снижение SpO2",
        priority=1
    ),

    "social_jetlag": Recommendation(
        date=date.today(),
        category="schedule",
        title="Выровняйте режим будни/выходные",
        text=(
            "Большая разница времени сна в будни и выходные — 'социальный джетлаг' — "
            "нарушает циркадные ритмы так же, как перелёт через часовые пояса. "
            "Постарайтесь сократить разницу до 1 часа: в выходные вставайте "
            "не позже чем на час позже обычного."
        ),
        based_on="Социальный джетлаг",
        priority=2
    ),

    "irregular_schedule": Recommendation(
        date=date.today(),
        category="schedule",
        title="Стабилизируйте время отхода ко сну",
        text=(
            "Нестабильный режим сна мешает организму настроить биологические часы. "
            "Выберите комфортное время сна и придерживайтесь его ±30 минут каждый день, "
            "включая выходные. Даже одна 'неправильная' ночь сдвигает ритм на 1-2 дня."
        ),
        based_on="Нестабильный режим сна",
        priority=2
    ),

    "chronic_sleep_deprivation": Recommendation(
        date=date.today(),
        category="schedule",
        title="Восстановите долг сна",
        text=(
            "Несколько ночей подряд с недостаточным сном создают накопленный долг сна. "
            "Он не восполняется одной долгой ночью — нужно 2-3 дня полноценного сна. "
            "Если это рабочая нагрузка — рассмотрите короткий дневной сон (20 мин до 15:00)."
        ),
        based_on="Хронический недосып",
        priority=1
    ),
}


# ─────────────────────────────────────────
#  КОНТЕКСТНЫЕ РЕКОМЕНДАЦИИ
#  На основе дневника пользователя
# ─────────────────────────────────────────

def get_context_recommendations(
    context_records: List[dict],
    sleep_records: List[SleepRecord]
) -> List[Recommendation]:
    """
    Анализирует корреляции между дневником пользователя
    и качеством сна. Возвращает персональные рекомендации.
    """
    recommendations = []

    if len(context_records) < 5 or len(sleep_records) < 5:
        return recommendations

    # Собираем данные для корреляций
    caffeine_nights = []
    no_caffeine_nights = []
    alcohol_nights = []
    no_alcohol_nights = []
    high_stress_nights = []
    low_stress_nights = []
    active_nights = []
    inactive_nights = []

    # Создаём словарь записей сна по дате
    sleep_by_date = {str(r.date): r for r in sleep_records}

    for ctx in context_records:
        ctx_date = ctx["date"]
        sleep = sleep_by_date.get(ctx_date)
        if not sleep or sleep.sleep_score is None:
            continue

        score = sleep.sleep_score

        if ctx["caffeine_after_15"]:
            caffeine_nights.append(score)
        else:
            no_caffeine_nights.append(score)

        if ctx["alcohol"]:
            alcohol_nights.append(score)
        else:
            no_alcohol_nights.append(score)

        if ctx["stress_level"] >= 4:
            high_stress_nights.append(score)
        else:
            low_stress_nights.append(score)

        if ctx["physical_activity"]:
            active_nights.append(score)
        else:
            inactive_nights.append(score)

    # ── Кофеин ──────────────────────────────────────────────────
    if len(caffeine_nights) >= 3 and len(no_caffeine_nights) >= 3:
        avg_with = sum(caffeine_nights) / len(caffeine_nights)
        avg_without = sum(no_caffeine_nights) / len(no_caffeine_nights)
        diff = avg_without - avg_with

        if diff > 8:
            recommendations.append(Recommendation(
                date=date.today(),
                category="lifestyle",
                title="Кофеин ухудшает ваш сон",
                text=(
                    f"На основе ваших данных: в дни без кофеина после 15:00 "
                    f"ваш Sleep Score в среднем выше на {diff:.0f} пунктов. "
                    f"Попробуйте перенести последний кофе на первую половину дня."
                ),
                based_on="Корреляция кофеин → Sleep Score",
                priority=1
            ))

    # ── Алкоголь ────────────────────────────────────────────────
    if len(alcohol_nights) >= 3 and len(no_alcohol_nights) >= 3:
        avg_with = sum(alcohol_nights) / len(alcohol_nights)
        avg_without = sum(no_alcohol_nights) / len(no_alcohol_nights)
        diff = avg_without - avg_with

        if diff > 8:
            recommendations.append(Recommendation(
                date=date.today(),
                category="lifestyle",
                title="Алкоголь снижает качество вашего сна",
                text=(
                    f"Данные показывают: в ночи после алкоголя ваш Sleep Score "
                    f"ниже в среднем на {diff:.0f} пунктов. "
                    f"Алкоголь подавляет REM и глубокий сон, даже если кажется что засыпаете лучше."
                ),
                based_on="Корреляция алкоголь → Sleep Score",
                priority=1
            ))

    # ── Стресс ──────────────────────────────────────────────────
    if len(high_stress_nights) >= 3 and len(low_stress_nights) >= 3:
        avg_high = sum(high_stress_nights) / len(high_stress_nights)
        avg_low = sum(low_stress_nights) / len(low_stress_nights)
        diff = avg_low - avg_high

        if diff > 10:
            recommendations.append(Recommendation(
                date=date.today(),
                category="lifestyle",
                title="Стресс заметно влияет на ваш сон",
                text=(
                    f"В дни с высоким стрессом ваш Sleep Score ниже на {diff:.0f} пунктов. "
                    f"Попробуйте вечерние практики снижения стресса: прогулка, медитация, "
                    f"тёплая ванна или запись мыслей в дневник перед сном."
                ),
                based_on="Корреляция стресс → Sleep Score",
                priority=2
            ))

    # ── Физическая активность ───────────────────────────────────
    if len(active_nights) >= 3 and len(inactive_nights) >= 3:
        avg_active = sum(active_nights) / len(active_nights)
        avg_inactive = sum(inactive_nights) / len(inactive_nights)
        diff = avg_active - avg_inactive

        if diff > 5:
            recommendations.append(Recommendation(
                date=date.today(),
                category="lifestyle",
                title="Физическая активность улучшает ваш сон",
                text=(
                    f"После физически активных дней ваш Sleep Score выше на {diff:.0f} пунктов. "
                    f"Старайтесь двигаться хотя бы 30 минут в день — "
                    f"но не позднее чем за 3 часа до сна."
                ),
                based_on="Корреляция активность → Sleep Score",
                priority=3
            ))

    return recommendations


# ─────────────────────────────────────────
#  ГЛАВНАЯ ФУНКЦИЯ РЕКОМЕНДАЦИЙ
# ─────────────────────────────────────────

def generate_recommendations(
    anomalies: List[SleepAnomaly],
    context_records: List[dict] = None,
    sleep_records: List[SleepRecord] = None
) -> List[Recommendation]:
    """
    Генерирует персональные рекомендации на основе:
    1. Выявленных аномалий
    2. Корреляций с дневником пользователя
    """
    recommendations = []
    seen_types = set()

    today = date.today()

    # Рекомендации по аномалиям (без дублей)
    for anomaly in anomalies:
        atype = anomaly.anomaly_type
        if atype in seen_types:
            continue

        if atype in RECOMMENDATIONS_DB:
            rec = RECOMMENDATIONS_DB[atype].copy()
            rec.date = today
            rec.user_id = anomaly.user_id
            recommendations.append(rec)
            seen_types.add(atype)

    # Контекстные рекомендации
    if context_records and sleep_records:
        context_recs = get_context_recommendations(context_records, sleep_records)
        recommendations.extend(context_recs)

    # Сортируем по приоритету
    recommendations.sort(key=lambda r: r.priority)

    return recommendations
