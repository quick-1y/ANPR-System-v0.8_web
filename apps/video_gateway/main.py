from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Dict, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


QualityProfile = Literal["low", "medium", "high"]


@dataclass
class Session:
    channel_id: int
    source: str
    profile: QualityProfile
    process: subprocess.Popen


class VideoGatewayService:
    """Управляет HLS-пайплайнами FFmpeg для каждого канала и профиля качества."""

    PROFILE_SCALE: Dict[QualityProfile, tuple[int, int, int]] = {
        "low": (640, 360, 12),
        "medium": (960, 540, 18),
        "high": (1280, 720, 25),
    }

    def __init__(self, output_root: str = "data/hls") -> None:
        self._lock = RLock()
        self._sessions: Dict[int, Session] = {}
        self._output_root = Path(output_root)
        self._output_root.mkdir(parents=True, exist_ok=True)

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
            "ffmpeg",
            "-rtsp_transport",
            "tcp",
            "-i",
            source,
            "-an",
            "-vf",
            f"fps={fps},scale={width}:{height}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-g",
            str(gop),
            "-keyint_min",
            str(gop),
            "-f",
            "hls",
            "-hls_time",
            "2",
            "-hls_list_size",
            "6",
            "-hls_flags",
            "delete_segments+append_list",
            str(playlist),
        ]

    def start(self, channel_id: int, source: str, profile: QualityProfile) -> Session:
        with self._lock:
            if channel_id in self._sessions:
                self.stop(channel_id)
            playlist = self._playlist_path(channel_id, profile)
            cmd = self._build_ffmpeg_command(source, playlist, profile)
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
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
                    "webrtc_url": f"/video/webrtc/{channel_id}?profile={session.profile}",
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


service = VideoGatewayService()
app = FastAPI(title="ANPR Video Gateway", version="0.8-stage5")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/hls", StaticFiles(directory="data/hls"), name="hls")


@app.on_event("shutdown")
def shutdown() -> None:
    service.stop_all()


@app.get("/video/health")
def health() -> Dict[str, int | str]:
    return {"status": "ok", "active_streams": len(service.list())}


@app.get("/video/channels")
def list_channels() -> Dict[int, Dict[str, str | int]]:
    return service.list()


@app.post("/video/channels/{channel_id}/start")
def start_channel(channel_id: int, payload: StartPayload) -> Dict[str, str | int]:
    session = service.start(channel_id=channel_id, source=payload.source, profile=payload.profile)
    return {
        "channel_id": channel_id,
        "profile": session.profile,
        "hls_url": f"/hls/channel_{channel_id}/{session.profile}/index.m3u8",
        "webrtc_url": f"/video/webrtc/{channel_id}?profile={session.profile}",
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
        "webrtc_url": f"/video/webrtc/{channel_id}?profile={session.profile}",
    }


@app.get("/video/webrtc/{channel_id}")
def webrtc_endpoint(channel_id: int, profile: QualityProfile = "medium") -> Dict[str, str | int]:
    """Контракт для интеграции с внешним WebRTC SFU/медиасервером."""
    sessions = service.list()
    if channel_id not in sessions:
        raise HTTPException(status_code=404, detail="Канал не активирован")
    return {
        "channel_id": channel_id,
        "profile": profile,
        "mode": "external-sfu-required",
        "hint": "Подключите WHEP/WHIP сервер (например, go2rtc/mediamtx) и используйте этот endpoint как discovery-контракт.",
    }
