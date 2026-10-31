"""HTTP 路由與 WebSocket 入口（SPEC B7）。邏輯都在 room.py，這裡只負責收送。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from server import auth, config, media, protocol
from server.db import Database, is_healthy, restore_latest_backup
from server.errors import ErrorCode, GameError
from server.hub import Connection, Session
from server.room import RoomService

log = logging.getLogger("bmt")

_STATUS = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.BANNED: 403,
    ErrorCode.NO_ROOM: 404,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.LOCKED: 423,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.STORAGE_FULL: 507,
}
_ASSET_FOLDERS = ("bg", "ui", "roles", "audio")


def build_default_service() -> RoomService:
    """正式啟動：檢查管理員設定（E7）與資料庫（E5）。"""
    store = auth.AdminStore()
    store.load()
    if config.DB_PATH.exists() and not is_healthy(config.DB_PATH):
        log.error("資料庫損毀，嘗試從最新備份還原")
        if not restore_latest_backup(config.DB_PATH, config.BACKUP_DIR):
            config.DB_PATH.rename(config.DB_PATH.with_suffix(".broken"))
    return RoomService(Database(), store)


def create_app(service: RoomService | None = None) -> FastAPI:
    """建立 FastAPI app。測試可注入 service（假時鐘、暫存資料夾）。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = service or build_default_service()
        app.state.service = svc
        await svc.start()
        try:
            yield
        finally:
            await svc.stop()

    app = FastAPI(title="血月酒館", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.ALLOWED_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=600,  # CODING_RULES N20
    )
    _install_error_handlers(app)
    _install_no_store(app)
    _install_routes(app)
    _install_socket(app)
    if config.WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
    return app


def _service(request: Request) -> RoomService:
    service: RoomService = request.app.state.service
    return service


def _ip(request: Request) -> str:
    # 經 Tunnel 時真實 IP 在 CF-Connecting-IP；只用於寬鬆上限，不用來判斷身分（N15）
    forwarded = request.headers.get("cf-connecting-ip")
    return forwarded or (request.client.host if request.client else "unknown")


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:] if header.lower().startswith("bearer ") else None


def _require_admin(request: Request) -> str:
    token = _bearer(request)
    service = _service(request)
    if token is None or auth.token_hash(token) not in service.admin_tokens:
        raise GameError(ErrorCode.UNAUTHORIZED)
    return token


