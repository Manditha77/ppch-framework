"""Fetches a single file's raw content from a public GitHub repo at a specific
commit, without needing a full local clone. Used by the Act layer to retrieve
the actual source of a file a PR touched, so the ILP engine has real code to
analyze (see java_statement_extractor.py)."""

import requests

RAW_BASE = "https://raw.githubusercontent.com"


def fetch_file_at_commit(owner: str, repo: str, commit_sha: str, file_path: str) -> str:
    url = f"{RAW_BASE}/{owner}/{repo}/{commit_sha}/{file_path}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text