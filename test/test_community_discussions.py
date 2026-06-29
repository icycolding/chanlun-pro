from pathlib import Path
import sys
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.community_discussions import (
    normalize_discussion_item,
    summarize_discussion_items,
)
import cl_app.community_providers as community_providers
from cl_app.community_providers import EastmoneyGubaProvider
from cl_app.community_sync import sync_community_discussions_for_stock


def test_normalize_discussion_item_distinguishes_post_and_comment():
    post = normalize_discussion_item(
        {
            "platform": "eastmoney",
            "content_type": "post",
            "platform_item_id": "p-1",
            "title": "光模块继续走强",
            "content": "看多 1.6T 和 CPO。",
            "author_name": "用户A",
            "published_at": "2026-06-27 10:00:00",
            "reply_count": 12,
            "like_count": 5,
            "url": "https://example.com/post/1",
            "symbol": "002281",
            "company_name": "光迅科技",
        }
    )
    comment = normalize_discussion_item(
        {
            "platform": "eastmoney",
            "content_type": "comment",
            "platform_item_id": "c-1",
            "parent_item_id": "p-1",
            "content": "核心还是看订单兑现。",
            "author_name": "用户B",
            "published_at": "2026-06-27 11:00:00",
            "reply_count": 0,
            "like_count": 2,
            "url": "https://example.com/post/1#comment-1",
            "symbol": "002281",
            "company_name": "光迅科技",
        }
    )

    assert post["content_type"] == "post"
    assert post["title"] == "光模块继续走强"
    assert comment["content_type"] == "comment"
    assert comment["parent_item_id"] == "p-1"
    assert comment["title"] == ""


def test_summarize_discussion_items_groups_platform_counts_and_empty_warning():
    summary = summarize_discussion_items(
        [
            normalize_discussion_item(
                {
                    "platform": "eastmoney",
                    "content_type": "post",
                    "platform_item_id": "p-1",
                    "title": "帖子 1",
                    "content": "看多 1.6T。",
                    "published_at": "2026-06-27 10:00:00",
                    "symbol": "002281",
                    "company_name": "光迅科技",
                }
            ),
            normalize_discussion_item(
                {
                    "platform": "eastmoney",
                    "content_type": "comment",
                    "platform_item_id": "c-1",
                    "parent_item_id": "p-1",
                    "content": "评论 1",
                    "published_at": "2026-06-27 10:10:00",
                    "symbol": "002281",
                    "company_name": "光迅科技",
                }
            ),
        ]
    )

    assert summary["noise_warning"] == ""
    assert summary["platform_breakdown"][0]["platform"] == "eastmoney"
    assert summary["platform_breakdown"][0]["posts"] == 1
    assert summary["platform_breakdown"][0]["comments"] == 1


def test_eastmoney_provider_fetch_posts_parses_public_article_list(monkeypatch):
    sample_html = """
    <html>
      <script>
        var article_list={"re":[
          {"post_id":1733704956,"post_title":"CPO 还是核心主线","stockbar_code":"002281","stockbar_name":"光迅科技吧","user_nickname":"股友A","post_comment_count":7,"post_click_count":321,"post_publish_time":"2026-06-27 09:18:47","post_display_time":"2026-06-27 09:18:47"},
          {"post_id":1733654663,"post_title":"财富号内容不应混入","stockbar_code":"cfhpl","stockbar_name":"财富号评论吧","user_nickname":"长风揽盈C","post_comment_count":4,"post_click_count":1855,"post_publish_time":"2026-06-26 22:05:02","post_display_time":"2026-06-26 22:05:02"}
        ],"count":2,"bar_name":"光迅科技","bar_code":"002281","rc":1,"me":"操作成功"};
      </script>
    </html>
    """

    class DummyResponse:
        text = sample_html
        encoding = "utf-8"

        def raise_for_status(self):
            return None

    def fake_get(url, headers=None, timeout=0):
        assert "list,002281,f_1.html" in url
        return DummyResponse()

    monkeypatch.setattr(
        community_providers,
        "requests",
        SimpleNamespace(get=fake_get),
        raising=False,
    )

    provider = EastmoneyGubaProvider()
    posts = provider.fetch_posts(symbol="sz002281", company_name="光迅科技", limit=5)

    assert len(posts) == 1
    assert posts[0]["platform"] == "eastmoney"
    assert posts[0]["content_type"] == "post"
    assert posts[0]["platform_item_id"] == "1733704956"
    assert posts[0]["title"] == "CPO 还是核心主线"
    assert posts[0]["author_name"] == "股友A"
    assert posts[0]["reply_count"] == 7
    assert posts[0]["like_count"] == 321
    assert posts[0]["symbol"] == "002281"
    assert posts[0]["company_name"] == "光迅科技"
    assert posts[0]["url"] == "https://guba.eastmoney.com/news,002281,1733704956.html"


