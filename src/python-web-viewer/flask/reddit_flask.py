"""
Reddit Subreddit Data Viewer - Flask Backend

Clean Flask application for viewing scraped Reddit data with media support.
"""

import os
from datetime import datetime
from math import ceil
from typing import Dict, List, Optional

import polars as pl
from flask import Flask, jsonify, render_template, send_from_directory

from reddit_scraper.config import Config


class RedditDataManager:
    """Manager for Reddit data with media support."""

    def __init__(self, subreddit_name: str):
        """Initialize the Reddit data manager."""
        self.subreddit_name = subreddit_name
        self.subreddit_dir = Config.get_subreddit_dir(subreddit_name)
        self.posts_file = self.subreddit_dir / "posts.parquet"
        self.comments_file = self.subreddit_dir / "comments.parquet"
        self.media_dir = Config.get_media_dir(subreddit_name)

        os.makedirs(self.media_dir, exist_ok=True)

        self._posts_cache = None
        self._comments_cache = None

    def _extract_filename(self, path: Optional[str]) -> Optional[str]:
        """Extract filename from a path."""
        if not path:
            return None
        return path.split("\\")[-1] if "\\" in path else path.split("/")[-1]

    def _format_timestamp(self, utc_timestamp: float) -> str:
        """Convert UTC timestamp to readable format."""
        try:
            dt = datetime.fromtimestamp(utc_timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            return str(utc_timestamp)

    def _get_media_type(self, filename: str) -> str:
        """Determine media type from filename - simplified version."""
        if not filename:
            return "none"

        filename_lower = filename.lower()

        if any(ext in filename_lower for ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"]):
            return "image"
        elif ".gif" in filename_lower:
            return "gif"
        elif filename_lower.endswith(".webm"):
            # Simple check for GIF-converted WebM
            return "gif" if "gif" in filename_lower else "video"
        elif any(ext in filename_lower for ext in [".mp4", ".mov", ".avi"]):
            return "video"
        else:
            return "image"  # Default fallback

    def _extract_gallery_info(self, post_id: str) -> Optional[Dict]:
        """Extract gallery information by scanning media directory."""
        gallery_items = []

        # Look for gallery files matching pattern: {post_id}_gallery_01, {post_id}_gallery_02, etc.
        for file_path in self.media_dir.glob(f"{post_id}_gallery_*"):
            filename = file_path.name

            # Extract index from filename (e.g., "abc123_gallery_01.jpg" -> 1)
            try:
                index_part = filename.split("_gallery_")[1].split(".")[0]
                index = int(index_part)
            except (IndexError, ValueError):
                continue

            gallery_items.append(
                {
                    "filename": filename,
                    "index": index,
                    "type": self._get_media_type(filename),
                }
            )

        # Also check for GIF gallery items: gif_{post_id}_gallery_01.webm
        for file_path in self.media_dir.glob(f"gif_{post_id}_gallery_*.webm"):
            filename = file_path.name

            try:
                index_part = filename.split("_gallery_")[1].split(".")[0]
                index = int(index_part)
            except (IndexError, ValueError):
                continue

            gallery_items.append(
                {
                    "filename": filename,
                    "index": index,
                    "type": "gif",
                }
            )

        if not gallery_items:
            return None

        # Sort by index
        gallery_items.sort(key=lambda x: x["index"])

        return {"items": gallery_items, "count": len(gallery_items)}

    def load_posts(self) -> Optional[pl.DataFrame]:
        """Load posts from parquet file with caching."""
        if self._posts_cache is None and self.posts_file.exists():
            self._posts_cache = pl.read_parquet(self.posts_file)
        return self._posts_cache

    def load_comments(self) -> Optional[pl.DataFrame]:
        """Load comments from parquet file with caching."""
        if self._comments_cache is None and self.comments_file.exists():
            self._comments_cache = pl.read_parquet(self.comments_file)
        return self._comments_cache

    def format_comments(
        self, comments: pl.DataFrame, post_id: str, is_post: bool = True
    ) -> List[Dict]:
        """Format comments and their replies recursively."""
        if is_post:
            # Polars requires == True (not `is True` or bare col), hence noqa
            replies = comments.filter(
                (pl.col("post_id") == post_id) & (pl.col("is_root") == True)  # noqa: E712
            )
        else:
            replies = comments.filter(pl.col("parent_id") == post_id)

        formatted_comments = []
        for comment in replies.iter_rows(named=True):
            comment_id = comment["id"]

            # Reconstruct media from media directory
            media_filename = None
            media_type = "none"

            # Check for gif: gif_{comment_id}.webm
            gif_files = list(self.media_dir.glob(f"gif_{comment_id}.*"))
            if gif_files:
                media_filename = gif_files[0].name
                media_type = "gif"
            else:
                # Check for video: video_{comment_id}.*
                video_files = list(self.media_dir.glob(f"video_{comment_id}.*"))
                if video_files:
                    media_filename = video_files[0].name
                    media_type = "video"
                else:
                    # Check for image: {comment_id}.*
                    image_extensions = ["jpg", "jpeg", "png", "webp", "avif"]
                    for ext in image_extensions:
                        image_files = list(self.media_dir.glob(f"{comment_id}.{ext}"))
                        if image_files:
                            media_filename = image_files[0].name
                            media_type = "image"
                            break

            formatted_comment = {
                "comment_id": comment_id,
                "text": comment["body"],
                "image": media_filename,
                "image_type": media_type,
                "replies": self.format_comments(comments, comment_id, is_post=False),
            }
            formatted_comments.append(formatted_comment)

        return formatted_comments

    def get_comments_for_post(self, post_id: str) -> List[Dict]:
        """Get comments for a specific post."""
        comments = self.load_comments()
        if comments is None:
            return []
        return self.format_comments(comments, post_id, is_post=True)

    def get_chunked_posts(self, chunk: int, chunk_size: int) -> Dict:
        """Get a chunk of posts with streamlined media information."""
        posts = self.load_posts()
        comments = self.load_comments()

        if posts is None:
            return {"id": chunk, "posts": []}

        start_idx = (chunk - 1) * chunk_size
        end_idx = start_idx + chunk_size

        # Select only the columns we need
        chunked_posts = (
            posts[start_idx:end_idx]
            .select(
                [
                    "id",
                    "title",
                    "selftext",
                    "created_utc",
                ]
            )
            .to_dicts()
        )

        formatted_posts = []
        for post in chunked_posts:
            # Count comments without loading/formatting them
            comment_count = 0
            if comments is not None:
                comment_count = len(comments.filter(pl.col("post_id") == post["id"]))

            # Reconstruct media info from media directory
            media_info = self._get_media_info(post["id"])

            formatted_post = {
                "id": post["id"],
                "title": post["title"],
                "text": post["selftext"],
                "created_time": self._format_timestamp(post["created_utc"]),
                "commentCount": comment_count,
                "media": media_info,
            }

            formatted_posts.append(formatted_post)

        return {"id": chunk, "posts": formatted_posts}

    def _get_media_info(self, post_id: str) -> Dict:
        """Get media information by scanning media directory."""
        # Check for gallery first
        gallery_info = self._extract_gallery_info(post_id)
        if gallery_info and gallery_info["count"] > 0:
            return {
                "type": "gallery",
                "gallery": gallery_info,
            }

        # Check for GIF: gif_{post_id}.webm
        gif_files = list(self.media_dir.glob(f"gif_{post_id}.*"))
        if gif_files:
            return {
                "type": "gif",
                "gif": {"filename": gif_files[0].name},
            }

        # Check for video: video_{post_id}.* or {post_id}.webm or {post_id}.mp4
        video_files = list(self.media_dir.glob(f"video_{post_id}.*"))
        if not video_files:
            video_files = list(self.media_dir.glob(f"{post_id}.webm"))
        if not video_files:
            video_files = list(self.media_dir.glob(f"{post_id}.mp4"))
        if video_files:
            return {
                "type": "video",
                "video": {"filename": video_files[0].name},
            }

        # Check for image: {post_id}.* (any image extension)
        image_extensions = ["jpg", "jpeg", "png", "webp", "avif"]
        for ext in image_extensions:
            image_files = list(self.media_dir.glob(f"{post_id}.{ext}"))
            if image_files:
                return {
                    "type": "image",
                    "image": {"filename": image_files[0].name},
                }

        # Check for imgur: {post_id}_imgur.*
        imgur_files = list(self.media_dir.glob(f"{post_id}_imgur.*"))
        if imgur_files:
            return {
                "type": "image",
                "image": {"filename": imgur_files[0].name},
            }

        # Check for original: {post_id}_original.*
        original_files = list(self.media_dir.glob(f"{post_id}_original.*"))
        if original_files:
            return {
                "type": "image",
                "image": {"filename": original_files[0].name},
            }

        return {"type": "none"}

    def get_total_chunks(self, chunk_size: int) -> int:
        """Calculate total number of chunks based on post count."""
        posts = self.load_posts()
        if posts is None:
            return 0
        return ceil(len(posts) / chunk_size)


def create_app(subreddit_name: str, chunk_size: int) -> Flask:
    """Create the Flask application."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

    data_manager = RedditDataManager(subreddit_name)

    @app.route("/")
    def index():
        """Render the main page."""
        return render_template("index.html", subreddit=subreddit_name)

    @app.route("/media/<filename>")
    def serve_media(filename):
        """Serve media files."""
        return send_from_directory(data_manager.media_dir, filename)

    @app.route("/api/chunks/<int:chunk>")
    def get_chunked_posts(chunk):
        """Get posts for a specific chunk."""
        chunk_data = data_manager.get_chunked_posts(chunk, chunk_size)
        if not chunk_data["posts"]:
            return jsonify({"error": "No posts found."}), 404
        return jsonify(chunk_data)

    @app.route("/api/chunks/count")
    def get_total_chunks():
        """Get total number of chunks."""
        total_chunks = data_manager.get_total_chunks(chunk_size)
        if total_chunks == 0:
            return jsonify({"error": "No posts found."}), 404
        return jsonify({"count": total_chunks})

    @app.route("/api/comments/<post_id>")
    def get_comments(post_id):
        """Get comments for a specific post."""
        comments = data_manager.get_comments_for_post(post_id)
        return jsonify({"comments": comments})

    return app
