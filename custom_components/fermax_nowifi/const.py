"""Constants for the Fermax NOWIFI integration."""

from __future__ import annotations

DOMAIN = "fermax_nowifi"
MANUFACTURER = "Fermax"
MODEL_NOWIFI = "Duox Me (NOWIFI / 4G Skyline)"

# Platforms supported by fermax_nowifi
PLATFORMS: list[str] = [
    "button",
    "switch",
    "camera",
    "binary_sensor",
    "sensor",
]

# Default stream duration: 1 minute and 5 seconds (65 seconds)
DEFAULT_STREAM_DURATION = 65
MIN_STREAM_DURATION = 10
MAX_STREAM_DURATION = 300

# Doorbell ring reset timer (seconds)
DOORBELL_RESET_SECONDS = 30

# Signal dispatchers
SIGNAL_DOORBELL_RING = f"{DOMAIN}_doorbell_ring_{{}}"
SIGNAL_CALL_ENDED = f"{DOMAIN}_call_ended_{{}}"
SIGNAL_DOOR_OPENED = f"{DOMAIN}_door_opened_{{}}"
SIGNAL_CAMERA_ON = f"{DOMAIN}_camera_on_{{}}"
SIGNAL_CAMERA_OFF = f"{DOMAIN}_camera_off_{{}}"
SIGNAL_FACE_RECOGNIZED = f"{DOMAIN}_face_recognized_{{}}"

# Configuration keys
CONF_HOUSE_ID = "house_id"
CONF_PANEL_ID = "panel_id"
CONF_HOUSE_TAG = "house_tag"
CONF_DOOR_PARAMS = "door_params"
CONF_STREAM_DURATION = "stream_duration"
CONF_FACE_RECOGNITION_ENABLED = "face_recognition_enabled"
CONF_FACE_RECOGNITION_URL = "face_recognition_url"
CONF_FACE_RECOGNITION_THRESHOLD = "face_recognition_threshold"
CONF_FACE_RECOGNITION_AUTO_OPEN = "face_recognition_auto_open"
CONF_FACE_RECOGNITION_COOLDOWN = "face_recognition_cooldown"

DEFAULT_FACE_RECOGNITION_ENABLED = False
DEFAULT_FACE_RECOGNITION_URL = "http://192.168.1.50:8000/api/v1/recognize"
DEFAULT_FACE_RECOGNITION_THRESHOLD = 0.75
DEFAULT_FACE_RECOGNITION_AUTO_OPEN = True
DEFAULT_FACE_RECOGNITION_COOLDOWN = 15

# Fermax Cloud API URLs and credentials
FERMAX_AUTH_URL = "https://oauth-pro-duoxme.fermax.io/oauth/token"
FERMAX_BASE_URL = "https://pro-duoxme.fermax.io"
FERMAX_AUTH_BASIC = (
    "Basic b2U4N3k0bmo2YTJ2ejNoNjNscmg4eTFwOGxwNHpld3JoeW1od2E2bmd6NW94ZjA6"
    "OHIxZThqbzNkazMybzVpMGkxbDg5d2NnYXBwMDVzcDhvc3NycGpueHJvZHYwd3I="
)
DEFAULT_SIGNALING_URL = "https://signaling-pro-duoxme.fermax.io"

# Preconfigured Firebase Cloud Messaging (FCM) credentials for Fermax Blue
FIREBASE_PROJECT_ID = "fermax-blue"
FIREBASE_SENDER_ID = "879268374717"
FIREBASE_APP_ID = "1:879268374717:android:b8e39b52f4a7452b926fd4"
FIREBASE_API_KEY = "AIzaSyAp-B-zKrSwkJqiXoC2K-WCywH8xZ7TKus"
FIREBASE_PACKAGE_NAME = "com.fermax.blue.app"

# App headers matching official Android client
APP_HEADERS = {
    "app-version": "4.3.2",
    "accept-language": "es-ES;q=1.0, en-US;q=0.9",
    "phone-os": "14.0",
    "user-agent": "FermaxBlue/4.3.2 (Android; SDK 36)",
    "phone-model": "HA-FermaxNowifi",
    "app-build": "745",
}