def _require_session(request: Request) -> Session:
    token = _bearer(request)
    session = _service(request).session_for(token) if token else None
    if session is None:
        raise GameError(ErrorCode.UNAUTHORIZED)
    return session


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GameError)
    async def on_game_error(request: Request, err: GameError) -> JSONResponse:
        status = _STATUS.get(err.code, 409)
        return JSONResponse({"error": err.code.value, "detail": str(err)}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def on_invalid(request: Request, err: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": ErrorCode.BAD_REQUEST.value}, status_code=400)


def _install_no_store(app: FastAPI) -> None:
    @app.middleware("http")
    async def no_store(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        path = request.url.path
        # CODING_RULES N19：API 不得被快取；簽章媒體除外，本來就有短效網址
        if path.startswith("/api") and not path.startswith(("/api/media/", "/api/asset/")):
            response.headers["Cache-Control"] = "no-store"
        return response


def _install_routes(app: FastAPI) -> None:
    _install_public_routes(app)
    _install_admin_routes(app)
    _install_player_routes(app)
    _install_media_routes(app)


def _install_public_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        service = _service(request)
        room = service.room
        return {
            "ok": True,
            "version": config.VERSION,
            "protocol": config.PROTOCOL_VERSION,
            "room": (
                {"state": room.state, "name": room.name, "mode": room.mode.value} if room else None
            ),
        }


def _install_admin_routes(app: FastAPI) -> None:
    @app.post("/api/admin/login")
    async def admin_login(request: Request, body: protocol.AdminLogin) -> dict[str, Any]:
        service = _service(request)
        ip = _ip(request)
        now = service.now
        service.lockouts.check(body.device_id, body.username, ip, now)
        ok = await service.in_thread(lambda: service.admin.verify(body.username, body.password))
        if not ok:
            service.lockouts.fail(body.device_id, body.username, ip, now)
            raise GameError(ErrorCode.WRONG_PASSWORD)
        service.lockouts.success(body.device_id, body.username)
        token = auth.new_token()

        def remember() -> None:
            digest = auth.token_hash(token)
            service.admin_tokens.add(digest)
            service.sessions[digest] = Session(digest, None, True, body.device_id)

        await service.submit(remember)
        return {"token": token}

    @app.get("/api/admin/room")
    async def admin_room(request: Request) -> dict[str, Any]:
        _require_admin(request)
        service = _service(request)
        room = service.require_room()
        return {
            **(service.room_info() or {}),
            "password": room.password,
            "roster": service.roster_rows(),
        }

    @app.post("/api/admin/room")
    async def open_room(request: Request, body: protocol.OpenRoom) -> dict[str, Any]:
        _require_admin(request)
        service = _service(request)
        room = await service.submit(lambda: service.open_room(body))
        return {**(service.room_info() or {}), "password": room.password}

    @app.delete("/api/admin/room")
    async def close_room(request: Request) -> dict[str, bool]:
        _require_admin(request)
        service = _service(request)
        await service.submit(service.close_room)
        return {"ok": True}

    @app.post("/api/admin/room/reopen")
    async def reopen(request: Request) -> dict[str, Any]:
        _require_admin(request)
        service = _service(request)

        def run() -> dict[str, Any]:
            old = service.require_room()
            body = protocol.OpenRoom(mode=old.mode, name=old.name, settings=old.settings)
            service.close_room()
            room = service.open_room(body)
            return {**(service.room_info() or {}), "password": room.password}

        return await service.submit(run)

    @app.post("/api/admin/password")
    async def change_password(request: Request, body: protocol.ChangePassword) -> dict[str, bool]:
        _require_admin(request)
        service = _service(request)
        username = service.admin.load()["username"]
        ok = await service.in_thread(lambda: service.admin.verify(username, body.old_password))
        if not ok:
            raise GameError(ErrorCode.WRONG_PASSWORD)
        await service.in_thread(lambda: service.admin.save(username, body.new_password))
        return {"ok": True}


def _install_player_routes(app: FastAPI) -> None:
    @app.post("/api/join")
    async def join(request: Request, body: protocol.Join) -> dict[str, Any]:
        service = _service(request)
        name = protocol.validate_name(body.name)
        ip = _ip(request)
        await service.submit(lambda: service.precheck_join(body, name, ip))
        pin_hash = await service.in_thread(lambda: auth.hash_secret(body.pin))
        token = _bearer(request)
        admin_hash = auth.token_hash(token) if token else None
        return await service.submit(lambda: service.finish_join(body, name, pin_hash, admin_hash))

    @app.post("/api/rejoin")
    async def rejoin(request: Request, body: protocol.Rejoin) -> dict[str, Any]:
        service = _service(request)
        name = protocol.validate_name(body.name)
        ip = _ip(request)
        stored = await service.submit(lambda: service.lookup_rejoin(body, name, ip))
        new_hash = None
        if stored == "":
            # 管理員重設過 PIN：這次輸入的就是新 PIN（SPEC A10）
            new_hash = await service.in_thread(lambda: auth.hash_secret(body.pin))
            pin_ok = True
        else:
            pin_ok = await service.in_thread(lambda: auth.verify_secret(body.pin, stored))
        return await service.submit(lambda: service.finish_rejoin(body, name, pin_ok, new_hash, ip))


def _install_media_routes(app: FastAPI) -> None:
    @app.post("/api/media")
    async def upload(request: Request, kind: media.MediaKind) -> dict[str, Any]:
        session = _require_session(request)
        service = _service(request)
        room_uploads = service.paths.uploads
        data = await request.body()
        used = service.uploaded_bytes()
        stored = await service.in_thread(lambda: media.save_upload(data, kind, used, room_uploads))
        return await service.submit(lambda: service.register_media(session, stored))

    @app.get("/api/media/{media_id}")
    async def fetch(request: Request, media_id: str, exp: int, sig: str) -> FileResponse:
        service = _service(request)
        row = service.media_rows.get(media_id)
        if row is None or not service.signer.verify(f"media/{media_id}", exp, sig, service.wall()):
            # 過期或不存在都回 403，前端會重取（CODING_RULES N21）
            raise GameError(ErrorCode.FORBIDDEN)
        return FileResponse(row.path, media_type=row.mime)  # FileResponse 支援 Range（P7）

    @app.get("/api/assets")
    async def list_assets(request: Request) -> dict[str, dict[str, str]]:
        """列出 local_assets 可覆蓋素材，免登入（SPEC B7）。"""
        service = _service(request)
        root = service.paths.assets
        found: dict[str, str] = {}
        for folder in _ASSET_FOLDERS:
            base = root / folder
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(root).as_posix()
                    resource = f"asset/{relative}"
                    query = service.signer.query(resource, service.wall())
                    found[relative] = f"/api/{resource}?{query}"
        return {"assets": found}

    @app.get("/api/asset/{path:path}")
    async def fetch_asset(request: Request, path: str, exp: int, sig: str) -> FileResponse:
        service = _service(request)
        if not service.signer.verify(f"asset/{path}", exp, sig, service.wall()):
            raise GameError(ErrorCode.FORBIDDEN)
        root = service.paths.assets.resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file():
            raise GameError(ErrorCode.FORBIDDEN)
        return FileResponse(target)


def _origin_allowed(socket: WebSocket) -> bool:
    """WebSocket 要自己檢查 Origin（SPEC B8）；直連網址時 Origin 與 Host 相同。"""
    origin = socket.headers.get("origin")
    if origin is None or origin in config.ALLOWED_ORIGINS:
        return True
    return urlparse(origin).netloc == socket.headers.get("host")


async def _authenticate(socket: WebSocket, service: RoomService) -> Session | None:
    """第一則訊息必須是 auth（SPEC B7）。"""
    try:
        raw = json.loads(await asyncio.wait_for(socket.receive_text(), timeout=10))
        auth_msg = protocol.AuthMsg.model_validate(raw)
    except (ValueError, TimeoutError, WebSocketDisconnect):
        await socket.close(code=4400)
        return None
    if auth_msg.client_version != config.PROTOCOL_VERSION:
        code = ErrorCode.VERSION_MISMATCH.value
        await socket.send_text(json.dumps({"t": "error", "msg_id": None, "code": code}))
        await socket.close(code=4426)
        return None
    session = service.session_for(auth_msg.token)
    if session is None:
        code = ErrorCode.UNAUTHORIZED.value
        await socket.send_text(json.dumps({"t": "error", "msg_id": None, "code": code}))
        await socket.close(code=4401)
        return None
    return session


def _install_socket(app: FastAPI) -> None:
    @app.websocket("/ws")
    async def ws_endpoint(socket: WebSocket) -> None:
        if not _origin_allowed(socket):
            await socket.close(code=4403)
            return
        await socket.accept()
        service: RoomService = socket.app.state.service
        session = await _authenticate(socket, service)
        if session is None:
            return
        conn = await service.submit(lambda: service.connect(socket, session))
        await _pump(socket, service, conn)

    async def _pump(socket: WebSocket, service: RoomService, conn: Connection) -> None:
        try:
            while True:
                text = await socket.receive_text()
                await _deliver(service, conn, _parse_frame(text))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await service.submit(lambda: service.disconnect(conn))


async def _deliver(service: RoomService, conn: Connection, frame: Any) -> None:
    await service.submit(lambda: service.on_message(conn, frame))


def _parse_frame(text: str) -> Any:
    """太大或壞掉的訊息交給 parse_client 回 bad_request（CODING_RULES E1、N9）。"""
    if len(text) > config.WS_MAX_MESSAGE_BYTES:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


app = create_app()
