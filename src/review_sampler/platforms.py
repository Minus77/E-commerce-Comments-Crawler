from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit
import re


PlatformName = Literal["jd", "taobao", "pdd", "amazon", "demo"]

_DIGIT_ID = re.compile(r"^\d+$")
_ASIN = re.compile(r"^[A-Za-z0-9]{10}$")
_AMAZON_HOST = re.compile(
    r"^(?:www\.|smile\.)?amazon\.(?:com|co\.uk|de|fr|it|es|ca|com\.au|co\.jp|in|com\.br|com\.mx|ae|sa|sg|nl|se|pl|com\.tr)$"
)
_SHORT_HOSTS = {
    "3.cn",
    "a.co",
    "amzn.to",
    "m.tb.cn",
    "p.pinduoduo.com",
    "tb.cn",
    "u.jd.com",
}
_HOSTS: dict[str, set[str]] = {
    "jd": {"item.jd.com", "item.m.jd.com"},
    "taobao": {
        "item.taobao.com",
        "detail.tmall.com",
        "detail.tmall.hk",
        "world.taobao.com",
    },
    "pdd": {
        "mobile.yangkeduo.com",
        "www.yangkeduo.com",
        "yangkeduo.com",
        "mobile.pinduoduo.com",
        "pinduoduo.com",
    },
}
_CANONICAL = {
    "jd": "https://item.jd.com/{id}.html",
    "taobao": "https://item.taobao.com/item.htm?id={id}",
    "pdd": "https://mobile.yangkeduo.com/goods.html?goods_id={id}",
    "amazon": "https://www.amazon.com/dp/{id}",
}


@dataclass(frozen=True)
class ParsedProduct:
    platform: str
    product_id: str
    source_url: str


def _platform_for_host(host: str) -> str | None:
    for name, hosts in _HOSTS.items():
        if host in hosts:
            return name
    if _AMAZON_HOST.fullmatch(host):
        return "amazon"
    return None


def _extract_url_id(platform: str, parts) -> str:
    host = (parts.hostname or "").lower().rstrip(".")
    if _platform_for_host(host) != platform:
        raise ValueError("商品链接与所选平台不一致，请检查后重试")

    if platform == "jd":
        match = re.fullmatch(r"/(?:product/)?(\d+)(?:\.html)?/?", parts.path)
        if not match:
            raise ValueError("无法从此商品链接识别京东商品 ID")
        return match.group(1)

    if platform == "taobao":
        values = parse_qs(parts.query).get("id", [])
        if len(values) != 1 or not _DIGIT_ID.fullmatch(values[0]):
            raise ValueError("无法从此商品链接识别淘宝或天猫商品 ID")
        return values[0]

    if platform == "pdd":
        values = parse_qs(parts.query).get("goods_id", [])
        if len(values) != 1 or not _DIGIT_ID.fullmatch(values[0]):
            raise ValueError("无法从此商品链接识别拼多多商品 ID")
        return values[0]

    path_parts = [part for part in parts.path.split("/") if part]
    candidates: list[str] = []
    for index, part in enumerate(path_parts[:-1]):
        if part in {"dp", "product"} or (
            part == "product-reviews" and index == 0
        ):
            candidates.append(path_parts[index + 1])
    if len(path_parts) >= 2 and path_parts[0] == "gp" and path_parts[1] == "product":
        candidates.append(path_parts[2] if len(path_parts) > 2 else "")
    valid = [value for value in candidates if _ASIN.fullmatch(value)]
    if not valid:
        raise ValueError("无法从此商品链接识别 Amazon ASIN")
    return valid[0].upper()


def parse_product(platform: str | None, raw: str) -> ParsedProduct:
    value = (raw or "").strip()
    if not value:
        raise ValueError("请输入商品链接或商品 ID")

    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("商品链接格式不正确，请粘贴 http 或 https 地址")
        host = parts.hostname.lower().rstrip(".")
        if host in _SHORT_HOSTS:
            raise ValueError(
                "短链接无法离线解析，请粘贴最终商品地址或商品 ID"
            )
        inferred = _platform_for_host(host)
        if inferred is None:
            raise ValueError("无法识别此商品链接的平台")
        chosen = platform or inferred
        if chosen != inferred:
            raise ValueError("商品链接与所选平台不一致，请检查后重试")
        return ParsedProduct(chosen, _extract_url_id(chosen, parts), value)

    if platform is None:
        raise ValueError("请选择商品所在平台")
    if platform not in _CANONICAL:
        raise ValueError("不支持的商品平台")
    identifier = value.upper() if platform == "amazon" else value
    valid = _ASIN.fullmatch(identifier) if platform == "amazon" else _DIGIT_ID.fullmatch(identifier)
    if not valid:
        expected = "10 位字母数字 ASIN" if platform == "amazon" else "数字商品 ID"
        raise ValueError(f"商品 ID 格式不正确，请输入{expected}")
    return ParsedProduct(
        platform,
        identifier,
        _CANONICAL[platform].format(id=identifier),
    )


def platform_catalog(browser_available: bool) -> list[dict]:
    items = [
        (
            "jd",
            "京东",
            True,
            "公开评论接口可能限流或改版；触发验证时需人工处理。",
            "https://item.jd.com/100012043978.html",
        ),
        (
            "taobao",
            "淘宝 / 天猫",
            False,
            "自动读取需要平台授权的应用与账号权限。",
            "https://item.taobao.com/item.htm?id=654321",
        ),
        (
            "pdd",
            "拼多多",
            False,
            "未找到可公开查询任意商品全部评论的接口。",
            "https://mobile.yangkeduo.com/goods.html?goods_id=987654",
        ),
        (
            "amazon",
            "Amazon",
            False,
            "Creators API 不提供评论列表，需在浏览器中读取可见内容。",
            "https://www.amazon.com/dp/B0D1234567",
        ),
        (
            "demo",
            "演示数据",
            False,
            "仅用于体验创建、筛选和导出流程，不会访问平台。",
            "DEMO-001",
        ),
    ]
    return [
        {
            "platform": platform,
            "name": name,
            "auto_api": auto_api,
            "browser_assist": browser_available and platform != "demo",
            "limitation": limitation,
            "example": example,
        }
        for platform, name, auto_api, limitation, example in items
    ]
