"""Existing real-time connections must lose access when authorization changes."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api import websocket
from app.config import settings
from app.models.map_foundation import OperationalArea, UserAreaScope
from app.models.meeting import Meeting
from app.models.user import User, UserSession
from app.security import authenticate_websocket
from app.services.auth_service import AuthService
from tests.test_auth_security import _bootstrap_admin, _build_client


@pytest.fixture
def connected_app(monkeypatch):
    client, session_factory = _build_client()
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(websocket, "SessionLocal", session_factory)
    monkeypatch.setattr(websocket, "manager", websocket.ConnectionManager())
    monkeypatch.setattr(websocket, "meeting_manager", websocket.MeetingConnectionManager())
    client.app.include_router(websocket.router, prefix="/api")
    assert _bootstrap_admin(client).status_code == 201
    with session_factory() as db:
        area = OperationalArea(code="socket-test", name="实时推送测试辖区", status="active")
        db.add(area)
        db.flush()
        area_id = area.id
        db.add(Meeting(meeting_id="socket-test-meeting", operational_area_id=area_id, status="pending"))
        db.commit()
    yield client, session_factory, area_id
    client.close()


@pytest.mark.parametrize("channel", ["dashboard", "meeting"])
@pytest.mark.parametrize("change", ["revoked", "expired", "disabled", "role_downgraded", "scope_revoked"])
def test_existing_socket_rechecks_auth_and_scope_before_next_message(connected_app, channel, change):
    client, session_factory, area_id = connected_app
    if change == "scope_revoked":
        with session_factory() as db:
            user = db.query(User).one()
            user.role = "analyst"
            db.add(UserAreaScope(user_id=user.id, operational_area_id=area_id, access_level="read"))
            db.commit()
    path = (f"/api/ws/dashboard?operational_area_id={area_id}" if channel == "dashboard"
            else "/api/ws/meeting/socket-test-meeting")
    with client.websocket_connect(path) as socket:
        initial = socket.receive_json()
        assert initial["type"] == ("initial_data" if channel == "dashboard" else "connected")
        if channel == "meeting":
            assert socket.receive_json()["type"] == "meeting_status"
        with session_factory() as db:
            user = db.query(User).one()
            if change == "revoked":
                AuthService.revoke_user_sessions(db, user.id)
            elif change == "expired":
                db.query(UserSession).one().expires_at = AuthService.now() - timedelta(seconds=1)
            elif change == "disabled":
                user.is_active = False
            elif change == "role_downgraded":
                user.role = "viewer"
            else:
                db.query(UserAreaScope).filter(UserAreaScope.operational_area_id == area_id).delete()
            db.commit()
        socket.send_json({"type": "ping" if channel == "dashboard" else "get_status"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == (4403 if change in {"role_downgraded", "scope_revoked"} else 4401)
    assert websocket.manager.active_connections == []
    assert websocket.meeting_manager.get_connection_count("socket-test-meeting") == 0


@pytest.mark.asyncio
async def test_meeting_broadcast_rechecks_each_receiver_and_removes_revoked_connection(connected_app):
    client, session_factory, _ = connected_app

    class Receiver:
        def __init__(self):
            self.state = SimpleNamespace(meeting_id="socket-test-meeting")
            self.cookies = dict(client.cookies)
            self.app = SimpleNamespace(state=SimpleNamespace(auth_session_factory=session_factory))
            self.messages = []
            self.closed = None

        async def accept(self):
            pass

        async def close(self, *, code, reason):
            self.closed = code

        async def send_text(self, message):
            self.messages.append(message)

    receiver = Receiver()
    assert authenticate_websocket(receiver)
    await websocket.meeting_manager.connect(receiver, "socket-test-meeting")
    allowed_receiver = Receiver()
    with session_factory() as db:
        token, _ = AuthService.create_session(db, db.query(User).one(), client_ip=None, user_agent=None)
    allowed_receiver.cookies["aicommander_session"] = token
    assert authenticate_websocket(allowed_receiver)
    await websocket.meeting_manager.connect(allowed_receiver, "socket-test-meeting")
    with session_factory() as db:
        AuthService.revoke_session(db, receiver.state.principal.session_id)
    await websocket.broadcast_meeting_progress("socket-test-meeting", 1, "分析", "running", 25)
    assert receiver.messages == []
    assert receiver.closed == 4401
    assert len(allowed_receiver.messages) == 1
    assert allowed_receiver.closed is None
    assert websocket.meeting_manager.get_connection_count("socket-test-meeting") == 1
