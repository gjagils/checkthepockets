import importlib


def test_csrf_origin_check_rejects_cross_origin_authenticated_request(monkeypatch):
    import app.main as main
    from starlette.requests import Request

    monkeypatch.setattr(main, "CSRF_ENFORCE", True)
    monkeypatch.setattr(main, "APP_URL", "https://example.test")
    called = False

    async def next_handler(request):
        nonlocal called
        called = True
        return "ok"

    request = Request({
        "type": "http", "method": "POST", "path": "/settings/password",
        "headers": [(b"cookie", b"session=present"), (b"origin", b"https://evil.test")],
    })
    # Exercise the middleware function directly; this avoids booting the app.
    response = __import__("asyncio").run(main.csrf_origin_check(request, next_handler))
    assert response.status_code == 403
    assert not called


def test_csrf_origin_check_allows_same_origin_authenticated_request(monkeypatch):
    import app.main as main
    from starlette.requests import Request

    monkeypatch.setattr(main, "CSRF_ENFORCE", True)
    monkeypatch.setattr(main, "APP_URL", "https://example.test")

    async def next_handler(request):
        return "ok"

    request = Request({
        "type": "http", "method": "POST", "path": "/settings/password",
        "headers": [(b"cookie", b"session=present"), (b"origin", b"https://example.test")],
    })
    response = __import__("asyncio").run(main.csrf_origin_check(request, next_handler))
    assert response == "ok"
