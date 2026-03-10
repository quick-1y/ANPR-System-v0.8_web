from __future__ import annotations

import os
import signal
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Dict, Literal, Optional

from fastapi import Body, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

QualityProfile = Literal["low", "medium", "high"]
WebRTCProvider = Literal["none", "mediamtx", "go2rtc"]


@dataclass
class Session:
    channel_id: int
    source: str
    profile: QualityProfile
    process: subprocess.Popen


@dataclass
class WebRTCConfig:
    enabled: bool = False
    provider: WebRTCProvider = "none"
    signaling_base_url: str = ""
    whep_path_template: str = "/whep/channel_{channel_id}"
    play_url_template: str = ""

    def whep_url(self, channel_id: int) -> str:
        path = self.whep_path_template.format(channel_id=channel_id)
        return f"{self.signaling_base_url.rstrip('/')}{path}"

    def play_url(self, channel_id: int) -> str:
        if not self.play_url_template:
            return ""
        return self.play_url_template.format(channel_id=channel_id)


class VideoGatewayService:
    """Управляет HLS-пайплайнами FFmpeg и WebRTC adapter-контрактом."""

    PROFILE_SCALE: Dict[QualityProfile, tuple[int, int, int]] = {
        "low": (640, 360, 12),
        "medium": (960, 540, 18),
        "high": (1280, 720, 25),
    }

    def __init__(self, output_root: str = "data/hls", webrtc: Optional[WebRTCConfig] = None) -> None:
        self._lock = RLock()
        self._sessions: Dict[int, Session] = {}
        self._output_root = Path(output_root)
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._webrtc = webrtc or WebRTCConfig()

    def set_webrtc(self, cfg: WebRTCConfig) -> None:
        self._webrtc = cfg

    @property
    def webrtc(self) -> WebRTCConfig:
        return self._webrtc

    def _playlist_path(self, channel_id: int, profile: QualityProfile) -> Path:
        return self._output_root / f"channel_{channel_id}" / profile / "index.m3u8"

    def _build_ffmpeg_command(self, source: str, playlist: Path, profile: QualityProfile) -> list[str]:
        width, height, fps = self.PROFILE_SCALE[profile]
        playlist.parent.mkdir(parents=True, exist_ok=True)
        for old in playlist.parent.glob("*.ts"):
            old.unlink(missing_ok=True)
        playlist.unlink(missing_ok=True)
        gop = max(24, fps * 2)
        return [
            "ffmpeg", "-rtsp_transport", "tcp", "-i", source,
            "-an", "-vf", f"fps={fps},scale={width}:{height}", "-c:v", "libx264",
            "-preset", "veryfast", "-tune", "zerolatency", "-g", str(gop), "-keyint_min", str(gop),
            "-f", "hls", "-hls_time", "2", "-hls_list_size", "6", "-hls_flags", "delete_segments+append_list",
            str(playlist),
        ]

    def start(self, channel_id: int, source: str, profile: QualityProfile) -> Session:
        with self._lock:
            if channel_id in self._sessions:
                self.stop(channel_id)
            playlist = self._playlist_path(channel_id, profile)
            cmd = self._build_ffmpeg_command(source, playlist, profile)
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
            except FileNotFoundError as exc:
                raise RuntimeError("ffmpeg не найден в окружении") from exc
            session = Session(channel_id=channel_id, source=source, profile=profile, process=process)
            self._sessions[channel_id] = session
            return session

    def stop(self, channel_id: int) -> None:
        with self._lock:
            session = self._sessions.pop(channel_id, None)
        if not session:
            return
        try:
            os.killpg(os.getpgid(session.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return

    def switch_profile(self, channel_id: int, profile: QualityProfile) -> Session:
        with self._lock:
            session = self._sessions.get(channel_id)
            if not session:
                raise KeyError(channel_id)
            source = session.source
        return self.start(channel_id, source, profile)

    def list(self) -> Dict[int, Dict[str, str | int]]:
        with self._lock:
            return {
                channel_id: {
                    "channel_id": channel_id,
                    "source": session.source,
                    "profile": session.profile,
                    "hls_url": f"/hls/channel_{channel_id}/{session.profile}/index.m3u8",
                    "webrtc_offer_url": f"/video/webrtc/{channel_id}/offer",
                    "webrtc_play_url": self._webrtc.play_url(channel_id),
                }
                for channel_id, session in self._sessions.items()
            }

    def stop_all(self) -> None:
        for channel_id in list(self.list().keys()):
            self.stop(channel_id)


class StartPayload(BaseModel):
    source: str
    profile: QualityProfile = "medium"


class ProfilePayload(BaseModel):
    profile: QualityProfile


class WebRTCConfigPayload(BaseModel):
    enabled: bool = False
    provider: WebRTCProvider = "none"
    signaling_base_url: str = ""
    whep_path_template: str = Field(default="/whep/channel_{channel_id}")
    play_url_template: str = ""


def _default_webrtc() -> WebRTCConfig:
    return WebRTCConfig(
        enabled=os.getenv("WEBRTC_ENABLED", "false").lower() == "true",
        provider=os.getenv("WEBRTC_PROVIDER", "none"),
        signaling_base_url=os.getenv("WEBRTC_SIGNALING_BASE_URL", ""),
        whep_path_template=os.getenv("WEBRTC_WHEP_PATH_TEMPLATE", "/whep/channel_{channel_id}"),
        play_url_template=os.getenv("WEBRTC_PLAY_URL_TEMPLATE", ""),
    )


service = VideoGatewayService(webrtc=_default_webrtc())
app = FastAPI(title="ANPR Video Gateway", version="0.8-stage8")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/hls", StaticFiles(directory="data/hls"), name="hls")


@app.on_event("shutdown")
def shutdown() -> None:
    service.stop_all()


@app.get("/")
def root() -> Dict[str, str]:
    return {
        "service": "video-gateway",
        "health": "/video/health",
        "channels": "/video/channels",
        "webrtc_config": "/video/webrtc/config",
    }


@app.get("/video/health")
def health() -> Dict[str, int | str | bool]:
    return {
        "status": "ok",
        "active_streams": len(service.list()),
        "webrtc_enabled": service.webrtc.enabled,
        "webrtc_provider": service.webrtc.provider,
    }


@app.get("/video/channels")
def list_channels() -> Dict[int, Dict[str, str | int]]:
    return service.list()


@app.post("/video/channels/{channel_id}/start")
def start_channel(channel_id: int, payload: StartPayload) -> Dict[str, str | int]:
    try:
        session = service.start(channel_id=channel_id, source=payload.source, profile=payload.profile)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "channel_id": channel_id,
        "profile": session.profile,
        "hls_url": f"/hls/channel_{channel_id}/{session.profile}/index.m3u8",
        "webrtc_offer_url": f"/video/webrtc/{channel_id}/offer",
        "webrtc_play_url": service.webrtc.play_url(channel_id),
    }


@app.post("/video/channels/{channel_id}/stop")
def stop_channel(channel_id: int) -> Dict[str, str]:
    service.stop(channel_id)
    return {"status": "stopped"}


@app.post("/video/channels/{channel_id}/profile")
def switch_channel_profile(channel_id: int, payload: ProfilePayload) -> Dict[str, str | int]:
    try:
        session = service.switch_profile(channel_id=channel_id, profile=payload.profile)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Канал не активирован в Video Gateway") from exc
    return {
        "channel_id": channel_id,
        "profile": session.profile,
        "hls_url": f"/hls/channel_{channel_id}/{session.profile}/index.m3u8",
        "webrtc_offer_url": f"/video/webrtc/{channel_id}/offer",
        "webrtc_play_url": service.webrtc.play_url(channel_id),
    }


@app.get("/video/webrtc/config")
def get_webrtc_config() -> Dict[str, str | bool]:
    cfg = service.webrtc
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "signaling_base_url": cfg.signaling_base_url,
        "whep_path_template": cfg.whep_path_template,
        "play_url_template": cfg.play_url_template,
    }


