from datetime import datetime, timezone
import hashlib

from review_sampler.models import ReviewDraft


_CONTENT = [
    ("林舟", "打印速度比预期快。\n双面打印时进纸也稳定。"),
    ("晚风", '包装完好，客服说"当天发出"，实际第二天才揽收。'),
    ("小满", "字迹清楚，连续打印两小时没有卡纸。",),
    ("远山", "安装步骤写得简洁，手机上也能跟着完成。"),
    ("阿青", "耗材价格偏高，长期使用还要算一下成本。"),
    ("纸飞机", "外观普通，功能正常，符合这个价位。"),
    ("木棉", "无线连接偶尔掉线，重新连接后可以继续。"),
    ("北岸", "扫描清晰，合同上的小字也能辨认。"),
    ("早川", "运行时声音明显，但不影响白天使用。"),
    ("石榴", "收到时外壳有一道细划痕，机器本身正常。"),
    ("南星", "纸张较厚时会卷边，普通复印纸没有问题。"),
    ("海盐", "APP 功能够用，设置菜单还可以更直接。"),
    ("十安", "第二次购买，给办公室补了一台。"),
    ("晴窗", "第一周工作正常，打印量大的用户可以再观察。"),
    ("白果", "发票打印和文档打印都试过，结果一致。"),
    ("河野", "驱动器安装花了些时间，官网版本可用。"),
    ("栗子", "复印一张很快，预热时间也能接受。"),
    ("云杉", "客服回复准确，没有回避保修问题。"),
    ("半夏", "随机器附带的耗材余量偏少。"),
    ("一川", "目前没有发现漏墨或偏色。"),
    ("九月", "小尺寸照片效果一般，文字文档更合适。"),
    ("星野", "机身比照片里更紧凑，放在书桌上不占地方。"),
    ("竹影", "双面打印第二面偶尔会有轻微阴影。"),
    ("半夏 ", "整体符合需求，后续会补充长期使用情况。"),
]


class DemoCollector:
    def collect(self, task: dict, runtime) -> None:
        limit = min(int(task["limit"]), 24)
        drafts: list[ReviewDraft] = []
        for index, sample in enumerate(_CONTENT[:limit], start=1):
            author = sample[0].strip()
            content = sample[1]
            rating = (index - 1) % 5 + 1
            raw = f"{author}\0{content}\0{rating}\0{index}".encode()
            drafts.append(
                ReviewDraft(
                    platform="demo",
                    product_id=task["product_id"],
                    platform_review_id=f"demo-{index}",
                    fingerprint=hashlib.sha256(raw).hexdigest(),
                    author=author,
                    title=f"演示评论 {index}",
                    content=content,
                    rating=rating,
                    created_at_text=f"2026-10-{(index - 1) % 28 + 1:02d}",
                    created_at=datetime(
                        2026, 10, (index - 1) % 28 + 1, tzinfo=timezone.utc
                    ).isoformat(),
                    variant="演示规格",
                    verified_purchase=index % 3 != 0,
                    helpful_count=index % 7,
                    source_url="https://example.invalid/demo",
                )
            )
        for start in range(0, limit, 6):
            runtime.checkpoint()
            batch = drafts[start : start + 6]
            runtime.emit(batch, str(start + len(batch)))
