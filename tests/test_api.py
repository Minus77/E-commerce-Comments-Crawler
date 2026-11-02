import csv
import io
import json

import pytest

from review_sampler.models import ReviewDraft


def test_create_demo_task_and_query_reviews(client, wait_for_task):
    response = client.post(
        "/api/tasks",
        json={
            "platform": "demo",
            "product": "DEMO-001",
            "mode": "demo",
            "limit": 3,
            "browser_consent": False,
        },
    )

    assert response.status_code == 202
    task = wait_for_task(response.json()["id"])
    assert task["status"] == "completed"
    reviews = client.get(f"/api/reviews?task_id={task['id']}").json()
    assert reviews["total"] == 3
    assert len(reviews["reviews"]) == 3


def test_platform_catalog_includes_demo_and_real_platforms(client):
    response = client.get("/api/platforms")

    assert response.status_code == 200
    items = {item["platform"]: item for item in response.json()["platforms"]}
    assert set(items) == {"jd", "taobao", "pdd", "amazon", "demo"}
    assert items["amazon"]["auto_api"] is False


@pytest.mark.parametrize("limit", [1, 5000])
def test_create_accepts_limit_boundaries(client, wait_for_task, limit):
    response = client.post(
        "/api/tasks",
        json={
            "platform": "demo",
            "product": "DEMO-001",
            "mode": "demo",
            "limit": limit,
        },
    )

    assert response.status_code == 202
    assert response.json()["limit"] == limit
    wait_for_task(response.json()["id"])


@pytest.mark.parametrize("limit", [0, 5001])
def test_create_rejects_out_of_range_limit(client, limit):
    response = client.post(
        "/api/tasks",
        json={
            "platform": "demo",
            "product": "DEMO-001",
            "mode": "demo",
            "limit": limit,
        },
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_short_link_fails_with_actionable_message(client):
    response = client.post(
        "/api/tasks",
        json={
            "platform": "jd",
            "product": "https://u.jd.com/example",
            "mode": "auto",
            "limit": 10,
        },
    )

    assert response.status_code == 422
    assert "短链接无法离线解析" in response.json()["detail"]


def test_browser_platform_requires_consent(client):
    response = client.post(
        "/api/tasks",
        json={
            "platform": "pdd",
            "product": "https://mobile.yangkeduo.com/goods.html?goods_id=987654",
            "mode": "auto",
            "limit": 10,
            "browser_consent": False,
        },
    )

    assert response.status_code == 422
    assert "浏览器" in response.json()["detail"]


def test_unknown_task_returns_chinese_detail(client):
    response = client.get("/api/tasks/not-found")

    assert response.status_code == 404
    assert response.json() == {"detail": "采集任务不存在"}


def test_repeated_continue_does_not_duplicate_reviews(client, wait_for_task):
    created = client.post(
        "/api/tasks",
        json={
            "platform": "demo",
            "product": "DEMO-001",
            "mode": "demo",
            "limit": 3,
        },
    ).json()

    first = client.post(f"/api/tasks/{created['id']}/continue")
    second = client.post(f"/api/tasks/{created['id']}/continue")
    wait_for_task(created["id"])

    assert first.status_code in {200, 202}
    assert second.status_code in {200, 202}
    assert client.get(
        f"/api/reviews?task_id={created['id']}"
    ).json()["total"] == 3


def test_reviews_support_keyword_rating_platform_and_verified_filters(
    client, wait_for_task
):
    task = client.post(
        "/api/tasks",
        json={
            "platform": "demo",
            "product": "DEMO-001",
            "mode": "demo",
            "limit": 24,
        },
    ).json()
    wait_for_task(task["id"])

    keyword = client.get(
        f"/api/reviews?task_id={task['id']}&q=打印"
    ).json()
    rating = client.get(
        f"/api/reviews?task_id={task['id']}&rating=5"
    ).json()
    platform = client.get("/api/reviews?platform=demo").json()
    verified = client.get(
        f"/api/reviews?task_id={task['id']}&verified=true"
    ).json()

    assert keyword["total"] >= 1
    assert rating["total"] == 4
    assert platform["total"] == 24
    assert verified["total"] == 16
    assert all(
        "打印" in (
            item["author"] + item["title"] + item["content"]
        )
        for item in keyword["reviews"]
    )


def _draft(index, **overrides):
    values = dict(
        platform="demo",
        product_id="DEMO-CSV",
        platform_review_id=f"csv-{index}",
        fingerprint=f"{index + 100:064x}",
        author="作者",
        title="",
        content=f"评论 {index}",
        rating=3,
        created_at_text="2026-10-01",
        created_at=None,
        variant="",
        verified_purchase=None,
        helpful_count=0,
        source_url="https://example.invalid/item",
    )
    values.update(overrides)
    return ReviewDraft(**values)


def _insert_export_reviews(store, client, wait_for_task):
    task = client.post(
        "/api/tasks",
        json={
            "platform": "demo",
            "product": "DEMO-001",
            "mode": "demo",
            "limit": 1,
        },
    ).json()
    wait_for_task(task["id"])
    store.upsert_reviews(
        task["id"],
        [
            _draft(1, author='=HYPERLINK("https://evil.invalid")'),
            _draft(2, title="+cmd"),
            _draft(3, content="-2+3\n第二行"),
            _draft(
                4,
                author="@SUM(A1:A2)",
                content='HTML 仍按文本：<script>alert("x")</script>\n"quoted"',
            ),
        ],
    )
    return task


def test_csv_export_has_bom_safe_formula_text_and_multiline_content(
    store, client, wait_for_task
):
    task = _insert_export_reviews(store, client, wait_for_task)

    response = client.get(f"/api/tasks/{task['id']}/export.csv")

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    text = response.content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert list(rows[0]) == [
        "platform",
        "product_id",
        "platform_review_id",
        "author",
        "title",
        "content",
        "rating",
        "created_at_text",
        "created_at",
        "variant",
        "verified_purchase",
        "helpful_count",
        "source_url",
    ]
    assert "'=HYPERLINK" in text
    assert "'+cmd" in text
    assert "'-2+3" in text
    assert "'@SUM" in text
    assert any("\n第二行" in row["content"] for row in rows)
    assert any('"quoted"' in row["content"] for row in rows)


def test_json_export_is_structured_and_excludes_internal_cursor(
    store, client, wait_for_task
):
    task = _insert_export_reviews(store, client, wait_for_task)

    response = client.get(f"/api/tasks/{task['id']}/export.json")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"task", "reviews"}
    assert "cursor" not in data["task"]
    assert isinstance(data["reviews"], list)
    assert any(
        "<script>" in review["content"] for review in data["reviews"]
    )
    assert str(store.path) not in json.dumps(data)


def test_export_missing_task_returns_404(client):
    response = client.get("/api/tasks/missing/export.csv")
    assert response.status_code == 404
    assert response.json()["detail"] == "采集任务不存在"
