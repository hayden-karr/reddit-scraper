"""
Merge multiple subreddit datasets into a single dataset.
"""

import shutil
from typing import List

from .config import Config


def merge_subreddits(source_subreddits: List[str], target_name: str = "merged"):
    """Merge multiple subreddit datasets into one."""
    import polars as pl

    print(f"Merging {len(source_subreddits)} subreddits into '{target_name}'...")

    # Setup target directory
    target_dir = Config.get_subreddit_dir(target_name)
    target_media_dir = Config.get_media_dir(target_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_media_dir.mkdir(parents=True, exist_ok=True)

    all_posts = []
    all_comments = []

    # Collect all posts and comments
    for subreddit in source_subreddits:
        print(f"\nProcessing r/{subreddit}...")

        source_dir = Config.get_subreddit_dir(subreddit)
        posts_file = source_dir / "posts.parquet"
        comments_file = source_dir / "comments.parquet"

        if not posts_file.exists():
            print(f"  Warning: No posts file found for r/{subreddit}, skipping...")
            continue

        # Load posts - convert Object columns to String
        posts_df = pl.read_parquet(posts_file)

        # Convert Object dtype columns to String
        for col in posts_df.columns:
            if posts_df[col].dtype == pl.Object:
                posts_df = posts_df.with_columns(
                    pl.col(col).map_elements(
                        lambda x: str(x) if x is not None else None, return_dtype=pl.Utf8
                    )
                )

        print(f"  Found {len(posts_df)} posts")
        all_posts.append(posts_df)

        # Load comments if they exist
        if comments_file.exists():
            comments_df = pl.read_parquet(comments_file)

            # Convert Object dtype columns to String
            for col in comments_df.columns:
                if comments_df[col].dtype == pl.Object:
                    comments_df = comments_df.with_columns(
                        pl.col(col).map_elements(
                            lambda x: str(x) if x is not None else None, return_dtype=pl.Utf8
                        )
                    )

            print(f"  Found {len(comments_df)} comments")
            all_comments.append(comments_df)

        # Copy media files
        source_media_dir = Config.get_media_dir(subreddit)
        if source_media_dir.exists():
            media_files = list(source_media_dir.glob("*"))
            print(f"  Copying {len(media_files)} media files...")

            for media_file in media_files:
                if media_file.is_file():
                    target_file = target_media_dir / media_file.name
                    # Skip if file already exists (avoid duplicates)
                    if not target_file.exists():
                        shutil.copy2(media_file, target_file)

    if not all_posts:
        print("\nNo posts found in any subreddit!")
        return

    # Merge posts
    print("\nMerging posts...")
    merged_posts = pl.concat(all_posts, how="vertical_relaxed")
    merged_posts = merged_posts.unique(subset=["id"], keep="last")
    merged_posts = merged_posts.sort("created_utc", descending=True)

    # Merge comments
    if all_comments:
        print("Merging comments...")
        merged_comments = pl.concat(all_comments, how="vertical_relaxed")
        merged_comments = merged_comments.unique(subset=["id"], keep="last")
        merged_comments = merged_comments.sort("created_utc", descending=True)
    else:
        merged_comments = None

    # Save merged data
    target_posts_file = target_dir / "posts.parquet"
    target_comments_file = target_dir / "comments.parquet"

    print(f"\nSaving merged data to {target_dir}...")
    merged_posts.write_parquet(target_posts_file, compression="zstd")
    print(f"  Saved {len(merged_posts)} posts")

    if merged_comments is not None:
        merged_comments.write_parquet(target_comments_file, compression="zstd")
        print(f"  Saved {len(merged_comments)} comments")

    # Count media files
    media_count = len(list(target_media_dir.glob("*")))
    print(f"  {media_count} media files")

    print(f"\nMerge complete! Dataset: r/{target_name}")
    print(f"   Posts: {len(merged_posts)}")
    if merged_comments is not None:
        print(f"   Comments: {len(merged_comments)}")
    print(f"   Media files: {media_count}")

    # Show media type breakdown
    print("\nMedia breakdown:")
    images = (
        len(list(target_media_dir.glob("*.jpg")))
        + len(list(target_media_dir.glob("*.jpeg")))
        + len(list(target_media_dir.glob("*.png")))
        + len(list(target_media_dir.glob("*.webp")))
    )
    videos = len(list(target_media_dir.glob("*.mp4"))) + len(
        list(target_media_dir.glob("video_*.webm"))
    )
    gifs = len(list(target_media_dir.glob("gif_*.webm"))) + len(
        list(target_media_dir.glob("*.gif"))
    )
    galleries = len(
        set([f.name.split("_gallery_")[0] for f in target_media_dir.glob("*_gallery_*")])
    )

    print(f"  Images: {images}")
    print(f"  Videos: {videos}")
    print(f"  GIFs: {gifs}")
    print(f"  Gallery posts: {galleries}")

    print(f"\nTo view: uv run reddit-scraper web {target_name} --help")
