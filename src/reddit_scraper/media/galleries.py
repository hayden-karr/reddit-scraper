"""
Gallery handler - processes Reddit gallery posts with proper ordering and conversion.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import Config
from .gif import GifHandler
from .images import ImageHandler


class GalleryHandler:
    """Handle Reddit gallery posts with proper ordering and media conversion."""

    def __init__(self, subreddit: str):
        self.subreddit = subreddit
        self.media_dir = Config.get_media_dir(subreddit)

        # Initialize media handlers
        self.image_handler = ImageHandler(subreddit)
        self.gif_handler = GifHandler(subreddit)

    def process_gallery(
        self, gallery_urls: List[str], post_id: str, max_workers: int = 4
    ) -> Dict[str, List[str]]:
        """Process gallery with proper ordering and media type conversion."""

        if not gallery_urls:
            return {"images": [], "gifs": [], "failed": []}

        print(f"Processing gallery with {len(gallery_urls)} items for post {post_id}")

        # Create ordered download tasks
        gallery_tasks = []
        for index, media_url in enumerate(gallery_urls, 1):
            if not self._is_reddit_media_url(media_url):
                print(f"Skipping non-Reddit URL: {media_url}")
                continue

            media_type = self._detect_media_type(media_url)
            task = {
                "index": index,
                "url": media_url,
                "post_id": post_id,
                "media_type": media_type,
                "item_id": f"{post_id}_gallery_{index:02d}",
            }
            gallery_tasks.append(task)

        # Process in parallel but maintain order
        results = {"images": [], "gifs": [], "failed": []}

        # Store results with their original indices to maintain order
        indexed_results = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(self._process_single_gallery_item, task): task
                for task in gallery_tasks
            }

            # Collect results
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result_path = future.result()
                    if result_path:
                        indexed_results[task["index"]] = {
                            "path": result_path,
                            "type": task["media_type"],
                        }
                        print(f"Gallery item {task['index']} processed: {result_path}")
                    else:
                        results["failed"].append(task["url"])
                        print(f"Gallery item {task['index']} failed")
                except Exception as e:
                    print(f"Gallery item {task['index']} error: {e}")
                    results["failed"].append(task["url"])

        # Sort results by index to maintain order
        sorted_indices = sorted(indexed_results.keys())
        for index in sorted_indices:
            result = indexed_results[index]
            if result["type"] == "gif":
                results["gifs"].append(result["path"])
            else:
                results["images"].append(result["path"])

        print(
            f"Gallery processing complete: {len(results['images'])} images, {len(results['gifs'])} gifs, {len(results['failed'])} failed"
        )
        return results

    def _process_single_gallery_item(self, task: Dict) -> Optional[str]:
        """Process a single gallery item."""
        import asyncio

        try:
            media_url = task["url"]
            # Clean the URL by removing our tag
            clean_url = media_url.replace("#reddit_gif", "").replace("#REDDIT_GIF", "")

            item_id = task["item_id"]
            media_type = task["media_type"]

            print(f"Processing gallery item {task['index']}: {media_type} - {clean_url}")

            # Run async handlers in sync context
            if media_type == "gif":
                result = asyncio.run(self.gif_handler.download_and_convert(clean_url, item_id))
            else:
                result = asyncio.run(self.image_handler.download_and_convert(clean_url, item_id))

            # Extract path from ProcessingResult
            if result and result.success:
                return result.path
            return None
        except Exception as e:
            print(f"Gallery item processing error: {e}")
            return None

    def _detect_media_type(self, url: str) -> str:
        """Detect media type from URL with better GIF detection."""
        url_lower = url.lower()

        # Check for Reddit GIF tag first (most reliable)
        if "#reddit_gif" in url_lower:
            return "gif"

        # Check for explicit GIF indicators
        gif_indicators = [".gif", ".gifv", "animated", "gif?", "gif&"]
        for indicator in gif_indicators:
            if indicator in url_lower:
                return "gif"

        # For preview.redd.it URLs, check if they should be GIFs
        if "preview.redd.it" in url_lower:
            # These are often GIFs that need to be converted to i.redd.it
            return "gif"  # Assume GIF for preview URLs in galleries

        return "image"

    def _is_reddit_media_url(self, url: str) -> bool:
        """Check if URL is from Reddit media domains."""
        safe_domains = {"i.redd.it", "preview.redd.it", "external-preview.redd.it"}

        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return parsed.netloc in safe_domains
        except Exception:
            return False

    def get_gallery_info(self, gallery_urls: List[str], post_id: str) -> Dict:
        """Get information about gallery items without processing."""
        info = {
            "total_items": len(gallery_urls),
            "images": 0,
            "gifs": 0,
            "reddit_urls": 0,
            "items": [],
        }

        for index, url in enumerate(gallery_urls, 1):
            media_type = self._detect_media_type(url)
            is_reddit_url = self._is_reddit_media_url(url)

            item_info = {
                "index": index,
                "url": url,
                "type": media_type,
                "is_reddit_url": is_reddit_url,
                "expected_filename": f"{post_id}_gallery_{index:02d}",
            }

            info["items"].append(item_info)

            if is_reddit_url:
                info["reddit_urls"] += 1
                if media_type == "gif":
                    info["gifs"] += 1
                else:
                    info["images"] += 1

        return info

    def verify_gallery_order(self, gallery_paths: List[str]) -> bool:
        """Verify that gallery items are in correct order."""
        try:
            # Extract indices from filenames
            indices = []
            for path in gallery_paths:
                filename = Path(path).stem
                match = re.search(r"_gallery_(\d+)", filename)
                if match:
                    indices.append(int(match.group(1)))
                else:
                    print(f"Could not extract index from: {filename}")
                    return False

            # Check if indices are sequential
            expected_indices = list(range(1, len(indices) + 1))
            is_ordered = sorted(indices) == expected_indices

            if not is_ordered:
                print(
                    f"Gallery order mismatch. Expected: {expected_indices}, Got: {sorted(indices)}"
                )

            return is_ordered

        except Exception as e:
            print(f"Gallery order verification error: {e}")
            return False

    def reorder_gallery_paths(self, gallery_paths: List[str]) -> List[str]:
        """Reorder gallery paths based on embedded indices."""
        try:
            indexed_paths = []

            for path in gallery_paths:
                filename = Path(path).stem
                match = re.search(r"_gallery_(\d+)", filename)
                if match:
                    index = int(match.group(1))
                    indexed_paths.append((index, path))
                else:
                    # Put unindexed items at the end
                    indexed_paths.append((9999, path))

            # Sort by index
            indexed_paths.sort(key=lambda x: x[0])

            # Return just the paths
            ordered_paths = [path for index, path in indexed_paths]

            print(f"Reordered {len(ordered_paths)} gallery items")
            return ordered_paths

        except Exception as e:
            print(f"Gallery reordering error: {e}")
            return gallery_paths  # Return original order if reordering fails

    def get_gallery_stats(self, gallery_paths: List[str]) -> Dict:
        """Get statistics about processed gallery."""
        stats = {
            "total_items": len(gallery_paths),
            "total_size_bytes": 0,
            "images": 0,
            "gifs": 0,
            "webm_videos": 0,
            "file_types": {},
            "ordered_correctly": False,
        }

        try:
            for path in gallery_paths:
                file_path = Path(path)
                if not file_path.exists():
                    continue

                file_size = file_path.stat().st_size
                file_ext = file_path.suffix.lower()

                stats["total_size_bytes"] += file_size

                # Count by extension
                if file_ext in stats["file_types"]:
                    stats["file_types"][file_ext] += 1
                else:
                    stats["file_types"][file_ext] = 1

                # Count by type
                if file_ext in [".avif", ".webp", ".png", ".jpg", ".jpeg"]:
                    stats["images"] += 1
                elif file_ext == ".gif":
                    stats["gifs"] += 1
                elif file_ext == ".webm":
                    stats["webm_videos"] += 1

            # Check order
            stats["ordered_correctly"] = self.verify_gallery_order(gallery_paths)

            # Human readable size
            stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)

        except Exception as e:
            print(f"Gallery stats error: {e}")

        return stats

    def batch_process_galleries(self, gallery_data: List[Tuple[List[str], str]]) -> Dict:
        """Process multiple galleries in batch."""
        results = {"processed_galleries": 0, "total_images": 0, "total_gifs": 0, "total_failed": 0}

        print(f"Processing {len(gallery_data)} galleries...")

        for gallery_urls, post_id in gallery_data:
            try:
                gallery_results = self.process_gallery(gallery_urls, post_id)

                results["processed_galleries"] += 1
                results["total_images"] += len(gallery_results["images"])
                results["total_gifs"] += len(gallery_results["gifs"])
                results["total_failed"] += len(gallery_results["failed"])

            except Exception as e:
                print(f"Gallery batch processing error for {post_id}: {e}")
                results["total_failed"] += len(gallery_urls)

        print(f"Batch gallery processing complete: {results}")
        return results
