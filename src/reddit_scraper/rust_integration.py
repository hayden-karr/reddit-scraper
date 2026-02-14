"""
Bridge between existing Python scraper and new Rust media engine
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import existing components
from .models import RedditComment, RedditPost

# Import Rust engine
try:
    from rust_media_engine import MediaTask, RustMediaEngine  # type: ignore

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    MediaTask = None  # type: ignore
    RustMediaEngine = None  # type: ignore

logger = logging.getLogger(__name__)


class RustMediaProcessor:
    """Processes media using the Rust engine"""

    def __init__(self, output_dir: str):
        if not RUST_AVAILABLE or RustMediaEngine is None:
            raise ImportError(
                "Rust media engine not available. Run: cd rust-media-engine && maturin develop"
            )

        self.output_dir = Path(output_dir)
        self.rust_engine = RustMediaEngine()  # type: ignore

    async def __aenter__(self):
        """Initialize async resources"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up async resources"""

    async def process_posts_media(
        self,
        posts: List[RedditPost],
        comments: List[RedditComment],
        max_concurrent: int = 15,
    ) -> Dict[str, Any]:
        """Process media for posts and comments using Rust engine"""

        # Extract and categorize all media URLs
        regular_tasks = self._extract_and_categorize_media(posts, comments)

        total_items = len(regular_tasks)
        if total_items == 0:
            logger.info("No media items found to process")
            return {
                "total_media": 0,
                "successful_media": 0,
                "success_rate": 0,
                "results": [],
            }

        logger.info(f"Processing {len(regular_tasks)} regular")

        tasks = []

        if regular_tasks:
            tasks.append(self._process_regular_media(regular_tasks, max_concurrent))

        # Wait for all processing
        if tasks:
            all_results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            all_results = []

        # Flatten and compile results
        successful_count = 0
        total_size_bytes = 0
        all_individual_results = []

        for result_group in all_results:
            if isinstance(result_group, Exception):
                logger.error(f"Processing group failed: {result_group}")
                continue

            if not isinstance(result_group, list):
                continue

            for item_result in result_group:
                if not isinstance(item_result, dict):
                    continue
                all_individual_results.append(item_result)
                if item_result.get("success"):
                    successful_count += 1
                    total_size_bytes += item_result.get("converted_size", 0)

        return {
            "total_media": total_items,
            "successful_media": successful_count,
            "success_rate": successful_count / total_items if total_items > 0 else 0,
            "total_size_mb": total_size_bytes / (1024 * 1024),
            "results": all_individual_results,
        }

    def _extract_and_categorize_media(
        self, posts: List[RedditPost], comments: List[RedditComment]
    ) -> List[Any]:
        """Extract media URLs and categorize by processing method"""

        regular_tasks: List[Any] = []

        # Process posts
        for post in posts:
            # Check specific media fields first (with validation)
            if hasattr(post, "video_url") and post.video_url and self._is_media_url(post.video_url):
                task = self._create_media_task(post.video_url, post.id)
                if task:
                    regular_tasks.append(task)
            elif hasattr(post, "gif_url") and post.gif_url and self._is_media_url(post.gif_url):
                task = self._create_media_task(post.gif_url, post.id)
                if task:
                    regular_tasks.append(task)
            elif (
                hasattr(post, "image_url") and post.image_url and self._is_media_url(post.image_url)
            ):
                task = self._create_media_task(post.image_url, post.id)
                if task:
                    regular_tasks.append(task)
            elif post.url and self._is_media_url(post.url):
                # Fallback to generic URL
                task = self._create_media_task(post.url, post.id)
                if task:
                    regular_tasks.append(task)

            # Gallery URLs
            if hasattr(post, "gallery_urls") and post.gallery_urls:
                gallery_urls = post.gallery_urls
                for i, gallery_url in enumerate(gallery_urls):
                    if self._is_media_url(gallery_url):
                        item_id = f"{post.id}_gallery_{i + 1:02d}"

                        task = self._create_media_task(gallery_url, item_id)
                        if task:
                            regular_tasks.append(task)

        # Process comments
        for comment in comments:
            # Extract URLs from comment body
            urls = self._extract_urls_from_text(comment.body)
            for url in urls:
                if self._is_media_url(url):
                    task = self._create_media_task(url, comment.id)
                    if task:
                        regular_tasks.append(task)

        return regular_tasks

    def _create_media_task(self, url: str, item_id: str) -> Optional[Any]:
        """Create a MediaTask for the Rust engine"""
        if not RUST_AVAILABLE or MediaTask is None:
            return None

        media_type = self._detect_media_type(url)
        if media_type == "unknown":
            return None

        # Check if imgur URL to match Python naming
        is_imgur = self._is_imgur_url(url)

        # Determine output path based on media type
        if media_type == "image":
            suffix = "_imgur" if is_imgur else ""
            output_path = self.output_dir / f"{item_id}{suffix}.avif"
        elif media_type == "gif":
            suffix = "_imgur" if is_imgur else ""
            output_path = self.output_dir / f"{item_id}{suffix}.webm"
        elif media_type == "video":
            output_path = self.output_dir / f"{item_id}.mp4"
        else:
            return None

        task = MediaTask()  # type: ignore
        task.url = url
        task.item_id = item_id
        task.media_type = media_type
        task.output_path = str(output_path)

        logger.debug(f"Created task: {item_id} -> {output_path}")
        return task

    def _is_imgur_url(self, url: str) -> bool:
        """Check if URL is from imgur"""
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            return parsed.netloc in ["imgur.com", "i.imgur.com", "m.imgur.com"]
        except Exception:
            return False

    async def _process_regular_media(
        self, tasks: List[Any], max_concurrent: int
    ) -> List[Dict[str, Any]]:
        """Process regular media through Rust engine"""

        try:
            logger.info(f"Rust processing {len(tasks)} regular media items...")

            # Call Rust engine
            rust_results = await self.rust_engine.process_media_batch(tasks, max_concurrent)

            # Convert to our format
            results = []
            for rust_result in rust_results:
                result_dict = {
                    "success": rust_result.success,
                    "item_id": rust_result.item_id,
                    "output_path": rust_result.output_path,
                    "original_size": rust_result.original_size,
                    "converted_size": rust_result.converted_size,
                    "error": rust_result.error,
                    "source": "rust_regular",
                }
                results.append(result_dict)

                # Log errors for debugging
                if not rust_result.success and rust_result.error:
                    logger.warning(f"Failed {rust_result.item_id}: {rust_result.error}")
                elif rust_result.success:
                    logger.debug(
                        f"Success {rust_result.item_id}: saved to {rust_result.output_path}"
                    )

            successful = [r for r in results if r["success"]]
            logger.info(f"Rust regular media: {len(successful)}/{len(results)} successful")

            return results

        except Exception as e:
            logger.error(f"Rust processing failed: {e}")
            # Return failed results for all tasks
            return [
                {
                    "success": False,
                    "item_id": getattr(task, "item_id", "unknown"),
                    "output_path": None,
                    "original_size": 0,
                    "converted_size": 0,
                    "error": f"Rust engine error: {e}",
                    "source": "rust_regular",
                }
                for task in tasks
            ]

    def _is_media_url(self, url: str) -> bool:
        """Check if URL is a media URL we can process (matches Python version)"""
        if not url:
            return False

        from urllib.parse import urlparse

        url_lower = url.lower()

        # Debug: log what we're checking
        logger.debug(f"Checking URL: {url}")

        # Check for direct media file extensions first
        media_extensions = [
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".gifv",
            ".mp4",
            ".webm",
            ".mov",
            ".avif",
        ]
        if any(url_lower.endswith(ext) for ext in media_extensions):
            logger.debug("  -> Accepted (file extension)")
            return True

        # Parse URL and check actual domain (not query parameters!)
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
        except Exception as e:
            logger.debug(f"  -> Rejected (URL parse error: {e})")
            return False

        # Whitelist of allowed media domains (matches Python version)
        media_domains = [
            "i.redd.it",
            "v.redd.it",
            "i.imgur.com",
            "imgur.com",
            "gfycat.com",
            "tenor.com",
            "preview.redd.it",
            "external-preview.redd.it",
        ]

        is_media = domain in media_domains
        if is_media:
            logger.debug(f"  -> Accepted (media domain: {domain})")
        else:
            logger.debug(f"  -> Rejected (domain '{domain}' not in whitelist)")
        return is_media

    def _detect_media_type(self, url: str) -> str:
        """Detect media type from URL"""
        url_lower = url.lower()

        # Check for video domains/extensions first (including v.redd.it)
        if "v.redd.it" in url_lower or any(ext in url_lower for ext in [".mp4", ".webm", ".mov"]):
            return "video"
        elif any(ext in url_lower for ext in [".gif", ".gifv"]) or "#reddit_gif" in url_lower:
            return "gif"
        elif any(ext in url_lower for ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"]):
            return "image"
        else:
            return "unknown"

    def _extract_urls_from_text(self, text: str) -> List[str]:
        """Extract URLs from text using regex"""
        import re

        url_pattern = r'https?://[^\s)"]+'
        return re.findall(url_pattern, text or "")


# Main convenience function for CLI integration
async def process_posts_with_rust(
    posts_data: List[Dict[str, Any]],
    output_directory: str,
    max_concurrent_posts: int = 3,
    max_concurrent_media: int = 15,
) -> Dict[str, Any]:
    """
    Process Reddit posts data with Rust engine

    Args:
        posts_data: List of post dictionaries with 'id', 'url', 'gallery_urls', etc.
        output_directory: Base directory for media files
        max_concurrent_posts: How many posts to process simultaneously
        max_concurrent_media: How many media items to download simultaneously

    Returns:
        Dictionary with processing statistics
    """

    # Convert dict format to RedditPost objects for processing
    posts = []
    for post_dict in posts_data:
        # Create minimal RedditPost object for media processing
        post = RedditPost(
            id=post_dict.get("id", "unknown"),
            title=post_dict.get("title", ""),
            url=post_dict.get("url", ""),
            permalink="",
            score=0,
            upvote_ratio=0.0,
            num_comments=0,
            author="",
            selftext="",
            created_utc=0.0,
            is_video=False,
            has_gallery=bool(post_dict.get("gallery_urls")),
            media_type="unknown",
            domain="",
        )

        # Add gallery URLs if present
        if "gallery_urls" in post_dict:
            post.gallery_urls = post_dict["gallery_urls"]

        posts.append(post)

    # Process with Rust engine
    async with RustMediaProcessor(output_directory) as processor:
        # Process posts in batches to avoid overwhelming APIs
        post_semaphore = asyncio.Semaphore(max_concurrent_posts)

        async def process_post_batch(post_batch: List[RedditPost]) -> Dict[str, Any]:
            async with post_semaphore:
                return await processor.process_posts_media(
                    post_batch,
                    [],  # No comments for now
                    max_concurrent_media,
                )

        # Split posts into small batches
        batch_size = 10
        post_batches = [posts[i : i + batch_size] for i in range(0, len(posts), batch_size)]

        # Process all batches
        batch_results = await asyncio.gather(
            *[process_post_batch(batch) for batch in post_batches],
            return_exceptions=True,
        )

        # Compile overall statistics
        total_media = 0
        successful_media = 0
        total_size_mb = 0
        all_results = []

        for batch_result in batch_results:
            if isinstance(batch_result, Exception):
                logger.error(f"Batch processing failed: {batch_result}")
                continue

            if not isinstance(batch_result, dict):
                continue

            total_media += batch_result.get("total_media", 0)
            successful_media += batch_result.get("successful_media", 0)
            total_size_mb += batch_result.get("total_size_mb", 0)
            all_results.extend(batch_result.get("results", []))

        return {
            "total_posts": len(posts_data),
            "successful_posts": len(
                [
                    r
                    for r in batch_results
                    if isinstance(r, dict) and r.get("successful_media", 0) > 0
                ]
            ),
            "total_media": total_media,
            "successful_media": successful_media,
            "success_rate": successful_media / total_media if total_media > 0 else 0,
            "total_size_mb": total_size_mb,
            "results": all_results,
        }
