from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from review_sampler.models import ReviewDraft


_FIELDS = {
    "id": {
        "_id",
        "id",
        "commentId",
        "comment_id",
        "rateId",
        "reviewId",
        "review_id",
        "skuCommentId",
    },
    "content": {
        "_text",
        "body",
        "commentContent",
        "comment_content",
        "content",
        "rateContent",
        "reviewBody",
        "reviewText",
        "review_body",
        "text",
    },
    "author": {
        "_author",
        "author",
        "displayUserNick",
        "nickname",
        "nickName",
        "reviewer_name",
        "userName",
        "userNick",
        "user_name",
    },
    "title": {"reviewTitle", "review_title", "subject", "title"},
    "rating": {
        "rating",
        "score",
        "starRating",
        "star_rating",
        "stars",
    },
    "created_at_text": {
        "createTime",
        "creationTime",
        "date",
        "rateDate",
        "referenceTime",
        "reviewTime",
        "review_date",
        "time",
    },
    "variant": {
        "auctionSku",
        "productColor",
        "productSize",
        "product_variant",
        "sku",
        "spec",
        "specs",
        "variant",
    },
    "verified_purchase": {
        "avp",
        "hasVoucher",
        "isVerified",
        "valid",
        "verified",
        "verifiedPurchase",
        "verified_purchase",
    },
    "helpful_count": {
        "helpful",
        "helpfulVotes",
        "usefulVoteCount",
        "voteCount",
    },
    "source_url": {"sourceUrl", "source_url", "url"},
}
_MAX_DEPTH = 8
_MAX_CONTENT = 20_000


def _first(item: dict, field: str):
    for alias in _FIELDS[field]:
        if alias in item and item[alias] is not None:
            return item[alias]
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _rating(value: Any) -> tuple[int | None, bool]:
    if value is None or isinstance(value, bool):
        return None, False
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None, False
    rating = float(match.group())
    if rating <= 0:
        return None, True
    if rating > 10:
        return 5, False
    if rating > 5:
        rating /= 2
    return max(1, min(5, round(rating))), False


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    marker = _text(value).lower()
    if not marker:
        return None
    if marker in {"false", "0", "no", "否", "未购买"}:
        return False
    if marker in {"true", "1", "yes", "是", "verified purchase", "已购买"}:
        return True
    return None


def _integer(value: Any) -> int:
    match = re.search(r"\d+", _text(value))
    return int(match.group()) if match else 0


def _created_at(value: str) -> str | None:
    if not value:
        return None
    for candidate in (
        value,
        value.replace("年", "-").replace("月", "-").replace("日", ""),
    ):
        try:
            return datetime.fromisoformat(candidate).isoformat()
        except ValueError:
            continue
    return None


def _fingerprint(
    platform: str,
    product_id: str,
    review_id: str | None,
    author: str,
    content: str,
    created_at_text: str,
    rating: int | None,
) -> str:
    stable_content = " ".join(content.split())
    identity = review_id or "\0".join(
        [
            " ".join(author.split()),
            stable_content,
            " ".join(created_at_text.split()),
            str(rating or ""),
        ]
    )
    raw = "\0".join([platform, product_id, identity])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _make_review(
    platform: str,
    product_id: str,
    source_url: str,
    *,
    review_id: Any = None,
    author: Any = None,
    title: Any = None,
    content: Any = None,
    rating: Any = None,
    created_at_text: Any = None,
    variant: Any = None,
    verified_purchase: Any = None,
    helpful_count: Any = None,
) -> ReviewDraft | None:
    cleaned_content = _text(content)[:_MAX_CONTENT]
    cleaned_author = _text(author)
    if not cleaned_content or not cleaned_author:
        return None
    parsed_rating, invalid_rating = _rating(rating)
    if invalid_rating:
        return None
    cleaned_id = _text(review_id) or None
    cleaned_created = _text(created_at_text)
    return ReviewDraft(
        platform=platform,
        product_id=product_id,
        platform_review_id=cleaned_id,
        fingerprint=_fingerprint(
            platform,
            product_id,
            cleaned_id,
            cleaned_author,
            cleaned_content,
            cleaned_created,
            parsed_rating,
        ),
        author=cleaned_author,
        title=_text(title),
        content=cleaned_content,
        rating=parsed_rating,
        created_at_text=cleaned_created,
        created_at=_created_at(cleaned_created),
        variant=_text(variant),
        verified_purchase=_boolean(verified_purchase),
        helpful_count=max(0, _integer(helpful_count)),
        source_url=_text(source_url),
    )


