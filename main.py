"""
Calories Tracker - Main Application Entrypoint
FastAPI application with custom mobile-first nutrition tracking UI, onboarding flow,
metabolic calculation, multimodal food camera scanner, weight charts, and meal edit/delete capabilities.
"""
import base64
import logging
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from auth import get_current_user, router as auth_router
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
import uvicorn

from config import settings
import database
import nutrition_calc
import vision_service

logger = logging.getLogger(__name__)

database.init_db()


class ProfilePayload(BaseModel):
    name: str = Field(default="Usuario", min_length=1, max_length=100)
    gender: Literal["male", "female"] = "male"
    age: int = Field(default=25, ge=13, le=120)
    height_cm: float = Field(default=175, ge=80, le=250)
    current_weight_kg: float = Field(default=75, ge=20, le=500)
    target_weight_kg: float = Field(default=70, ge=20, le=500)
    activity_level: Literal["sedentary", "light", "moderate", "very_active"] = "moderate"
    goal: Literal["lose_weight", "maintain", "gain_muscle"] = "lose_weight"
    target_weeks: int = Field(default=8, ge=1, le=260)


class MealPayload(BaseModel):
    dish_name: str = Field(default="Comida", min_length=1, max_length=200)
    total_calories: float = Field(default=0, ge=0, le=100000)
    protein_g: float = Field(default=0, ge=0, le=10000)
    carbs_g: float = Field(default=0, ge=0, le=10000)
    fat_g: float = Field(default=0, ge=0, le=10000)
    fiber_g: float = Field(default=0, ge=0, le=10000)
    confidence_score: float = Field(default=1, ge=0, le=1)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    image_base64: str | None = Field(default=None, max_length=500000)
    meal_type: str = Field(default="Comida", min_length=1, max_length=50)
    date_logged: date | None = None


class WeightPayload(BaseModel):
    weight_kg: float = Field(ge=20, le=500)
    date_logged: date | None = None
    notes: str = Field(default="", max_length=500)

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)
app.include_router(auth_router)
app.mount(
    "/assets",
    StaticFiles(directory=Path(__file__).resolve().parent / "static"),
    name="assets",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.JWT_SECRET,
    max_age=600,
    same_site="lax",
    https_only=settings.COOKIE_SECURE,
)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# -------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------

@app.get("/api/profile")
def get_profile(current_user: int = Depends(get_current_user)):
    profile = database.get_user_profile(current_user)
    return {"profile": profile}

@app.post("/api/profile")
async def save_profile(
    data: ProfilePayload,
    current_user: int = Depends(get_current_user),
):
    payload = data.model_dump()
    plan = nutrition_calc.calculate_nutrition_plan(
        gender=payload["gender"],
        age=payload["age"],
        height_cm=payload["height_cm"],
        current_weight_kg=payload["current_weight_kg"],
        target_weight_kg=payload["target_weight_kg"],
        activity_level=payload["activity_level"],
        goal=payload["goal"],
        weeks=payload["target_weeks"],
    )
    full_profile = {
        "user_id": current_user,
        **payload,
        **plan
    }
    database.save_user_profile(full_profile)
    return {"status": "ok", "profile": full_profile}


@app.post("/api/onboard-profile")
async def onboard_profile(
    data: ProfilePayload,
    current_user: int = Depends(get_current_user),
):
    return await save_profile(data, current_user)

@app.get("/api/dashboard")
def get_dashboard(date_str: date | None = None, current_user: int = Depends(get_current_user)):
    target_date = date_str.isoformat() if date_str else None
    profile = database.get_user_profile(current_user)
    if not profile:
        return {"has_profile": False}

    summary = database.get_daily_summary(current_user, target_date)
    meals = database.get_meals_for_date(current_user, target_date)
    weights = database.get_weight_history(current_user)

    return {
        "has_profile": True,
        "profile": profile,
        "summary": summary,
        "meals": meals,
        "weight_history": weights
    }

@app.post("/api/scan-food")
async def scan_food(
    request: Request,
    file: UploadFile = File(...),
    current_user: int = Depends(get_current_user),
):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 6 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Image size must be 5 MB or less")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP image")
    contents = await file.read(5 * 1024 * 1024 + 1)
    await file.close()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded image is empty")
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image size must be 5 MB or less")
    mime_type = file.content_type

    try:
        with Image.open(BytesIO(contents)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(status_code=415, detail="Unsupported image format")
            mime_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }[source.format]
            if source.width * source.height > 20_000_000:
                raise HTTPException(status_code=413, detail="Image dimensions are too large")
            source.load()
            preview = ImageOps.exif_transpose(source)
            preview.thumbnail((512, 512), Image.Resampling.LANCZOS)
            preview = preview.convert("RGB")
            preview_buffer = BytesIO()
            preview.save(preview_buffer, format="JPEG", quality=75, optimize=True)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or unreadable image") from exc

    try:
        analysis = vision_service.analyze_food_image(contents, mime_type=mime_type)
    except Exception as exc:
        logger.exception("Food image analysis failed")
        raise HTTPException(status_code=503, detail="Food analysis is temporarily unavailable") from exc
    if analysis.get("error"):
        logger.warning("Food analysis unavailable: %s", analysis["error"])
        raise HTTPException(status_code=503, detail="Food analysis is temporarily unavailable")

    encoded = base64.b64encode(preview_buffer.getvalue()).decode("ascii")
    preview_url = f"data:image/jpeg;base64,{encoded}"
    return {
        "analysis": analysis,
        "preview_url": preview_url
    }

@app.post("/api/log-meal")
async def log_meal_endpoint(
    data: MealPayload,
    current_user: int = Depends(get_current_user),
):
    meal_id = database.log_meal(
        user_id=current_user,
        dish_name=data.dish_name,
        total_calories=data.total_calories,
        protein_g=data.protein_g,
        carbs_g=data.carbs_g,
        fat_g=data.fat_g,
        fiber_g=data.fiber_g,
        confidence_score=data.confidence_score,
        items=data.items,
        image_base64=data.image_base64,
        meal_type=data.meal_type,
        target_date=data.date_logged.isoformat() if data.date_logged else None,
    )
    return {"status": "ok", "meal_id": meal_id}

