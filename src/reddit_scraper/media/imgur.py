"""
Imgur handler - downloads imgur media (async version).
"""

import asyncio
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .base import BaseMediaHandler, MediaConfig, ProcessingResult


class ImgurHandler(BaseMediaHandler):
    """Handle imgur media downloads (async)."""

    def __init__(self, subreddit: str):
        super().__init__(subreddit, "imgur")
        # Add imgur-specific headers
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://imgur.com/",
            }
        )

    def is_imgur_url(self, url: str) -> bool:
        """Check if URL is from imgur."""
        parsed = urlparse(url)
        return parsed.netloc in ["imgur.com", "i.imgur.com", "m.imgur.com"]

    async def download_media(self, url: str, item_id: str) -> ProcessingResult:
        """Download imgur media with direct link conversion."""
        try:
            direct_urls = await self._get_direct_urls(url)

            if not direct_urls:
                return ProcessingResult(
                    url=url, item_id=item_id, success=False, error="No direct URLs found"
                )

            for direct_url, expected_type in direct_urls:
                try:
                    result = await self._download_direct_url(direct_url, item_id, expected_type)
                    if result.success:
                        return result
                except Exception as e:
                    self.logger.debug(f"Failed to download {direct_url}: {e}")
                    continue

            return ProcessingResult(
                url=url, item_id=item_id, success=False, error="All imgur download attempts failed"
            )

        except Exception as e:
            self.logger.error(f"Imgur processing failed for {url}: {e}")
            return ProcessingResult(url=url, item_id=item_id, success=False, error=str(e))

    async def _get_direct_urls(self, url: str) -> List[Tuple[str, str]]:
        """Convert imgur URL to direct media URLs."""
        try:
            parsed = urlparse(url)

            if parsed.netloc == "i.imgur.com":
                media_type = self._detect_media_type(url)
                return [(url, media_type)]

            if "/a/" in url or "/gallery/" in url:
                return []

            return await self._convert_single_url(url)

        except Exception as e:
            self.logger.error(f"Direct URL extraction error: {e}")
            return []

    async def _convert_single_url(self, url: str) -> List[Tuple[str, str]]:
        """Convert single imgur page URL to direct media URL."""
        try:
            imgur_id = self._extract_imgur_id(url)
            if not imgur_id:
                return []

            extensions_to_try = [
                (".mp4", "video"),
                (".webm", "video"),
                (".gif", "gif"),
                (".jpg", "image"),
                (".png", "image"),
                (".webp", "image"),
            ]

            direct_urls = []

            for ext, media_type in extensions_to_try:
                direct_url = f"https://i.imgur.com/{imgur_id}{ext}"

                try:
                    response = await asyncio.to_thread(
                        self.session.head, direct_url, timeout=MediaConfig.HEAD_REQUEST_TIMEOUT
                    )
                    if response.status_code == 200:
                        self.logger.debug(f"Found direct URL: {direct_url}")
                        direct_urls.append((direct_url, media_type))

                        if media_type == "image":
                            break
                except Exception:
                    continue

            return direct_urls

        except Exception as e:
            self.logger.error(f"Single URL conversion error: {e}")
            return []

    def _extract_imgur_id(self, url: str) -> Optional[str]:
        """Extract imgur ID from URL."""
        try:
            url = url.split("?")[0].split("#")[0]
            path_parts = url.split("/")

            for part in reversed(path_parts):
                if part and part.lower() not in ["gallery", "a", "r"]:
                    imgur_id = part.split(".")[0]

                    if re.match(r"^[a-zA-Z0-9]+$", imgur_id) and len(imgur_id) >= 5:
                        return imgur_id

            return None

        except Exception as e:
            self.logger.error(f"ID extraction error: {e}")
            return None

    def _detect_media_type(self, url: str) -> str:
        """Detect media type from URL."""
        url_lower = url.lower()

        if any(ext in url_lower for ext in [".mp4", ".webm", ".mov"]):
            return "video"
        elif ".gif" in url_lower:
            return "gif"
        else:
            return "image"

    async def _download_direct_url(
        self, url: str, item_id: str, media_type: str
    ) -> ProcessingResult:
        """Download from direct imgur URL."""
        try:
            if media_type == "video":
                ext = ".mp4"
            elif media_type == "gif":
                ext = ".gif"
            else:
                ext = ".avif"

            output_path = self.media_dir / f"{item_id}_imgur{ext}"

            if await self.check_file_exists(output_path):
                return ProcessingResult(
                    url=url, item_id=item_id, success=True, path=str(output_path), skipped=True
                )

            self.logger.debug(f"Downloading imgur media: {url}")
            content = await self.download_with_retry(url, timeout=MediaConfig.DOWNLOAD_TIMEOUT)

            if not content:
                return ProcessingResult(
                    url=url, item_id=item_id, success=False, error="Download failed after retries"
                )

            output_path.write_bytes(content)

            file_size = output_path.stat().st_size
            self.logger.info(
                f"Downloaded imgur {media_type}: {output_path.name} ({file_size:,} bytes)"
            )

            return ProcessingResult(url=url, item_id=item_id, success=True, path=str(output_path))

        except Exception as e:
            self.logger.error(f"Direct download failed for {url}: {e}")
            return ProcessingResult(url=url, item_id=item_id, success=False, error=str(e))

    async def batch_download(
        self, url_id_pairs: List[Tuple[str, str]], max_concurrent: Optional[int] = None
    ) -> dict:
        """Download multiple imgur URLs concurrently."""
        if max_concurrent is None:
            max_concurrent = MediaConfig.MAX_CONCURRENT_IMGUR

        result = await self.batch_process_with_progress(
            url_id_pairs, self.download_media, max_concurrent, "Processing imgur"
        )

        return result.to_dict()
