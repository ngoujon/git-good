"""Thin PyGithub wrapper returning plain dataclasses (never PyGithub objects),
so results can safely cross the thread boundary like everything in git_ops."""
from __future__ import annotations

from dataclasses import dataclass

from github import Auth, Github
from github.GithubException import BadCredentialsException, GithubException


class GitHubAuthError(Exception):
    pass


@dataclass
class GitHubUser:
    login: str
    name: str | None
    avatar_url: str


@dataclass
class GitHubRepo:
    full_name: str
    clone_url: str
    private: bool
    description: str | None
    updated_at: str
    default_branch: str


class GitHubClient:
    def __init__(self, token: str):
        self._gh = Github(auth=Auth.Token(token))

    def current_user(self) -> GitHubUser:
        try:
            u = self._gh.get_user()
            login = u.login  # triggers the API call; raises if the token is bad
            return GitHubUser(login=login, name=u.name, avatar_url=u.avatar_url)
        except BadCredentialsException as e:
            raise GitHubAuthError("Invalid GitHub token") from e
        except GithubException as e:
            raise GitHubAuthError(f"GitHub API error: {e}") from e
        except Exception as e:  # noqa: BLE001 - network/DNS/timeout errors etc. must never escape as a raw
            # exception: this runs on a background thread, so an uncaught error here
            # silently kills the thread and leaves the caller's dialog stuck loading forever.
            raise GitHubAuthError(f"Could not reach GitHub: {e}") from e

    def list_repos(self) -> list[GitHubRepo]:
        try:
            user = self._gh.get_user()
            return [
                GitHubRepo(
                    full_name=r.full_name,
                    clone_url=r.clone_url,
                    private=r.private,
                    description=r.description,
                    updated_at=r.updated_at.isoformat() if r.updated_at else "",
                    default_branch=r.default_branch,
                )
                for r in user.get_repos(sort="updated")
            ]
        except GithubException as e:
            raise GitHubAuthError(f"Could not list repositories: {e}") from e
        except Exception as e:  # noqa: BLE001 - see current_user()
            raise GitHubAuthError(f"Could not reach GitHub: {e}") from e
