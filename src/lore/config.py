"""Central configuration for Lore, loaded from environment variables.

Nothing here is hardcoded to a specific repo, model, or workspace — every
deployment of Lore points itself at a different GitHub repo, working
directory, and Slack/Teams destination via .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    github_token: str | None
    github_repo: str | None

    aws_region: str
    bedrock_chat_model_id: str
    bedrock_embed_model_id: str

    slack_bot_token: str | None
    slack_signing_secret: str | None
    slack_app_token: str | None
    slack_flags_channel: str

    teams_incoming_webhook_url: str | None

    watch_repo_path: str | None
    data_dir: Path
    api_port: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lore.sqlite3"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("LORE_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        github_token=os.environ.get("GITHUB_TOKEN") or None,
        github_repo=os.environ.get("GITHUB_REPO") or None,
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        bedrock_chat_model_id=os.environ.get(
            "BEDROCK_CHAT_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
        ),
        bedrock_embed_model_id=os.environ.get(
            "BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"
        ),
        slack_bot_token=os.environ.get("SLACK_BOT_TOKEN") or None,
        slack_signing_secret=os.environ.get("SLACK_SIGNING_SECRET") or None,
        slack_app_token=os.environ.get("SLACK_APP_TOKEN") or None,
        slack_flags_channel=os.environ.get("SLACK_FLAGS_CHANNEL", "#lore-flags"),
        teams_incoming_webhook_url=os.environ.get("TEAMS_INCOMING_WEBHOOK_URL") or None,
        watch_repo_path=os.environ.get("WATCH_REPO_PATH") or None,
        data_dir=data_dir,
        api_port=int(os.environ.get("LORE_API_PORT", "8000")),
    )


settings = load_settings()
