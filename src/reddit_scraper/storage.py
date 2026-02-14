"""
Data storage using Polars DataFrames.
"""

from typing import Any, Dict, List, Optional

import polars as pl

from .config import Config
from .models import COMMENTS_SCHEMA, POSTS_SCHEMA, RedditComment, RedditPost


class DataStorage:
    """Handle data storage using Polars."""

    def __init__(self, subreddit: str):
        self.subreddit = subreddit
        self.data_dir = Config.get_subreddit_dir(subreddit)
        self.posts_file = self.data_dir / "posts.parquet"
        self.comments_file = self.data_dir / "comments.parquet"

    def save_posts(self, posts: List[RedditPost]) -> int:
        """Save posts to parquet file."""
        if not posts:
            print("No posts to save")
            return 0

        # Convert posts to dictionaries
        post_dicts = [post.to_dict() for post in posts]

        # Create DataFrame
        df = pl.DataFrame(post_dicts, schema=POSTS_SCHEMA, strict=False)

        # Load existing data if it exists
        if self.posts_file.exists():
            existing_df = pl.read_parquet(self.posts_file)
            # Combine and deduplicate
            df = pl.concat([existing_df, df], how="vertical")
            df = df.unique(subset=["id"], keep="last")

        # Sort by created_utc descending
        df = df.sort("created_utc", descending=True)

        # Save to parquet
        df.write_parquet(self.posts_file, compression="zstd")

        print(f"Saved {len(posts)} posts to {self.posts_file}")
        return len(posts)

    def save_comments(self, comments: List[RedditComment]) -> int:
        """Save comments to parquet file."""
        if not comments:
            print("No comments to save")
            return 0

        # Convert comments to dictionaries
        comment_dicts = [comment.to_dict() for comment in comments]

        # Create DataFrame
        df = pl.DataFrame(comment_dicts, schema=COMMENTS_SCHEMA, strict=False)

        # Load existing data if it exists
        if self.comments_file.exists():
            existing_df = pl.read_parquet(self.comments_file)
            # Combine and deduplicate
            df = pl.concat([existing_df, df], how="vertical")
            df = df.unique(subset=["id"], keep="last")

        # Sort by created_utc descending
        df = df.sort("created_utc", descending=True)

        # Save to parquet
        df.write_parquet(self.comments_file, compression="zstd")

        print(f"Saved {len(comments)} comments to {self.comments_file}")
        return len(comments)

    def load_posts(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load posts from parquet file."""
        if not self.posts_file.exists():
            return []

        df = pl.read_parquet(self.posts_file)

        if limit:
            df = df.limit(limit)

        return df.to_dicts()

    def load_comments(
        self, post_id: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Load comments from parquet file."""
        if not self.comments_file.exists():
            return []

        df = pl.read_parquet(self.comments_file)

        if post_id:
            df = df.filter(pl.col("post_id") == post_id)

        if limit:
            df = df.limit(limit)

        return df.to_dicts()

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored data."""
        stats = {
            "subreddit": self.subreddit,
            "posts": 0,
            "comments": 0,
            "data_dir": str(self.data_dir),
        }

        if self.posts_file.exists():
            df = pl.read_parquet(self.posts_file)
            stats["posts"] = len(df)

        if self.comments_file.exists():
            df = pl.read_parquet(self.comments_file)
            stats["comments"] = len(df)

        return stats

    def get_media_stats(self) -> Dict[str, Any]:
        """Get statistics about media files."""
        stats = {"images": 0, "videos": 0, "gifs": 0, "total_files": 0, "total_size_mb": 0.0}

        media_dir = Config.get_media_dir(self.subreddit)
        if not media_dir.exists():
            return stats

        total_size = 0
        for file_path in media_dir.iterdir():
            if file_path.is_file():
                stats["total_files"] += 1
                total_size += file_path.stat().st_size

                ext = file_path.suffix.lower()
                if ext == ".gif":
                    stats["gifs"] += 1
                elif ext in [".mp4", ".webm", ".mov"]:
                    stats["videos"] += 1
                elif ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"]:
                    stats["images"] += 1

        stats["total_size_mb"] = round(total_size / (1024 * 1024), 2)
        return stats
