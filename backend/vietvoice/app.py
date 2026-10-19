import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import struct
import time
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from .config import Settings
from .models import ModelBundle, SR
from .pipeline import Pipeline
from .store import Store, export_transcript

log = logging.getLogger("vietvoice")


class Login(BaseModel):
    key: str = Field(max_length=256)


class SpeakerName(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def create_app(settings=None, bundle_factory=ModelBundle):
    settings = settings or Settings()
    settings.validate()
    signer = URLSafeTimedSerializer(settings.app_key, salt="vietvoice-v1")
    store = Store(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        app.state.bundle = None
        app.state.model_error = "LOAD_MODELS=false: chỉ chạy giao diện/API, chưa nạp AI"
        app.state.active = 0
        if settings.startup_models:
            try:
                app.state.bundle = await asyncio.to_thread(bundle_factory, settings)
                app.state.model_error = None
            except Exception as exc:
                log.exception("Model initialization failed")
                app.state.model_error = f"{type(exc).__name__}: {exc}"
        yield
        app.state.bundle = None
        store.engine.dispose()

    app = FastAPI(title="VietVoice Local", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)

    def authenticated(cookies):
        try:
            return signer.loads(cookies.get("vv_session", ""), max_age=43200) == "operator"
        except BadSignature:
            return False

    def require_auth(request):
        if not authenticated(request.cookies):
            raise HTTPException(401, "Cần đăng nhập")

    def valid_origin(headers):
        origin = headers.get("origin")
        return origin is None or origin in settings.origins

    @app.middleware("http")
    async def headers(request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not valid_origin(request.headers):
            return JSONResponse({"detail": "Origin bị từ chối"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; worker-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        ok = app.state.bundle is not None
        return JSONResponse({"ready": ok}, status_code=200 if ok else 503)

    @app.post("/api/login")
    def login(payload: Login, response: Response):
        if not hmac.compare_digest(payload.key, settings.app_key):
            raise HTTPException(401, "Mã truy cập không đúng")
        response.set_cookie("vv_session", signer.dumps("operator"), httponly=True,
                            secure=settings.secure_cookie, samesite="strict", max_age=43200)
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie("vv_session")
        return {"ok": True}

    @app.get("/api/status")
    def status(request: Request):
        require_auth(request)
        return {"ready": app.state.bundle is not None, "error": app.state.model_error,
                "active_sessions": app.state.active, "max_sessions": settings.max_sessions,
                "diar_device": settings.diar_device, "diar_mode": settings.diar_mode, "max_speakers": 8}

    @app.get("/api/sessions")
    def sessions(request: Request):
        require_auth(request)
        return store.list()

    @app.get("/api/sessions/{sid}")
    def session(sid: str, request: Request):
        require_auth(request)
        result = store.get(sid)
        if not result:
            raise HTTPException(404, "Không tìm thấy phiên")
        return result

    @app.put("/api/sessions/{sid}/speakers/{speaker_id}")
    def rename(sid: str, speaker_id: str, payload: SpeakerName, request: Request):
        require_auth(request)
        if speaker_id not in {f"speaker_{i}" for i in range(1, 9)} or not payload.name.strip():
            raise HTTPException(400, "Tên người nói không hợp lệ")
        if not store.rename(sid, speaker_id, payload.name.strip()):
            raise HTTPException(404, "Không tìm thấy phiên")
        return {"ok": True}

    @app.get("/api/sessions/{sid}/export/{fmt}")
    def export(sid: str, fmt: str, request: Request):
        require_auth(request)
        if fmt not in ("txt", "json", "srt"):
            raise HTTPException(400, "Chỉ hỗ trợ txt, json, srt")
        result = store.get(sid)
        if not result:
            raise HTTPException(404, "Không tìm thấy phiên")
        body, mime = export_transcript(result, fmt)
        return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="vietvoice-{sid}.{fmt}"'})

    @app.websocket("/api/stream")
    async def stream(ws: WebSocket):
        if not authenticated(ws.cookies) or not valid_origin(ws.headers):
            await ws.close(code=1008)
            return
        await ws.accept()
        if not app.state.bundle or app.state.active >= settings.max_sessions:
            await ws.send_json({"type": "error", "code": "not_ready", "message": "Model chưa sẵn sàng hoặc máy chủ đã đủ phiên."})
            await ws.close(code=1013)
            return
        app.state.active += 1
        pipeline, sid, completed, connected = None, None, False, True
        started, next_seq = time.monotonic(), 0

        async def emit(events):
            nonlocal connected
            for event in events:
                if event["type"] == "final":
                    await asyncio.to_thread(store.final, sid, event)
                if connected:
                    try:
                        await ws.send_json(event)
                    except (WebSocketDisconnect, RuntimeError, OSError):
                        connected = False

        try:
            config = await asyncio.wait_for(ws.receive_json(), timeout=15)
            if config.get("type") != "start" or config.get("sample_rate") != SR or config.get("encoding") != "pcm_s16le":
                raise ValueError("Cần PCM16 little-endian, mono, 16000 Hz")
            sid = str(uuid4())
            pipeline = await asyncio.to_thread(Pipeline, app.state.bundle, settings.segment_seconds)
            await asyncio.to_thread(store.create, sid, str(config.get("title", "Cuộc trò chuyện mới"))[:120])
            await ws.send_json({"type": "started", "session_id": sid, "next_seq": 0})
            while True:
                packet = await asyncio.wait_for(ws.receive(), timeout=30)
                if packet["type"] == "websocket.disconnect":
                    connected = False
                    break
                if packet.get("bytes") is not None:
                    data = packet["bytes"]
                    if len(data) < 6 or len(data) > 6404 or (len(data) - 4) % 2:
                        raise ValueError("Gói cần 4 byte sequence + 1–3200 mẫu PCM16")
                    seq = struct.unpack_from("<I", data)[0]
                    if seq < next_seq:
                        await ws.send_json({"type": "ack", "seq": seq, "duplicate": True})
                        continue
                    if seq != next_seq:
                        raise ValueError(f"Thiếu gói âm thanh: cần {next_seq}, nhận {seq}")
                    incoming = (len(data) - 4) // 2
                    if pipeline.samples + incoming > settings.max_seconds * SR:
                        raise ValueError("Đã đạt giới hạn thời lượng phiên")
                    if (pipeline.samples + incoming) / SR > time.monotonic() - started + 8:
                        raise ValueError("Cần gửi âm thanh theo thời gian thực")
                    events = await asyncio.to_thread(pipeline.feed, data[4:])
                    next_seq += 1
                    await emit(events)
                    await ws.send_json({"type": "ack", "seq": seq, "audio_seconds": pipeline.samples / SR})
                else:
                    if json.loads(packet.get("text", "{}" )).get("type") != "end":
                        raise ValueError("Lệnh không hỗ trợ")
                    completed = True
                    break
        except (WebSocketDisconnect, OSError):
            connected = False
        except Exception as exc:
            log.exception("Streaming failed: %s", sid)
            if connected:
                try:
                    await ws.send_json({"type": "error", "code": "stream_failed", "message": str(exc) if isinstance(exc, ValueError) else "Phiên bị gián đoạn; xem log máy chủ."})
                except Exception:
                    connected = False
        finally:
            try:
                if pipeline is not None and sid is not None:
                    try:
                        events = await asyncio.to_thread(pipeline.finish)
                        await emit([e for e in events if e["type"] != "done"])
                        result_status = "completed" if completed else "interrupted"
                        await asyncio.to_thread(store.finish, sid, pipeline.samples / SR, result_status)
                        await emit([{**events[-1], "status": result_status}])
                    except Exception:
                        log.exception("Final flush failed: %s", sid)
                        await asyncio.to_thread(store.finish, sid, pipeline.samples / SR, "failed")
                        if connected:
                            await ws.send_json({"type": "error", "code": "flush_failed", "message": "Không chốt được phần cuối. Các đoạn đã chốt vẫn được lưu."})
            finally:
                app.state.active -= 1
                if connected:
                    try:
                        await ws.close()
                    except Exception:
                        pass

    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
    return app
