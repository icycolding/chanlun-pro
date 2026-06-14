import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart" / "cl_app"))

import news_vector_db as nvd


class FakeCollection:
    def __init__(self):
        self.records = []
        self.last_query = None
        self.name = "news_vectors"

    def count(self):
        return max(len(self.records), 1)

    def get_or_create_collection(self, **kwargs):
        return self

    def get(self, where=None):
        return {"ids": []}

    def add(self, ids, documents, metadatas):
        self.records.extend(
            zip(ids, documents, metadatas)
        )

    def query(self, query_texts, n_results, where=None, where_document=None):
        self.last_query = {
            "query_texts": query_texts,
            "n_results": n_results,
            "where": where,
            "where_document": where_document,
        }
        return {
            "ids": [["news_1_chunk_1"]],
            "documents": [["标题: 欧元美元"]],
            "metadatas": [[{
                "news_id": "news_1",
                "title": "欧元美元",
                "source": "test",
                "published_at": "2026-04-04T10:00:00",
                "published_at_ts": 1775296800.0,
                "importance_score": 0.8,
                "market_relevance": 1.0,
            }]],
            "distances": [[0.1]],
        }


class FakePersistentClient:
    def __init__(self, path):
        self.path = path
        self.collection = FakeCollection()

    def get_or_create_collection(self, **kwargs):
        return self.collection


class FakeChromaModule:
    PersistentClient = FakePersistentClient
    Client = FakePersistentClient


def test_vector_db_initializes_on_first_use_and_fallback_split(monkeypatch, tmp_path):
    monkeypatch.setattr(nvd, "chromadb", FakeChromaModule())
    monkeypatch.setattr(nvd, "RecursiveCharacterTextSplitter", None)

    vector_db = nvd.NewsVectorDB(db_path=str(tmp_path / "chroma"))

    assert vector_db.collection is None
    assert vector_db.is_ready() is True

    ok = vector_db.add_news(
        {
            "news_id": "news_1",
            "title": "欧元美元波动",
            "body": "这是一个较长的新闻正文 " * 50,
            "source": "jin10",
            "published_at": "2026-04-04T10:00:00",
        }
    )

    assert ok is True
    assert len(vector_db.collection.records) >= 1
    metadata = vector_db.collection.records[0][2]
    assert "direct_assets" in metadata
    assert "driver_assets" in metadata


def test_vector_db_constructor_is_lazy(monkeypatch, tmp_path):
    calls = {"db": 0, "model": 0}

    def fake_init_database(self):
        calls["db"] += 1
        self.collection = SimpleNamespace(count=lambda: 0)

    def fake_init_embedding_model(self):
        calls["model"] += 1
        self.embedding_model = object()

    monkeypatch.setattr(nvd.NewsVectorDB, "_init_database", fake_init_database)
    monkeypatch.setattr(nvd.NewsVectorDB, "_init_embedding_model", fake_init_embedding_model)

    vector_db = nvd.NewsVectorDB(db_path=str(tmp_path / "chroma"))

    assert calls == {"db": 0, "model": 0}
    assert vector_db.collection is None

    assert vector_db.ensure_initialized() is True
    assert calls == {"db": 1, "model": 1}


def test_semantic_search_keeps_keyword_filters(monkeypatch, tmp_path):
    monkeypatch.setattr(nvd, "chromadb", FakeChromaModule())
    monkeypatch.setattr(nvd, "RecursiveCharacterTextSplitter", None)

    vector_db = nvd.NewsVectorDB(db_path=str(tmp_path / "chroma"))

    recorded = {}

    def fake_build_hybrid_filter(keywords, start_date, end_date, filters):
        recorded["keywords"] = keywords
        return {"published_at_ts": {"$gte": 1}}, {"$contains": "EURUSD"}

    monkeypatch.setattr(vector_db, "_build_hybrid_filter", fake_build_hybrid_filter)

    results = vector_db.semantic_search(
        query="EURUSD",
        n_results=5,
        keywords=["EURUSD", "欧元"],
        start_date="2026-04-01T00:00:00",
        end_date="2026-04-05T00:00:00",
    )

    assert recorded["keywords"] == ["EURUSD", "欧元"]
    assert vector_db.collection.last_query["query_texts"] == ["EURUSD"]
    assert len(results) == 1


def test_vector_db_add_news_extracts_asset_links(monkeypatch, tmp_path):
    monkeypatch.setattr(nvd, "chromadb", FakeChromaModule())
    monkeypatch.setattr(nvd, "RecursiveCharacterTextSplitter", None)

    vector_db = nvd.NewsVectorDB(db_path=str(tmp_path / "chroma"))
    ok = vector_db.add_news(
        {
            "news_id": "news_usdcny",
            "title": "美元兑离岸人民币上涨，市场关注中国人民银行中间价",
            "body": "USDCNH 走强，交易员关注 PBOC 和美联储政策路径。",
            "source": "jin10",
            "published_at": "2026-04-04T10:00:00",
        }
    )

    assert ok is True
    metadata = vector_db.collection.records[0][2]
    assert "USDCNY" in metadata["direct_assets"]
    assert "USDCNY" in metadata["driver_assets"] or "CNY" in metadata["driver_assets"]
