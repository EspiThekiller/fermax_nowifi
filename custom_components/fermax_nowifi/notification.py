"""Firebase Cloud Messaging listener for Fermax NOWIFI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from firebase_messaging import FcmPushClient, FcmPushClientConfig
from firebase_messaging.fcmregister import FcmRegister, FcmRegisterConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    FIREBASE_API_KEY,
    FIREBASE_APP_ID,
    FIREBASE_PACKAGE_NAME,
    FIREBASE_PROJECT_ID,
    FIREBASE_SENDER_ID,
)

_LOGGER = logging.getLogger(__name__)

_FCM_STORAGE_VERSION = 1
_FCM_STORAGE_KEY = f"{DOMAIN}_fcm_credentials"

FCM_UPSTREAM_LOGGER = "firebase_messaging.fcmpushclient"
FCM_ABORT_SEQUENTIAL_ERROR_COUNT = 3
FCM_RESTART_BACKOFF_INITIAL = 60.0
FCM_RESTART_BACKOFF_MAX = 600.0


def _patch_firebase_messaging() -> None:
    """Monkeypatch upstream firebase-messaging to fix base64 padding and crypto-key header parsing."""
    try:
        from base64 import urlsafe_b64decode
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.serialization import load_der_private_key
        from http_ece import decrypt as http_decrypt

        def _safe_b64decode(s: str | bytes) -> bytes:
            b = s.encode("ascii") if isinstance(s, str) else s
            return urlsafe_b64decode(b + b"=" * (-len(b) % 4))

        @staticmethod
        def _patched_decrypt_raw_data(
            credentials: dict[str, dict[str, str]],
            crypto_key_str: str,
            salt_str: str,
            raw_data: bytes,
        ) -> bytes:
            crypto_key = _safe_b64decode(crypto_key_str)
            salt = _safe_b64decode(salt_str)
            der_data = _safe_b64decode(credentials["keys"]["private"])
            secret = _safe_b64decode(credentials["keys"]["secret"])
            privkey = load_der_private_key(
                der_data, password=None, backend=default_backend()
            )
            return http_decrypt(
                raw_data,
                salt=salt,
                private_key=privkey,
                dh=crypto_key,
                version="aesgcm",
                auth_secret=secret,
            )

        FcmPushClient._decrypt_raw_data = _patched_decrypt_raw_data

        orig_handle = FcmPushClient._handle_data_message

        def _patched_handle_data_message(self: FcmPushClient, msg: Any) -> None:
            # Normalize crypto-key and encryption if they contain multiple parameters
            for item in getattr(msg, "app_data", []):
                if item.key == "crypto-key":
                    val = item.value
                    if ";" in val:
                        for part in val.split(";"):
                            part = part.strip()
                            if part.startswith("dh="):
                                item.value = part
                                break
                elif item.key == "encryption":
                    val = item.value
                    if ";" in val:
                        for part in val.split(";"):
                            part = part.strip()
                            if part.startswith("salt="):
                                item.value = part
                                break
            try:
                orig_handle(self, msg)
            except Exception as exc:
                _LOGGER.debug("Handled exception in push data message safely: %s", exc)

        FcmPushClient._handle_data_message = _patched_handle_data_message
        _LOGGER.debug("firebase-messaging monkeypatch applied successfully")
    except Exception as exc:
        _LOGGER.debug("Could not apply firebase-messaging monkeypatch: %s", exc)


_patch_firebase_messaging()


class _FcmExcInfoRateLimitFilter(logging.Filter):
    """Strip repetitive tracebacks from upstream FCM records after a burst."""

    def __init__(self, limit: int = 3, window: float = 300.0) -> None:
        super().__init__()
        self._limit = limit
        self._window = window
        self._timestamps: deque[float] = deque()

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.exc_info or record.exc_info[0] is None:
            return True
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > self._window:
            self._timestamps.popleft()
        if len(self._timestamps) < self._limit:
            self._timestamps.append(now)
            return True
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.msg = f"{record.msg} (traceback suppressed: rate limit exceeded)"
        return True


def _install_fcm_log_rate_limit() -> None:
    upstream = logging.getLogger(FCM_UPSTREAM_LOGGER)
    if not any(isinstance(f, _FcmExcInfoRateLimitFilter) for f in upstream.filters):
        upstream.addFilter(_FcmExcInfoRateLimitFilter())


class FermaxNotificationListener:
    """Manages Firebase Cloud Messaging for Fermax doorbell push notifications."""

    def __init__(
        self,
        hass: HomeAssistant,
        notification_callback: Callable[[dict[str, Any], str], None],
    ) -> None:
        self._hass = hass
        self._notification_callback = notification_callback
        self._credentials: dict[str, Any] | None = None
        self._push_client: FcmPushClient | None = None
        self._fcm_config = FcmRegisterConfig(
            project_id=FIREBASE_PROJECT_ID,
            app_id=FIREBASE_APP_ID,
            api_key=FIREBASE_API_KEY,
            messaging_sender_id=str(FIREBASE_SENDER_ID),
            bundle_id=FIREBASE_PACKAGE_NAME,
        )
        self._store: Store = Store(hass, _FCM_STORAGE_VERSION, _FCM_STORAGE_KEY)
        self._lifecycle_lock = asyncio.Lock()
        self._restart_backoff = FCM_RESTART_BACKOFF_INITIAL
        self._restart_at: float | None = None

    @property
    def fcm_token(self) -> str | None:
        """Return the FCM registration token for push notifications."""
        if self._credentials:
            fcm_reg = self._credentials.get("fcm", {}).get("registration", {})
            token: str | None = fcm_reg.get("token")
            if token:
                return token
            gcm_token: str | None = self._credentials.get("gcm", {}).get("token")
            return gcm_token
        return None

    def _on_credentials_updated(self, new_creds: dict) -> None:
        self._credentials = new_creds
        self._hass.loop.call_soon_threadsafe(
            self._hass.async_create_task,
            self._save_credentials(),
        )

    async def _save_credentials(self) -> None:
        if self._credentials:
            await self._store.async_save(self._credentials)

    async def _load_credentials(self) -> dict | None:
        return await self._store.async_load()

    def _on_notification(
        self,
        notification: dict[str, Any],
        persistent_id: str,
        obj: Any = None,
    ) -> None:
        _LOGGER.debug("Received FCM push notification (id=%s)", persistent_id)
        self._notification_callback(notification, persistent_id)

    async def register(self) -> str | None:
        """Register with Firebase if needed and return the FCM token."""
        self._credentials = await self._load_credentials()

        if not self._credentials:
            _LOGGER.info("Registering new FCM push client with Firebase")
            session = async_get_clientsession(self._hass)
            registerer = FcmRegister(
                config=self._fcm_config,
                credentials_updated_callback=self._on_credentials_updated,
                http_client_session=session,
            )
            for attempt in range(1, 4):
                try:
                    self._credentials = await registerer.register()
                    break
                except Exception as err:
                    if attempt == 3:
                        await registerer.close()
                        raise
                    _LOGGER.warning(
                        "FCM registration attempt %d/3 failed (%s), retrying in 2s...",
                        attempt,
                        err,
                    )
                    await asyncio.sleep(2)

            await self._save_credentials()
            await registerer.close()
            _LOGGER.info("FCM push registration complete")

        return self.fcm_token

    async def start(self) -> None:
        """Start listening for push notifications."""
        async with self._lifecycle_lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        if not self._credentials:
            await self.register()

        if not self._credentials:
            _LOGGER.error("Cannot start FCM listener: no credentials available")
            return

        _install_fcm_log_rate_limit()

        session = async_get_clientsession(self._hass)
        self._push_client = FcmPushClient(
            callback=self._on_notification,
            fcm_config=self._fcm_config,
            credentials=self._credentials,
            credentials_updated_callback=self._on_credentials_updated,
            http_client_session=session,
            config=FcmPushClientConfig(
                abort_on_sequential_error_count=FCM_ABORT_SEQUENTIAL_ERROR_COUNT
            ),
        )

        await self._push_client.start()
        _LOGGER.info("FCM push notification listener started")

    async def stop(self) -> None:
        """Stop listening for push notifications."""
        async with self._lifecycle_lock:
            if self._push_client:
                with contextlib.suppress(Exception):
                    await self._push_client.stop()
                self._push_client = None
                _LOGGER.info("FCM push listener stopped")

    @property
    def is_started(self) -> bool:
        """Return True if listener is active."""
        return self._push_client is not None and self._push_client.is_started()

    async def ensure_running(self) -> bool:
        """Watchdog revival for FCM listener if interrupted."""
        if self.is_started:
            self._restart_backoff = FCM_RESTART_BACKOFF_INITIAL
            self._restart_at = None
            return True

        async with self._lifecycle_lock:
            if self.is_started:
                return True
            if not self._credentials:
                return False

            now = time.monotonic()
            if self._restart_at is None:
                self._restart_at = now + self._restart_backoff
                return False

            if now < self._restart_at:
                return False

            self._restart_at = None
            self._restart_backoff = min(self._restart_backoff * 2, FCM_RESTART_BACKOFF_MAX)

            _LOGGER.warning("FCM listener restart triggered by watchdog")
            if self._push_client is not None:
                with contextlib.suppress(Exception):
                    await self._push_client.stop()
                self._push_client = None

            try:
                await self._start_locked()
                return True
            except Exception as exc:
                _LOGGER.error("Failed to revive FCM listener: %s", exc)
                return False
