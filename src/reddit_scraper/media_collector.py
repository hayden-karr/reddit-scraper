"""
Updated media collector using modular media handlers.
"""

import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from .config import Config
from .media.galleries import GalleryHandler
from .media.gif import GifHandler

# Import modular handlers
from .media.images import ImageHandler
from .media.imgur import ImgurHandler
from .media.video import VideoHandler
from .models import MediaItem, RedditComment, RedditPost


class MediaCollector:
    """Enhanced media collector using modular handlers for each media type."""

    def __init__(self, subreddit: str):
        self.subreddit = subreddit
        self.media_dir = Config.get_media_dir(subreddit)

        # Initialize all media handlers
        self.image_handler = ImageHandler(subreddit)
        self.gif_handler = GifHandler(subreddit)
        self.video_handler = VideoHandler(subreddit)
        self.imgur_handler = ImgurHandler(subreddit)
        self.gallery_handler = GalleryHandler(subreddit)

        # General session for URL extraction
        self.session = requests.Session()

    def extract_media_urls(
        self, posts: List[RedditPost], comments: List[RedditComment]
    ) -> List[MediaItem]:
        """Extract all media URLs from posts and comments."""
        media_items = []

        # Extract from posts (including galleries)
        for post in posts:
            items = self._extract_from_post(post)
            media_items.extend(items)

        # Extract from comments
        for comment in comments:
            items = self._extract_from_comment(comment)
            media_items.extend(items)

        print(f"Extracted {len(media_items)} media items")
        return media_items

    def _extract_from_post(self, post: RedditPost) -> List[MediaItem]:
        """Extract media URLs from a post including galleries."""
        items = []

        # Handle galleries first (highest priority)
        if post.has_gallery and hasattr(post, "gallery_urls") and post.gallery_urls:
            gallery_urls = post.gallery_urls
            print(f"Found gallery with {len(gallery_urls)} items in post {post.id}")
            for i, gallery_url in enumerate(gallery_urls):
                if self._is_media_url(gallery_url):
                    media_type = self._get_media_type(gallery_url)
                    items.append(
                        MediaItem(
                            url=gallery_url,
                            item_id=f"{post.id}_gallery_{i + 1:02d}",
                            item_type="post",
                            media_type=media_type,
                            post_id=post.id,
                        )
                    )
            return items  # Return only gallery items for gallery posts

        # Handle main post URL
        if post.url and self._is_media_url(post.url):
            media_type = self._get_media_type(post.url)
            items.append(
                MediaItem(
                    url=post.url,
                    item_id=post.id,
                    item_type="post",
                    media_type=media_type,
                    post_id=post.id,
                )
            )

        # Handle selftext URLs
        if post.selftext:
            urls = self._extract_urls_from_text(post.selftext)
            for url in urls:
                if self._is_media_url(url):
                    media_type = self._get_media_type(url)
                    items.append(
                        MediaItem(
                            url=url,
                            item_id=f"{post.id}_text",
                            item_type="post",
                            media_type=media_type,
                            post_id=post.id,
                        )
                    )

        return items

    def _extract_from_comment(self, comment: RedditComment) -> List[MediaItem]:
        """Extract media URLs from a comment."""
        items = []

        if comment.body:
            urls = self._extract_urls_from_text(comment.body)
            for url in urls:
                if self._is_media_url(url):
                    media_type = self._get_media_type(url)
                    items.append(
                        MediaItem(
                            url=url,
                            item_id=comment.id,
                            item_type="comment",
                            media_type=media_type,
                            post_id=comment.post_id,
                        )
                    )

        return items

    def _extract_urls_from_text(self, text: str) -> List[str]:
        """Extract URLs from text using regex."""
        url_pattern = r'https?://[^\s)"]+'
        return re.findall(url_pattern, text)

    def _is_media_url(self, url: str) -> bool:
        """Check if URL points to media content."""
        if not url:
            return False

        try:
            # Basic URL validation first
            parsed = urlparse(url)
            if not parsed.netloc or not parsed.scheme:
                print(f"Skipping invalid URL (no scheme/netloc): {url}")
                return False

            # Check for IPv6 issues or other malformed URLs
            if "[" in url and "]" not in url:
                print(f"Skipping malformed IPv6 URL: {url}")
                return False

        except Exception as e:
            print(f"Skipping URL due to parsing error: {url} - {e}")
            return False

        # Check for imgur
        if self.imgur_handler.is_imgur_url(url):
            return True

        # Check for direct media URLs
        url_lower = url.lower()
        image_extensions = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
        video_extensions = (".mp4", ".webm", ".mov")

        if any(url_lower.endswith(ext) for ext in image_extensions + video_extensions):
            return True

        # Check for known media domains
        parsed = urlparse(url)
        media_domains = {
            "i.redd.it",
            "v.redd.it",
            "i.imgur.com",
            "imgur.com",
            "gfycat.com",
            "tenor.com",
            "preview.redd.it",
            "external-preview.redd.it",
        }

        return parsed.netloc in media_domains

    def _get_media_type(self, url: str) -> str:
        """Determine media type from URL."""

        url_lower = url.lower()

        # Video URLs
        if any(ext in url_lower for ext in [".mp4", ".webm", ".mov"]) or "v.redd.it" in url_lower:
            return "video"

        # GIF URLs
        if any(ext in url_lower for ext in [".gif", ".gifv"]) or "gif" in url_lower:
            return "gif"

        # Default to image
        return "image"

    async def download_all_media(self, media_items: List[MediaItem]) -> Dict[str, Any]:
        """Download all media using async handlers."""
        import asyncio

        # Categorize media items
        categorized_items = {"imgur": [], "reddit_videos": [], "gifs": [], "images": []}

        for item in media_items:
            if self.imgur_handler.is_imgur_url(item.url):
                categorized_items["imgur"].append(item)
            elif item.media_type == "video":
                categorized_items["reddit_videos"].append(item)
            elif item.media_type == "gif":
                categorized_items["gifs"].append(item)
            else:
                categorized_items["images"].append(item)

        results: Dict[str, Any] = {}

        # Process all types concurrently using async handlers
        tasks = []

        if categorized_items["imgur"]:
            print(f"Processing {len(categorized_items['imgur'])} imgur items...")
            urls_ids = [(item.url, item.item_id) for item in categorized_items["imgur"]]
            tasks.append(("imgur", self.imgur_handler.batch_download(urls_ids)))

        if categorized_items["reddit_videos"]:
            print(f"Processing {len(categorized_items['reddit_videos'])} Reddit videos...")
            urls_ids = [(item.url, item.item_id) for item in categorized_items["reddit_videos"]]
            tasks.append(("videos", self.video_handler.batch_process(urls_ids)))

        if categorized_items["gifs"]:
            print(f"Processing {len(categorized_items['gifs'])} GIFs...")
            urls_ids = [(item.url, item.item_id) for item in categorized_items["gifs"]]
            tasks.append(("gifs", self.gif_handler.batch_convert(urls_ids)))

        if categorized_items["images"]:
            print(f"Processing {len(categorized_items['images'])} images...")
            urls_ids = [(item.url, item.item_id) for item in categorized_items["images"]]
            tasks.append(("images", self.image_handler.batch_convert(urls_ids)))

        # Run all media processing concurrently
        if tasks:
            completed_results = await asyncio.gather(
                *[task[1] for task in tasks], return_exceptions=True
            )

            for (media_type, _), result in zip(tasks, completed_results):
                if isinstance(result, Exception):
                    print(f"{media_type} processing error: {result}")
                    # Create error result dict
                    results[media_type] = {"downloaded": 0, "skipped": 0, "failed": 0, "total": 0}
                elif isinstance(result, dict):
                    # Store the full result dict
                    results[media_type] = result

        return results

    def process_galleries(self, posts: List[RedditPost]) -> Dict[str, List[str]]:
        """Process gallery posts separately for better organization."""
        gallery_posts = [
            post
            for post in posts
            if post.has_gallery and hasattr(post, "gallery_urls") and post.gallery_urls
        ]

        if not gallery_posts:
            print("No gallery posts to process")
            return {"processed": [], "failed": []}

        print(f"Processing {len(gallery_posts)} gallery posts...")

        results = {"processed": [], "failed": []}

        for post in gallery_posts:
            try:
                if not post.gallery_urls:
                    continue
                gallery_results = self.gallery_handler.process_gallery(post.gallery_urls, post.id)

                # Track all successful items
                success_count = len(gallery_results["images"]) + len(gallery_results["gifs"])
                if success_count > 0:
                    results["processed"].extend(gallery_results["images"])
                    results["processed"].extend(gallery_results["gifs"])

                # Track failures
                results["failed"].extend(gallery_results["failed"])

            except Exception as e:
                print(f"Gallery processing error for post {post.id}: {e}")
                if hasattr(post, "gallery_urls") and post.gallery_urls:
                    results["failed"].extend(post.gallery_urls)

        print(f"Gallery processing complete: {len(results['processed'])} items processed")
        return results

    def update_posts_with_paths(
        self, posts: List[RedditPost], download_results: Dict[str, Any]
    ) -> List[RedditPost]:
        """Update post objects with downloaded media paths."""
        # Create mapping from item_id to path with better filename parsing
        id_to_path = {}

        for media_type, result_dict in download_results.items():
            # Extract success paths from result dict
            if not isinstance(result_dict, dict):
                continue
            paths = result_dict.get("success_paths", [])
            for path in paths:
                filename = Path(path).stem

                # Extract item_id based on different naming patterns
                if filename.startswith("gif_") and "_gallery_" in filename:
                    # gif_postid_gallery_01.webm -> postid_gallery_01
                    item_id = filename[4:]  # Remove 'gif_' prefix
                elif "_gallery_" in filename:
                    item_id = filename  # Keep full gallery ID (for regular images)
                elif filename.startswith("video_"):
                    # video_{item_id}.webm -> item_id
                    item_id = filename[6:]  # Remove 'video_' prefix
                elif filename.startswith("gif_"):
                    # gif_{item_id}.webm -> item_id
                    item_id = filename[4:]  # Remove 'gif_' prefix
                elif "_imgur" in filename:
                    # {item_id}_imgur.ext -> item_id
                    item_id = filename.split("_imgur")[0]
                elif filename.endswith("_original"):
                    # {item_id}_original.ext -> item_id
                    item_id = filename.replace("_original", "")
                else:
                    # Default case: {item_id}.ext
                    item_id = filename

                id_to_path[item_id] = path

        # Update posts
        for post in posts:
            # Handle gallery posts
            if post.has_gallery and hasattr(post, "gallery_urls") and post.gallery_urls:
                gallery_urls = post.gallery_urls
                gallery_paths = []
                for i, gallery_url in enumerate(gallery_urls):
                    gallery_id = f"{post.id}_gallery_{i + 1:02d}"
                    if gallery_id in id_to_path:
                        gallery_paths.append(id_to_path[gallery_id])

                        # Set individual URL fields based on original URL
                        if not post.image_url and not post.video_url and not post.gif_url:
                            if (
                                "#reddit_gif" in gallery_url.lower()
                                or ".gif" in gallery_url.lower()
                            ):
                                post.gif_url = gallery_url.replace("#reddit_gif", "")
                            else:
                                post.image_url = gallery_url

                if gallery_paths:
                    # Set the first gallery item as the main media and store all gallery paths
                    main_path = gallery_paths[0]
                    post.gallery_paths = gallery_paths  # Store all gallery paths

                    filename = Path(main_path).name.lower()
                    if main_path.endswith(".webm") or filename.startswith("gif_"):
                        post.gif_path = main_path
                    elif main_path.endswith((".mp4")):
                        post.video_path = main_path
                    else:
                        post.image_path = main_path
                continue

            # Handle regular posts - check main media
            if post.id in id_to_path:
                path = id_to_path[post.id]
                filename = Path(path).name.lower()

                if path.endswith(".webm") and filename == f"{post.id.lower()}.webm":
                    post.video_path = path
                    if not post.video_url:
                        post.video_url = post.url
                elif filename.startswith("gif_") and path.endswith(".webm"):
                    post.gif_path = path
                    if not post.gif_url:
                        post.gif_url = post.url
                elif path.endswith(".gif"):
                    post.gif_path = path
                    if not post.gif_url:
                        post.gif_url = post.url
                elif filename.startswith("video_") or path.endswith((".mp4")):
                    post.video_path = path
                    if not post.video_url:
                        post.video_url = post.url
                else:
                    post.image_path = path
                    if not post.image_url:
                        post.image_url = post.url

            # Check text media
            text_id = f"{post.id}_text"
            if text_id in id_to_path:
                path = id_to_path[text_id]
                if not post.image_path and not post.video_path and not post.gif_path:
                    filename = Path(path).name.lower()
                    if filename.startswith("gif_") or path.endswith(".webm"):
                        post.gif_path = path
                    elif filename.startswith("video_") or path.endswith((".mp4")):
                        post.video_path = path
                    else:
                        post.image_path = path

        return posts

    def update_comments_with_paths(
        self, comments: List[RedditComment], download_results: Dict[str, Any]
    ) -> List[RedditComment]:
        """Update comment objects with downloaded media paths."""
        # Create mapping from item_id to path with better filename parsing
        id_to_path = {}

        for media_type, result_dict in download_results.items():
            # Extract success paths from result dict
            if not isinstance(result_dict, dict):
                continue
            paths = result_dict.get("success_paths", [])
            for path in paths:
                filename = Path(path).stem

                # Extract item_id based on different naming patterns
                if filename.startswith("video_"):
                    item_id = filename[6:]  # Remove 'video_' prefix
                elif filename.startswith("gif_"):
                    item_id = filename[4:]  # Remove 'gif_' prefix
                elif "_imgur" in filename:
                    item_id = filename.split("_imgur")[0]
                elif filename.endswith("_original"):
                    item_id = filename.replace("_original", "")
                else:
                    item_id = filename

                id_to_path[item_id] = path

        # Update comments
        for comment in comments:
            if comment.id in id_to_path:
                path = id_to_path[comment.id]
                filename = Path(path).name.lower()

                if filename.startswith("gif_") or path.endswith(".gif"):
                    comment.gif_path = path
                    if not comment.gif_url:
                        # Extract URL from comment body
                        urls = self._extract_urls_from_text(comment.body)
                        for url in urls:
                            if self._is_media_url(url) and self._get_media_type(url) == "gif":
                                comment.gif_url = url
                                break
                elif filename.startswith("video_") or path.endswith((".mp4", ".webm")):
                    # Check if it's actually a converted gif
                    if "gif_" in filename:
                        comment.gif_path = path
                    else:
                        comment.video_path = path
                    if not comment.video_url and not comment.gif_url:
                        # Extract URL from comment body
                        urls = self._extract_urls_from_text(comment.body)
                        for url in urls:
                            if self._is_media_url(url):
                                media_type = self._get_media_type(url)
                                if media_type == "video":
                                    comment.video_url = url
                                    break
                                elif media_type == "gif":
                                    comment.gif_url = url
                                    break
                else:
                    comment.image_path = path
                    if not comment.image_url:
                        # Extract URL from comment body
                        urls = self._extract_urls_from_text(comment.body)
                        for url in urls:
                            if self._is_media_url(url) and self._get_media_type(url) == "image":
                                comment.image_url = url
                                break

        return comments
