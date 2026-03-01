"""GitHub API client for fetching pull request data."""

import base64
import re
from typing import Optional

import requests

_API = "https://api.github.com"


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Extract owner, repo, and PR number from a GitHub PR URL.

    Accepts URLs like:
        https://github.com/owner/repo/pull/123
        https://github.com/owner/repo/pull/123/files
    """
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    return m.group(1), m.group(2), int(m.group(3))


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_pr_metadata(owner: str, repo: str, pr_number: int, token: str) -> dict:
    """Return PR metadata including base/head SHAs and title."""
    url = f"{_API}/repos/{owner}/{repo}/pulls/{pr_number}"
    resp = requests.get(url, headers=_headers(token))
    resp.raise_for_status()
    data = resp.json()
    return {
        "title": data["title"],
        "base_sha": data["base"]["sha"],
        "head_sha": data["head"]["sha"],
        "base_ref": data["base"]["ref"],
        "head_ref": data["head"]["ref"],
    }


def get_pr_files(owner: str, repo: str, pr_number: int, token: str) -> list[dict]:
    """Return list of changed files with their patches.

    Paginates automatically (up to 300 files / 3 pages).
    Each dict has keys: filename, status, patch (may be empty for binary).
    """
    files: list[dict] = []
    page = 1
    while True:
        url = f"{_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        resp = requests.get(
            url, headers=_headers(token), params={"per_page": 100, "page": page}
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for f in batch:
            files.append(
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "patch": f.get("patch", ""),
                    "previous_filename": f.get("previous_filename"),
                }
            )
        if len(batch) < 100:
            break
        page += 1
    return files


def get_file_content(
    owner: str, repo: str, path: str, ref: str, token: str
) -> Optional[str]:
    """Fetch the full text content of a file at a given ref (SHA/branch).

    Returns None if the file doesn't exist at that ref (e.g. newly added file
    when querying base, or deleted file when querying head).
    """
    url = f"{_API}/repos/{owner}/{repo}/contents/{path}"
    resp = requests.get(url, headers=_headers(token), params={"ref": ref})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if data.get("encoding") == "base64" and data.get("content"):
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return ""
