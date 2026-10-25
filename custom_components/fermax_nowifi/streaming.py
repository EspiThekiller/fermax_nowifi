"""Mediasoup video streaming client for Fermax NOWIFI."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import socketio

_LOGGER = logging.getLogger(__name__)

try:
    import aiortc  # noqa: F401
    import pymediasoup  # noqa: F401
    import av  # noqa: F401
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False

# Suppress noisy H264 decode warnings
logging.getLogger("aiortc.codecs.h264").setLevel(logging.ERROR)

SIGNALING_VERSION = "0.8.2"


def _patch_pymediasoup_audio_channels() -> None:
    """Fix pymediasoup bug: channels=None vs channels=1 for mono audio codecs."""
    if not WEBRTC_AVAILABLE:
        return
    try:
        from pymediasoup.handlers.aiortc_handler import AiortcHandler as _Handler
        from pymediasoup.rtp_parameters import RtpCapabilities as _Caps

        _orig_get = _Handler.getNativeRtpCapabilities

        async def _patched_get(self: _Handler) -> _Caps:
            caps = await _orig_get(self)
            for codec in caps.codecs:
                if codec.kind == "audio" and codec.channels is None:
                    codec.channels = 1
            return caps

        _Handler.getNativeRtpCapabilities = _patched_get  # type: ignore[assignment]
    except Exception as exc:
        _LOGGER.debug("Could not patch pymediasoup audio channels: %s", exc)


_PYMEDIASOUP_PATCHED = False
DEFAULT_SIGNALING_URL = "https://signaling-pro-duoxme.fermax.io"


def _create_switchable_audio_track() -> Any:
    """Create a silent SwitchableAudioTrack for sending audio."""
    if not WEBRTC_AVAILABLE:
        return None
    from aiortc import MediaStreamTrack

    class _Track(MediaStreamTrack):  # type: ignore[misc]
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._pts = 0

        async def recv(self) -> Any:
            import av

            frame = av.AudioFrame(format="s16", layout="mono", samples=960)
            for p in frame.planes:
                p.update(bytes(p.buffer_size))
            frame.sample_rate = 48000
            frame.pts = self._pts
            self._pts += 960
            await asyncio.sleep(0.02)
            return frame

    return _Track()


@dataclass
class TransportData:
    """WebRTC transport parameters from mediasoup."""

    id: str
    dtls_parameters: str
    ice_candidates: str
    ice_parameters: str


@dataclass
class RoomJoinResult:
    """Result of joining a mediasoup room."""

    video_producer_id: str
    audio_producer_id: str
    router_rtp_capabilities: str
    recv_video_transport: TransportData
    recv_audio_transport: TransportData
    send_transport: TransportData
    ice_servers: str | None = None


@dataclass
class ConsumeResult:
    """Result of a transport_consume request."""

    consumer_id: str
    producer_id: str
    kind: str
    rtp_parameters: Any


class FermaxSignalingClient:
    """Socket.IO client for Fermax Blue mediasoup signaling."""

    def __init__(
        self,
        signaling_url: str = DEFAULT_SIGNALING_URL,
        oauth_token: str = "",
        fcm_token: str = "",
    ) -> None:
        self._signaling_url = signaling_url
        self._oauth_token = oauth_token
        self._fcm_token = fcm_token
        self._sio: socketio.AsyncClient | None = None
        self._connected = False
        self._room_join_result: RoomJoinResult | None = None
        self._on_end_up: Callable[[str], None] | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def room_join_result(self) -> RoomJoinResult | None:
        return self._room_join_result

    async def connect(self, room_id: str) -> RoomJoinResult | None:
        """Connect to signaling server and join a room."""
        self._sio = socketio.AsyncClient(logger=False, engineio_logger=False)

        @self._sio.event
        async def connect() -> None:
            self._connected = True

        @self._sio.event
        async def disconnect() -> None:
            self._connected = False

        @self._sio.on("end_up")
        async def on_end_up(data: Any) -> None:
            code = data.get("code", "") if isinstance(data, dict) else str(data)
            _LOGGER.info("Intercom call ended by signaling: %s", code)
            if self._on_end_up:
                self._on_end_up(code)

        try:
            await self._sio.connect(self._signaling_url, transports=["websocket"])

            response = await self._sio.call(
                "join_call",
                {
                    "roomId": room_id,
                    "appToken": self._fcm_token,
                    "fermaxOauthToken": self._oauth_token,
                    "protocolVersion": SIGNALING_VERSION,
                },
                timeout=15,
            )

            if not isinstance(response, dict) or "error" in response:
                _LOGGER.error("join_call failed: %s", response)
                return None

            result_data = response.get("result", {})
            if not result_data:
                return None

            recv_video = result_data.get("recvTransportVideo", {})
            recv_audio = result_data.get("recvTransportAudio", {})
            send = result_data.get("sendTransport", {})

            self._room_join_result = RoomJoinResult(
                video_producer_id=result_data.get("producerIdVideo", ""),
                audio_producer_id=result_data.get("producerIdAudio", ""),
                router_rtp_capabilities=json.dumps(result_data.get("routerRtpCapabilities", {})),
                recv_video_transport=self._parse_transport(recv_video),
                recv_audio_transport=self._parse_transport(recv_audio),
                send_transport=self._parse_transport(send),
                ice_servers=json.dumps(result_data.get("iceServers", [])),
            )

            _LOGGER.info(
                "Mediasoup room joined: video_id=%s, audio_id=%s",
                self._room_join_result.video_producer_id,
                self._room_join_result.audio_producer_id,
            )
            return self._room_join_result

        except Exception as exc:
            _LOGGER.error("Failed to connect to signaling server %s: %s", self._signaling_url, exc)
            return None

    @staticmethod
    def _parse_transport(data: dict) -> TransportData:
        return TransportData(
            id=data.get("id", ""),
            dtls_parameters=json.dumps(data.get("dtlsParameters", {})),
            ice_candidates=json.dumps(data.get("iceCandidates", [])),
            ice_parameters=json.dumps(data.get("iceParameters", {})),
        )

    async def consume_transport(
        self, transport_id: str, producer_id: str, rtp_capabilities: str
    ) -> ConsumeResult | None:
        """Request to consume a media track."""
        if not self._sio or not self._connected:
            return None

        try:
            caps = (
                json.loads(rtp_capabilities)
                if isinstance(rtp_capabilities, str)
                else rtp_capabilities
            )
            response = await self._sio.call(
                "transport_consume",
                {
                    "transportId": transport_id,
                    "producerId": producer_id,
                    "rtpCapabilities": caps,
                },
                timeout=10,
            )

            if not isinstance(response, dict) or "error" in response:
                _LOGGER.error("transport_consume error: %s", response)
                return None

            result = response.get("result", {})
            return ConsumeResult(
                consumer_id=result.get("id", ""),
                producer_id=result.get("producerId", ""),
                kind=result.get("kind", ""),
                rtp_parameters=result.get("rtpParameters", {}),
            )
        except Exception:
            _LOGGER.exception("Failed to consume transport")
            return None

    async def connect_transport(self, transport_id: str, dtls_parameters: str) -> bool:
        """Connect a transport with DTLS parameters."""
        if not self._sio or not self._connected:
            return False

        try:
            dtls = (
                json.loads(dtls_parameters) if isinstance(dtls_parameters, str) else dtls_parameters
            )
            response = await self._sio.call(
                "transport_connect",
                {"transportId": transport_id, "dtlsParameters": dtls},
                timeout=10,
            )
            return isinstance(response, dict) and "error" not in response
        except Exception:
            _LOGGER.exception("Failed to connect transport")
            return False

    async def pickup(
        self,
        kind: str,
        rtp_parameters: str,
        app_data: str,
        rtp_capabilities: str,
    ) -> dict | None:
        """Signal pickup to establish audio channel."""
        if not self._sio or not self._connected:
            return None

        try:
            caps = (
                json.loads(rtp_capabilities)
                if isinstance(rtp_capabilities, str)
                else rtp_capabilities
            )
            rtp = json.loads(rtp_parameters) if isinstance(rtp_parameters, str) else rtp_parameters
            app = json.loads(app_data) if isinstance(app_data, str) else app_data

            response = await self._sio.call(
                "pickup",
                {
                    "parameters": {
                        "kind": kind,
                        "rtpParameters": rtp,
                        "appData": app,
                    },
                    "rtpCapabilities": caps,
                },
                timeout=10,
            )

            if isinstance(response, dict) and "error" not in response:
                return response.get("result", {})
            return None
        except Exception:
            _LOGGER.debug("Pickup failed", exc_info=True)
            return None

    async def hangup(self) -> None:
        if self._sio and self._connected:
            try:
                await self._sio.emit("hang_up", {})
            except Exception:
                pass

    async def disconnect(self) -> None:
        if self._sio:
            try:
                if self._connected:
                    await self.hangup()
                await self._sio.disconnect()
            except Exception:
                pass
            finally:
                self._sio = None
                self._connected = False
                self._room_join_result = None


class FermaxStreamSession:
    """Full streaming session: signaling + Mediasoup SFU consumer + frame grabber."""

    def __init__(
        self,
        signaling_url: str,
        oauth_token: str,
        fcm_token: str,
        room_id: str,
        on_end: Callable[[], None] | None = None,
        on_frame: Callable[[bytes], None] | None = None,
    ) -> None:
        if signaling_url and not signaling_url.startswith(("https://", "wss://")):
            signaling_url = signaling_url.replace("http://", "https://", 1).replace(
                "ws://", "wss://", 1
            )
        self._signaling = FermaxSignalingClient(
            signaling_url=signaling_url,
            oauth_token=oauth_token,
            fcm_token=fcm_token,
        )
        self._room_id = room_id
        self._on_end = on_end
        self._on_frame = on_frame
        self._device: Any = None
        self._recv_transport: Any = None
        self._recv_audio_transport: Any = None
        self._send_transport: Any = None
        self._audio_producer: Any = None
        self._consumer: Any = None
        self._audio_consumer: Any = None
        self._frame_task: asyncio.Task | None = None
        self._latest_frame: bytes | None = None
        self._active = False

    @property
    def room_id(self) -> str:
        """Return the active room ID."""
        return self._room_id

    @property
    def is_active(self) -> bool:
        """Return True if session is running and consuming frames."""
        return self._active

    @property
    def latest_frame(self) -> bytes | None:
        """Return latest captured JPEG frame."""
        return self._latest_frame

    async def start(self) -> bool:
        """Start Mediasoup streaming pipeline."""
        if not WEBRTC_AVAILABLE:
            _LOGGER.warning(
                "WebRTC streaming de Fermax no disponible: dependencias 'aiortc' / 'pymediasoup' "
                "no instaladas o incompatibles con av 19 en esta versión de Home Assistant (HA 2026.10+). "
                "Las funciones de apertura de puertas, timbres y sensores continúan 100%% operativas."
            )
            return False
        try:
            return await self._start_inner()
        except Exception:
            _LOGGER.exception("Failed to start stream session")
            await self.stop()
            return False

    async def _start_inner(self) -> bool:
        global _PYMEDIASOUP_PATCHED
        from pymediasoup import Device
        from pymediasoup.handlers.aiortc_handler import AiortcHandler
        from pymediasoup.models.transport import (
            DtlsParameters,
            IceCandidate,
            IceParameters,
        )
        from pymediasoup.rtp_parameters import RtpCapabilities, RtpParameters

        if not _PYMEDIASOUP_PATCHED:
            _patch_pymediasoup_audio_channels()
            _PYMEDIASOUP_PATCHED = True

        # 1. Conexión Socket.IO y join_call
        room = await self._signaling.connect(self._room_id)
        if not room:
            _LOGGER.error("Failed to join room %s", self._room_id)
            return False

        loop = asyncio.get_running_loop()

        def _handle_end_up(_code: str) -> None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.stop()))

        self._signaling._on_end_up = _handle_end_up

        # 2. Mediasoup Device
        self._device = Device(handlerFactory=AiortcHandler.createFactory(tracks=[]))
        router_caps = json.loads(room.router_rtp_capabilities)
        await self._device.load(RtpCapabilities(**router_caps))

        # 3. RecvTransport Vídeo
        video_tp = room.recv_video_transport
        ice_params = json.loads(video_tp.ice_parameters)
        ice_candidates = json.loads(video_tp.ice_candidates)
        dtls_params = json.loads(video_tp.dtls_parameters)

        self._recv_transport = self._device.createRecvTransport(
            id=video_tp.id,
            iceParameters=IceParameters(**ice_params),
            iceCandidates=[IceCandidate(**c) for c in ice_candidates],
            dtlsParameters=DtlsParameters(**dtls_params),
        )

        @self._recv_transport.on("connect")
        async def on_connect(dtls_parameters: DtlsParameters) -> None:
            await self._signaling.connect_transport(
                transport_id=video_tp.id,
                dtls_parameters=json.dumps(dtls_parameters.dict(exclude_none=True)),
            )

        # 4. Consumo de Vídeo
        device_caps = self._device.rtpCapabilities
        consume_result = await self._signaling.consume_transport(
            transport_id=video_tp.id,
            producer_id=room.video_producer_id,
            rtp_capabilities=json.dumps(device_caps.dict(exclude_none=True)),
        )
        if not consume_result:
            _LOGGER.error("Failed to consume video transport")
            return False

        self._consumer = await self._recv_transport.consume(
            id=consume_result.consumer_id,
            producerId=consume_result.producer_id,
            kind=consume_result.kind,
            rtpParameters=RtpParameters(**consume_result.rtp_parameters)
            if isinstance(consume_result.rtp_parameters, dict)
            else consume_result.rtp_parameters,
        )

        # 5. Iniciar captura de frames
        self._active = True
        self._frame_task = asyncio.create_task(self._grab_frames())
        _LOGGER.info("Stream session successfully established for room %s", self._room_id)
        return True

    @staticmethod
    def _overlay_live_indicator(img: Any) -> Any:
        """Superpone el distintivo '● LIVE [HH:MM:SS]' en la esquina superior izquierda."""
        try:
            from datetime import datetime
            from PIL import ImageDraw, ImageFont

            draw = ImageDraw.Draw(img)
            now = datetime.now().strftime("%H:%M:%S")
            font = ImageFont.load_default(size=16)

            draw.rectangle([(8, 8), (145, 30)], fill=(220, 38, 38))
            draw.text((14, 9), f"\u25cf LIVE {now}", fill=(255, 255, 255), font=font)
        except Exception:
            pass
        return img

    async def _grab_frames(self) -> None:
        """Lee fotogramas de la pista aiortc, añade el distintivo y codifica en JPEG."""
        from aiortc.mediastreams import MediaStreamError

        track = self._consumer.track
        frame_count = 0
        try:
            while self._active:
                frame = await track.recv()
                frame_count += 1
                img = frame.to_image()

                img = self._overlay_live_indicator(img)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75)
                jpeg_bytes = buf.getvalue()

                self._latest_frame = jpeg_bytes
                if self._on_frame:
                    self._on_frame(jpeg_bytes)

                if frame_count == 1:
                    _LOGGER.info("First video frame received from Fermax panel: %d bytes", len(jpeg_bytes))
        except (MediaStreamError, asyncio.CancelledError):
            pass
        except Exception as exc:
            _LOGGER.debug("Frame grabber ended: %s", exc)
        finally:
            self._active = False
            if self._on_end:
                self._on_end()

    async def stop(self) -> None:
        """Detiene la sesión y limpia recursos."""
        self._active = False

        if self._frame_task and not self._frame_task.done():
            self._frame_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._frame_task

        if self._consumer:
            with contextlib.suppress(Exception):
                await self._consumer.close()
            self._consumer = None

        if self._recv_transport:
            with contextlib.suppress(Exception):
                await self._recv_transport.close()
            self._recv_transport = None

        await self._signaling.disconnect()
        _LOGGER.info("Fermax video stream session stopped")
