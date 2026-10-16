"""Async REST API client for Fermax Duox Me NOWIFI."""

from __future__ import annotations

import base64
import logging
import time
from urllib.parse import quote
from typing import Any

import httpx

from .const import (
    APP_HEADERS,
    FERMAX_AUTH_BASIC,
    FERMAX_AUTH_URL,
    FERMAX_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)


class FermaxApiError(Exception):
    """General Fermax API error."""


class FermaxAuthError(FermaxApiError):
    """Fermax authentication error."""


class FermaxNowifiApi:
    """Async client implementing the Fermax Duox Me REST API."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        client: httpx.AsyncClient | None = None,
        auth_url: str = FERMAX_AUTH_URL,
        base_url: str = FERMAX_BASE_URL,
        auth_basic: str = FERMAX_AUTH_BASIC,
    ) -> None:
        self._username = username
        self._password = password
        self._auth_url = auth_url
        self._base_url = base_url.rstrip("/")
        self._auth_basic = auth_basic
        self._client = client
        self._own_client = client is None
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    @property
    def is_authenticated(self) -> bool:
        """Return True if currently authenticated with a non-expired token."""
        return bool(self._access_token) and time.time() < self._token_expires_at

    @property
    def access_token(self) -> str:
        """Return current access token."""
        return self._access_token

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
            self._own_client = True
        return self._client

    async def close(self) -> None:
        """Close underlying HTTP client if created internally."""
        if self._own_client and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            **APP_HEADERS,
        }

    async def authenticate(self) -> str:
        """Authenticate with Fermax OAuth2 server using password grant."""
        username_enc = quote(self._username)
        password_enc = quote(self._password)
        payload = f"grant_type=password&password={password_enc}&username={username_enc}"

        headers = {
            "Authorization": self._auth_basic,
            "Content-Type": "application/x-www-form-urlencoded",
            **APP_HEADERS,
        }

        client = await self._get_client()
        try:
            response = await client.post(self._auth_url, headers=headers, content=payload)
        except Exception as exc:
            raise FermaxApiError(f"Connection error to Fermax OAuth server: {exc}") from exc

        if response.status_code == 400 or response.status_code == 401:
            try:
                data = response.json()
                msg = data.get("error_description", data.get("error", "Invalid credentials"))
            except Exception:
                msg = f"HTTP {response.status_code}"
            raise FermaxAuthError(f"Fermax authentication failed: {msg}")

        if response.status_code != 200:
            raise FermaxApiError(f"Fermax OAuth server returned HTTP {response.status_code}")

        data = response.json()
        self._access_token = data.get("access_token", "")
        if not self._access_token:
            raise FermaxApiError("No access_token returned by Fermax OAuth endpoint")

        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.time() + expires_in - 60
        _LOGGER.debug("Successfully authenticated with Fermax Cloud")
        return self._access_token

    async def _ensure_authenticated(self) -> None:
        if not self.is_authenticated:
            await self.authenticate()

    async def _request(
        self, method: str, path: str, *, json_data: Any = None, params: dict | None = None
    ) -> httpx.Response:
        await self._ensure_authenticated()
        client = await self._get_client()
        url = f"{self._base_url}{path}"
        headers = self._get_headers()

        response = await client.request(
            method, url, json=json_data, params=params, headers=headers
        )

        # Token refresh on 401
        if response.status_code == 401:
            _LOGGER.debug("Token expired during request, re-authenticating...")
            await self.authenticate()
            headers = self._get_headers()
            response = await client.request(
                method, url, json=json_data, params=params, headers=headers
            )

        return response

    async def get_pairings(self) -> list[dict[str, Any]]:
        """Fetch paired homes, devices, and door configurations."""
        response = await self._request("GET", "/pairing/api/v4/pairings/me")
        if response.status_code != 200:
            raise FermaxApiError(f"Failed to fetch pairings (HTTP {response.status_code})")
        return response.json()

    async def register_app_token(self, fcm_token: str, active: bool = True) -> bool:
        """Register the FCM token with Fermax Cloud to receive push notifications."""
        app_token_id = f"ha_{fcm_token[:16]}"
        payload = {
            "id": app_token_id,
            "token": fcm_token,
            "appVersion": "4.3.2",
            "locale": "es-ES",
            "os": "ANDROID",
            "osVersion": "14",
            "appBuild": "745",
            "phoneMobile": "Pixel 7",
            "active": active,
            "force": True,
        }
        try:
            response = await self._request(
                "POST", "/notification/api/v2/apptoken", json_data=payload
            )
            return response.status_code in (200, 204)
        except Exception as exc:
            _LOGGER.warning("Exception registering FCM app token: %s", exc)
            return False

    async def auto_on(
        self, panel_id: str, fcm_token: str, house_id: str
    ) -> dict[str, Any] | None:
        """Trigger camera auto-on on the outdoor panel.

        Returns the response dict or None if busy/failed.
        """
        payload = {
            "directedToSippo": None,
            "directedToBluestream": fcm_token,
            "callAs": house_id,
            "pairingType": None,
        }
        try:
            response = await self._request(
                "POST", f"/deviceaction/api/v2/device/{panel_id}/autoon", json_data=payload
            )
            if response.status_code in (200, 204):
                return response.json() if response.content else {"status": "ok"}
            if response.status_code == 409:
                _LOGGER.warning("Outdoor panel is currently busy (HTTP 409)")
                return {"status": "busy", "busy": True}
            _LOGGER.error("autoOn failed: HTTP %s - %s", response.status_code, response.text)
            return None
        except Exception as exc:
            _LOGGER.error("autoOn exception: %s", exc)
            return None

    async def open_door_incall(
        self, panel_id: str, room_id: str, fcm_token: str, house_id: str
    ) -> bool:
        """Open the door while in an active video call or preview session."""
        payload = {
            "deviceId": panel_id,
            "roomId": room_id,
            "appTokenId": fcm_token,
            "unitId": house_id,
        }
        try:
            response = await self._request(
                "POST", "/deviceaction/api/v1/device/incall/opendoor", json_data=payload
            )
            return response.status_code in (200, 204)
        except Exception as exc:
            _LOGGER.warning("Error opening door in-call: %s", exc)
            return False

    async def open_door_nowifi(
        self,
        panel_id: str,
        house_id: str,
        block: int = 0,
        subblock: int = 0,
        number: int = 1,
    ) -> bool:
        """Open door when idle via directOpenDoorNoWifi."""
        url = (
            f"/deviceaction/api/v1/device/{panel_id}/directed-opendoor"
            f"?unitId={house_id}&pairingType=NOWIFI"
        )
        payload = {"block": block, "subblock": subblock, "number": number}
        try:
            response = await self._request("POST", url, json_data=payload)
            if response.status_code in (200, 204):
                return True
        except Exception as exc:
            _LOGGER.debug("directOpenDoorNoWifi failed: %s", exc)

        # Fallback 1: directOpenDoor on monitor
        try:
            resp2 = await self._request(
                "POST", f"/deviceaction/api/v1/device/{house_id}/directed-opendoor", json_data=payload
            )
            if resp2.status_code in (200, 204):
                return True
        except Exception:
            pass

        # Fallback 2: generic /opendoor
        try:
            resp3 = await self._request("POST", f"/deviceaction/api/v1/device/{house_id}/opendoor")
            if resp3.status_code in (200, 204):
                return True
        except Exception:
            pass

        return False

    async def press_f1(self, house_id: str) -> bool:
        """Send F1 courtesy function / auxiliary relay command."""
        try:
            response = await self._request("POST", f"/deviceaction/api/v1/device/{house_id}/f1")
            return response.status_code in (200, 204)
        except Exception as exc:
            _LOGGER.warning("Error triggering F1: %s", exc)
            return False

    async def get_call_photo(self, photo_id: str) -> bytes | None:
        """Fetch and decode the JPEG photo captured during a doorbell ring."""
        try:
            response = await self._request(
                "GET", "/callmanager/api/v1/photocall", params={"photoId": photo_id}
            )
            if response.status_code == 200:
                data = response.json()
                img_data = data.get("image", {}).get("data")
                if img_data:
                    return base64.b64decode(img_data)
        except Exception as exc:
            _LOGGER.debug("Failed to fetch call photo: %s", exc)
        return None

    async def ack_notification(self, message_id: str, *, is_call: bool = False) -> None:
        """Acknowledge receipt of a push notification."""
        path = "/callmanager/api/v1/message/ack" if is_call else "/notification/api/v1/message/ack"
        try:
            await self._request("POST", path, json_data={"attended": True, "fcmMessageId": message_id})
        except Exception:
            pass
