"""Pulls a GitHub repo's commits, pull requests, and issues into normalized
`HistoryItem` records ready for chunking and indexing.

Works against any owner/repo — nothing here is specific to one project.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Literal

import httpx

GITHUB_API = "https://api.github.com"

ItemKind = Literal["commit", "pull_request", "issue"]


@dataclass
class HistoryItem:
    kind: ItemKind
    id: str  # stable id, e.g. "pr:owner/repo#123" or "commit:sha"
    title: str
    body: str
    author: str
    created_at: datetime
    url: str
    file_paths: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Flatten into a single text blob for embedding."""
        parts = [f"[{self.kind}] {self.title}"]
        if self.body:
            parts.append(self.body.strip())
        if self.file_paths:
            parts.append("Files touched: " + ", ".join(self.file_paths))
        return "\n\n".join(parts)


class GitHubIngestor:
    def __init__(self, repo: str, token: str | None = None, per_page: int = 100):
        """`repo` is any "owner/name" string, e.g. "octocat/hello-world"."""
        self.repo = repo
        self.per_page = per_page
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(base_url=GITHUB_API, headers=headers, timeout=30.0)

    def close(self) -> None:
        self.client.close()

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        params = dict(params or {})
        params["per_page"] = self.per_page
        page = 1
        while True:
            params["page"] = page
            resp = self.client.get(path, params=params)
            if resp.status_code in (403, 429) and (
                "rate limit" in resp.text.lower() or resp.status_code == 429
            ):
                reset = resp.headers.get("X-RateLimit-Reset")
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait = int(retry_after)
                elif reset:
                    wait = max(1, int(reset) - int(time.time()))
                else:
                    wait = 30
                time.sleep(min(wait, 120))
                continue
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                return
            yield from batch
            if len(batch) < self.per_page:
                return
            page += 1

    def iter_commits(self, max_items: int | None = None) -> Iterator[HistoryItem]:
        count = 0
        for c in self._paginate(f"/repos/{self.repo}/commits"):
            sha = c["sha"]
            commit = c.get("commit", {})
            author = (commit.get("author") or {}).get("name") or (c.get("author") or {}).get("login") or "unknown"
            message = commit.get("message", "")
            title, _, body = message.partition("\n")
            created_at = _parse_dt(commit.get("author", {}).get("date"))

            files = []
            try:
                detail = self.client.get(f"/repos/{self.repo}/commits/{sha}").json()
                files = [f["filename"] for f in detail.get("files", [])]
            except Exception:
                pass

            yield HistoryItem(
                kind="commit",
                id=f"commit:{sha}",
                title=title.strip(),
                body=body.strip(),
                author=author,
                created_at=created_at,
                url=c.get("html_url", ""),
                file_paths=files,
            )
            count += 1
            if max_items and count >= max_items:
                return

    def get_pull_request_files(self, pr_number: int) -> list[dict]:
        """Returns [{filename, patch}] for a PR — patch is the unified diff text
        (absent for binary/very large files, which GitHub omits it for)."""
        resp = self.client.get(f"/repos/{self.repo}/pulls/{pr_number}/files")
        resp.raise_for_status()
        return [{"filename": f["filename"], "patch": f.get("patch", "")} for f in resp.json()]

    def post_pull_request_comment(self, pr_number: int, body: str) -> dict:
        """Posts a plain (non-inline) comment on a PR via the issues comments
        endpoint — PRs are issues under the hood in the GitHub API."""
        resp = self.client.post(f"/repos/{self.repo}/issues/{pr_number}/comments", json={"body": body})
        resp.raise_for_status()
        return resp.json()

    def get_pull_request_meta(self, pr_number: int) -> dict:
        resp = self.client.get(f"/repos/{self.repo}/pulls/{pr_number}")
        resp.raise_for_status()
        pr = resp.json()
        return {"title": pr.get("title", ""), "url": pr.get("html_url", ""), "author": (pr.get("user") or {}).get("login", "unknown")}

    def iter_pull_requests(self, max_items: int | None = None) -> Iterator[HistoryItem]:
        count = 0
        for pr in self._paginate(f"/repos/{self.repo}/pulls", params={"state": "all"}):
            number = pr["number"]
            files = []
            try:
                files = [f["filename"] for f in self.client.get(f"/repos/{self.repo}/pulls/{number}/files").json()]
            except Exception:
                pass

            comments_text = ""
            try:
                comments = self.client.get(f"/repos/{self.repo}/issues/{number}/comments").json()
                comments_text = "\n".join(f"- {c['user']['login']}: {c['body']}" for c in comments if isinstance(c, dict) and "body" in c)
            except Exception:
                pass

            body = (pr.get("body") or "").strip()
            if comments_text:
                body = f"{body}\n\nDiscussion:\n{comments_text}"

            yield HistoryItem(
                kind="pull_request",
                id=f"pr:{self.repo}#{number}",
                title=pr.get("title", ""),
                body=body,
                author=(pr.get("user") or {}).get("login", "unknown"),
                created_at=_parse_dt(pr.get("created_at")),
                url=pr.get("html_url", ""),
                file_paths=files,
            )
            count += 1
            if max_items and count >= max_items:
                return

    def iter_issues(self, max_items: int | None = None) -> Iterator[HistoryItem]:
        count = 0
        for issue in self._paginate(f"/repos/{self.repo}/issues", params={"state": "all"}):
            if "pull_request" in issue:
                continue  # PRs also show up in the issues endpoint; skip duplicates

            comments_text = ""
            try:
                comments = self.client.get(issue["comments_url"]).json()
                comments_text = "\n".join(f"- {c['user']['login']}: {c['body']}" for c in comments if isinstance(c, dict) and "body" in c)
            except Exception:
                pass

            body = (issue.get("body") or "").strip()
            if comments_text:
                body = f"{body}\n\nDiscussion:\n{comments_text}"

            yield HistoryItem(
                kind="issue",
                id=f"issue:{self.repo}#{issue['number']}",
                title=issue.get("title", ""),
                body=body,
                author=(issue.get("user") or {}).get("login", "unknown"),
                created_at=_parse_dt(issue.get("created_at")),
                url=issue.get("html_url", ""),
            )
            count += 1
            if max_items and count >= max_items:
                return

    def iter_all(self, max_per_kind: int | None = None) -> Iterator[HistoryItem]:
        yield from self.iter_commits(max_per_kind)
        yield from self.iter_pull_requests(max_per_kind)
        yield from self.iter_issues(max_per_kind)


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
