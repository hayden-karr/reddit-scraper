"""
Click-based CLI for Reddit scraper.
"""

import asyncio
import logging

import click

from reddit_scraper.config import Config
from reddit_scraper.media_collector import MediaCollector
from reddit_scraper.merge import merge_subreddits
from reddit_scraper.scraper import RedditScraper
from reddit_scraper.storage import DataStorage


def setup_logging(verbose: bool = False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def main(ctx, verbose):
    """Reddit scraper with PRAW and optional Rust-powered media processing.

    Use --help with any command to see its options (e.g., reddit-scraper scrape --help)
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@main.command()
@click.argument("subreddit")
@click.option("-p", "--posts", default=100, help="Number of posts to scrape")
@click.option(
    "-c",
    "--comments",
    type=int,
    default=None,
    help="Number of comments per post (None = all)",
)
@click.option(
    "-s",
    "--sort",
    default="new",
    type=click.Choice(["new", "hot", "top", "rising"], case_sensitive=False),
    metavar="ORDER",
    help="Sort order: new, hot, top, rising",
)
@click.option(
    "-t",
    "--time",
    "time_filter",
    default="all",
    type=click.Choice(["hour", "day", "week", "month", "year", "all"], case_sensitive=False),
    metavar="FILTER",
    help="Time filter for top sort: hour, day, week, month, year, all",
)
@click.option("--no-media", is_flag=True, help="Skip media download")
@click.option(
    "--use-rust",
    is_flag=True,
    help="Use Rust engine for media processing (faster)",
)
def scrape(
    subreddit: str,
    posts: int,
    comments: int,
    sort: str,
    time_filter: str,
    no_media: bool,
    use_rust: bool,
):
    """Scrape a subreddit for posts and comments."""
    try:
        # Initialize components
        print(f"Initializing scraper for r/{subreddit}")
        scraper = RedditScraper(subreddit)
        storage = DataStorage(subreddit)

        # Scrape data
        scraped_posts, scraped_comments = scraper.scrape_subreddit(
            post_limit=posts, comment_limit=comments, sort=sort, time_filter=time_filter
        )

        # Handle media collection
        if not no_media and scraped_posts:
            try:
                if use_rust:
                    print("Using Rust engine for media processing...")
                    try:
                        from reddit_scraper.rust_integration import RustMediaProcessor

                        media_dir = (storage.data_dir / "media").resolve()

                        async def process_with_rust():
                            async with RustMediaProcessor(str(media_dir)) as processor:
                                return await processor.process_posts_media(
                                    scraped_posts, scraped_comments
                                )

                        rust_results = asyncio.run(process_with_rust())
                        print(
                            f"Rust processing complete: {rust_results['successful_media']}/{rust_results['total_media']} successful"
                        )

                    except ImportError:
                        print("Rust engine not available. Install with:")
                        print("  cd src/rust-media-engine && maturin develop --release")
                        print("Falling back to Python processing...")
                        use_rust = False

                if not use_rust:
                    logger = logging.getLogger(__name__)
                    logger.info("Using Python engine for media processing...")
                    media_collector = MediaCollector(subreddit)

                    # Extract media URLs
                    media_items = media_collector.extract_media_urls(
                        scraped_posts, scraped_comments
                    )

                    if media_items:
                        try:
                            # Download all media
                            download_results = asyncio.run(
                                media_collector.download_all_media(media_items)
                            )

                            # Update posts and comments with media paths
                            scraped_posts = media_collector.update_posts_with_paths(
                                scraped_posts, download_results
                            )
                            scraped_comments = media_collector.update_comments_with_paths(
                                scraped_comments, download_results
                            )

                            # Display summary
                            total_downloaded = sum(
                                r.get("downloaded", 0) for r in download_results.values()
                            )
                            total_skipped = sum(
                                r.get("skipped", 0) for r in download_results.values()
                            )
                            total_failed = sum(
                                r.get("failed", 0) for r in download_results.values()
                            )

                            print("\nMedia processing complete:")
                            print(f"  Downloaded: {total_downloaded}")
                            print(f"  Skipped (already exist): {total_skipped}")
                            print(f"  Failed: {total_failed}")

                        except Exception as e:
                            logger.error(f"Media download error: {e}", exc_info=True)
                    else:
                        logger.info("No media URLs found")
            except Exception as e:
                print(f"Media processing error: {e}")

        # Save data
        storage.save_posts(scraped_posts)
        storage.save_comments(scraped_comments)

        # Show summary
        stats = storage.get_stats()
        media_stats = storage.get_media_stats()

        print("\nScrape complete!")
        print(f"Data saved to: {stats['data_dir']}")
        print(f"Posts: {stats['posts']}")
        print(f"Comments: {stats['comments']}")
        if not no_media:
            print(f"Media files: {media_stats['total_files']} ({media_stats['total_size_mb']} MB)")
            print(f"  Images: {media_stats['images']}")
            print(f"  Videos: {media_stats['videos']}")
            print(f"  GIFs: {media_stats['gifs']}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@main.command()
@click.argument("subreddit")
def stats(subreddit: str):
    """Show statistics for a scraped subreddit."""
    try:
        storage = DataStorage(subreddit)
        data_stats = storage.get_stats()
        media_stats = storage.get_media_stats()

        print(f"Statistics for r/{subreddit}")
        print(f"Data directory: {data_stats['data_dir']}")
        print(f"Posts: {data_stats['posts']}")
        print(f"Comments: {data_stats['comments']}")
        print(f"Media files: {media_stats['total_files']} ({media_stats['total_size_mb']} MB)")
        print(f"  Images: {media_stats['images']}")
        print(f"  Videos: {media_stats['videos']}")
        print(f"  GIFs: {media_stats['gifs']}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@main.command("merge")
@click.argument("subreddits", nargs=-1)
@click.option("--output", default="merged", help="Name for merged dataset")
def merge_cmd(subreddits: tuple, output: str):
    """Merge multiple subreddit datasets into one."""
    if not subreddits:
        click.echo("Error: Please provide at least one subreddit to merge", err=True)
        raise click.Abort()

    try:
        import builtins

        merge_subreddits(builtins.list(subreddits), target_name=output)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@main.command()
def list():
    """List all scraped subreddits."""
    data_dir = Config.DATA_DIR

    if not data_dir.exists():
        print("No data directory found")
        return

    subreddits = []
    for path in data_dir.iterdir():
        if path.is_dir() and path.name.startswith("r_"):
            subreddit_name = path.name[2:]  # Remove 'r_' prefix
            subreddits.append(subreddit_name)

    if subreddits:
        print("Scraped subreddits:")
        for subreddit in sorted(subreddits):
            print(f"  r/{subreddit}")
    else:
        print("No scraped subreddits found")


@main.command()
@click.argument("subreddit")
@click.option("--limit", default=10, help="Number of posts to show")
def show(subreddit: str, limit: int):
    """Show recent posts from a scraped subreddit."""
    try:
        storage = DataStorage(subreddit)
        posts = storage.load_posts(limit=limit)

        if not posts:
            print(f"No posts found for r/{subreddit}")
            return

        print(f"Recent posts from r/{subreddit}:")
        print("-" * 60)

        for i, post in enumerate(posts, 1):
            print(f"{i}. {post['title']}")
            print(
                f"   Score: {post['score']} | Comments: {post['num_comments']} | Author: {post['author']}"
            )
            print(f"   URL: {post['url']}")

            # Show media info
            media_info = []
            if post.get("image_path"):
                media_info.append("Image")
            if post.get("video_path"):
                media_info.append("Video")
            if post.get("gif_path"):
                media_info.append("GIF")

            if media_info:
                print(f"   Media: {', '.join(media_info)}")

            print()

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@main.command()
@click.argument("subreddit")
def media_only(subreddit: str):
    """Download media for existing posts without re-scraping."""
    try:
        storage = DataStorage(subreddit)

        # Load existing posts
        posts_data = storage.load_posts()
        comments_data = storage.load_comments()

        if not posts_data:
            print(f"No posts found for r/{subreddit}")
            return

        # Convert to model objects
        from .models import RedditComment, RedditPost

        posts = [RedditPost(**post_data) for post_data in posts_data]
        comments = [RedditComment(**comment_data) for comment_data in comments_data]

        print(f"Processing media for {len(posts)} posts and {len(comments)} comments...")

        # Collect and download media
        media_collector = MediaCollector(subreddit)
        media_items = media_collector.extract_media_urls(posts, comments)

        if media_items:
            download_results = asyncio.run(media_collector.download_all_media(media_items))

            # Update with paths
            posts = media_collector.update_posts_with_paths(posts, download_results)
            comments = media_collector.update_comments_with_paths(comments, download_results)

            # Save updated data
            storage.save_posts(posts)
            storage.save_comments(comments)

            print("Media download complete!")
        else:
            print("No media URLs found")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@main.command()
@click.argument("subreddit")
@click.option("--chunk-size", default=5, help="Number of posts per chunk")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to (Flask uses 5000)")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.option("--backend-only", is_flag=True, help="Start only the backend (no frontend)")
@click.option("--flask", is_flag=True, help="Use Flask viewer (simple, no npm needed)")
@click.option("--dioxus", is_flag=True, help="Use Dioxus desktop app (Rust GUI, experimental)")
def web(
    subreddit: str,
    chunk_size: int,
    host: str,
    port: int,
    reload: bool,
    backend_only: bool,
    flask: bool,
    dioxus: bool,
):
    """Start the web viewer for a scraped subreddit.

    Default: FastAPI + React (modern, requires npm)
    --flask: Simple Flask-only viewer (no build step)
    --dioxus: Experimental Rust desktop app (no web server)
    """
    import subprocess
    import sys
    from pathlib import Path

    # Dioxus mode - Rust desktop app, zero runtime dependencies
    if dioxus:
        try:
            print(f"\n{'=' * 60}")
            print(f"Reddit Data Viewer - r/{subreddit} (Dioxus Desktop)")
            print(f"{'=' * 60}\n")

            rust_viewer_dir = Path(__file__).parent.parent / "rust-web-viewer"

            if not rust_viewer_dir.exists():
                click.echo("Error: Dioxus viewer not found at src/rust-web-viewer", err=True)
                raise click.Abort()

            print("Building and launching Dioxus desktop app...")
            print("(First build may take a few minutes)\n")

            # Build and run the Dioxus desktop app
            result = subprocess.run(
                [
                    "cargo",
                    "run",
                    "--release",
                    "--bin",
                    "reddit-viewer-desktop",
                    "--",
                    subreddit,
                    str(chunk_size),
                ],
                cwd=rust_viewer_dir,
            )

            sys.exit(result.returncode)

        except FileNotFoundError:
            click.echo("Error: Cargo not found. Install Rust toolchain first.", err=True)
            raise click.Abort()
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort()

    # Flask mode - simpler, Python-only
    if flask:
        try:
            print(f"\n{'=' * 60}")
            print(f"Reddit Data Viewer - r/{subreddit} (Flask)")
            print(f"{'=' * 60}")
            flask_port = port if port != 8000 else 5000  # Default Flask to 5000
            print(f"Server: http://{host}:{flask_port}")
            print(f"{'=' * 60}\n")

            flask_app_path = Path(__file__).parent.parent / "python-web-viewer" / "flask"
            sys.path.insert(0, str(flask_app_path))

            from reddit_flask import create_app as create_flask_app

            flask_app = create_flask_app(subreddit, chunk_size)
            flask_app.run(debug=reload, host=host, port=flask_port)
            return

        except Exception as e:
            import traceback

            click.echo(f"Error starting Flask viewer: {e}", err=True)
            traceback.print_exc()
            raise click.Abort()

    # FastAPI + React
    try:
        # Import FastAPI backend directly from file path
        backend_path = Path(__file__).parent.parent / "web_new" / "backend"
        sys.path.insert(0, str(backend_path))

        from main import create_app

        app = create_app(subreddit, chunk_size)

        print(f"\n{'=' * 60}")
        print(f"Reddit Data Viewer - r/{subreddit}")
        print(f"{'=' * 60}")
        print(f"Backend API: http://{host}:{port}")

        frontend_process = None

        if not backend_only:
            # Start frontend dev server
            frontend_dir = Path(__file__).parent.parent / "web_new" / "frontend"

            if not frontend_dir.exists():
                click.echo(
                    "Warning: Frontend directory not found. Starting backend only.", err=True
                )
            elif not (frontend_dir / "node_modules").exists():
                click.echo("\nFrontend dependencies not installed. Run:", err=True)
                click.echo(f"  cd {frontend_dir} && npm install\n", err=True)
                click.echo("Starting backend only...", err=True)
            else:
                try:
                    print("Frontend: http://localhost:5173")
                    print(f"{'=' * 60}\n")
                    print("Starting frontend dev server...")

                    frontend_process = subprocess.Popen(
                        ["npm", "run", "dev"],
                        cwd=frontend_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )

                    # Give frontend a moment to start
                    import time

                    time.sleep(2)

                    if frontend_process.poll() is not None:
                        click.echo(
                            "Warning: Frontend failed to start. Check npm installation.", err=True
                        )
                        frontend_process = None
                    else:
                        print("Frontend server started!")
                        print("\n→ Open http://localhost:5173 in your browser\n")

                except FileNotFoundError:
                    click.echo("Warning: npm not found. Starting backend only.", err=True)
                    frontend_process = None
        else:
            print(f"{'=' * 60}\n")
            print("Backend-only mode (use --backend-only=false to start frontend)\n")

        print("Starting backend server...")

        import uvicorn

        try:
            uvicorn.run(app, host=host, port=port, reload=reload)
        finally:
            # Clean up frontend process on exit
            if frontend_process:
                print("\nStopping frontend server...")
                frontend_process.terminate()
                try:
                    frontend_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    frontend_process.kill()

    except ImportError:
        click.echo("Error: Web dependencies not installed. Run: uv sync --extra web", err=True)
        raise click.Abort()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        if "frontend_process" in locals() and frontend_process:
            frontend_process.terminate()
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if "frontend_process" in locals() and frontend_process:
            frontend_process.terminate()
        raise click.Abort()


if __name__ == "__main__":
    main()
