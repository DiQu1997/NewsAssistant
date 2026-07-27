"""纯逻辑单元测试 —— 不碰网络、不碰数据库。"""
from pathlib import Path

from newsassistant.contentstore import ContentStore
from newsassistant.extract import extract_article
from newsassistant.feeds import parse_feed
from newsassistant.simhash import from_signed, hamming, simhash64, to_signed
from newsassistant.urlnorm import canonical_url

FIX = Path(__file__).parent / "fixtures"


# ── URL 规范化 ──────────────────────────────────────────────
def test_canonical_strips_tracking_and_fragment():
    u = canonical_url(
        "https://Example.com/News/story/?utm_source=x&fbclid=abc&b=2&a=1#frag")
    assert u == "https://example.com/News/story?a=1&b=2"


def test_canonical_same_article_same_key():
    a = canonical_url("https://site.com/a/b/?utm_campaign=mail")
    b = canonical_url("https://SITE.com:443/a/b")
    assert a == b


def test_canonical_keeps_meaningful_query():
    u = canonical_url("https://site.com/watch?v=xyz123")
    assert "v=xyz123" in u


def test_canonical_root_path():
    assert canonical_url("https://site.com") == "https://site.com/"


# ── simhash ────────────────────────────────────────────────
# 贴近真实转述场景的长度：~200 词正文，转述稿只改标题句的一个词。
# （3-shingle 对短文本的改动很敏感 —— 这是特性不是缺陷：几十词的
# 快讯里改三个词，本来就不该再算同一篇。）
TEXT = " ".join(
    f"Paragraph {i} of the notice describes provision number {i} of the "
    f"proposed rule and the expected compliance burden for filers."
    for i in range(12))


def test_simhash_near_duplicate_close():
    a = simhash64("The department published a proposed rule today. " + TEXT)
    b = simhash64("The department released a proposed rule today. " + TEXT)
    assert hamming(a, b) <= 3          # 长文一词之差 → 近距离


def test_simhash_different_text_far():
    a = simhash64(TEXT)
    b = simhash64("Earthquake of magnitude five point one struck off the "
                  "coast on Tuesday morning, seismologists reported." * 5)
    assert hamming(a, b) > 15


def test_simhash_signed_roundtrip():
    for h in (0, 1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1):
        assert from_signed(to_signed(h)) == h


# ── 内容存储 ────────────────────────────────────────────────
def test_contentstore_roundtrip_and_dedup(tmp_path):
    cs = ContentStore(tmp_path)
    sha1, ref1 = cs.put("hello 世界")
    sha2, ref2 = cs.put("hello 世界")
    assert (sha1, ref1) == (sha2, ref2)          # 内容寻址：同文同址
    assert cs.get(ref1) == "hello 世界"
    assert ref1.startswith(f"content/{sha1[:2]}/")


# ── feed 解析 ───────────────────────────────────────────────
def test_parse_feed_fixture():
    items = parse_feed((FIX / "sample_rss.xml").read_bytes())
    assert len(items) == 2
    assert items[0].url == "https://example.com/articles/rule-proposed"
    assert items[0].title == "Agency proposes new rule"
    assert items[0].published_at is not None
    assert items[0].published_at.tzinfo is not None
    assert items[1].summary and "summary only" in items[1].summary


# ── 正文抽取 ────────────────────────────────────────────────
def test_extract_article_fixture():
    ex = extract_article((FIX / "sample_article.html").read_bytes(),
                         url="https://example.com/articles/rule-proposed")
    assert ex.text and "proposed rule would revise" in ex.text
    assert "cookie banner" not in ex.text        # boilerplate 被剥掉
    assert ex.title and "rule" in ex.title.lower()
