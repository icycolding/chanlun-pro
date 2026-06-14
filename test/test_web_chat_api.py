import io
import json
import sys
from pathlib import Path

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "web" / "chanlun_chart"))

from cl_app.ai_agent import chat_api
from cl_app.ai_agent.hermes_bridge import HermesBridge
from cl_app import news_vector_api as api


class _TestUser(UserMixin):
    def __init__(self, user_id: str = "test-user") -> None:
        self.id = user_id


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat_test.sqlite'}", echo=False)
    chat_api.ChatBase.metadata.create_all(engine)
    chat_api._CHAT_SESSION_FACTORY = sessionmaker(bind=engine)
    monkeypatch.setattr(chat_api, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(HermesBridge, "get_user_hermes_home", staticmethod(lambda tenant_id, user_id: tmp_path / "hermes_runtime" / tenant_id / user_id))

    app = Flask(__name__)
    app.secret_key = "test-secret"
    login_manager = LoginManager()
    login_manager.init_app(app)

    login_manager.user_loader(lambda user_id: _TestUser(user_id))

    app.register_blueprint(chat_api.chat_bp)
    api.register_vector_api_routes(app)

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "test-user"
        session["_fresh"] = True
    yield app, client
    chat_api._CHAT_SESSION_FACTORY = None


def _cleanup_chat_rows():
    with chat_api._get_chat_session_factory()() as session:
        session.query(chat_api.TableByChatMessage).filter(
            chat_api.TableByChatMessage.tenant_id == "default",
            chat_api.TableByChatMessage.user_id == "test-user",
        ).delete()
        session.query(chat_api.TableByChatSession).filter(
            chat_api.TableByChatSession.tenant_id == "default",
            chat_api.TableByChatSession.user_id == "test-user",
        ).delete()
        session.commit()


def test_chat_session_endpoints_persist_messages(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    class _FakeAgent:
        def chat_stream(self, messages):
            assert messages[-1]["content"] == "澳元为什么跌"
            yield json.dumps({"type": "citation", "tool": "search_market_news", "data": [{"title": "澳洲联储偏鸽", "content": "测试新闻"}]}, ensure_ascii=False)
            yield json.dumps({"type": "content", "content": "澳元走弱与利差预期回落有关。"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "get_agent", lambda: _FakeAgent())

    created = client.post("/api/ai/chat/sessions", json={"title": "澳元研究", "context": {"market": "fx", "code": "AUDUSD"}})
    assert created.status_code == 200
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={
            "message": {"type": "user_text", "content": "澳元为什么跌"},
            "context": {"market": "fx", "code": "AUDUSD"},
            "options": {"analysis_type": "chat"},
        },
    )
    assert response.status_code == 200
    stream_text = response.get_data(as_text=True)
    assert "澳元走弱与利差预期回落有关" in stream_text
    assert "[DONE]" in stream_text

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    assert detail.status_code == 200
    payload = detail.get_json()["data"]
    assert payload["session"]["title"] == "澳元研究"
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["structured_payload"]["citations"][0]["tool"] == "search_market_news"

    _cleanup_chat_rows()


def test_chat_attachment_upload_and_context_injection(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client
    captured_messages = []

    class _FakeAgent:
        def chat_stream(self, messages):
            captured_messages.extend(messages)
            yield json.dumps({"type": "content", "content": "已结合附件内容分析。"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "get_agent", lambda: _FakeAgent())

    created = client.post("/api/ai/chat/sessions", json={"title": "附件研究"})
    session_id = created.get_json()["data"]["session"]["id"]

    upload_response = client.post(
        f"/api/ai/chat/sessions/{session_id}/attachments",
        data={"file": (io.BytesIO("澳洲联储纪要显示政策偏鸽。".encode("utf-8")), "rba_note.txt")},
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 200
    attachment = upload_response.get_json()["data"]["attachment"]
    assert attachment["parse_status"] == "parsed"
    assert "澳洲联储纪要" in attachment["parsed_text_preview"]

    list_response = client.get(f"/api/ai/chat/sessions/{session_id}/attachments")
    assert list_response.status_code == 200
    assert len(list_response.get_json()["data"]["attachments"]) == 1

    message_response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "结合附件看澳元"}}
    )
    assert message_response.status_code == 200
    assert "已结合附件内容分析" in message_response.get_data(as_text=True)
    assert any("[会话附件证据]" in item["content"] for item in captured_messages)
    assert any("rba_note.txt" in item["content"] for item in captured_messages)

    _cleanup_chat_rows()


def test_delete_chat_session_removes_messages_and_attachments(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    class _FakeAgent:
        def chat_stream(self, _messages):
            yield json.dumps({"type": "content", "content": "会话内容"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "get_agent", lambda: _FakeAgent())

    created = client.post("/api/ai/chat/sessions", json={"title": "待删除会话", "context": {"market": "fx", "code": "AUDUSD"}})
    session_id = created.get_json()["data"]["session"]["id"]

    upload_response = client.post(
        f"/api/ai/chat/sessions/{session_id}/attachments",
        data={"file": (io.BytesIO("delete me".encode("utf-8")), "delete.txt")},
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 200

    with chat_api._get_chat_session_factory()() as session:
        attachment_row = (
            session.query(chat_api.TableByChatAttachment)
            .filter(chat_api.TableByChatAttachment.session_id == session_id)
            .first()
        )
        assert attachment_row is not None
        attachment_path = Path(attachment_row.storage_path)
        assert attachment_path.exists()

    message_response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "删除前发一条消息"}, "options": {"analysis_type": "chat"}},
    )
    assert message_response.status_code == 200
    message_response.get_data(as_text=True)

    delete_response = client.delete(f"/api/ai/chat/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.get_json()["data"]["id"] == session_id

    detail_response = client.get(f"/api/ai/chat/sessions/{session_id}")
    assert detail_response.status_code == 404

    with chat_api._get_chat_session_factory()() as session:
        assert (
            session.query(chat_api.TableByChatSession)
            .filter(chat_api.TableByChatSession.id == session_id)
            .count()
            == 0
        )
        assert (
            session.query(chat_api.TableByChatMessage)
            .filter(chat_api.TableByChatMessage.session_id == session_id)
            .count()
            == 0
        )
        assert (
            session.query(chat_api.TableByChatAttachment)
            .filter(chat_api.TableByChatAttachment.session_id == session_id)
            .count()
            == 0
        )

    assert not attachment_path.exists()


def test_service_theme_simulation_requires_token_when_configured(monkeypatch, app_client):
    _, client = app_client
    monkeypatch.setenv("CHANLUN_SERVICE_TOKEN", "svc-token")

    unauthorized = client.post("/api/service/theme_simulation", json={"market": "fx", "code": "AUDUSD", "theme_text": "澳元"})
    assert unauthorized.status_code == 401
    assert unauthorized.get_json()["error"]["code"] == "UNAUTHORIZED"

    monkeypatch.setattr(
        api,
        "_generate_theme_simulation_payload",
        lambda payload: {
            "summary": f"主题 {payload['theme_label']}",
            "report": {"title": "测试报告"},
            "research_agent": {"mode": "test"},
            "comprehensive_reasoning": {"summary": "测试综合推演"},
        },
    )

    authorized = client.post(
        "/api/service/theme_simulation",
        json={"market": "fx", "code": "AUDUSD", "theme_text": "澳元"},
        headers={
            "Authorization": "Bearer svc-token",
            "X-Session-Id": "sess_test",
            "X-Request-Source": "pytest",
        },
    )
    assert authorized.status_code == 200
    payload = authorized.get_json()
    assert payload["success"] is True
    assert payload["session_id"] == "sess_test"
    assert payload["data"]["summary"] == "主题 澳元"

    monkeypatch.delenv("CHANLUN_SERVICE_TOKEN", raising=False)


def test_service_market_data_view_maps_market_and_code(monkeypatch, app_client):
    _, client = app_client

    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=8: {
            "market": current_market,
            "code": current_code,
            "limit": limit,
        },
    )

    response = client.post(
        "/api/service/market_data/view",
        json={"market": "fx", "code": "AUDUSD", "limit": 6},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["market"] == "fx"
    assert payload["data"]["code"] == "AUDUSD"
    assert payload["data"]["limit"] == 6


def test_chat_message_can_route_to_theme_simulation(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "主题推演", "context": {"market": "fx", "code": "AUDUSD", "theme": "aud_rba"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]
    captured = {}

    def _fake_theme_simulation(payload):
        captured.update(payload)
        return {
            "summary": "澳元主题推演完成",
            "report": {"trade_bias": "谨慎看空"},
            "research_agent": {"key_points": ["利差回落", "风险偏好偏弱"]},
            "comprehensive_reasoning": {
                "router": {"route_label": "央行路径"},
                "arbiter_execution": {"pricing_stage": "部分定价", "execution_bias": "等待反弹后偏空"},
            },
        }

    monkeypatch.setattr(api, "_generate_theme_simulation_payload", _fake_theme_simulation)

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={
            "message": {"type": "user_text", "content": "分析澳元"},
            "context": {"market": "fx", "code": "AUDUSD", "theme": "aud_rba"},
            "options": {"analysis_type": "theme_simulation"},
        },
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "analysis_result" in body
    assert "澳元主题推演完成" in body
    assert captured["current_market"] == "fx"
    assert captured["current_code"] == "AUDUSD"
    assert captured["theme_label"] == "aud_rba"

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    messages = detail.get_json()["data"]["messages"]
    assert messages[-1]["message_type"] == "analysis_summary"
    assert messages[-1]["structured_payload"]["analysis_type"] == "theme_simulation"

    _cleanup_chat_rows()


def test_chat_mode_uses_primary_agent_bridge(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    created = client.post("/api/ai/chat/sessions", json={"title": "Hermes 聊天"})
    session_id = created.get_json()["data"]["session"]["id"]

    class _FakeHermes:
        def stream_chat(self, message, _history, session_id, tenant_id, user_id):
            assert message == "Hermes 你好"
            assert session_id
            assert tenant_id == "default"
            assert user_id == "test-user"
            yield json.dumps({"type": "content", "content": "这里是 Hermes 回复。"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "get_agent", lambda: _FakeHermes())

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "Hermes 你好"}},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "这里是 Hermes 回复" in body

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    messages = detail.get_json()["data"]["messages"]
    assert messages[-1]["content"] == "这里是 Hermes 回复。"

    _cleanup_chat_rows()


def test_hermes_bridge_can_inject_chanlun_tool_result(monkeypatch, tmp_path):
    from cl_app.ai_agent.hermes_bridge import HermesBridge

    bridge = HermesBridge()
    monkeypatch.setattr(
        HermesBridge,
        "get_user_hermes_home",
        staticmethod(lambda tenant_id, user_id: tmp_path / "hermes_runtime" / tenant_id / user_id),
    )
    monkeypatch.setattr(bridge, "is_ready", lambda: True)
    monkeypatch.setattr(
        bridge,
        "_invoke_chanlun_tool",
        lambda action, payload: {
            "action": action,
            "data": {"summary": "澳元主题推演完成"},
        },
    )

    captured = {}

    def fake_popen(_cmd, **_kwargs):
        class _Proc:
            returncode = 0

            def communicate(self, input_text, **_kwargs):
                captured["payload"] = json.loads(input_text)
                return (
                    json.dumps({"type": "content", "content": "Hermes 已综合工具结果。"}, ensure_ascii=False) + "\n"
                    + json.dumps({"type": "done", "final_response": "Hermes 已综合工具结果。"}, ensure_ascii=False),
                    "",
                )

        return _Proc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    chunks = list(
        bridge.stream_chat(
            message="分析澳元",
            history=[],
            session_id="sess_demo",
            tenant_id="default",
            user_id="u1",
            context={"market": "fx", "code": "AUDUSD", "theme": "aud_rba"},
        )
    )
    assert any("Hermes 已综合工具结果" in chunk for chunk in chunks)
    assert captured["payload"]["tool_result"]["action"] == "theme_simulation"
    assert captured["payload"]["context"]["code"] == "AUDUSD"


def test_hermes_bridge_can_include_selected_user_skill(monkeypatch, tmp_path):
    from cl_app.ai_agent.hermes_bridge import HermesBridge

    hermes_home = tmp_path / "hermes_runtime" / "default" / "u1"
    skill_dir = hermes_home / "skills" / "aud-research"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: AUD Research\ndescription: 澳元研究技能\n---\n\n# AUD Research\n\n## Instructions\n先看联储、商品和中国数据。\n",
        encoding="utf-8",
    )

    bridge = HermesBridge()
    monkeypatch.setattr(HermesBridge, "get_user_hermes_home", staticmethod(lambda tenant_id, user_id: hermes_home))
    monkeypatch.setattr(bridge, "_invoke_chanlun_tool", lambda action, payload: {"action": action, "data": {"summary": "ok"}})

    captured = {}

    def fake_popen(_cmd, **_kwargs):
        class _Proc:
            returncode = 0

            def communicate(self, input_text, **_kw):
                captured["payload"] = json.loads(input_text)
                return (
                    json.dumps({"type": "content", "content": "ok"}, ensure_ascii=False) + "\n"
                    + json.dumps({"type": "done", "final_response": "ok"}, ensure_ascii=False),
                    "",
                )

        return _Proc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    list(
        bridge.stream_chat(
            message="请用我的技能分析澳元",
            history=[],
            session_id="sess_1",
            tenant_id="default",
            user_id="u1",
            context={"market": "fx", "code": "AUDUSD", "skill_name": "aud-research"},
        )
    )
    assert captured["payload"]["selected_skills"][0]["name"] == "aud-research"
    assert "澳元研究技能" in captured["payload"]["selected_skills"][0]["content"]


def test_hermes_bridge_can_auto_match_user_skill(monkeypatch, tmp_path):
    from cl_app.ai_agent.hermes_bridge import HermesBridge

    hermes_home = tmp_path / "hermes_runtime" / "default" / "u1"
    skill_dir = hermes_home / "skills" / "gold-playbook"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Gold Playbook\ndescription: 黄金研究技能\n---\n\n# Gold Playbook\n\n## Instructions\n先看美债和美元。\n",
        encoding="utf-8",
    )

    bridge = HermesBridge()
    monkeypatch.setattr(HermesBridge, "get_user_hermes_home", staticmethod(lambda tenant_id, user_id: hermes_home))

    selected = bridge._select_relevant_skills(
        message="请用 Gold Playbook 看下黄金",
        skills=bridge._load_enabled_skills("default", "u1"),
        context={},
    )
    assert selected
    assert selected[0]["name"] == "gold-playbook"


def test_hermes_default_finance_skills_bootstrap(app_client):
    _, client = app_client

    response = client.get("/api/ai/hermes/skills")
    assert response.status_code == 200
    skills = response.get_json()["data"]["skills"]
    skill_names = {item["name"] for item in skills}

    assert "macro-news-scout" in skill_names
    assert "fx-price-action" in skill_names
    assert "commodities-crossasset" in skill_names


def test_hermes_bridge_can_parse_noisy_tool_stdout():
    from cl_app.ai_agent.hermes_bridge import HermesBridge

    payload = HermesBridge._load_json_from_output(
        "_code FE.AUDUSD\nmarket: 10\n"
        + json.dumps({"action": "market_data_view", "data": {"summary": "ok"}}, ensure_ascii=False)
    )
    assert payload["action"] == "market_data_view"
    assert payload["data"]["summary"] == "ok"


def test_hermes_bridge_invoke_chanlun_tool_tolerates_debug_stdout(monkeypatch):
    from cl_app.ai_agent.hermes_bridge import HermesBridge

    bridge = HermesBridge()

    class _FakeCompletedProcess:
        returncode = 0
        stdout = (
            "_code FE.AUDUSD\n"
            "market: 10\n"
            + json.dumps({"action": "market_data_view", "data": {"summary": "快照完成"}}, ensure_ascii=False)
        )
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _FakeCompletedProcess())

    payload = bridge._invoke_chanlun_tool(
        "market_data_view",
        {"current_market": "fx", "current_code": "AUDUSD"},
    )
    assert payload["action"] == "market_data_view"
    assert payload["data"]["summary"] == "快照完成"


def test_hermes_memory_management_endpoints(app_client):
    _, client = app_client

    list_resp = client.get("/api/ai/hermes/memories")
    assert list_resp.status_code == 200
    assert list_resp.get_json()["data"]["memory"] == []

    add_resp = client.post(
        "/api/ai/hermes/memories",
        json={"target": "memory", "action": "add", "content": "我偏好先看外汇和黄金"},
    )
    assert add_resp.status_code == 200
    assert "我偏好先看外汇和黄金" in add_resp.get_json()["data"]["entries"]

    remove_resp = client.post(
        "/api/ai/hermes/memories",
        json={"target": "memory", "action": "remove", "old_text": "外汇和黄金"},
    )
    assert remove_resp.status_code == 200
    assert remove_resp.get_json()["data"]["entries"] == []


def test_hermes_skill_management_endpoints(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    class _FakeHermes:
        def stream_chat(self, *_args, **_kwargs):
            yield json.dumps({"type": "content", "content": "测试助手回复。"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "get_agent", lambda: _FakeHermes())

    created = client.post("/api/ai/chat/sessions", json={"title": "技能来源会话"})
    session_id = created.get_json()["data"]["session"]["id"]
    client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "这是一个用于澳元研究的会话"}} ,
    ).get_data(as_text=True)

    create_resp = client.post(
        "/api/ai/hermes/skills",
        json={
            "name": "AUD Research",
            "description": "澳元研究 skill",
            "instructions": "先看联储、商品和中国数据，再给结论",
            "session_id": session_id,
        },
    )
    assert create_resp.status_code == 200
    skill = create_resp.get_json()["data"]["skill"]
    assert skill["name"] == "aud-research"
    assert skill["enabled"] is True

    list_resp = client.get("/api/ai/hermes/skills")
    skills = list_resp.get_json()["data"]["skills"]
    assert any(item["name"] == "aud-research" for item in skills)

    disable_resp = client.post("/api/ai/hermes/skills/aud-research/status", json={"enabled": False})
    assert disable_resp.status_code == 200
    assert disable_resp.get_json()["data"]["skill"]["enabled"] is False

    delete_resp = client.delete("/api/ai/hermes/skills/aud-research")
    assert delete_resp.status_code == 200


