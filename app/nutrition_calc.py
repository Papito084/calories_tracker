"""
Metabolic calculations using Mifflin-St Jeor formula and macronutrient distributions.
"""
from typing import Dict, Any

ACTIVITY_MULTIPLIERS: Dict[str, float] = {
    "sedentary": 1.2,          # Poco o ningún ejercicio
    "light": 1.375,            # Ejercicio ligero (1-3 días/semana)
    "moderate": 1.55,          # Ejercicio moderado (3-5 días/semana)
    "very_active": 1.725       # Ejercicio intenso (6-7 días/semana)
}

def calculate_bmr(gender: str, weight_kg: float, height_cm: float, age: int) -> float:
    """
    Calculates Basal Metabolic Rate (BMR) using Mifflin-St Jeor Equation.
    Men: 10 * weight(kg) + 6.25 * height(cm) - 5 * age + 5
    Women: 10 * weight(kg) + 6.25 * height(cm) - 5 * age - 161
    """
    base = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age)
    if gender.lower() == "male":
        return base + 5.0
    if gender.lower() == "female":
        return base - 161.0
    raise ValueError("gender must be 'male' or 'female'")

def calculate_tdee(bmr: float, activity_level: str) -> float:
    """
    Calculates Total Daily Energy Expenditure (TDEE).
    """
    try:
        factor = ACTIVITY_MULTIPLIERS[activity_level.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported activity level: {activity_level}") from exc
    return bmr * factor

def calculate_nutrition_plan(
    gender: str,
    age: int,
    height_cm: float,
    current_weight_kg: float,
    target_weight_kg: float,
    activity_level: str,
    goal: str,
    weeks: int | str,
) -> Dict[str, Any]:
    """Calculate a full nutrition plan.
    ``weeks`` may be supplied as a string from the frontend, so we coerce it to an int
    and enforce a minimum of 1 to avoid division‑by‑zero or NaN results.
    """
    # ------------------------------------------------------------------
    # 1️⃣ Sanitize weeks input
    # ------------------------------------------------------------------
    try:
        weeks = int(weeks)
    except (TypeError, ValueError) as exc:
        raise ValueError("weeks must be a positive integer") from exc
    if weeks < 1:
        raise ValueError("weeks must be a positive integer")
    if goal not in {"lose_weight", "maintain", "gain_muscle"}:
        raise ValueError(f"Unsupported goal: {goal}")

    # ------------------------------------------------------------------
    # 2️⃣ Core metabolic calculations (unchanged)
    # ------------------------------------------------------------------
    bmr = calculate_bmr(gender, current_weight_kg, height_cm, age)
    tdee = calculate_tdee(bmr, activity_level)

    weight_diff = target_weight_kg - current_weight_kg
    total_days = weeks * 7.0

    # 1 kg ≈ 7700 kcal
    raw_daily_adj = (weight_diff * 7700.0) / total_days

    # ------------------------------------------------------------------
    # 3️⃣ Goal‑specific calorie adjustment
    # ------------------------------------------------------------------
    if goal == "lose_weight":
        daily_deficit = (
            abs(raw_daily_adj)
            if raw_daily_adj < 0
            else (500.0 if weight_diff == 0 else abs(raw_daily_adj))
        )
        daily_deficit = min(daily_deficit, 1000.0)
        daily_calories = max(1200.0, tdee - daily_deficit)
    elif goal == "gain_muscle":
        daily_surplus = raw_daily_adj if raw_daily_adj > 0 else 300.0
        daily_surplus = min(max(daily_surplus, 200.0), 750.0)
        daily_calories = tdee + daily_surplus
    else:
        daily_calories = tdee

    daily_calories = round(daily_calories)

    # ------------------------------------------------------------------
    # 4️⃣ Macronutrient split
    # ------------------------------------------------------------------
    protein_g = round(current_weight_kg * 2.0, 1)
    protein_cals = protein_g * 4.0

    fat_cals = daily_calories * 0.27
    fat_g = round(fat_cals / 9.0, 1)

    remaining_cals = max(0.0, daily_calories - (protein_cals + fat_cals))
    carbs_g = round(remaining_cals / 4.0, 1)

    # ------------------------------------------------------------------
    # 5️⃣ Weekly pace (kg per week) – weeks is guaranteed >= 1
    # ------------------------------------------------------------------
    pace_kg_week = round(weight_diff / weeks, 2)

    # ------------------------------------------------------------------
    # 6️⃣ Return the full plan
    # ------------------------------------------------------------------
    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "daily_calories": daily_calories,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
        "kg_per_week": pace_kg_week,
        "deficit_or_surplus": round(daily_calories - tdee),
    }
