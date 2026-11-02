import json
from pathlib import Path

from review_sampler.normalize import (
    looks_like_challenge,
    normalize_payload,
    parse_dom_reviews,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_all_platform_payload_shapes_generate_reviews_and_fingerprints():
    payloads = json.loads((FIXTURES / "platform_payloads.json").read_text())

    for platform, payload in payloads.items():
        reviews = normalize_payload(
            platform,
            "PRODUCT-1",
            payload,
            f"https://example.invalid/{platform}",
        )
        assert len(reviews) == 1
        assert len(reviews[0].fingerprint) == 64
        assert reviews[0].author
        assert reviews[0].content


def test_external_rating_text_becomes_an_integer():
    payload = {
        "reviews": [
            {
                "reviewer_name": "A",
                "review_body": "ok",
                "star_rating": "5.0 out of 5 stars",
            }
        ]
    }

    assert normalize_payload("amazon", "P", payload, "")[0].rating == 5


def test_fingerprint_ignores_whitespace_changes():
    a = normalize_payload(
        "jd",
        "1",
        {"comments": [{"id": "7", "content": "很好  用", "nickname": "A"}]},
        "",
    )
    b = normalize_payload(
        "jd",
        "1",
        {"comments": [{"id": "7", "content": " 很好 用 ", "nickname": "A"}]},
        "",
    )

    assert a[0].fingerprint == b[0].fingerprint


def test_script_text_stays_inert_string():
    reviews = normalize_payload(
        "taobao",
        "2",
        {
            "rateList": [
                {
                    "rateContent": "<script>alert(1)</script>",
                    "id": "9",
                    "displayUserNick": "A",
                }
            ]
        },
        "",
    )

    assert reviews[0].content == "<script>alert(1)</script>"


def test_nested_pagination_and_recursive_arrays_are_supported():
    payload = {
        "data": {
            "pages": [
                {
                    "items": [
                        {
                            "_id": "nested-1",
                            "_author": "A",
                            "_text": "嵌套数组里的评论",
                        }
                    ]
                }
            ],
            "page": {"next": 2},
            "status": "ok",
        }
    }

    reviews = normalize_payload("pdd", "3", payload, "")

    assert len(reviews) == 1
    assert reviews[0].content == "嵌套数组里的评论"


def test_negative_rating_and_empty_content_are_discarded():
    payload = {
        "reviews": [
            {"id": "1", "nickname": "A", "content": "负评分", "score": -1},
            {"id": "2", "nickname": "B", "content": "   ", "score": 5},
            {"id": "3", "nickname": "C", "content": "有效", "score": 4},
        ]
    }

    reviews = normalize_payload("jd", "4", payload, "")

    assert [item.content for item in reviews] == ["有效"]


def test_long_review_is_truncated_and_duplicates_are_removed():
    payload = {
        "reviews": [
            {"id": "1", "nickname": "A", "content": "x" * 20_050},
            {"id": "1", "nickname": "A", "content": "x" * 20_050},
        ]
    }

    reviews = normalize_payload("pdd", "5", payload, "")

    assert len(reviews) == 1
    assert len(reviews[0].content) == 20_000


def test_amazon_dom_is_parsed_from_public_review_markup():
    html = (FIXTURES / "amazon_reviews.html").read_text()

    reviews = parse_dom_reviews(
        "amazon",
        "B0D1234567",
        html,
        "https://www.amazon.com/dp/B0D1234567",
    )

    assert len(reviews) == 2
    assert reviews[0].rating == 5
    assert reviews[0].author == "林舟"
    assert reviews[0].verified_purchase is True
    assert reviews[1].rating == 2


def test_jd_dom_is_parsed_from_public_comment_markup():
    html = """
    <div class="comment-item">
      <div class="user-info"><span class="user-name">星河</span></div>
      <div class="comment-star star5"></div>
      <p class="comment-con">运行稳定</p>
      <div class="comment-message"><span class="date">2026-10-01</span></div>
    </div>
    """

    reviews = parse_dom_reviews(
        "jd",
        "100012043978",
        html,
        "https://item.jd.com/100012043978.html",
    )

    assert len(reviews) == 1
    assert reviews[0].content == "运行稳定"
    assert reviews[0].rating == 5


def test_challenge_detection_uses_page_signals_not_review_text():
    assert looks_like_challenge(
        "https://passport.example.com/login",
        "登录",
        "",
    )
    assert looks_like_challenge(
        "https://example.com/product",
        "安全验证",
        "请完成滑块验证",
    )
    assert not looks_like_challenge(
        "https://example.com/product",
        "商品评论",
        "评论内容：登录后才能同步，但我今天没有登录。",
    )


def test_unknown_fields_do_not_break_parsing():
    payload = {"meta": {"foo": [1, {"bar": None}]}, "reviews": [{"other": 1}]}

    assert normalize_payload("pdd", "6", payload, "") == []
