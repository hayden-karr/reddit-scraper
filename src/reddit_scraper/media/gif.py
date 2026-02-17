"""
GIF handler - converts GIFs to WebM with proper looping (async version).
"""

import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional

from .base import BaseMediaHandler, MediaConfig, ProcessingResult


class GifHandler(BaseMediaHandler):
    """Handle GIF downloads and WebM conversion with looping (async)."""

    def __init__(self, subreddit: str):
        super().__init__(subreddit, "gif")

    async def download_and_convert(self, url: str, item_id: str) -> ProcessingResult:
        """Download GIF and convert to WebM with proper looping."""
        try:
            webm_path = self.media_dir / f"gif_{item_id}.webm"

            if await self.check_file_exists(webm_path):
                return ProcessingResult(
                    url=url, item_id=item_id, success=True, path=str(webm_path), skipped=True
                )

            # Download GIF bytes with retry logic
            gif_bytes = await self.download_with_retry(url, timeout=MediaConfig.DOWNLOAD_TIMEOUT)
            if not gif_bytes:
                return ProcessingResult(
                    url=url, item_id=item_id, success=False, error="Download failed after retries"
                )

            # Convert in thread pool (FFmpeg is blocking)
            result_path = await asyncio.to_thread(self._convert_to_webm, gif_bytes, webm_path)

            if result_path:
                self.logger.info(f"GIF converted to WebM: {webm_path.name}")
                return ProcessingResult(url=url, item_id=item_id, success=True, path=result_path)
            else:
                return ProcessingResult(
                    url=url, item_id=item_id, success=False, error="Conversion failed"
                )

        except Exception as e:
            self.logger.error(f"GIF processing failed for {url}: {e}")
            return ProcessingResult(url=url, item_id=item_id, success=False, error=str(e))

    def _convert_to_webm(self, gif_bytes: bytes, output_path: Path) -> Optional[str]:
        """Convert GIF bytes to WebM using ffmpeg (runs in thread)."""
        temp_input = None
        try:
            # Write temp file
            temp_input = output_path.parent / f"{output_path.stem}_temp.gif"
            with open(temp_input, "wb") as f:
                f.write(gif_bytes)

            cmd = [
                "ffmpeg",
                "-i",
                str(temp_input),
                "-c:v",
                "libvpx-vp9",
                "-crf",
                str(MediaConfig.GIF_CRF),
                "-b:v",
                "0",
                "-an",
                "-loop",
                "0",
                "-auto-alt-ref",
                "0",
                "-lag-in-frames",
                "0",
                "-cpu-used",
                str(MediaConfig.GIF_CPU_USED),
                "-row-mt",
                "1",
                "-threads",
                "4",
                "-y",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and output_path.exists():
                return str(output_path)
            else:
                self.logger.error(f"FFmpeg conversion failed: {result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            self.logger.error(f"GIF conversion timeout for {output_path.name}")
            return None
        except Exception as e:
            self.logger.error(f"GIF conversion error: {e}")
            return None
        finally:
            if temp_input and temp_input.exists():
                try:
                    temp_input.unlink()
                except Exception:
                    pass

    async def batch_convert(
        self, url_id_pairs: List[tuple], max_concurrent: Optional[int] = None
    ) -> dict:
        """Convert multiple GIFs concurrently."""
        if max_concurrent is None:
            max_concurrent = MediaConfig.MAX_CONCURRENT_GIFS

        result = await self.batch_process_with_progress(
            url_id_pairs, self.download_and_convert, max_concurrent
        )

        return result.to_dict()