@app.put("/video/webrtc/config")
def update_webrtc_config(payload: WebRTCConfigPayload) -> Dict[str, str | bool]:
    if payload.enabled and not payload.signaling_base_url.strip():
        raise HTTPException(status_code=422, detail="signaling_base_url обязателен при enabled=true")
    cfg = WebRTCConfig(**payload.model_dump())
    service.set_webrtc(cfg)
    return get_webrtc_config()


@app.post("/video/webrtc/{channel_id}/offer")
def webrtc_offer(channel_id: int, offer_sdp: str = Body(..., media_type="application/sdp")) -> Response:
    if channel_id not in service.list():
        raise HTTPException(status_code=404, detail="Канал не активирован")
    cfg = service.webrtc
    if not cfg.enabled or not cfg.signaling_base_url:
        raise HTTPException(status_code=503, detail="WebRTC адаптер выключен")

    url = cfg.whep_url(channel_id)
    req = urllib.request.Request(
        url,
        data=offer_sdp.encode("utf-8"),
        headers={"Content-Type": "application/sdp"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as response:
            answer = response.read().decode("utf-8")
        return Response(content=answer, media_type="application/sdp")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=502, detail=f"WebRTC upstream error: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Не удалось связаться с WebRTC upstream: {exc}") from exc


@app.get("/video/webrtc/{channel_id}")
def webrtc_info(channel_id: int) -> Dict[str, str | int | bool]:
    if channel_id not in service.list():
        raise HTTPException(status_code=404, detail="Канал не активирован")
    cfg = service.webrtc
    return {
        "channel_id": channel_id,
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "offer_url": f"/video/webrtc/{channel_id}/offer",
        "whep_url": cfg.whep_url(channel_id) if cfg.signaling_base_url else "",
        "play_url": cfg.play_url(channel_id),
    }
