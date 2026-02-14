"""
Data models for Reddit scraper using dataclasses.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import polars as pl

# Schemas for Polars DataFrames
POSTS_SCHEMA = {
    "id": pl.String,
    "title": pl.String,
    "url": pl.String,
    "permalink": pl.String,
    "score": pl.Int64,
    "upvote_ratio": pl.Float32,
    "num_comments": pl.Int64,
    "author": pl.String,
    "selftext": pl.String,
    "created_utc": pl.Float64,
    "is_video": pl.Boolean,
    "has_gallery": pl.Boolean,
    "media_type": pl.String,
    "domain": pl.String,
    "image_url": pl.String,
    "image_path": pl.String,
    "video_url": pl.String,
    "video_path": pl.String,
    "gif_url": pl.String,
    "gif_path": pl.String,
}

COMMENTS_SCHEMA = {
    "id": pl.String,
    "parent_id": pl.String,
    "post_id": pl.String,
    "permalink": pl.String,
    "body": pl.String,
    "score": pl.Int64,
    "author": pl.String,
    "created_utc": pl.Float64,
    "depth": pl.Int32,
    "is_root": pl.Boolean,
    "image_url": pl.String,
    "image_path": pl.String,
    "video_url": pl.String,
    "video_path": pl.String,
    "gif_url": pl.String,
    "gif_path": pl.String,
}


@dataclass
class RedditPost:
    """Reddit post data model."""

    id: str
    title: str
    url: str
    permalink: str
    score: int
    upvote_ratio: float
    num_comments: int
    author: str
    selftext: str
    created_utc: float
    is_video: bool
    has_gallery: bool
    media_type: str
    domain: str
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    video_url: Optional[str] = None
    video_path: Optional[str] = None
    gif_url: Optional[str] = None
    gif_path: Optional[str] = None
    gallery_urls: Optional[List[str]] = None
    gallery_paths: Optional[List[str]] = None

    def __post_init__(self):
        if self.gallery_urls is None:
            self.gallery_urls = []
        if self.gallery_paths is None:
            self.gallery_paths = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class RedditComment:
    """Reddit comment data model."""

    id: str
    parent_id: Optional[str]
    post_id: str
    permalink: str
    body: str
    score: int
    author: str
    created_utc: float
    depth: int
    is_root: bool
    image_url: Optional[str] = None
    image_path: Optional[str] = None
    video_url: Optional[str] = None
    video_path: Optional[str] = None
    gif_url: Optional[str] = None
    gif_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class MediaItem:
    """Media item for deferred download."""

    url: str
    item_id: str
    item_type: str  # 'post' or 'comment'
    media_type: str  # 'image', 'video', 'gif'
    post_id: str  # For comments, this is the parent post ID


@dataclass
class ScrapingResult:
    """Results of a scraping operation."""

    subreddit: str
    posts_count: int = 0
    comments_count: int = 0
    media_items_count: int = 0
    errors: Optional[List[str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
