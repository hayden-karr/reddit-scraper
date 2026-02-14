"""
Simple configuration for Reddit scraper.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Simple configuration class."""

    # Reddit API
    REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "")

    # Storage - resolve relative to project root
    _PROJECT_ROOT = Path(__file__).parent.parent.parent
    DATA_DIR = (_PROJECT_ROOT / os.getenv("DATA_DIR", "data")).resolve()

    # Ensure data directory exists
    DATA_DIR.mkdir(exist_ok=True)

    @classmethod
    def get_subreddit_dir(cls, subreddit: str) -> Path:
        """Get directory for subreddit data."""
        subreddit_dir = cls.DATA_DIR / subreddit
        subreddit_dir.mkdir(exist_ok=True)
        return subreddit_dir

    @classmethod
    def get_media_dir(cls, subreddit: str) -> Path:
        """Get directory for subreddit media."""
        media_dir = cls.get_subreddit_dir(subreddit) / "media"
        media_dir.mkdir(exist_ok=True)
        return media_dir