def test_chat_message_can_create_skill(app_client):
    _cleanup_chat_rows()
    _, client = app_client

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "创建技能", "context": {"theme": "AUD Workflow"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={
            "message": {"type": "user_text", "content": "先看联储，再看商品和中国数据，最后给交易偏向"},
            "context": {"theme": "AUD Workflow"},
            "options": {"analysis_type": "skill_create"},
        },
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "已创建技能" in body

    skills_resp = client.get("/api/ai/hermes/skills")
    skills = skills_resp.get_json()["data"]["skills"]
    assert any(item["title"] == "AUD Workflow" for item in skills)


def test_chat_analysis_response_includes_chart_metadata(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "图形测试", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=8: {
            "summary": "市场快照完成",
            "market": current_market,
            "code": current_code,
        },
    )

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={
            "message": {"type": "user_text", "content": "看看当前价格图"},
            "context": {"market": "fx", "code": "AUDUSD", "frequency": "1h"},
            "options": {"analysis_type": "market_data_view"},
        },
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '"type": "chart"' in body

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    messages = detail.get_json()["data"]["messages"]
    charts = messages[-1]["structured_payload"]["charts"]
    assert charts[0]["homepage_url"].startswith("/?market=fx&code=AUDUSD&embedded=1")
    assert charts[0]["db_chart_url"].startswith("/chart?market=fx&code=AUDUSD&frequency=1h")


def test_chat_message_infers_symbol_and_persists_session_context(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    class _FakeAgent:
        def chat_stream(self, _messages):
            yield json.dumps({"type": "content", "content": "已展示 AUDUSD 图表。"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "get_agent", lambda: _FakeAgent())

    created = client.post("/api/ai/chat/sessions", json={"title": "自动识别"})
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "audusd 价格图"}},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '"type": "chart"' in body

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    payload = detail.get_json()["data"]
    assert payload["session"]["context_market"] == "fx"
    assert payload["session"]["context_code"] == "AUDUSD"
    assert payload["session"]["context"]["market"] == "fx"
    assert payload["session"]["context"]["code"] == "AUDUSD"
    assert payload["messages"][-1]["structured_payload"]["charts"][0]["homepage_url"].startswith(
        "/?market=fx&code=AUDUSD&embedded=1"
    )


def test_chat_message_reuses_persisted_session_context_when_request_context_missing(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client
    captured_contexts = []

    def fake_stream(_agent, _messages, _session_id, _identity, context):
        captured_contexts.append(dict(context))
        yield json.dumps({"type": "content", "content": "继续分析已保存的标的。"}, ensure_ascii=False)

    monkeypatch.setattr(chat_api, "_stream_agent_response", fake_stream)
    monkeypatch.setattr(chat_api, "get_agent", lambda: object())

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "上下文复用", "context": {"market": "fx", "code": "AUDUSD", "frequency": "1h"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={
            "message": {"type": "user_text", "content": "继续分析这组标的"},
            "options": {"analysis_type": "chat"},
        },
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert captured_contexts[-1]["market"] == "fx"
    assert captured_contexts[-1]["code"] == "AUDUSD"
    assert captured_contexts[-1]["frequency"] == "1h"
    assert "继续分析已保存的标的" in body


def test_chat_message_auto_detects_market_data_view_without_selector(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=8: {
            "summary": "自动识别为市场快照",
            "market": current_market,
            "code": current_code,
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "自动市场快照", "context": {"market": "fx", "code": "AUDUSD", "frequency": "1h"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "看看当前价格图"}},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "自动识别为市场快照" in body

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["message_type"] == "analysis_summary"
    assert message["structured_payload"]["analysis_type"] == "market_data_view"


def test_chat_message_new_symbol_overrides_persisted_context(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client
    captured = {}

    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=8: captured.update(
            {"market": current_market, "code": current_code, "limit": limit}
        ) or {
            "summary": f"{current_code} 市场快照",
            "market": current_market,
            "code": current_code,
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "切换标的", "context": {"market": "fx", "code": "AUDUSD", "frequency": "1h"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "usdcny 价格图"}},
    )
    assert response.status_code == 200
    assert "USDCNY 市场快照" in response.get_data(as_text=True)
    assert captured["market"] == "fx"
    assert captured["code"] == "USDCNY"

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    payload = detail.get_json()["data"]
    assert payload["session"]["context_market"] == "fx"
    assert payload["session"]["context_code"] == "USDCNY"
    assert payload["session"]["context"]["code"] == "USDCNY"
    charts = payload["messages"][-1]["structured_payload"]["charts"]
    assert charts[0]["homepage_url"].startswith("/?market=fx&code=USDCNY&embedded=1")


def test_chat_message_auto_detects_theme_simulation_without_selector(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        api,
        "_generate_theme_simulation_payload",
        lambda payload: {
            "summary": "自动识别为主题推演",
            "report": {"direction": "bearish"},
            "research_agent": {"key_points": ["美元偏强", "风险偏好回落"]},
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "自动主题推演", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "为什么 AUDUSD 走弱"}},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "自动识别为主题推演" in body

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["message_type"] == "analysis_summary"
    assert message["structured_payload"]["analysis_type"] == "theme_simulation"


def test_chat_message_auto_detects_research_report_intent_without_selector(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        chat_api,
        "_query_existing_market_reports",
        lambda text, context, limit=5: {
            "summary": "已从数据库找到 2 份相关研究报告",
            "report_items": [
                {"summary_id": 11, "title": "EURUSD 周度研究", "summary_type": "market_analysis", "market": "fx", "code": "EURUSD", "created_at": "2026-04-01T08:00:00", "preview": "周度逻辑回顾"},
                {"summary_id": 12, "title": "EURUSD 历史分析", "summary_type": "historical_analysis", "market": "fx", "code": "EURUSD", "created_at": "2026-03-30T08:00:00", "preview": "历史阶段表现"},
            ],
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "研究报告", "context": {"market": "fx", "code": "EURUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "给我一份 EURUSD 研究报告"}},
    )
    assert response.status_code == 200
    assert "已从数据库找到 2 份相关研究报告" in response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["structured_payload"]["analysis_type"] == "db_report_lookup"
    assert len(message["structured_payload"]["result"]["report_items"]) == 2


def test_chat_message_auto_detects_latest_news_from_db_without_selector(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        chat_api,
        "_query_latest_db_news",
        lambda text, context, limit=5: {
            "summary": "已从数据库找到 2 条最新相关重要新闻",
            "news_items": [
                {"metadata": {"title": "澳洲联储措辞转鸽", "source": "Reuters", "published_at": "2026-04-10T08:00:00"}, "document": "央行措辞偏鸽，澳元承压"},
                {"metadata": {"title": "美国收益率回落", "source": "Bloomberg", "published_at": "2026-04-10T06:00:00"}, "document": "美元走弱带动外汇波动"},
            ],
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "数据库新闻", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "AUDUSD 最新新闻"}},
    )
    assert response.status_code == 200
    assert "已从数据库找到 2 条最新相关重要新闻" in response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["structured_payload"]["analysis_type"] == "db_latest_news"
    assert len(message["structured_payload"]["result"]["news_items"]) == 2


def test_theme_simulation_includes_existing_db_reports(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        api,
        "_generate_theme_simulation_payload",
        lambda payload: {
            "summary": "已生成主题分析",
            "report": {"trade_bias": "偏空"},
            "research_agent": {"key_points": ["美元偏强"]},
        },
    )
    monkeypatch.setattr(
        chat_api,
        "_query_existing_market_reports",
        lambda text, context, limit=3: {
            "summary": "已从数据库找到 1 份相关研究报告",
            "report_items": [
                {"summary_id": 88, "title": "AUDUSD 已有研究", "summary_type": "market_analysis", "market": "fx", "code": "AUDUSD", "created_at": "2026-04-01T08:00:00", "preview": "已有数据库报告"},
            ],
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "主题分析包含报告", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "分析 AUDUSD 为什么走弱"}},
    )
    assert response.status_code == 200
    assert "市场观点已整理好" in response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["structured_payload"]["analysis_type"] == "theme_simulation"
    assert len(message["structured_payload"]["result"]["existing_reports"]) == 1


def test_chat_message_auto_detects_trade_intent_as_market_view_without_selector(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=8: {
            "summary": "已准备交易前快照",
            "market": current_market,
            "code": current_code,
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "交易意图", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "点击交易 AUDUSD"}},
    )
    assert response.status_code == 200
    assert "已准备交易前快照" in response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["structured_payload"]["analysis_type"] == "market_data_view"


def test_chat_message_auto_detects_skill_create_without_selector(app_client):
    _cleanup_chat_rows()
    _, client = app_client

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "自动创建技能", "context": {"theme": "AUD Workflow"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "请帮我创建技能：先看联储，再看商品和中国数据，最后给交易偏向"}},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "已创建技能" in body

    skills_resp = client.get("/api/ai/hermes/skills")
    skills = skills_resp.get_json()["data"]["skills"]
    assert any(item["title"] == "AUD Workflow" for item in skills)


def test_chat_message_auto_detects_drawdown_analysis_and_returns_skill_suggestion(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        chat_api,
        "_query_drawdown_analysis",
        lambda text, context: {
            "summary": "AUDUSD 在最近30天内最大回撤 8.2%",
            "max_drawdown_pct": 8.2,
            "period_return_pct": 3.4,
            "drawdown": {
                "peak_dt": "2026-03-01T08:00:00",
                "peak_price": 0.6621,
                "trough_dt": "2026-03-17T10:00:00",
                "trough_price": 0.6078,
                "recovery_dt": "",
                "recovery_price": None,
                "recovery_hours": None,
                "latest_dt": "2026-04-10T08:00:00",
                "latest_price": 0.6312,
            },
            "news_items": [],
            "report_items": [],
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "回撤分析", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "帮我跑一下 AUDUSD 近30天最大回撤"}},
    )
    assert response.status_code == 200
    assert "AUDUSD 在最近30天内最大回撤 8.2%" in response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["structured_payload"]["analysis_type"] == "drawdown_analysis"
    assert message["structured_payload"]["skill_suggestion"]["title"] == "AUDUSD 回撤复盘助手"


def test_chat_message_auto_detects_event_chart_review_without_selector(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        chat_api,
        "_query_event_chart_review",
        lambda text, context, identity, session_id: {
            "summary": "已整理最近48小时内 3 个关键事件窗口，并补充 2 个相似历史样本",
            "summary_id": 123,
            "lookback_label": "48小时",
            "event_frequency": "15m",
            "events": [
                {
                    "trigger_dt": "2026-04-10T08:00:00",
                    "storyline": "利率预期重估",
                    "direction": "up",
                    "cause_summary": "收益率回落与风险偏好改善共振",
                    "top_news_titles": ["美债收益率回落"],
                }
            ],
            "similar_events": [{"storyline": "历史利率下修"}],
            "event_trade_templates": [{"title": "事件后回踩跟随", "summary": "等待回踩后顺势跟随"}],
            "report_items": [],
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "历史事件图", "context": {"market": "fx", "code": "XAUUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "看最近几次黄金历史事件图"}},
    )
    assert response.status_code == 200
    assert "已整理最近48小时内 3 个关键事件窗口" in response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    assert message["structured_payload"]["analysis_type"] == "event_chart_review"
    assert message["structured_payload"]["result"]["summary_id"] == 123
    assert message["structured_payload"]["skill_suggestion"]["title"] == "XAUUSD 历史事件图助手"


def test_chat_message_includes_trading_brief_for_market_view(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        api,
        "_build_market_data_view_payload",
        lambda current_market, current_code, limit=8: {
            "summary": "已准备 AUDUSD 价格图与盘面快照",
            "market": current_market,
            "code": current_code,
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "交易摘要", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    response = client.post(
        f"/api/ai/chat/sessions/{session_id}/messages",
        json={"message": {"type": "user_text", "content": "看看 AUDUSD 价格图"}},
    )
    assert response.status_code == 200
    response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    trading_brief = message["structured_payload"]["trading_brief"]
    assert "AUDUSD" in trading_brief["conclusion"]
    assert "已准备 AUDUSD 价格图与盘面快照" in trading_brief["evidence"]
    assert trading_brief["risk"]
    assert trading_brief["action"]


def test_chat_message_repeated_drawdown_adds_repeat_skill_reason(monkeypatch, app_client):
    _cleanup_chat_rows()
    _, client = app_client

    monkeypatch.setattr(
        chat_api,
        "_query_drawdown_analysis",
        lambda text, context: {
            "summary": "AUDUSD 在最近30天内最大回撤 8.2%",
            "max_drawdown_pct": 8.2,
            "period_return_pct": 3.4,
            "drawdown": {
                "peak_dt": "2026-03-01T08:00:00",
                "peak_price": 0.6621,
                "trough_dt": "2026-03-17T10:00:00",
                "trough_price": 0.6078,
                "recovery_dt": "",
                "recovery_price": None,
                "recovery_hours": None,
                "latest_dt": "2026-04-10T08:00:00",
                "latest_price": 0.6312,
            },
            "news_items": [],
            "report_items": [],
        },
    )

    created = client.post(
        "/api/ai/chat/sessions",
        json={"title": "重复回撤", "context": {"market": "fx", "code": "AUDUSD"}},
    )
    session_id = created.get_json()["data"]["session"]["id"]

    for _ in range(3):
        response = client.post(
            f"/api/ai/chat/sessions/{session_id}/messages",
            json={"message": {"type": "user_text", "content": "帮我跑一下 AUDUSD 近30天最大回撤"}},
        )
        assert response.status_code == 200
        response.get_data(as_text=True)

    detail = client.get(f"/api/ai/chat/sessions/{session_id}")
    message = detail.get_json()["data"]["messages"][-1]
    suggestion = message["structured_payload"]["skill_suggestion"]
    assert suggestion["repeat_count"] >= 3
    assert "最近已经多次执行" in suggestion["reason"]