@app.put("/api/meal/{meal_id}")
async def update_meal_endpoint(
    meal_id: int,
    data: MealPayload,
    current_user: int = Depends(get_current_user),
):
    success = database.update_meal(
        user_id=current_user,
        meal_id=meal_id,
        dish_name=data.dish_name,
        total_calories=data.total_calories,
        protein_g=data.protein_g,
        carbs_g=data.carbs_g,
        fat_g=data.fat_g,
        fiber_g=data.fiber_g,
        meal_type=data.meal_type,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Meal not found")
    return {"status": "ok", "updated": True}

@app.delete("/api/meal/{meal_id}")
def delete_meal_endpoint(meal_id: int, current_user: int = Depends(get_current_user)):
    success = database.delete_meal(meal_id, current_user)
    return {"status": "ok", "deleted": success}

@app.post("/api/weight")
async def log_weight_endpoint(
    data: WeightPayload,
    current_user: int = Depends(get_current_user),
):
    target_date = data.date_logged.isoformat() if data.date_logged else None
    log_id = database.log_weight(current_user, data.weight_kg, target_date, data.notes)
    return {"status": "ok", "log_id": log_id}

@app.get("/api/weight-history")
def get_weight_history_endpoint(current_user: int = Depends(get_current_user)):
    history = database.get_weight_history(current_user)
    return {"history": history}

@app.post("/api/reset-profile")
def reset_profile(current_user: int = Depends(get_current_user)):
    database.clear_user_data(current_user)
    return {"status": "ok"}

# -------------------------------------------------------------
# Frontend mobile-first single-page application.
# -------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index_page():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <meta name="theme-color" content="#0d0f12">
  <title>Calories Tracker — Nutrición y progreso</title>
  <!-- Google Fonts: Inter -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest"></script>
  <!-- Chart.js for Weight Progress -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {
      --bg: #090a0d;
      --card-bg: #15181e;
      --card-border: #232730;
      --text-main: #f3f4f6;
      --text-muted: #9ca3af;
      --accent: #22c55e;
      --accent-glow: rgba(34, 197, 94, 0.25);
      --protein: #3b82f6;
      --carbs: #f59e0b;
      --fats: #ec4899;
      --danger: #ef4444;
      --radius: 20px;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    body {
      background-color: #030406;
      color: var(--text-main);
      display: flex;
      justify-content: center;
      min-height: 100vh;
      min-height: 100dvh;
      overflow-x: hidden;
    }
    body.flow-open {
      height: 100vh;
      height: 100dvh;
      overflow: hidden;
    }

    /* Mobile First Shell (max-width: 480px) */
    #app-container {
      width: 100%;
      max-width: 480px;
      min-height: 100vh;
      min-height: 100dvh;
      background-color: var(--bg);
      position: relative;
      padding-bottom: 100px;
      display: flex;
      flex-direction: column;
      box-shadow: 0 0 50px rgba(0, 0, 0, 0.8);
    }

    /* Header */
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px 20px;
      position: sticky;
      top: 0;
      background: rgba(9, 10, 13, 0.88);
      backdrop-filter: blur(12px);
      z-index: 40;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 1.25rem;
      font-weight: 800;
      letter-spacing: -0.5px;
    }

    .brand-badge {
      background: linear-gradient(135deg, #22c55e, #10b981);
      color: #000;
      font-size: 0.65rem;
      font-weight: 900;
      padding: 4px 7px;
      border-radius: 6px;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }

    .icon-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      width: 38px;
      height: 38px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
    }
    .icon-btn:active {
      transform: scale(0.92);
      background: #252a34;
    }

    /* Card styling */
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 20px;
      margin: 12px 16px;
    }

    /* Calorie Hero Ring Section */
    .hero-card {
      text-align: center;
      position: relative;
      overflow: hidden;
      padding: 24px 20px;
    }
    .hero-card::before {
      content: '';
      position: absolute;
      top: -30%;
      left: 50%;
      transform: translateX(-50%);
      width: 200px;
      height: 200px;
      background: radial-gradient(circle, var(--accent-glow) 0%, transparent 70%);
      pointer-events: none;
    }

    .ring-wrapper {
      position: relative;
      width: 190px;
      height: 190px;
      margin: 0 auto 16px auto;
    }
    .ring-wrapper svg {
      width: 100%;
      height: 100%;
      transform: rotate(-90deg);
    }
    .ring-bg {
      fill: none;
      stroke: #20242e;
      stroke-width: 14;
    }
    .ring-progress {
      fill: none;
      stroke: var(--accent);
      stroke-width: 14;
      stroke-linecap: round;
      transition: stroke-dashoffset 0.8s ease-in-out;
    }

    .ring-content {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .ring-cals {
      font-size: 2.3rem;
      font-weight: 800;
      line-height: 1.1;
      letter-spacing: -1px;
    }
    .ring-label {
      font-size: 0.8rem;
      color: var(--text-muted);
      font-weight: 500;
      margin-top: 4px;
    }

    .goal-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(34, 197, 94, 0.12);
      border: 1px solid rgba(34, 197, 94, 0.25);
      color: #4ade80;
      padding: 6px 14px;
      border-radius: 30px;
      font-size: 0.8rem;
      font-weight: 600;
    }

    /* Macros row */
    .macros-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin: 4px 16px 14px 16px;
    }
    .macro-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 14px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .macro-title {
      font-size: 0.75rem;
      color: var(--text-muted);
      font-weight: 600;
      display: flex;
      justify-content: space-between;
    }
    .macro-val {
      font-size: 1.05rem;
      font-weight: 700;
    }
    .macro-bar-bg {
      height: 6px;
      background: #252932;
      border-radius: 4px;
      overflow: hidden;
      margin-top: 2px;
    }
    .macro-bar-fill {
      height: 100%;
      border-radius: 4px;
      transition: width 0.6s ease;
    }
    .fill-protein { background: var(--protein); }
    .fill-carbs { background: var(--carbs); }
    .fill-fats { background: var(--fats); }

    /* Target Goal Banner */
    .target-banner {
      background: linear-gradient(135deg, #1b212d, #141720);
      border: 1px solid #2d3444;
      border-radius: 16px;
      padding: 14px 16px;
      margin: 0 16px 16px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .target-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .target-title {
      font-size: 0.85rem;
      font-weight: 700;
      color: #e5e7eb;
    }
    .target-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .target-rate {
      font-size: 0.8rem;
      font-weight: 700;
      color: var(--accent);
      background: rgba(34, 197, 94, 0.12);
      padding: 4px 10px;
      border-radius: 20px;
    }

    /* Weight Chart Card */
    .weight-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 18px 16px;
      margin: 0 16px 16px 16px;
    }
    .weight-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .weight-btn {
      background: #1e2430;
      border: 1px solid #2f3747;
      color: #38bdf8;
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 0.78rem;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .chart-container {
      position: relative;
      height: 170px;
      width: 100%;
    }

    /* Section Title */
    .section-header {
      padding: 8px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .section-title {
      font-size: 1.05rem;
      font-weight: 700;
      letter-spacing: -0.3px;
    }
    .section-sub {
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    /* Meal Items List */
    .meals-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 0 16px;
      margin-bottom: 20px;
    }
    .meal-item {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 14px;
      display: flex;
      align-items: center;
      gap: 14px;
      position: relative;
    }
    .meal-thumb {
      width: 50px;
      height: 50px;
      border-radius: 12px;
      object-fit: cover;
      background: #252932;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .meal-info {
      flex: 1;
      min-width: 0;
    }
    .meal-name {
      font-size: 0.95rem;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      margin-bottom: 3px;
    }
    .meal-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      display: flex;
      gap: 10px;
    }
    .meal-cals {
      font-size: 1.1rem;
      font-weight: 800;
      color: #f3f4f6;
      text-align: right;
    }
    .meal-actions {
      display: flex;
      align-items: center;
      gap: 4px;
      margin-top: 4px;
      justify-content: flex-end;
    }
    .meal-action-btn {
      background: transparent;
      border: none;
      color: #9ca3af;
      cursor: pointer;
      padding: 4px;
      display: flex;
      align-items: center;
      border-radius: 6px;
    }
    .meal-action-btn:hover {
      background: #232834;
      color: #fff;
    }
    .meal-action-btn.del:hover {
      color: var(--danger);
    }

    .empty-state {
      text-align: center;
      padding: 40px 20px;
      color: var(--text-muted);
    }
    .empty-icon {
      margin-bottom: 12px;
      opacity: 0.4;
    }

    /* Bottom Action Bar (Camera & Gallery Dual Triggers) */
    .bottom-nav {
      position: fixed;
      bottom: 0;
      width: 100%;
      max-width: 480px;
      background: rgba(13, 15, 18, 0.95);
      backdrop-filter: blur(20px);
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 12px;
      padding: 12px 16px 24px 16px;
      z-index: 50;
    }

    .gallery-btn {
      background: #1c222c;
      border: 1px solid #2d3646;
      color: #e5e7eb;
      border-radius: 35px;
      padding: 12px 18px;
      font-size: 0.95rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      transition: transform 0.15s ease;
    }
    .gallery-btn:active {
      transform: scale(0.96);
    }

    .scan-btn {
      background: linear-gradient(135deg, #22c55e, #16a34a);
      color: #000;
      border: none;
      border-radius: 35px;
      padding: 12px 24px;
      font-size: 1rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 4px 20px var(--accent-glow);
      cursor: pointer;
      transition: transform 0.15s ease;
    }
    .scan-btn:active {
      transform: scale(0.96);
    }

    /* Hidden Native File Inputs */
    #camera-file-input, #gallery-file-input {
      display: none;
    }

    /* Modal / Bottom Sheet */
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(8px);
      z-index: 100;
      display: none;
      justify-content: center;
      align-items: flex-end;
    }
    .modal-overlay.open {
      display: flex;
    }
    .sheet-card {
      background: #14171d;
      width: 100%;
      max-width: 480px;
      border-radius: 28px 28px 0 0;
      border-top: 1px solid #2a303c;
      padding: 24px 20px 40px 20px;
      max-height: 90vh;
      overflow-y: auto;
      animation: slideUp 0.25s ease-out;
    }
    .modal-overlay.fullscreen-flow {
      align-items: stretch;
      background: var(--bg);
      backdrop-filter: none;
      overflow-y: auto;
    }
    .fullscreen-flow .sheet-card {
      width: 100%;
      max-width: 480px;
      height: 100vh;
      height: 100dvh;
      max-height: none;
      margin: 0 auto;
      padding: max(28px, env(safe-area-inset-top)) 24px max(28px, env(safe-area-inset-bottom));
      border: 0;
      border-radius: 0;
      display: flex;
      flex-direction: column;
      justify-content: center;
      overflow-y: auto;
      animation: none;
    }
    #modal-onboarding.fullscreen-flow .sheet-card {
      justify-content: flex-start;
    }
    .auth-screen {
      width: 100%;
    }
    .auth-brand {
      margin-bottom: 12px;
      color: var(--accent);
      font-size: 0.8rem;
      font-weight: 900;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    .auth-illustration {
      display: block;
      width: min(88vw, 300px);
      height: min(27dvh, 210px);
      object-fit: contain;
      margin: 0 auto 12px;
    }
    .auth-title {
      margin-bottom: 10px;
      font-size: clamp(1.8rem, 8vw, 2.35rem);
      line-height: 1.1;
      font-weight: 800;
      letter-spacing: -0.05em;
    }
    .auth-description {
      margin-bottom: 30px;
      color: var(--text-muted);
      font-size: 0.95rem;
      line-height: 1.5;
    }
    .auth-screen .btn-primary,
    .auth-screen .btn-secondary {
      width: 100%;
      margin: 0 0 12px;
    }
    .auth-screen .auth-action-button {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
    }
    .auth-button-icon {
      width: 19px;
      height: 19px;
      flex: 0 0 19px;
    }
    .google-logo {
      width: 20px;
      height: 20px;
      flex: 0 0 20px;
    }
    .auth-back {
      align-self: flex-start;
      margin: 0 0 24px;
      padding: 8px 0;
      color: var(--text-muted);
      background: none;
      border: 0;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    @keyframes slideUp {
      from { transform: translateY(100%); }
      to { transform: translateY(0); }
    }

    /* Onboarding Flow Styles */
    .step-indicator {
      display: flex;
      gap: 6px;
      margin-bottom: 24px;
    }
    .step-bar {
      flex: 1;
      height: 4px;
      background: #252a34;
      border-radius: 4px;
    }
    .step-bar.active {
      background: var(--accent);
    }

    .form-group {
      margin-bottom: 18px;
    }
    .form-label {
      display: block;
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-bottom: 8px;
      font-weight: 600;
    }
    .input-field {
      width: 100%;
      background: #1a1e27;
      border: 1px solid #2a303c;
      border-radius: 14px;
      padding: 14px 16px;
      color: #fff;
      font-size: 1rem;
      font-weight: 600;
      outline: none;
      transition: border-color 0.2s;
    }
    .input-field:focus {
      border-color: var(--accent);
    }

    .option-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }
    .choice-card {
      background: #1a1e27;
      border: 2px solid #2a303c;
      border-radius: 16px;
      padding: 14px 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: all 0.2s;
    }
    .choice-card.selected {
      border-color: var(--accent);
      background: rgba(34, 197, 94, 0.08);
    }
    .choice-text {
      font-weight: 700;
      font-size: 0.95rem;
    }
    .choice-desc {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 2px;
    }

    .btn-primary {
      width: 100%;
      background: var(--accent);
      color: #000;
      border: none;
      border-radius: 16px;
      padding: 16px;
      font-size: 1rem;
      font-weight: 800;
      cursor: pointer;
      margin-top: 14px;
      transition: transform 0.15s;
    }
    .btn-primary:active {
      transform: scale(0.98);
    }

    .btn-secondary {
      width: 100%;
      background: #252a34;
      color: #e5e7eb;
      border: none;
      border-radius: 16px;
      padding: 14px;
      font-size: 0.95rem;
      font-weight: 700;
      cursor: pointer;
      margin-top: 10px;
    }

    /* Scanner Loading State */
    .scanner-loader {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 20px;
      gap: 16px;
    }
    .spinner {
      width: 50px;
      height: 50px;
      border: 4px solid #252a34;
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    /* Ingredient breakdown table */
    .ingr-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid #202632;
    }
    .ingr-name {
      font-size: 0.9rem;
      font-weight: 600;
    }
    .ingr-qty {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .ingr-cal {
      font-size: 0.9rem;
      font-weight: 700;
      color: #f3f4f6;
    }

    /* Notification pill */
    .toast {
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: #1f2937;
      border: 1px solid #374151;
      color: #fff;
      padding: 10px 18px;
      border-radius: 30px;
      font-size: 0.85rem;
      font-weight: 600;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
      z-index: 200;
      display: none;
      animation: fadeIn 0.3s;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translate(-50%, -10px); }
      to { opacity: 1; transform: translate(-50%, 0); }
    }
  </style>
</head>
<body class="flow-open">

<div id="app-container">

  <!-- Top Navigation Header -->
  <header class="top-bar">
    <div class="brand">
      <span>Calories</span>
      <span class="brand-badge">Tracker</span>
    </div>
    <div style="display: flex; gap: 8px;">
      <button class="icon-btn" onclick="openProfileModal()" title="Editar Perfil / Metas">
        <i data-lucide="sliders-horizontal" style="width: 18px; height: 18px;"></i>
      </button>
      <button class="icon-btn" onclick="openSettingsModal()" title="Configuración">
        <i data-lucide="settings" style="width: 18px; height: 18px;"></i>
      </button>
    </div>
  </header>

  <!-- Notification Toast -->
  <div id="toast" class="toast"></div>

  <!-- MAIN DASHBOARD VIEW -->
  <main id="view-dashboard">
    <!-- Hero Ring Card -->
    <div class="card hero-card">
      <div class="ring-wrapper">
        <svg viewBox="0 0 160 160">
          <circle class="ring-bg" cx="80" cy="80" r="68"></circle>
          <circle id="cal-ring" class="ring-progress" cx="80" cy="80" r="68"
                  stroke-dasharray="427.26" stroke-dashoffset="427.26"></circle>
        </svg>
        <div class="ring-content">
          <div id="cals-remaining" class="ring-cals">0</div>
          <div class="ring-label">kcal restantes</div>
        </div>
      </div>

      <div style="display: flex; justify-content: center; gap: 8px; margin-bottom: 12px;">
        <span class="goal-pill">
          <i data-lucide="flame" style="width: 14px; height: 14px;"></i>
          Consumidas: <b id="cals-consumed">0</b> / <span id="cals-target">2000</span> kcal
        </span>
      </div>
    </div>

    <!-- Target Goal & Pace Banner -->
    <div class="target-banner">
      <div class="target-info">
        <span id="goal-summary-title" class="target-title">Objetivo: Progreso</span>
        <span id="goal-summary-sub" class="target-sub">Déficit metabólico</span>
      </div>
      <div id="goal-summary-rate" class="target-rate">-0.5 kg/sem</div>
    </div>

    <!-- Macronutrients Breakdown -->
    <div class="macros-grid">
      <!-- Protein -->
      <div class="macro-card">
        <div class="macro-title">
          <span>Proteína</span>
          <span id="protein-target" style="color: var(--protein);">0g</span>
        </div>
        <div class="macro-val"><span id="protein-consumed">0</span>g</div>
        <div class="macro-bar-bg">
          <div id="protein-bar" class="macro-bar-fill fill-protein" style="width: 0%;"></div>
        </div>
      </div>

      <!-- Carbs -->
      <div class="macro-card">
        <div class="macro-title">
          <span>Carbos</span>
          <span id="carbs-target" style="color: var(--carbs);">0g</span>
        </div>
        <div class="macro-val"><span id="carbs-consumed">0</span>g</div>
        <div class="macro-bar-bg">
          <div id="carbs-bar" class="macro-bar-fill fill-carbs" style="width: 0%;"></div>
        </div>
      </div>

      <!-- Fats -->
      <div class="macro-card">
        <div class="macro-title">
          <span>Grasas</span>
          <span id="fats-target" style="color: var(--fats);">0g</span>
        </div>
        <div class="macro-val"><span id="fats-consumed">0</span>g</div>
        <div class="macro-bar-bg">
          <div id="fats-bar" class="macro-bar-fill fill-fats" style="width: 0%;"></div>
        </div>
      </div>
    </div>

    <!-- WEIGHT PROGRESS CHART CARD -->
    <div class="weight-card">
      <div class="weight-card-header">
        <div>
          <div style="font-size: 0.95rem; font-weight: 800;">Evolución de Peso</div>
          <div id="weight-trend-sub" style="font-size: 0.75rem; color: var(--text-muted);">Seguimiento temporal</div>
        </div>
        <button class="weight-btn" onclick="openWeightModal()">
          <i data-lucide="scale" style="width: 14px; height: 14px;"></i>
          <span>Registrar Peso</span>
        </button>
      </div>
      <div class="chart-container">
        <canvas id="weightChart"></canvas>
      </div>
    </div>

    <!-- Meals Logged Today -->
    <div class="section-header">
      <h3 class="section-title">Comidas de Hoy</h3>
      <span id="meal-count" class="section-sub">0 registradas</span>
    </div>

    <div id="meals-container" class="meals-list">
      <!-- Injected dynamically -->
    </div>
  </main>

  <!-- Bottom Floating Navigation (Gallery & Camera Triggers) -->
  <nav class="bottom-nav">
    <!-- Native Camera Input (with capture) -->
    <input type="file" id="camera-file-input" accept="image/*" capture="environment" onchange="handleImageSelected(event)">
    <!-- Native Gallery Input (NO capture attribute for photo gallery picker) -->
    <input type="file" id="gallery-file-input" accept="image/*" onchange="handleImageSelected(event)">

    <button class="gallery-btn" onclick="triggerGallery()" title="Subir desde galería">
      <i data-lucide="image" style="width: 18px; height: 18px; color: #38bdf8;"></i>
      <span>Galería</span>
    </button>
    <button class="scan-btn" onclick="triggerCamera()" title="Tomar foto ahora">
      <i data-lucide="camera" style="width: 18px; height: 18px;"></i>
      <span>Cámara IA</span>
    </button>
  </nav>

</div>

<!-- ------------------------------------------------------------------ -->
<!-- MODAL: AI FOOD SCAN RESULT & CONFIRMATION -->
<!-- ------------------------------------------------------------------ -->
<div id="modal-scan" class="modal-overlay">
  <div class="sheet-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3 style="font-size: 1.2rem; font-weight: 800;">Análisis Nutricional IA</h3>
      <button class="icon-btn" onclick="closeModal('modal-scan')">
        <i data-lucide="x" style="width: 18px; height: 18px;"></i>
      </button>
    </div>

    <!-- Scanner Loading Spinner -->
    <div id="scan-loading" class="scanner-loader" style="display: none;">
      <div class="spinner"></div>
      <p style="font-weight: 700; font-size: 1rem;">La IA está analizando tu plato...</p>
      <p style="font-size: 0.8rem; color: var(--text-muted); text-align: center;">Identificando ingredientes y macronutrientes con Visión Multimodal</p>
    </div>

    <!-- Scanner Result Details -->
    <div id="scan-result" style="display: none;">
      <div style="position: relative; border-radius: 18px; overflow: hidden; margin-bottom: 16px; max-height: 190px;">
        <img id="scan-preview-img" src="" style="width: 100%; height: 190px; object-fit: cover;" alt="Plato">
        <div style="position: absolute; bottom: 10px; right: 10px; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700;">
          Confianza: <span id="scan-confidence" style="color: var(--accent);">95%</span>
        </div>
      </div>

      <h2 id="scan-dish-name" style="font-size: 1.35rem; font-weight: 800; margin-bottom: 4px;">Plato analizado</h2>
      <p style="font-size: 1.8rem; font-weight: 900; color: var(--accent); margin-bottom: 16px;">
        <span id="scan-calories">0</span> <span style="font-size: 1rem; color: var(--text-muted); font-weight: 600;">kcal</span>
      </p>

      <!-- Scan Macros Mini Row -->
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 20px;">
        <div style="background: #1c212b; padding: 10px; border-radius: 12px; text-align: center;">
          <div style="font-size: 0.7rem; color: var(--protein); font-weight: 700;">Proteínas</div>
          <div id="scan-protein" style="font-size: 1.1rem; font-weight: 800;">0g</div>
        </div>
        <div style="background: #1c212b; padding: 10px; border-radius: 12px; text-align: center;">
          <div style="font-size: 0.7rem; color: var(--carbs); font-weight: 700;">Carbohidratos</div>
          <div id="scan-carbs" style="font-size: 1.1rem; font-weight: 800;">0g</div>
        </div>
        <div style="background: #1c212b; padding: 10px; border-radius: 12px; text-align: center;">
          <div style="font-size: 0.7rem; color: var(--fats); font-weight: 700;">Grasas</div>
          <div id="scan-fats" style="font-size: 1.1rem; font-weight: 800;">0g</div>
        </div>
      </div>

      <!-- Ingredient breakdown -->
      <h4 style="font-size: 0.9rem; font-weight: 700; color: var(--text-muted); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px;">Desglose de Ingredientes</h4>
      <div id="scan-ingredients-list" style="margin-bottom: 24px;"></div>

      <button class="btn-primary" onclick="confirmLogMeal()">
        <i data-lucide="plus-circle" style="width: 18px; height: 18px; display: inline-block; vertical-align: middle; margin-right: 6px;"></i>
        Añadir al Diario de Hoy
      </button>
      <button class="btn-secondary" onclick="closeModal('modal-scan')">Descartar</button>
    </div>
  </div>
</div>

<!-- ------------------------------------------------------------------ -->
<!-- MODAL: EDIT MEAL -->
<!-- ------------------------------------------------------------------ -->
<div id="modal-edit-meal" class="modal-overlay">
  <div class="sheet-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h3 style="font-size: 1.2rem; font-weight: 800;">Editar Comida</h3>
      <button class="icon-btn" onclick="closeModal('modal-edit-meal')">
        <i data-lucide="x" style="width: 18px; height: 18px;"></i>
      </button>
    </div>

    <input type="hidden" id="edit-meal-id">

    <div class="form-group">
      <label class="form-label">Nombre del Plato</label>
      <input type="text" id="edit-dish-name" class="input-field">
    </div>

    <div class="form-group">
      <label class="form-label">Calorías Totales (kcal)</label>
      <input type="number" id="edit-calories" class="input-field" step="1">
    </div>

    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 18px;">
      <div>
        <label class="form-label">Proteínas (g)</label>
        <input type="number" id="edit-protein" class="input-field" step="0.5">
      </div>
      <div>
        <label class="form-label">Carbos (g)</label>
        <input type="number" id="edit-carbs" class="input-field" step="0.5">
      </div>
      <div>
        <label class="form-label">Grasas (g)</label>
        <input type="number" id="edit-fats" class="input-field" step="0.5">
      </div>
    </div>

    <button class="btn-primary" onclick="saveEditedMeal()">Guardar Cambios</button>
    <button class="btn-secondary" onclick="closeModal('modal-edit-meal')">Cancelar</button>
  </div>
</div>

<!-- ------------------------------------------------------------------ -->
<!-- MODAL: LOG WEIGHT -->
<!-- ------------------------------------------------------------------ -->
<div id="modal-weight" class="modal-overlay">
  <div class="sheet-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h3 style="font-size: 1.2rem; font-weight: 800;">Registrar Peso Actual</h3>
      <button class="icon-btn" onclick="closeModal('modal-weight')">
        <i data-lucide="x" style="width: 18px; height: 18px;"></i>
      </button>
    </div>

    <div class="form-group">
      <label class="form-label">Peso Corporal (kg)</label>
      <input type="number" id="input-log-weight" class="input-field" step="0.1" placeholder="Ej: 77.5">
    </div>

    <div class="form-group">
      <label class="form-label">Fecha del Pesaje</label>
      <input type="date" id="input-weight-date" class="input-field">
    </div>

    <div class="form-group">
      <label class="form-label">Notas (Opcional)</label>
      <input type="text" id="input-weight-notes" class="input-field" placeholder="En ayunas, después de entrenar...">
    </div>

    <button class="btn-primary" onclick="submitWeightLog()">Guardar y Actualizar Gráfica</button>
    <button class="btn-secondary" onclick="closeModal('modal-weight')">Cancelar</button>
  </div>
</div>

<!-- ------------------------------------------------------------------ -->
<!-- MODAL: ONBOARDING & PROFILE QUESTIONNAIRE -->
<!-- ------------------------------------------------------------------ -->
<div id="modal-onboarding" class="modal-overlay">
  <div class="sheet-card">
    <!-- Step Indicator -->
    <div class="step-indicator">
      <div id="step-bar-1" class="step-bar active"></div>
      <div id="step-bar-2" class="step-bar"></div>
      <div id="step-bar-3" class="step-bar"></div>
    </div>

    <!-- Step 1: Personal physical attributes -->
    <div id="step-1" class="wizard-step">
      <h2 style="font-size: 1.4rem; font-weight: 800; margin-bottom: 6px;">Tus Datos Físicos</h2>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 20px;">Para calcular con exactitud tu tasa metabólica basal (BMR).</p>

      <div class="form-group">
        <label class="form-label">Sexo Biológico</label>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
          <div id="gender-male" class="choice-card selected" onclick="selectGender('male')">
            <span class="choice-text">Hombre</span>
          </div>
          <div id="gender-female" class="choice-card" onclick="selectGender('female')">
            <span class="choice-text">Mujer</span>
          </div>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">Edad (años)</label>
        <input type="number" id="input-age" class="input-field" value="26" min="14" max="100">
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
        <div class="form-group">
          <label class="form-label">Altura (cm)</label>
          <input type="number" id="input-height" class="input-field" value="175" min="100" max="250">
        </div>
        <div class="form-group">
          <label class="form-label">Peso Actual (kg)</label>
          <input type="number" id="input-current-weight" class="input-field" value="78" step="0.5" min="30" max="300">
        </div>
      </div>

      <button class="btn-primary" onclick="goToStep(2)">Continuar</button>
    </div>

    <!-- Step 2: Activity level -->
    <div id="step-2" class="wizard-step" style="display: none;">
      <h2 style="font-size: 1.4rem; font-weight: 800; margin-bottom: 6px;">Nivel de Actividad</h2>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 20px;">Calcula tu Gasto Energético Total Diario (TDEE).</p>

      <div class="option-grid">
        <div id="act-sedentary" class="choice-card" onclick="selectActivity('sedentary')">
          <div>
            <div class="choice-text">Sedentario</div>
            <div class="choice-desc">Poco o ningún ejercicio regular.</div>
          </div>
        </div>
        <div id="act-light" class="choice-card" onclick="selectActivity('light')">
          <div>
            <div class="choice-text">Ligeramente Activo</div>
            <div class="choice-desc">Ejercicio ligero 1 a 3 días por semana.</div>
          </div>
        </div>
        <div id="act-moderate" class="choice-card selected" onclick="selectActivity('moderate')">
          <div>
            <div class="choice-text">Moderadamente Activo</div>
            <div class="choice-desc">Entrenamiento de 3 a 5 días por semana.</div>
          </div>
        </div>
        <div id="act-very_active" class="choice-card" onclick="selectActivity('very_active')">
          <div>
            <div class="choice-text">Muy Activo</div>
            <div class="choice-desc">Entrenamiento intenso o trabajo físico diario.</div>
          </div>
        </div>
      </div>

      <button class="btn-primary" onclick="goToStep(3)">Continuar</button>
      <button class="btn-secondary" onclick="goToStep(1)">Atrás</button>
    </div>

    <!-- Step 3: Objective and timeline -->
    <div id="step-3" class="wizard-step" style="display: none;">
      <h2 style="font-size: 1.4rem; font-weight: 800; margin-bottom: 6px;">Tu Meta y Plazo</h2>
      <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 20px;">Establece tus metas y el algoritmo ajustará tus macros.</p>

      <div class="form-group">
        <label class="form-label">Objetivo Principal</label>
        <div class="option-grid">
          <div id="goal-lose" class="choice-card selected" onclick="selectGoal('lose_weight')">
            <div>
              <div class="choice-text">Perder Grasa / Peso</div>
              <div class="choice-desc">Déficit calórico progresivo y saludable.</div>
            </div>
          </div>
          <div id="goal-maintain" class="choice-card" onclick="selectGoal('maintain')">
            <div>
              <div class="choice-text">Mantener Peso Actual</div>
              <div class="choice-desc">Equilibrio calórico normocalórico.</div>
            </div>
          </div>
          <div id="goal-gain" class="choice-card" onclick="selectGoal('gain_muscle')">
            <div>
              <div class="choice-text">Ganar Masa Muscular</div>
              <div class="choice-desc">Superávit calórico controlado y alta proteína.</div>
            </div>
          </div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
        <div class="form-group">
          <label class="form-label">Peso Meta (kg)</label>
          <input type="number" id="input-target-weight" class="input-field" value="73" step="0.5">
        </div>
        <div class="form-group">
          <label class="form-label">Plazo (semanas)</label>
          <input type="number" id="input-target-weeks" class="input-field" value="8" min="1" max="52">
        </div>
      </div>

      <button class="btn-primary" onclick="finishOnboarding()">Calcular mi plan</button>
      <button class="btn-secondary" onclick="goToStep(2)">Atrás</button>
    </div>
  </div>
</div>

<!-- ------------------------------------------------------------------ -->
<!-- MODAL: SETTINGS & RESET -->
<!-- ------------------------------------------------------------------ -->
<div id="modal-settings" class="modal-overlay">
  <div class="sheet-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h3 style="font-size: 1.2rem; font-weight: 800;">Ajustes del Sistema</h3>
      <button class="icon-btn" onclick="closeModal('modal-settings')">
        <i data-lucide="x" style="width: 18px; height: 18px;"></i>
      </button>
    </div>

    <div style="background: #1a1e27; padding: 16px; border-radius: 16px; margin-bottom: 16px;">
      <div style="font-weight: 700; margin-bottom: 4px;">Modo de Red Local (Móvil)</div>
      <div style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.4;">
        Servidor listo en <b>host="0.0.0.0:8000"</b>. Abre en tu navegador de Android usando tu IP local: <code>http://192.168.1.22:8000</code>.
      </div>
    </div>

    <div style="background: #1a1e27; padding: 16px; border-radius: 16px; margin-bottom: 24px;">
      <div style="font-weight: 700; margin-bottom: 4px;">IA Multimodal Visión</div>
      <div style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.4;">
        Conectado con <b>Gemini 2.5 Flash</b> mediante la API Key oficial configurada en <code>.env</code>.
      </div>
    </div>

    <button class="btn-secondary" style="color: var(--danger); background: rgba(239, 68, 68, 0.1);" onclick="resetAllData()">
      Reiniciar Todos los Datos y Perfil
    </button>
  </div>
</div>

<!-- FULL-SCREEN AUTHENTICATION FLOW -->
<div id="modal-login" class="modal-overlay fullscreen-flow open" role="dialog" aria-modal="true" aria-label="Acceso a Calories Tracker">
  <div class="sheet-card">
    <section id="auth-welcome" class="auth-screen">
      <img
        class="auth-illustration"
        src="/assets/cal-tracker-welcome.svg"
        width="420"
        height="320"
        alt="Plato saludable con seguimiento de calorías, nutrientes y objetivo de peso"
        fetchpriority="high"
      >
      <div class="auth-brand">Calories Tracker</div>
      <h1 class="auth-title">Tu progreso,<br>sin complicaciones.</h1>
      <p class="auth-description">Inicia sesión para continuar o crea una cuenta y configura tu plan personal.</p>
      <button id="google-auth-welcome" class="btn-secondary auth-action-button" style="display: none;" onclick="startGoogleLogin()">
        <svg class="google-logo" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.2-2.27H12v4.51h6.44a5.5 5.5 0 0 1-2.39 3.61v3h3.87c2.26-2.08 3.57-5.15 3.57-8.85Z"/>
          <path fill="#34A853" d="M12 24c3.24 0 5.96-1.08 7.95-2.92l-3.87-3c-1.08.72-2.46 1.14-4.08 1.14-3.13 0-5.78-2.11-6.73-4.96H1.27v3.09A12 12 0 0 0 12 24Z"/>
          <path fill="#FBBC05" d="M5.27 14.26a7.2 7.2 0 0 1 0-4.52V6.65H1.27a12 12 0 0 0 0 10.7l4-3.09Z"/>
          <path fill="#EA4335" d="M12 4.77c1.77 0 3.35.61 4.6 1.8l3.43-3.43A11.53 11.53 0 0 0 12 0 12 12 0 0 0 1.27 6.65l4 3.09C6.22 6.88 8.87 4.77 12 4.77Z"/>
        </svg>
        <span>Continuar con Google</span>
      </button>
      <button class="btn-primary auth-action-button" onclick="showAuthForm('login')">
        <i class="auth-button-icon" data-lucide="log-in" aria-hidden="true"></i>
        <span>Iniciar sesión</span>
      </button>
      <button class="btn-secondary auth-action-button" onclick="showAuthForm('register')">
        <i class="auth-button-icon" data-lucide="user-plus" aria-hidden="true"></i>
        <span>Registrarme</span>
      </button>
    </section>

    <section id="auth-form" class="auth-screen" style="display: none;">
      <button class="auth-back" onclick="showAuthWelcome()">← Volver</button>
      <div class="auth-brand">Calories Tracker</div>
      <h1 id="auth-form-title" class="auth-title">Iniciar sesión</h1>
      <p id="auth-form-description" class="auth-description">Accede a tu diario y continúa con tus objetivos.</p>
      <form id="auth-credentials-form">
        <div class="form-group">
          <label class="form-label" for="auth-username">Usuario</label>
          <input type="text" id="auth-username" class="input-field" placeholder="Tu usuario" autocomplete="username" required maxlength="80">
        </div>
        <div class="form-group">
          <label class="form-label" for="auth-password">Contraseña</label>
          <input type="password" id="auth-password" class="input-field" placeholder="Tu contraseña" autocomplete="current-password" required maxlength="1024">
        </div>
        <p id="auth-password-hint" class="auth-description" style="display: none; margin: -4px 0 20px; font-size: 0.8rem;">Usa al menos 12 caracteres.</p>
        <button id="auth-submit" class="btn-primary auth-action-button" type="submit">
          <i class="auth-button-icon" data-lucide="log-in" aria-hidden="true"></i>
          <span>Iniciar sesión</span>
        </button>
      </form>
    </section>
  </div>
</div>
<!-- Scripts -->
<script>
  let currentProfile = null;
  let authMode = 'login';
  function getAuthHeaders() {
    return {};
  }
  async function apiFetch(url, options = {}) {
    const authHeaders = getAuthHeaders();
    options.headers = { ...(options.headers || {}), ...authHeaders };
    return fetch(url, options);
  }
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[char]);
  }
  let currentScanData = null;
  let weightChartInstance = null;
  let currentMealsCache = [];
  let onboardingState = {
    gender: 'male',
    activity_level: 'moderate',
    goal: 'lose_weight'
  };

  const CIRCLE_CIRCUMFERENCE = 2 * Math.PI * 68; // ~427.26

  document.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();
    document.getElementById('input-weight-date').value = new Date().toISOString().split('T')[0];
    document.getElementById('auth-credentials-form').addEventListener('submit', event => {
      event.preventDefault();
      authMode === 'register' ? submitRegister() : submitLogin();
    });
    configureGoogleAuth();
    fetchDashboard();
  });

  function showToast(msg) {
    const t = document.getElementById('toast');
    t.innerText = msg;
    t.style.display = 'block';
    setTimeout(() => { t.style.display = 'none'; }, 3000);
  }

  function openModal(id) {
    document.getElementById(id).classList.add('open');
    syncPageScrollLock();
    lucide.createIcons();
  }

  function closeModal(id) {
    document.getElementById(id).classList.remove('open');
    if (id === 'modal-onboarding') {
      document.getElementById(id).classList.remove('fullscreen-flow');
    }
    syncPageScrollLock();
  }

  function syncPageScrollLock() {
    const authOpen = document.getElementById('modal-login').classList.contains('open');
    const onboarding = document.getElementById('modal-onboarding');
    const onboardingOpen = onboarding.classList.contains('open')
      && onboarding.classList.contains('fullscreen-flow');
    document.body.classList.toggle('flow-open', authOpen || onboardingOpen);
  }

  function openProfileModal(fullscreen = false) {
    const modal = document.getElementById('modal-onboarding');
    modal.classList.toggle('fullscreen-flow', fullscreen);
    goToStep(1);
    modal.classList.add('open');
    syncPageScrollLock();
    lucide.createIcons();
  }

  function openSettingsModal() {
    openModal('modal-settings');
  }

  function openWeightModal() {
    if (currentProfile) {
      document.getElementById('input-log-weight').value = currentProfile.current_weight_kg;
    }
    document.getElementById('input-weight-date').value = new Date().toISOString().split('T')[0];
    openModal('modal-weight');
  }

  // Dashboard Loader
  async function fetchDashboard() {
    try {
      const query = new URLSearchParams(window.location.search);
      if (query.get('auth_error') === 'google') {
        showToast('No se pudo completar el acceso con Google. Inténtalo de nuevo.');
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      const res = await apiFetch('/api/dashboard');
      if (res.status === 401) {
        openLoginModal();
        return;
      }
      if (!res.ok) {
        throw new Error(`No se pudo cargar el dashboard (${res.status})`);
      }
      const data = await res.json();
      closeModal('modal-login');

      if (!data.has_profile) {
        openProfileModal(true);
        return;
      }

      currentProfile = data.profile;
      currentMealsCache = data.meals || [];
      renderDashboard(data.profile, data.summary, data.meals, data.weight_history || []);
    } catch (err) {
      console.error(err);
      showToast('Error conectando con Calories Tracker');
    }
  }

  function renderDashboard(profile, summary, meals, weightHistory) {
    // 1. Calories Hero Ring
    const targetCals = Math.round(profile.daily_calories);
    const consumedCals = Math.round(summary.calories);
    const remainingCals = Math.max(0, targetCals - consumedCals);

    document.getElementById('cals-target').innerText = targetCals.toLocaleString();
    document.getElementById('cals-consumed').innerText = consumedCals.toLocaleString();
    document.getElementById('cals-remaining').innerText = remainingCals.toLocaleString();

    // Progress Ring SVG
    const pct = Math.min(1.0, consumedCals / targetCals);
    const offset = CIRCLE_CIRCUMFERENCE - (pct * CIRCLE_CIRCUMFERENCE);
    const ring = document.getElementById('cal-ring');
    ring.style.strokeDashoffset = offset;
    ring.style.stroke = pct > 1.0 ? 'var(--danger)' : 'var(--accent)';

    // 2. Goal banner
    const weightDiff = Math.abs(profile.target_weight_kg - profile.current_weight_kg);
    let goalText = "Mantener Peso";
    if (profile.goal === 'lose_weight') {
      goalText = `Objetivo: Perder ${weightDiff} kg`;
    } else if (profile.goal === 'gain_muscle') {
      goalText = `Objetivo: Ganar ${weightDiff} kg músculo`;
    }
    document.getElementById('goal-summary-title').innerText = goalText;
    document.getElementById('goal-summary-sub').innerText = `En ${profile.target_weeks} sem • Meta: ${profile.target_weight_kg} kg (Actual: ${profile.current_weight_kg} kg)`;

    const currentWeight = Number(profile.current_weight_kg);
    const targetWeight = Number(profile.target_weight_kg);
    const targetWeeks = Number(profile.target_weeks);
    const weeklyRate = Number.isFinite(currentWeight)
      && Number.isFinite(targetWeight)
      && Number.isFinite(targetWeeks)
      && targetWeeks > 0
      ? (targetWeight - currentWeight) / targetWeeks
      : 0;
    const rateVal = weeklyRate.toFixed(1);
    document.getElementById('goal-summary-rate').innerText = `${weeklyRate > 0 ? '+' : ''}${rateVal} kg/sem`;


    // 3. Macronutrients
    renderMacro('protein', summary.proteins, profile.protein_g);
    renderMacro('carbs', summary.carbs, profile.carbs_g);
    renderMacro('fats', summary.fats, profile.fat_g);

    // 4. Weight Trend Chart
    renderWeightChart(weightHistory, profile.target_weight_kg);

    // 5. Meals history
    renderMealsList(meals);
    lucide.createIcons();
  }

  function renderMacro(key, consumed, target) {
    const c = Math.round(consumed);
    const t = Math.round(target);
    document.getElementById(`${key}-consumed`).innerText = c;
    document.getElementById(`${key}-target`).innerText = `${t}g`;
    const pct = Math.min(100, Math.round((c / t) * 100));
    document.getElementById(`${key}-bar`).style.width = `${pct}%`;
  }

  // Weight Chart Render with Chart.js
  function renderWeightChart(history, targetWeight) {
    const ctx = document.getElementById('weightChart').getContext('2d');

    // Prepare data points
    let labels = [];
    let weights = [];

    if (history.length === 0 && currentProfile) {
      labels = ['Inicio'];
      weights = [currentProfile.current_weight_kg];
    } else {
      labels = history.map(h => {
        const parts = h.date_logged.split('-');
        return `${parts[2]}/${parts[1]}`;
      });
      weights = history.map(h => h.weight_kg);
    }

    if (weights.length >= 2) {
      const diff = weights[weights.length - 1] - weights[0];
      const sign = diff > 0 ? '+' : '';
      document.getElementById('weight-trend-sub').innerText = `Cambio total: ${sign}${diff.toFixed(1)} kg (${weights[weights.length - 1]} kg hoy)`;
    } else if (weights.length === 1) {
      document.getElementById('weight-trend-sub').innerText = `Peso actual: ${weights[0]} kg • Meta: ${targetWeight} kg`;
    }

    if (weightChartInstance) {
      weightChartInstance.destroy();
    }

    weightChartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Peso (kg)',
            data: weights,
            borderColor: '#22c55e',
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointBackgroundColor: '#22c55e',
            pointRadius: 4,
            pointHoverRadius: 6
          },
          {
            label: 'Meta',
            data: Array(labels.length).fill(targetWeight),
            borderColor: 'rgba(239, 68, 68, 0.6)',
            borderDash: [5, 5],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            backgroundColor: '#1f2937',
            titleColor: '#fff',
            bodyColor: '#e5e7eb',
            borderColor: '#374151',
            borderWidth: 1,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${ctx.raw} kg`
            }
          }
        },
        scales: {
          x: {
            grid: { display: false, color: '#252a34' },
            ticks: { color: '#9ca3af', font: { size: 10 } }
          },
          y: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#9ca3af', font: { size: 10 } }
          }
        }
      }
    });
  }

  async function submitWeightLog() {
    const weightVal = parseFloat(document.getElementById('input-log-weight').value);
    const dateVal = document.getElementById('input-weight-date').value;
    const notesVal = document.getElementById('input-weight-notes').value;

    if (!weightVal || weightVal <= 0) {
      showToast('Introduce un peso válido');
      return;
    }

    try {
      const res = await apiFetch('/api/weight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          weight_kg: weightVal,
          date_logged: dateVal,
          notes: notesVal
        })
      });
      if (!res.ok) throw new Error('No se pudo registrar el peso');

      closeModal('modal-weight');
      showToast('¡Peso registrado en la gráfica!');
      fetchDashboard();
    } catch (err) {
      showToast('Error al registrar peso');
    }
  }

  // Meals List & Actions
  function renderMealsList(meals) {
    const container = document.getElementById('meals-container');
    document.getElementById('meal-count').innerText = `${meals.length} registrada${meals.length === 1 ? '' : 's'}`;

    if (!meals || meals.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon"><i data-lucide="utensils" style="width: 44px; height: 44px;"></i></div>
          <div style="font-weight: 700; margin-bottom: 4px;">Aún no has registrado comidas hoy</div>
          <div style="font-size: 0.8rem;">Usa los botones de Cámara o Galería abajo para analizar con la IA.</div>
        </div>
      `;
      return;
    }

    container.innerHTML = meals.map(meal => `
      <div class="meal-item" id="meal-card-${meal.id}">
        ${typeof meal.image_base64 === 'string' && /^data:image\\/(?:jpeg|png|webp);base64,/i.test(meal.image_base64)
          ? `<img src="${escapeHtml(meal.image_base64)}" class="meal-thumb" alt="${escapeHtml(meal.dish_name)}">`
          : `<div class="meal-thumb"><i data-lucide="coffee" style="width: 20px; height: 20px; color: var(--accent);"></i></div>`
        }
        <div class="meal-info">
          <div class="meal-name">${escapeHtml(meal.dish_name)}</div>
          <div class="meal-meta">
            <span>P: <b>${Math.round(meal.protein_g)}g</b></span>
            <span>C: <b>${Math.round(meal.carbs_g)}g</b></span>
            <span>G: <b>${Math.round(meal.fat_g)}g</b></span>
          </div>
        </div>
        <div style="text-align: right;">
          <div class="meal-cals">${Math.round(meal.total_calories)} kcal</div>
          <div class="meal-actions">
            <button class="meal-action-btn" onclick="openEditMeal(${meal.id})" title="Editar plato">
              <i data-lucide="pencil" style="width: 14px; height: 14px;"></i>
            </button>
            <button class="meal-action-btn del" onclick="deleteMeal(${meal.id})" title="Eliminar plato">
              <i data-lucide="trash-2" style="width: 14px; height: 14px;"></i>
            </button>
          </div>
        </div>
      </div>
    `).join('');
  }

  // Open Edit Meal Modal
  function openEditMeal(mealId) {
    const meal = currentMealsCache.find(m => m.id === mealId);
    if (!meal) return;

    document.getElementById('edit-meal-id').value = meal.id;
    document.getElementById('edit-dish-name').value = meal.dish_name;
    document.getElementById('edit-calories').value = Math.round(meal.total_calories);
    document.getElementById('edit-protein').value = meal.protein_g;
    document.getElementById('edit-carbs').value = meal.carbs_g;
    document.getElementById('edit-fats').value = meal.fat_g;

    openModal('modal-edit-meal');
  }

  async function saveEditedMeal() {
    const id = document.getElementById('edit-meal-id').value;
    const payload = {
      dish_name: document.getElementById('edit-dish-name').value,
      total_calories: parseFloat(document.getElementById('edit-calories').value) || 0,
      protein_g: parseFloat(document.getElementById('edit-protein').value) || 0,
      carbs_g: parseFloat(document.getElementById('edit-carbs').value) || 0,
      fat_g: parseFloat(document.getElementById('edit-fats').value) || 0
    };

    try {
      const res = await apiFetch(`/api/meal/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('No se pudo actualizar la comida');
      closeModal('modal-edit-meal');
      showToast('Plato actualizado correctamente');
      fetchDashboard();
    } catch (err) {
      showToast('Error al actualizar el plato');
    }
  }

  async function deleteMeal(mealId) {
    if (!confirm('¿Deseas eliminar este registro de comida?')) return;
    try {
      const res = await apiFetch(`/api/meal/${mealId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('No se pudo eliminar la comida');
      showToast('Comida eliminada');
      fetchDashboard();
    } catch (err) {
      showToast('Error al eliminar');
    }
  }

  // Camera & Gallery Triggers
  function triggerCamera() {
    document.getElementById('camera-file-input').click();
  }

  function triggerGallery() {
    document.getElementById('gallery-file-input').click();
  }

  async function handleImageSelected(event) {
    const file = event.target.files[0];
    if (!file) return;

    openModal('modal-scan');
    document.getElementById('scan-loading').style.display = 'flex';
    document.getElementById('scan-result').style.display = 'none';

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/scan-food', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Fallo en la llamada a la IA');
      }
      currentScanData = {
        ...data.analysis,
        preview_url: data.preview_url
      };
      displayScanResult(currentScanData);
    } catch (err) {
      console.error(err);
      alert('Error de IA: ' + err.message);
      showToast('Error: ' + err.message);
      closeModal('modal-scan');
    } finally {
      event.target.value = '';
    }
  }

  function displayScanResult(data) {
    document.getElementById('scan-loading').style.display = 'none';
    document.getElementById('scan-result').style.display = 'block';

    document.getElementById('scan-preview-img').src = data.preview_url || '';
    document.getElementById('scan-dish-name').innerText = data.dish_name || 'Comida detectada';
    document.getElementById('scan-confidence').innerText = `${Math.round((data.confidence_score || 0.95) * 100)}%`;
    document.getElementById('scan-calories').innerText = Math.round(data.total_calories || 0);

    const macros = data.macronutrients || {};
    document.getElementById('scan-protein').innerText = `${Math.round(macros.proteins_g || 0)}g`;
    document.getElementById('scan-carbs').innerText = `${Math.round(macros.carbs_g || 0)}g`;
    document.getElementById('scan-fats').innerText = `${Math.round(macros.fats_g || 0)}g`;

    const ingrContainer = document.getElementById('scan-ingredients-list');
    const items = data.items || [];
    if (items.length > 0) {
      ingrContainer.innerHTML = items.map(it => `
        <div class="ingr-item">
          <div>
            <div class="ingr-name">${escapeHtml(it.ingredient)}</div>
            <div class="ingr-qty">${escapeHtml(it.estimated_weight_g || 100)}g estimados</div>
          </div>
          <div class="ingr-cal">${escapeHtml(it.calories || 0)} kcal</div>
        </div>
      `).join('');
    } else {
      ingrContainer.innerHTML = '<p style="font-size: 0.8rem; color: var(--text-muted);">Plato consolidado.</p>';
    }
    lucide.createIcons();
  }

  async function confirmLogMeal() {
    if (!currentScanData) return;
    try {
      const payload = {
        dish_name: currentScanData.dish_name,
        total_calories: currentScanData.total_calories,
        protein_g: currentScanData.macronutrients?.proteins_g || 0,
        carbs_g: currentScanData.macronutrients?.carbs_g || 0,
        fat_g: currentScanData.macronutrients?.fats_g || 0,
        fiber_g: currentScanData.macronutrients?.fiber_g || 0,
        confidence_score: currentScanData.confidence_score || 1.0,
        items: currentScanData.items || [],
        image_base64: currentScanData.preview_url
      };

      const res = await apiFetch('/api/log-meal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('No se pudo guardar la comida');

      closeModal('modal-scan');
      showToast('¡Comida añadida al diario con éxito!');
      fetchDashboard();
    } catch (err) {
      showToast('Error guardando la comida');
    }
  }

  // Onboarding Wizard Logic
  function goToStep(step) {
    document.getElementById('step-1').style.display = step === 1 ? 'block' : 'none';
    document.getElementById('step-2').style.display = step === 2 ? 'block' : 'none';
    document.getElementById('step-3').style.display = step === 3 ? 'block' : 'none';

    document.getElementById('step-bar-1').className = `step-bar ${step >= 1 ? 'active' : ''}`;
    document.getElementById('step-bar-2').className = `step-bar ${step >= 2 ? 'active' : ''}`;
    document.getElementById('step-bar-3').className = `step-bar ${step >= 3 ? 'active' : ''}`;
  }

  function selectGender(g) {
    onboardingState.gender = g;
    document.getElementById('gender-male').className = `choice-card ${g === 'male' ? 'selected' : ''}`;
    document.getElementById('gender-female').className = `choice-card ${g === 'female' ? 'selected' : ''}`;
  }

  function selectActivity(act) {
    onboardingState.activity_level = act;
    ['sedentary', 'light', 'moderate', 'very_active'].forEach(k => {
      document.getElementById(`act-${k}`).className = `choice-card ${act === k ? 'selected' : ''}`;
    });
  }

  function selectGoal(g) {
    onboardingState.goal = g;
    document.getElementById('goal-lose').className = `choice-card ${g === 'lose_weight' ? 'selected' : ''}`;
    document.getElementById('goal-maintain').className = `choice-card ${g === 'maintain' ? 'selected' : ''}`;
    document.getElementById('goal-gain').className = `choice-card ${g === 'gain_muscle' ? 'selected' : ''}`;
  }

  async function finishOnboarding() {
    const payload = {
      gender: onboardingState.gender,
      age: parseInt(document.getElementById('input-age').value) || 26,
      height_cm: parseFloat(document.getElementById('input-height').value) || 175,
      current_weight_kg: parseFloat(document.getElementById('input-current-weight').value) || 75,
      target_weight_kg: parseFloat(document.getElementById('input-target-weight').value) || 70,
      activity_level: onboardingState.activity_level,
      goal: onboardingState.goal,
      target_weeks: parseInt(document.getElementById('input-target-weeks').value) || 8
    };

    try {
      const res = await apiFetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('No se pudo guardar el perfil');
      closeModal('modal-onboarding');
      showToast('¡Plan metabólico personalizado calculado!');
      fetchDashboard();
    } catch (err) {
      showToast('Error al guardar el perfil');
    }
  }

  async function resetAllData() {
    if (!confirm('¿Seguro que deseas reiniciar el perfil, las comidas y el registro de peso?')) return;
    try {
      const res = await apiFetch('/api/reset-profile', { method: 'POST' });
      if (!res.ok) throw new Error('No se pudieron borrar los datos');
      closeModal('modal-settings');
      location.reload();
    } catch (err) {
      showToast(err.message || 'Error al reiniciar los datos');
    }
  }
  // Open login modal (used when 401)
  function openLoginModal() {
    closeModal('modal-onboarding');
    showAuthWelcome();
    openModal('modal-login');
  }

  function showAuthWelcome() {
    document.getElementById('auth-form').style.display = 'none';
    document.getElementById('auth-welcome').style.display = 'block';
    document.getElementById('auth-username').value = '';
    document.getElementById('auth-password').value = '';
  }

  async function configureGoogleAuth() {
    try {
      const response = await fetch('/api/auth/google/status');
      if (!response.ok) throw new Error('No se pudo comprobar el acceso con Google');
      const config = await response.json();
      document.getElementById('google-auth-welcome').style.display =
        config.enabled ? 'block' : 'none';
    } catch (error) {
      console.error(error);
    }
  }

  function startGoogleLogin() {
    window.location.assign('/auth/google');
  }

  function showAuthForm(mode) {
    authMode = mode;
    document.getElementById('auth-welcome').style.display = 'none';
    document.getElementById('auth-form').style.display = 'block';
    document.getElementById('auth-form-title').innerText =
      mode === 'register' ? 'Crear cuenta' : 'Iniciar sesión';
    document.getElementById('auth-form-description').innerText =
      mode === 'register'
        ? 'Crea tu cuenta y después configuraremos tus objetivos.'
        : 'Accede a tu diario y continúa con tus objetivos.';
    document.getElementById('auth-submit').innerHTML = mode === 'register'
      ? '<i class="auth-button-icon" data-lucide="user-plus" aria-hidden="true"></i><span>Crear cuenta</span>'
      : '<i class="auth-button-icon" data-lucide="log-in" aria-hidden="true"></i><span>Iniciar sesión</span>';
    lucide.createIcons();
    document.getElementById('auth-password-hint').style.display =
      mode === 'register' ? 'block' : 'none';
    document.getElementById('auth-password').autocomplete =
      mode === 'register' ? 'new-password' : 'current-password';
    document.getElementById('auth-password').minLength =
      mode === 'register' ? 12 : 1;
    document.getElementById('auth-password').focus();
  }

  // Submit login credentials
  async function submitLogin() {
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    if (!username || !password) {
      showToast('Introduce tu usuario y contraseña');
      return;
    }
    try {
      const res = await apiFetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      if (!res.ok) {
        const err = await res.json();
        showToast(err.detail || 'Error al iniciar sesión');
        return;
      }
      closeModal('modal-login');
      fetchDashboard();
    } catch (e) {
      console.error(e);
      showToast('Fallo al contactar el servidor de login');
    }
  }

  // Submit registration credentials
  async function submitRegister() {
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    if (!username || password.length < 12) {
      showToast('Introduce un usuario y una contraseña de al menos 12 caracteres');
      return;
    }
    try {
      const res = await apiFetch('/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      if (!res.ok) {
        const err = await res.json();
        showToast(err.detail || 'Error al registrar');
        return;
      }
      closeModal('modal-login');
      onboardingState = {
        gender: 'male',
        activity_level: 'moderate',
        goal: 'lose_weight'
      };
      openProfileModal(true);
    } catch (e) {
      console.error(e);
      showToast('Fallo al contactar el servidor de registro');
    }
  }

</script>
</body>
</html>
"""

if __name__ == "__main__":
    print(f"Starting Calories Tracker on http://{settings.HOST}:{settings.PORT} ...")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
# End of file (cleaned)
