import logging


def test_provider_failure_logs_reason_without_exposing_api_key(
    test_environment,
    monkeypatch,
    caplog,
):
    from app import vision_service

    api_key = "test-gemini-secret-key"
    monkeypatch.setattr(vision_service.settings, "GEMINI_API_KEY", api_key)
    monkeypatch.setattr(vision_service.settings, "OPENAI_API_KEY", "")

    def fail_analysis(*args, **kwargs):
        raise RuntimeError("Gemini HTTP 429: quota exceeded; key=" + api_key)

    monkeypatch.setattr(vision_service, "analyze_with_gemini", fail_analysis)

    with caplog.at_level(logging.WARNING, logger="app.vision_service"):
        result = vision_service.analyze_food_image(b"image")

    assert result == {"error": "Food analysis is unavailable (Gemini: RuntimeError)"}
    assert "HTTP 429: quota exceeded" in caplog.text
    assert api_key not in caplog.text
