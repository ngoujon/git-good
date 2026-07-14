"""GitHub OAuth Device Flow -- the "open a browser, approve, done" sign-in
used instead of asking for a manually pasted Personal Access Token.

Requires a GitHub OAuth App (github.com -> Settings -> Developer settings ->
OAuth Apps -> New OAuth App) with "Enable Device Flow" turned on in that
app's settings. Device flow is a public-client flow: only the Client ID is
needed here, no client secret ever has to ship inside this app.

Set CLIENT_ID below once you've created the app.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import requests

CLIENT_ID = "REPLACE_WITH_YOUR_GITHUB_OAUTH_APP_CLIENT_ID"
SCOPE = "repo"

_DEVICE_CODE_URL = "https://github.com/login/device/code"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_REQUEST_TIMEOUT = 15


class DeviceFlowError(Exception):
    pass


class DeviceFlowNotConfigured(DeviceFlowError):
    pass


class DeviceFlowCancelled(Exception):
    pass


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


def request_device_code() -> DeviceCode:
    if not CLIENT_ID or CLIENT_ID.startswith("REPLACE_"):
        raise DeviceFlowNotConfigured(
            "GitGood isn't linked to a GitHub OAuth App yet -- set CLIENT_ID in "
            "gitgood/auth/github_oauth.py (see the module docstring for how to create one)."
        )
    try:
        resp = requests.post(
            _DEVICE_CODE_URL,
            data={"client_id": CLIENT_ID, "scope": SCOPE},
            headers={"Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise DeviceFlowError(f"Could not reach GitHub: {e}") from e
    if "error" in data:
        raise DeviceFlowError(data.get("error_description", data["error"]))
    return DeviceCode(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        interval=data.get("interval", 5),
        expires_in=data.get("expires_in", 900),
    )


def poll_for_token(code: DeviceCode, cancel_event: threading.Event) -> str:
    """Blocks (call this on a background thread) until the user approves the
    request on GitHub, the code expires, they deny it, or `cancel_event` is
    set. Returns the access token on success."""
    interval = code.interval
    deadline = time.monotonic() + code.expires_in
    while time.monotonic() < deadline:
        if cancel_event.wait(interval):
            raise DeviceFlowCancelled()
        try:
            resp = requests.post(
                _TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "device_code": code.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise DeviceFlowError(f"Could not reach GitHub: {e}") from e

        error = data.get("error")
        if error is None:
            return data["access_token"]
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = data.get("interval", interval + 5)
            continue
        if error == "expired_token":
            raise DeviceFlowError("The login code expired before it was approved. Try again.")
        if error == "access_denied":
            raise DeviceFlowError("Sign-in was cancelled on GitHub.")
        raise DeviceFlowError(data.get("error_description", error))

    raise DeviceFlowError("The login code expired before it was approved. Try again.")
