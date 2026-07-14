import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github.GithubException import BadCredentialsException

from gitgood.auth.github_api import GitHubAuthError, GitHubClient


def test_current_user_wraps_bad_credentials():
    with patch("gitgood.auth.github_api.Github") as mock_gh_cls:
        mock_gh = MagicMock()
        mock_gh_cls.return_value = mock_gh
        mock_user = MagicMock()
        type(mock_user).login = property(lambda self: (_ for _ in ()).throw(BadCredentialsException(401, {}, {})))
        mock_gh.get_user.return_value = mock_user

        client = GitHubClient("bad-token")
        try:
            client.current_user()
            assert False, "expected GitHubAuthError"
        except GitHubAuthError as e:
            assert "Invalid GitHub token" in str(e)


def test_current_user_wraps_arbitrary_network_errors():
    # Regression test: a raw connection/timeout error (anything that isn't a
    # GithubException) must still come out as GitHubAuthError -- otherwise it
    # escapes uncaught on the background thread and the calling dialog is
    # left stuck on "Validating.../Loading..." forever with no feedback.
    with patch("gitgood.auth.github_api.Github") as mock_gh_cls:
        mock_gh = MagicMock()
        mock_gh_cls.return_value = mock_gh
        mock_user = MagicMock()
        type(mock_user).login = property(lambda self: (_ for _ in ()).throw(ConnectionError("no network")))
        mock_gh.get_user.return_value = mock_user

        client = GitHubClient("some-token")
        try:
            client.current_user()
            assert False, "expected GitHubAuthError"
        except GitHubAuthError as e:
            assert "Could not reach GitHub" in str(e)


def test_list_repos_wraps_arbitrary_network_errors():
    with patch("gitgood.auth.github_api.Github") as mock_gh_cls:
        mock_gh = MagicMock()
        mock_gh_cls.return_value = mock_gh
        mock_gh.get_user.side_effect = TimeoutError("timed out")

        client = GitHubClient("some-token")
        try:
            client.list_repos()
            assert False, "expected GitHubAuthError"
        except GitHubAuthError as e:
            assert "Could not reach GitHub" in str(e)


def test_current_user_returns_plain_dataclass():
    with patch("gitgood.auth.github_api.Github") as mock_gh_cls:
        mock_gh = MagicMock()
        mock_gh_cls.return_value = mock_gh
        mock_user = MagicMock()
        mock_user.login = "octocat"
        mock_user.name = "The Octocat"
        mock_user.avatar_url = "https://example.com/avatar.png"
        mock_gh.get_user.return_value = mock_user

        client = GitHubClient("good-token")
        user = client.current_user()
        assert user.login == "octocat"
        assert user.name == "The Octocat"
