import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitgood.auth import github_oauth
from gitgood.auth.github_oauth import DeviceCode, DeviceFlowError, DeviceFlowNotConfigured


def test_request_device_code_requires_configured_client_id():
    with patch.object(github_oauth, "CLIENT_ID", "REPLACE_WITH_YOUR_GITHUB_OAUTH_APP_CLIENT_ID"):
        with pytest.raises(DeviceFlowNotConfigured):
            github_oauth.request_device_code()


def test_request_device_code_parses_response():
    with patch.object(github_oauth, "CLIENT_ID", "abc123"), patch("gitgood.auth.github_oauth.requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "device_code": "devcode",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        }
        mock_requests.post.return_value = mock_resp

        code = github_oauth.request_device_code()
        assert code.user_code == "ABCD-1234"
        assert code.device_code == "devcode"


def test_poll_for_token_returns_token_once_authorized():
    code = DeviceCode(device_code="dc", user_code="uc", verification_uri="https://x", interval=0, expires_in=60)
    responses = [{"error": "authorization_pending"}, {"access_token": "gho_xyz"}]

    with patch.object(github_oauth, "CLIENT_ID", "abc123"), patch("gitgood.auth.github_oauth.requests") as mock_requests:
        def post(*args, **kwargs):
            resp = MagicMock()
            resp.json.return_value = responses.pop(0)
            return resp

        mock_requests.post.side_effect = post
        token = github_oauth.poll_for_token(code, threading.Event())
        assert token == "gho_xyz"


def test_poll_for_token_raises_on_access_denied():
    code = DeviceCode(device_code="dc", user_code="uc", verification_uri="https://x", interval=0, expires_in=60)

    with patch.object(github_oauth, "CLIENT_ID", "abc123"), patch("gitgood.auth.github_oauth.requests") as mock_requests:
        resp = MagicMock()
        resp.json.return_value = {"error": "access_denied"}
        mock_requests.post.return_value = resp

        with pytest.raises(DeviceFlowError, match="cancelled"):
            github_oauth.poll_for_token(code, threading.Event())


def test_poll_for_token_stops_when_cancelled():
    code = DeviceCode(device_code="dc", user_code="uc", verification_uri="https://x", interval=0, expires_in=60)
    cancel_event = threading.Event()
    cancel_event.set()

    with patch.object(github_oauth, "CLIENT_ID", "abc123"):
        with pytest.raises(github_oauth.DeviceFlowCancelled):
            github_oauth.poll_for_token(code, cancel_event)
