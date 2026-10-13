"""
Multimodal Vision service to scan food dishes and extract nutritional JSON.
Sends real image bytes directly to Google Gemini (or OpenAI) with strict error reporting.
"""
import json
import re
import base64
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from .config import settings

logger = logging.getLogger(__name__)

VISION_PROMPT = """Eres el analista nutricional y experto en reconocimiento visual de alimentos por IA de Calories Tracker.
Tu tarea es analizar la comida real que aparece en esta imagen con máxima precisión visual.

INSTRUCCIONES CLAVE DE RECONOCIMIENTO GASTRONÓMICO:
1. Conoce ampliamente la gastronomía española, mediterránea y productos de supermercado (Mercadona, Carrefour, etc.):
   - Platos tradicionales: Tortilla de patatas (con o sin cebolla), Fabada asturiana, Paella / Arroz, Potaje de garbanzos o lentejas con chorizo, Gazpacho, Salmorejo, Croquetas, Solomillo o Pechuga con guarnición, Ensaladilla rusa, etc.
   - Productos cotidianos: Yogur griego, avena, tostadas con tomate y jamón serrano, batidos de proteínas, ensaladas mixtas, etc.
2. Identifica con exactitud los ingredientes visibles y estima el tamaño de la ración y peso en gramos de forma realista.
3. Calcula las calorías totales y los macronutrientes correspondientes (Proteínas ~4 kcal/g, Carbohidratos ~4 kcal/g, Grasas ~9 kcal/g, Fibra).

DEBES RESPONDER EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO.
NO incluyas bloques de código markdown como ```json ... ``` ni texto adicional antes o después.

ESQUEMA EXACTO:
{
  "dish_name": "Nombre descriptivo y específico del plato (ej: 'Tortilla de patatas casera')",
  "confidence_score": 0.95,
  "total_calories": 520,
  "macronutrients": {
    "proteins_g": 24.0,
    "carbs_g": 38.0,
    "fats_g": 30.0,
    "fiber_g": 4.5
  },
  "items": [
    {
      "ingredient": "Tortilla de patatas",
      "estimated_weight_g": 200,
      "calories": 420
    },
    {
      "ingredient": "Ensalada verde con aceite de oliva",
      "estimated_weight_g": 100,
      "calories": 100
    }
  ]
}
"""

# Ordered list of Gemini vision models to automatically cascade if one has a 503 spike
CANDIDATE_MODELS = [
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-image-preview",
]

def extract_json_from_text(text: str) -> Dict[str, Any]:
    """Helper to clean and parse JSON response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    text = text.strip()

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        text = match.group(1)

    return json.loads(text)

def analyze_with_gemini(image_bytes: bytes, mime_type: str = "image/jpeg", api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze image using Google Gemini REST endpoint directly with image bytes.
    Cascades through stable available flash models in case Google experiences temporary 503 high demand.
    """
    key = api_key or settings.GEMINI_API_KEY
    if not key:
        # Return a user-friendly error dict instead of raising, keeping the app alive
        return {"error": "Clave GEMINI_API_KEY no configurada. Por favor, configura la variable en .env."}

    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_image
                        }
                    },
                    {
                        "text": VISION_PROMPT
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }
    req_data = json.dumps(payload).encode("utf-8")

    last_error = None
    for model in CANDIDATE_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                candidate = res_json.get("candidates", [])[0]
                raw_text = candidate.get("content", {}).get("parts", [])[0].get("text", "")
                return extract_json_from_text(raw_text)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(error_body)
                msg = err_json.get("error", {}).get("message", error_body)
            except Exception:
                msg = error_body
            last_error = f"Gemini ({model} - HTTP {e.code}): {msg}"
            # If 503 (temporary high demand) or 404 (model deprecated), try next model
            # If 429 (rate limit), raise immediate error to be handled upstream
            if e.code in (503, 404):
                continue
            elif e.code == 429:
                raise RuntimeError("Rate limit exceeded")
            else:
                raise RuntimeError(last_error)
        except urllib.error.URLError as e:
            raise RuntimeError(f"Error de red/conexión con Google Gemini: {e.reason}")
        except Exception as e:
            last_error = f"Error al procesar ({model}): {str(e)}"
            continue

    raise RuntimeError(last_error or "No se pudo obtener respuesta de Gemini tras probar los modelos disponibles.")

def analyze_with_openai(image_bytes: bytes, mime_type: str = "image/jpeg", api_key: Optional[str] = None) -> Dict[str, Any]:
    """Analyze image using OpenAI GPT-4o API."""
    key = api_key or settings.OPENAI_API_KEY
    if not key:
        raise ValueError("OPENAI_API_KEY no encontrada en .env")

    from openai import OpenAI
    client = OpenAI(api_key=key)
    base64_img = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_img}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    content = response.choices[0].message.content
    return extract_json_from_text(content)

def analyze_food_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """Try configured vision providers in order and report unavailable service clearly."""
    errors = []
    if settings.GEMINI_API_KEY:
        try:
            return analyze_with_gemini(image_bytes, mime_type, settings.GEMINI_API_KEY)
        except Exception as exc:
            errors.append(f"Gemini: {type(exc).__name__}")
            logger.warning("Gemini image analysis failed (%s)", type(exc).__name__)

    if settings.OPENAI_API_KEY:
        try:
            return analyze_with_openai(image_bytes, mime_type, settings.OPENAI_API_KEY)
        except Exception as exc:
            errors.append(f"OpenAI: {type(exc).__name__}")
            logger.warning("OpenAI image analysis failed (%s)", type(exc).__name__)

    reason = "; ".join(errors) if errors else "no provider API key is configured"
    return {"error": f"Food analysis is unavailable ({reason})"}
