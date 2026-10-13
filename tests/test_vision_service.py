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
    monkeypatch.setattr(vision_service.settings, "GROQ_API_KEY", "")

    def fail_analysis(*args, **kwargs):
        raise RuntimeError("Gemini HTTP 429: quota exceeded; key=" + api_key)

    monkeypatch.setattr(vision_service, "analyze_with_gemini", fail_analysis)

    with caplog.at_level(logging.WARNING, logger="app.vision_service"):
        result = vision_service.analyze_food_image(b"image")

    assert result == {"error": "Food analysis is unavailable (Gemini: RuntimeError)"}
    assert "HTTP 429: quota exceeded" in caplog.text
    assert api_key not in caplog.text


def test_groq_vision_sends_image_and_parses_json(monkeypatch, test_environment):
    import base64

    import openai

    from app import vision_service

    api_key = "test-groq-secret-key"
    image_bytes = b"test-image-bytes"
    expected_analysis = {"dish_name": "Test meal", "total_calories": 250}
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return type(
                "Response",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {
                                "message": type(
                                    "Message",
                                    (),
                                    {"content": '{"dish_name":"Test meal","total_calories":250}'},
                                )()
                            },
                        )()
                    ]
                },
            )()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "OpenAI", FakeClient)

    result = vision_service.analyze_with_groq(
        image_bytes,
        mime_type="image/png",
        api_key=api_key,
    )

    assert result == expected_analysis
    assert captured["client"] == {
        "api_key": api_key,
        "base_url": "https://api.groq.com/openai/v1",
        "timeout": 8,
        "max_retries": 0,
    }
    request = captured["request"]
    assert request["model"] == "qwen/qwen3.8-27b"
    assert request["response_format"] == {"type": "json_object"}
    image_url = request["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url == f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"


def test_groq_is_tried_before_openai_when_gemini_fails(
    monkeypatch,
    test_environment,
):
    from app import vision_service

    monkeypatch.setattr(vision_service.settings, "GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(vision_service.settings, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(vision_service.settings, "OPENAI_API_KEY", "openai-key")

    def fail_gemini(*args, **kwargs):
        raise RuntimeError("Gemini quota exhausted")

    def succeed_groq(*args, **kwargs):
        return {"dish_name": "Groq meal"}

    def fail_openai(*args, **kwargs):
        raise AssertionError("OpenAI should not be used after Groq succeeds")

    monkeypatch.setattr(vision_service, "analyze_with_gemini", fail_gemini)
    monkeypatch.setattr(vision_service, "analyze_with_groq", succeed_groq)
    monkeypatch.setattr(vision_service, "analyze_with_openai", fail_openai)

    assert vision_service.analyze_food_image(b"image") == {"dish_name": "Groq meal"}