def test_eastmoney_provider_fetch_comments_maps_reply_api_payload(monkeypatch):
    sample_payload = {
        "re": [
            {
                "reply_id": 9001,
                "reply_text": "同意，先看 20 日线支撑。",
                "reply_publish_time": "2026-06-27 00:01:00",
                "reply_like_count": 3,
                "reply_count": 1,
                "source_post_id": 1733674904,
                "reply_user": {"user_id": "u1", "user_nickname": "股友甲"},
                "reply_state": 0,
                "child_replys": [
                    {
                        "reply_id": 9002,
                        "reply_text": "回复楼上，周一看板块强度。",
                        "reply_publish_time": "2026-06-27 00:05:00",
                        "reply_like_count": 1,
                        "source_post_id": 1733674904,
                        "source_reply_id": 9001,
                        "reply_user": {"user_id": "u2", "user_nickname": "股友乙"},
                        "reply_state": 0,
                    }
                ],
            },
        ],
        "rc": 1,
        "me": "操作成功",
    }

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return sample_payload

    def fake_post(url, data=None, headers=None, timeout=0):
        assert "api/getData" in url
        assert "code=002281" in url
        assert "path=reply/api/Reply/ArticleNewReplyList" in url
        assert data["plat"] == "Web"
        assert data["path"] == "reply/api/Reply/ArticleNewReplyList"
        assert data["product"] == "Guba"
        assert "postid=1733674904" in data["param"]
        return DummyResponse()

    monkeypatch.setattr(
        community_providers,
        "requests",
        SimpleNamespace(post=fake_post),
        raising=False,
    )

    provider = EastmoneyGubaProvider()
    comments = provider.fetch_comments(
        post_id="1733674904",
        limit=5,
        post={
            "platform_item_id": "1733674904",
            "symbol": "002281",
            "company_name": "光迅科技",
            "url": "https://guba.eastmoney.com/news,002281,1733674904.html",
        },
    )

    assert len(comments) == 2
    assert comments[0]["content_type"] == "comment"
    assert comments[0]["platform_item_id"] == "9001"
    assert comments[0]["parent_item_id"] == "1733674904"
    assert comments[0]["author_name"] == "股友甲"
    assert comments[0]["content"] == "同意，先看 20 日线支撑。"
    assert comments[0]["symbol"] == "002281"
    assert comments[1]["parent_item_id"] == "9001"
    assert comments[1]["company_name"] == "光迅科技"
    assert comments[1]["url"] == "https://guba.eastmoney.com/news,002281,1733674904.html#reply-9002"


def test_sync_community_discussions_passes_post_context_to_comment_fetch():
    captured_posts = []

    class FakeProvider:
        platform = "eastmoney"

        def fetch_posts(self, symbol: str, company_name: str, limit: int = 20):
            return [
                {
                    "platform": "eastmoney",
                    "content_type": "post",
                    "platform_item_id": "1733674904",
                    "title": "帖子",
                    "content": "帖子",
                    "symbol": symbol,
                    "company_name": company_name,
                    "url": "https://guba.eastmoney.com/news,002281,1733674904.html",
                }
            ]

        def fetch_comments(self, post_id: str, limit: int = 20, post=None):
            captured_posts.append(post)
            return []

        def provider_status(self):
            return {"status": "partial"}

    class FakeDb:
        def community_discussions_replace_or_upsert(self, rows):
            return True

    original_factory = community_providers.get_default_community_providers
    original_sync_factory = __import__("cl_app.community_sync", fromlist=["get_default_community_providers"]).get_default_community_providers
    try:
        community_providers.get_default_community_providers = lambda: [FakeProvider()]
        __import__("cl_app.community_sync", fromlist=["get_default_community_providers"]).get_default_community_providers = lambda: [FakeProvider()]
        sync_community_discussions_for_stock(
            symbol="002281",
            company_name="光迅科技",
            limit=5,
            db_instance=FakeDb(),
        )
    finally:
        community_providers.get_default_community_providers = original_factory
        __import__("cl_app.community_sync", fromlist=["get_default_community_providers"]).get_default_community_providers = original_sync_factory

    assert captured_posts
    assert captured_posts[0]["symbol"] == "002281"
    assert captured_posts[0]["company_name"] == "光迅科技"


def test_sync_community_discussions_keeps_partial_status_when_only_posts_available():
    class FakeProvider:
        platform = "eastmoney"

        def fetch_posts(self, symbol: str, company_name: str, limit: int = 20):
            return [
                {
                    "platform": "eastmoney",
                    "content_type": "post",
                    "platform_item_id": "1733674904",
                    "title": "帖子",
                    "content": "帖子",
                    "symbol": symbol,
                    "company_name": company_name,
                    "url": "https://guba.eastmoney.com/news,002281,1733674904.html",
                }
            ]

        def fetch_comments(self, post_id: str, limit: int = 20, post=None):
            return []

        def provider_status(self):
            return {"status": "partial", "coverage_note": "评论接口不稳定"}

    class FakeDb:
        def community_discussions_replace_or_upsert(self, rows):
            return True

    sync_module = __import__("cl_app.community_sync", fromlist=["get_default_community_providers"])
    original_sync_factory = sync_module.get_default_community_providers
    try:
        sync_module.get_default_community_providers = lambda: [FakeProvider()]
        result = sync_community_discussions_for_stock(
            symbol="002281",
            company_name="光迅科技",
            limit=5,
            db_instance=FakeDb(),
        )
    finally:
        sync_module.get_default_community_providers = original_sync_factory

    assert result["providers"][0]["posts"] == 1
    assert result["providers"][0]["comments"] == 0
    assert result["providers"][0]["status"] == "partial"
