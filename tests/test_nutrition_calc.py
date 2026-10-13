import pytest

from app.nutrition_calc import (
    calculate_bmr,
    calculate_nutrition_plan,
    calculate_tdee,
)


def test_calculate_bmr_for_supported_genders():
    assert calculate_bmr("male", 80, 180, 30) == pytest.approx(1780)
    assert calculate_bmr("female", 80, 180, 30) == pytest.approx(1614)


def test_calculate_tdee_uses_activity_multiplier():
    assert calculate_tdee(2000, "moderate") == pytest.approx(3100)


def test_nutrition_plan_returns_weekly_weight_change():
    plan = calculate_nutrition_plan(
        gender="male",
        age=30,
        height_cm=180,
        current_weight_kg=62,
        target_weight_kg=65,
        activity_level="moderate",
        goal="gain_muscle",
        weeks=10,
    )

    assert plan["kg_per_week"] == pytest.approx(0.3)
    assert plan["daily_calories"] > plan["tdee"]


@pytest.mark.parametrize(
    ("goal", "weeks"),
    [
        ("unsupported", 8),
        ("maintain", 0),
        ("maintain", "not-a-number"),
    ],
)
def test_nutrition_plan_rejects_invalid_goal_or_duration(goal, weeks):
    with pytest.raises(ValueError):
        calculate_nutrition_plan(
            gender="female",
            age=25,
            height_cm=165,
            current_weight_kg=60,
            target_weight_kg=60,
            activity_level="light",
            goal=goal,
            weeks=weeks,
        )
