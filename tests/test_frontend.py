import re


def test_workspace_page_contains_real_controls(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert 'id="task-form"' in html
    assert "商品链接或 ID" in html
    assert 'aria-live="polite"' in html
    assert "载入演示" in html
    assert 'class="review-content"' in html


def test_workspace_page_has_no_inline_event_handlers(client):
    html = client.get("/").text

    assert re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE) is None
    assert "innerHTML" not in html


def test_static_assets_are_served_with_their_media_types(client):
    css = client.get("/static/app.css")
    script = client.get("/static/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert ":focus-visible" in css.text
    assert "prefers-reduced-motion" in css.text
    assert "@media (max-width: 720px)" in css.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]


def test_client_uses_safe_dom_and_required_api_flows(client):
    script = client.get("/static/app.js").text

    assert "innerHTML" not in script
    assert "textContent" in script
    assert "URLSearchParams" in script
    assert "/api/platforms" in script
    assert "/api/tasks" in script
    assert "/api/demo" in script
    assert "setTimeout" in script
    assert "页面已处理，继续" in script
