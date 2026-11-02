import pytest

from review_sampler.platforms import parse_product, platform_catalog


@pytest.mark.parametrize(
    ("platform", "raw", "expected"),
    [
        ("jd", "https://item.jd.com/100012043978.html", ("jd", "100012043978")),
        (
            "taobao",
            "https://detail.tmall.com/item.htm?id=654321&spm=x",
            ("taobao", "654321"),
        ),
        (
            "pdd",
            "https://mobile.yangkeduo.com/goods.html?goods_id=987654",
            ("pdd", "987654"),
        ),
        (
            "amazon",
            "https://www.amazon.co.uk/dp/B0D1234567?th=1",
            ("amazon", "B0D1234567"),
        ),
    ],
)
def test_parse_supported_product_urls(platform, raw, expected):
    product = parse_product(platform, raw)
    assert (product.platform, product.product_id) == expected


def test_bare_digit_id_requires_platform():
    with pytest.raises(ValueError, match="请选择商品所在平台"):
        parse_product(None, "100012043978")


def test_amazon_asin_is_uppercased():
    assert parse_product("amazon", "b0d1234567").product_id == "B0D1234567"


@pytest.mark.parametrize(
    "url",
    [
        "https://item.jd.com.evil.test/100012043978.html",
        "https://detail.tmall.com.evil.test/item.htm?id=654321",
        "https://mobile.yangkeduo.com.evil.test/goods.html?goods_id=987654",
        "https://www.amazon.com.evil.test/dp/B0D1234567",
    ],
)
def test_rejects_lookalike_product_hosts(url):
    with pytest.raises(ValueError, match="商品链接"):
        parse_product(None, url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.amazon.com/gp/product/B0abc12345?psc=1", "B0ABC12345"),
        ("https://www.amazon.com/product-reviews/B0abc12345/", "B0ABC12345"),
    ],
)
def test_amazon_supported_product_paths(raw, expected):
    assert parse_product(None, raw).product_id == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.com/gp/slredirect/B0ABC12345",
        "https://www.amazon.com/stores/example/B0ABC12345",
        "https://www.amazon.com/B0ABC12345",
    ],
)
def test_rejects_amazon_paths_without_a_product_identifier(url):
    with pytest.raises(ValueError, match="商品链接"):
        parse_product("amazon", url)


@pytest.mark.parametrize(
    ("platform", "raw"),
    [
        ("jd", "10001204x978"),
        ("taobao", "654321-1"),
        ("pdd", "goods-987654"),
        ("amazon", "B0D12345"),
    ],
)
def test_rejects_invalid_bare_ids(platform, raw):
    with pytest.raises(ValueError):
        parse_product(platform, raw)


@pytest.mark.parametrize(
    ("raw", "expected_platform"),
    [
        ("https://item.jd.com/100012043978.html", "jd"),
        ("https://item.taobao.com/item.htm?id=654321", "taobao"),
        ("https://detail.tmall.com/item.htm?id=654322", "taobao"),
        ("https://mobile.yangkeduo.com/goods.html?goods_id=987654", "pdd"),
        ("https://www.amazon.de/dp/B0D1234567", "amazon"),
    ],
)
def test_platform_is_inferred_from_url(raw, expected_platform):
    assert parse_product(None, raw).platform == expected_platform


@pytest.mark.parametrize(
    "url",
    [
        "https://u.jd.com/abc",
        "https://m.tb.cn/example",
        "https://p.pinduoduo.com/example",
        "https://amzn.to/example",
    ],
)
def test_short_links_return_a_specific_message(url):
    with pytest.raises(ValueError, match="短链接无法离线解析"):
        parse_product(None, url)


def test_platform_and_url_must_match():
    with pytest.raises(ValueError, match="商品链接"):
        parse_product("jd", "https://item.taobao.com/item.htm?id=654321")


def test_bare_id_gets_a_canonical_source_url():
    result = parse_product("amazon", "b0d1234567")
    assert result.source_url == "https://www.amazon.com/dp/B0D1234567"


def test_platform_catalog_reports_capabilities_and_browser_availability():
    available = {item["platform"]: item for item in platform_catalog(True)}
    unavailable = {item["platform"]: item for item in platform_catalog(False)}

    assert set(available) == {"jd", "taobao", "pdd", "amazon", "demo"}
    assert available["jd"]["auto_api"] is True
    assert available["amazon"]["auto_api"] is False
    assert available["jd"]["browser_assist"] is True
    assert unavailable["jd"]["browser_assist"] is False
    assert all(item["limitation"] for item in available.values())
