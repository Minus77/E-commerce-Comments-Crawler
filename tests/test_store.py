from dataclasses import replace

import pytest

from review_sampler.models import ReviewDraft
from review_sampler.store import Store


def review(
    *,
    platform="jd",
    product_id="100012043978",
    review_id="r1",
    fingerprint="f" * 64,
    author="A",
    title="",
    content="很好用",
    rating=5,
    verified_purchase=None,
):
    return ReviewDraft(
        platform=platform,
        product_id=product_id,
        platform_review_id=review_id,
        fingerprint=fingerprint,
        author=author,
        title=title,
        content=content,
        rating=rating,
        created_at_text="2026-10-01",
        created_at=None,
        variant="",
        verified_purchase=verified_purchase,
        helpful_count=0,
        source_url="https://item.jd.com/100012043978.html",
    )


def test_review_upsert_is_idempotent(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task(
        platform="jd",
        product_id="100012043978",
        input_url=None,
        mode="auto",
        limit=100,
    )

    assert store.upsert_reviews(task["id"], [review()]) == 1
    assert store.upsert_reviews(task["id"], [review()]) == 0
    assert store.count_reviews(task_id=task["id"]) == 1


def test_same_fingerprint_with_different_review_id_is_deduplicated(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task("jd", "100012043978", None, "auto", 100)

    store.upsert_reviews(task["id"], [review(review_id="r1")])
    store.upsert_reviews(task["id"], [review(review_id="r2")])

    assert store.count_reviews(task_id=task["id"]) == 1


def test_same_fingerprint_can_exist_for_another_product(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task("jd", "100012043978", None, "auto", 100)

    store.upsert_reviews(task["id"], [review()])
    store.upsert_reviews(
        task["id"], [review(product_id="100000000001")]
    )

    assert store.count_reviews(product_id="100012043978") == 1
    assert store.count_reviews(product_id="100000000001") == 1


def test_upsert_fills_blank_fields_and_keeps_existing_text(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task("jd", "100012043978", None, "auto", 100)
    first = review(author="", content="原始内容")
    second = replace(first, author="新作者", content="不应覆盖")

    store.upsert_reviews(task["id"], [first])
    store.upsert_reviews(task["id"], [second])

    saved = store.list_reviews(task_id=task["id"])[0]
    assert saved["author"] == "新作者"
    assert saved["content"] == "原始内容"


def test_review_filters_only_search_text_fields(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    jd = store.create_task("jd", "100012043978", None, "auto", 100)
    taobao = store.create_task("taobao", "654321", None, "auto", 100)
    store.upsert_reviews(
        jd["id"],
        [
            review(author="咖啡爱好者", content="打印很快", rating=4),
            review(
                review_id="r2",
                fingerprint="e" * 64,
                author="B",
                content="不推荐",
                rating=1,
                verified_purchase=True,
            ),
        ],
    )
    store.upsert_reviews(
        taobao["id"],
        [
            review(
                platform="taobao",
                product_id="654321",
                review_id="t1",
                fingerprint="d" * 64,
                content="打印也很快",
                rating=4,
            )
        ],
    )

    assert store.count_reviews(query="打印") == 2
    assert store.count_reviews(query="100012043978") == 0
    assert store.count_reviews(rating=4, platform="jd") == 1
    assert store.count_reviews(verified=True) == 1
    assert store.count_reviews(platform="taobao") == 1


def test_list_reviews_applies_offset_and_caps_page_size(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task("jd", "100012043978", None, "auto", 100)
    reviews = [
        review(
            review_id=f"r{i}",
            fingerprint=f"{i:064x}",
            content=f"评论 {i}",
        )
        for i in range(3)
    ]
    store.upsert_reviews(task["id"], reviews)

    page = store.list_reviews(task_id=task["id"], offset=1, limit=1)
    too_large = store.list_reviews(task_id=task["id"], limit=6000)

    assert len(page) == 1
    assert len(too_large) == 3


def test_create_task_returns_complete_task(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task("jd", "100012043978", None, "auto", 100)

    assert task["status"] == "queued"
    assert task["collected_count"] == 0
    assert task["created_at"].endswith("+00:00")
    assert store.get_task(task["id"]) == task
    assert store.list_tasks()[0]["id"] == task["id"]


def test_update_task_rejects_unknown_fields(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task("jd", "100012043978", None, "auto", 100)

    with pytest.raises(ValueError, match="不支持"):
        store.update_task(task["id"], password="secret")


def test_recover_interrupted_only_changes_queued_and_running(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    queued = store.create_task("jd", "1", None, "auto", 10)
    running = store.create_task("jd", "2", None, "auto", 10)
    completed = store.create_task("jd", "3", None, "auto", 10)
    store.update_task(running["id"], status="running")
    store.update_task(completed["id"], status="completed")

    assert store.recover_interrupted() == 2
    assert store.get_task(queued["id"])["status"] == "interrupted"
    assert store.get_task(running["id"])["status"] == "interrupted"
    assert store.get_task(completed["id"])["status"] == "completed"