def _candidate_dicts(value: Any, depth: int = 0):
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, dict):
        if any(alias in value for alias in _FIELDS["content"]):
            yield value
            return
        for nested in value.values():
            yield from _candidate_dicts(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            yield from _candidate_dicts(nested, depth + 1)


def _has_review_identity(item: dict) -> bool:
    return any(
        alias in item
        for field in ("id", "author", "created_at_text", "rating")
        for alias in _FIELDS[field]
    )


def normalize_payload(
    platform: str,
    product_id: str,
    payload: object,
    source_url: str,
) -> list[ReviewDraft]:
    reviews: list[ReviewDraft] = []
    seen: set[str] = set()
    for item in _candidate_dicts(payload):
        if not _has_review_identity(item):
            continue
        review = _make_review(
            platform,
            product_id,
            _text(_first(item, "source_url")) or source_url,
            review_id=_first(item, "id"),
            author=_first(item, "author"),
            title=_first(item, "title"),
            content=_first(item, "content"),
            rating=_first(item, "rating"),
            created_at_text=_first(item, "created_at_text"),
            variant=_first(item, "variant"),
            verified_purchase=_first(item, "verified_purchase"),
            helpful_count=_first(item, "helpful_count"),
        )
        if review is not None and review.fingerprint not in seen:
            seen.add(review.fingerprint)
            reviews.append(review)
    return reviews


def _select_text(node, selector: str) -> str:
    match = node.select_one(selector)
    return match.get_text(" ", strip=True) if match else ""


def _amazon_dom(
    platform: str,
    product_id: str,
    html: str,
    source_url: str,
) -> list[ReviewDraft]:
    soup = BeautifulSoup(html, "html.parser")
    reviews = []
    for index, node in enumerate(soup.select('[data-hook="review"]')):
        verified = "Verified Purchase" in node.get_text(" ", strip=True)
        review = _make_review(
            platform,
            product_id,
            source_url,
            review_id=node.get("id") or f"dom-{index}",
            author=_select_text(node, '[data-hook="review-author"]'),
            title=_select_text(node, '[data-hook="review-title"]'),
            content=_select_text(node, '[data-hook="review-body"]'),
            rating=_select_text(node, '[data-hook="review-star-rating"]'),
            created_at_text=_select_text(node, '[data-hook="review-date"]'),
            verified_purchase=verified if verified else None,
            helpful_count=_select_text(
                node, '[data-hook="helpful-vote-statement"]'
            ),
        )
        if review:
            reviews.append(review)
    return reviews


def _jd_dom(
    platform: str,
    product_id: str,
    html: str,
    source_url: str,
) -> list[ReviewDraft]:
    soup = BeautifulSoup(html, "html.parser")
    reviews = []
    for index, node in enumerate(soup.select(".comment-item")):
        star_node = node.select_one(".comment-star")
        star = ""
        if star_node:
            match = re.search(r"star(\d)", " ".join(star_node.get("class", [])))
            star = match.group(1) if match else ""
        review = _make_review(
            platform,
            product_id,
            source_url,
            review_id=node.get("data-id") or f"dom-{index}",
            author=_select_text(node, ".user-name"),
            content=_select_text(node, ".comment-con"),
            rating=star,
            created_at_text=_select_text(node, ".date"),
        )
        if review:
            reviews.append(review)
    return reviews


def parse_dom_reviews(
    platform: str,
    product_id: str,
    html: str,
    source_url: str,
) -> list[ReviewDraft]:
    if platform == "amazon":
        return _amazon_dom(platform, product_id, html, source_url)
    if platform == "jd":
        return _jd_dom(platform, product_id, html, source_url)
    return []


def looks_like_challenge(url: str, title: str, body_text: str) -> bool:
    parts = urlsplit(url)
    path_words = set(re.split(r"[/_.-]+", parts.path.lower()))
    host = (parts.hostname or "").lower()
    if path_words & {"captcha", "challenge", "login", "risk", "verify"}:
        return True
    if "passport" in host or "login" in host:
        return True

    title_marker = title.lower()
    if any(
        marker in title_marker
        for marker in (
            "登录",
            "安全验证",
            "验证码",
            "robot check",
            "sign in",
            "sorry",
        )
    ):
        return True

    body_marker = body_text.lower()
    return any(
        marker in body_marker
        for marker in (
            "滑块验证",
            "安全验证",
            "请输入验证码",
            "enter the characters you see below",
            "type the characters you see",
            "robot check",
        )
    )
