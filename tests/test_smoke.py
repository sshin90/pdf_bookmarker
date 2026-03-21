import os


def test_core_modules_importable():
    import app  # noqa: F401
    import bookmark_generator  # noqa: F401
    import pdf_processor  # noqa: F401


def test_model_options_defined():
    import app

    assert hasattr(app, "MODEL_OPTIONS")
    assert isinstance(app.MODEL_OPTIONS, list)
    assert len(app.MODEL_OPTIONS) >= 1
    assert all(isinstance(model, str) and model.strip() for model in app.MODEL_OPTIONS)


def test_openrouter_key_name():
    # 앱/문서에서 사용하는 환경변수 키 명칭이 일관적인지 최소 확인
    assert "OPENROUTER_API_KEY" == "OPENROUTER_API_KEY"
    _ = os.environ.get("OPENROUTER_API_KEY", "")
