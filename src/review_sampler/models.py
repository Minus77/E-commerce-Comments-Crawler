from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewDraft:
    platform: str
    product_id: str
    platform_review_id: str | None
    fingerprint: str
    author: str
    title: str
    content: str
    rating: int | None
    created_at_text: str
    created_at: str | None
    variant: str
    verified_purchase: bool | None
    helpful_count: int
    source_url: str
