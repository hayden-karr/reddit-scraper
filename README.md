# Reddit Scraper

Reddit scraper with optional Rust-powered media processing. Converts all media to AVIF (images) and WebM (videos/GIFs) for efficient storage.

## Features

- Async media downloads
- Images → AVIF (lossless)
- GIFs → WebM (VP9, looping)
- Videos → WebM/MP4 (DASH stream merging)
- Gallery support
- Optional Rust engine (faster)
- Parquet storage

## Install

```bash
# With Nix
nix develop
uv sync

# Without Nix
uv venv
uv sync

# Setup Reddit API credentials
cp .env.example .env
# Edit .env with your Reddit API credentials
```

### Optional: Rust Engine

```bash
cd src/rust-media-engine
maturin develop --release
```

## Usage

```bash
# Basic
uv run reddit-scraper scrape subreddit1 --posts 100

# With Rust
uv run reddit-scraper scrape subreddit1 --posts 100 --use-rust

# With comments
uv run reddit-scraper scrape subreddit1 --posts 50 --comments 20

# Top posts
uv run reddit-scraper scrape subreddit1 --sort top --time week

# Stats
uv run reddit-scraper stats subreddit1
uv run reddit-scraper list

# Merge subreddits
uv run reddit-scraper merge subreddit1 subreddit2 subreddit3 --output combined
```

## Media Conversion

**Python:**

- AVIF (lossless)
- WebM (VP9, CRF 30)

**Rust:**

- AVIF (lossless)
- WebM (FFmpeg VP9)
- Faster

**To change quality:**

- Python: `src/reddit_scraper/media/images.py` line 72 - change `lossless: True`
- Rust: `src/rust-media-engine/src/lib.rs` line 250 - change quality `100` to lower value (e.g., `80`)

## Structure

```
src/
├── reddit_scraper/      # Python scraper
├── rust_media_engine/   # Rust engine (optional)
```

Data: `./data/<subreddit>/` (Parquet)
