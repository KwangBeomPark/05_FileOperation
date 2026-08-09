"""Canonical GitHub release repository settings for the installed application.

The standalone ``App05_FileOps`` launcher repeats these two values because it
must remain runnable without importing the application package. A regression
test keeps the launcher copy synchronized with this module.
"""

DEFAULT_GITHUB_OWNER = "KwangBeomPark"
DEFAULT_GITHUB_REPOSITORY = "05_FileOperation"
DEFAULT_GITHUB_REPOSITORY_SLUG = f"{DEFAULT_GITHUB_OWNER}/{DEFAULT_GITHUB_REPOSITORY}"


def latest_release_api_url(owner: str, repository: str) -> str:
    """Return the GitHub API endpoint used for update discovery."""
    return f"https://api.github.com/repos/{owner}/{repository}/releases/latest"


def releases_page_url(owner: str, repository: str, tag: str = "") -> str:
    """Return the public releases page, optionally narrowed to one tag."""
    base_url = f"https://github.com/{owner}/{repository}/releases"
    return f"{base_url}/tag/{tag}" if tag else base_url
