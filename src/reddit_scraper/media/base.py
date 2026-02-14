"""
Base handler with common functionality for all media handlers.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import Config

logger = logging.getLogger(__name__)


class MediaConfig:
    """Configuration for media processing."""

    # Network timeouts
    DOWNLOAD_TIMEOUT = 60
    HEAD_REQUEST_TIMEOUT = 10
    DASH_TIMEOUT = 15

    # Concurrency limits
    MAX_CONCURRENT_IMAGES = 15
    MAX_CONCURRENT_GIFS = 10
    MAX_CONCURRENT_VIDEOS = 5
    MAX_CONCURRENT_IMGUR = 10

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF = 0.5
    RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

    # FFmpeg quality settings
    VIDEO_CRF = 23
    VIDEO_CPU_USED = 2
    GIF_CRF = 30
    GIF_CPU_USED = 4
    AUDIO_BITRATE = "128k"


class ProcessingResult:
    """Result of processing a single media item."""

    def __init__(
        self,
        url: str,
        item_id: str,
        success: bool,
        path: Optional[str] = None,
        skipped: bool = False,
        error: Optional[str] = None,
        duration_ms: int = 0,
    ):
        self.url = url
        self.item_id = item_id
        self.success = success
        self.path = path
        self.skipped = skipped
        self.error = error
        self.duration_ms = duration_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "item_id": self.item_id,
            "success": self.success,
            "path": self.path,
            "skipped": self.skipped,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class BatchResult:
    """Result of batch processing."""

    def __init__(self):
        self.success: List[str] = []
        self.failed: List[str] = []
        self.skipped: List[str] = []
        self.results: List[ProcessingResult] = []

    def add_result(self, result: ProcessingResult):
        self.results.append(result)
        if result.skipped:
            # Skipped files always have a path
            self.skipped.append(result.path if result.path else result.url)
        elif result.success and result.path:
            # Successful downloads always have a path
            self.success.append(result.path)
        else:
            self.failed.append(result.url)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": len(self.results),
            "downloaded": len(self.success),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
            "success_paths": self.success,
            "failed_urls": self.failed,
            "skipped_paths": self.skipped,
            "results": [r.to_dict() for r in self.results],
        }


class BaseMediaHandler:
    """Base class for all media handlers with common functionality."""

    def __init__(self, subreddit: str, media_type: str):
        self.subreddit = subreddit
        self.media_type = media_type
        self.media_dir = Config.get_media_dir(subreddit)
        self.session = self._create_session()
        self.logger = logging.getLogger(f"{__name__}.{media_type}")

    def _create_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()

        retry_strategy = Retry(
            total=MediaConfig.MAX_RETRIES,
            backoff_factor=MediaConfig.RETRY_BACKOFF,
            status_forcelist=MediaConfig.RETRY_STATUS_CODES,
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    async def check_file_exists(self, path: Path) -> bool:
        """Check if file exists and is non-empty."""
        if path.exists() and path.stat().st_size > 0:
            self.logger.debug(f"File already exists: {path}")
            return True
        return False

    async def download_with_retry(
        self, url: str, timeout: int = MediaConfig.DOWNLOAD_TIMEOUT
    ) -> Optional[bytes]:
        """Download content with retry logic."""
        for attempt in range(MediaConfig.MAX_RETRIES):
            try:
                response = await asyncio.to_thread(self.session.get, url, timeout=timeout)
                response.raise_for_status()
                return response.content
            except requests.exceptions.RequestException as e:
                if attempt < MediaConfig.MAX_RETRIES - 1:
                    wait_time = MediaConfig.RETRY_BACKOFF * (2**attempt)
                    self.logger.warning(
                        f"Download attempt {attempt + 1} failed for {url}: {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"All download attempts failed for {url}: {e}")
                    return None
        return None

    async def batch_process_with_progress(
        self,
        items: List[Tuple[str, str]],
        process_func: Callable,
        max_concurrent: int,
    ) -> BatchResult:
        """Process items in batch with concurrency control and progress tracking."""
        result = BatchResult()

        if not items:
            self.logger.info(f"No {self.media_type} items to process")
            return result

        self.logger.info(f"Processing {len(items)} {self.media_type} items...")

        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_limit(url: str, item_id: str):
            async with semaphore:
                start_time = time.time()
                process_result = await process_func(url, item_id)
                duration_ms = int((time.time() - start_time) * 1000)

                if isinstance(process_result, ProcessingResult):
                    process_result.duration_ms = duration_ms
                    result.add_result(process_result)
                elif process_result:
                    result.add_result(
                        ProcessingResult(
                            url=url,
                            item_id=item_id,
                            success=True,
                            path=process_result,
                            duration_ms=duration_ms,
                        )
                    )
                else:
                    result.add_result(
                        ProcessingResult(
                            url=url,
                            item_id=item_id,
                            success=False,
                            error="Processing failed",
                            duration_ms=duration_ms,
                        )
                    )

        tasks = [process_with_limit(url, item_id) for url, item_id in items]
        await asyncio.gather(*tasks, return_exceptions=True)

        self.logger.info(
            f"{self.media_type.capitalize()} processing complete: "
            f"{len(result.success)} downloaded, "
            f"{len(result.skipped)} skipped (already exist), "
            f"{len(result.failed)} failed"
        )

        return result
