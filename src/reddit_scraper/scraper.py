"""
Simple PRAW-based Reddit scraper.
"""

import re
from typing import List, Optional

import praw
import prawcore

from .config import Config
from .models import RedditComment, RedditPost


class RedditScraper:
    """Simple Reddit scraper using PRAW."""

    def __init__(self, subreddit: str):
        self.subreddit = subreddit

        if not Config.REDDIT_CLIENT_ID or not Config.REDDIT_CLIENT_SECRET:
            raise ValueError(
                "Reddit API credentials required. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET"
            )

        self.reddit = praw.Reddit(
            client_id=Config.REDDIT_CLIENT_ID,
            client_secret=Config.REDDIT_CLIENT_SECRET,
            user_agent=Config.REDDIT_USER_AGENT,
        )

        try:
            self.subreddit_obj = self.reddit.subreddit(subreddit)
            # Test access
            _ = self.subreddit_obj.display_name
            print(f"Connected to r/{subreddit}")
        except prawcore.exceptions.NotFound:
            raise ValueError(f"Subreddit r/{subreddit} not found")
        except Exception as e:
            raise ValueError(f"Failed to connect to Reddit: {e}")

    def scrape_posts(
        self, limit: int = 100, sort: str = "new", time_filter: str = "all"
    ) -> List[RedditPost]:
        """Scrape posts from the subreddit."""
        posts = []

        try:
            if sort == "hot":
                submissions = self.subreddit_obj.hot(limit=limit)
            elif sort == "top":
                submissions = self.subreddit_obj.top(
                    time_filter=time_filter, limit=limit
                )  # Add time_filter
            elif sort == "rising":
                submissions = self.subreddit_obj.rising(limit=limit)
            else:  # default to new
                submissions = self.subreddit_obj.new(limit=limit)

            print(f"Scraping {limit} {sort} posts from r/{self.subreddit}...")

            for submission in submissions:
                try:
                    post = self._submission_to_post(submission)
                    posts.append(post)

                    if len(posts) % 10 == 0:
                        print(f"Scraped {len(posts)} posts...")

                except Exception as e:
                    print(f"Error processing submission {submission.id}: {e}")
                    continue

            print(f"Scraped {len(posts)} posts")
            return posts

        except Exception as e:
            print(f"Error scraping posts: {e}")
            return posts

    def scrape_comments(
        self, post_ids: List[str], limit: Optional[int] = None
    ) -> List[RedditComment]:
        """Scrape comments for given post IDs."""
        all_comments = []

        print(f"Scraping comments for {len(post_ids)} posts...")

        for post_id in post_ids:
            try:
                comments = self._scrape_post_comments(post_id, limit)
                all_comments.extend(comments)

                if (
                    len(post_ids) > 10
                    and len([pid for pid in post_ids[: post_ids.index(post_id) + 1]]) % 10 == 0
                ):
                    print(
                        f"Processed comments for {post_ids.index(post_id) + 1}/{len(post_ids)} posts..."
                    )

            except Exception as e:
                print(f"Error scraping comments for post {post_id}: {e}")
                continue

        print(f"Scraped {len(all_comments)} comments")
        return all_comments

    def _scrape_post_comments(
        self, post_id: str, limit: Optional[int] = None
    ) -> List[RedditComment]:
        """Scrape comments for a single post."""
        comments = []

        try:
            submission = self.reddit.submission(id=post_id)
            submission.comments.replace_more(limit=0)  # Remove "more comments" objects

            comment_count = 0
            for comment in submission.comments.list():
                if not isinstance(comment, praw.models.Comment):  # type: ignore
                    continue

                if limit and comment_count >= limit:
                    break

                try:
                    reddit_comment = self._comment_to_comment(comment, post_id)
                    comments.append(reddit_comment)
                    comment_count += 1
                except Exception as e:
                    comment_id = getattr(comment, "id", "unknown")
                    print(f"Error processing comment {comment_id}: {e}")
                    continue

            return comments

        except prawcore.exceptions.NotFound:
            print(f"Post {post_id} not found")
            return []
        except Exception as e:
            print(f"Error scraping comments for post {post_id}: {e}")
            return []

    def _submission_to_post(self, submission) -> RedditPost:
        """Convert PRAW submission to RedditPost."""
        # Determine media type
        media_type = "text"
        is_video = False
        has_gallery = False

        # Initialize URL fields
        image_url = None
        video_url = None
        gif_url = None

        if hasattr(submission, "is_video") and submission.is_video:
            media_type = "video"
            is_video = True
            # Extract actual v.redd.it URL from media data
            if hasattr(submission, "media") and submission.media:
                try:
                    video_url = submission.media["reddit_video"]["fallback_url"]
                    # Remove quality suffix if present to get base URL
                    if "DASH_" in video_url:
                        video_url = video_url.split("/DASH_")[0]
                except (KeyError, TypeError):
                    video_url = submission.url
            else:
                video_url = submission.url
        elif hasattr(submission, "is_gallery") and submission.is_gallery:
            media_type = "gallery"
            has_gallery = True
        elif submission.url and any(
            ext in submission.url.lower() for ext in [".jpg", ".png", ".gif", ".webp"]
        ):
            if ".gif" in submission.url.lower():
                media_type = "gif"
                gif_url = submission.url  # Set gif_url
            else:
                media_type = "image"
                image_url = submission.url  # Set image_url
        elif submission.url and submission.url != submission.permalink:
            media_type = "link"

        gallery_urls = []
        if hasattr(submission, "is_gallery") and submission.is_gallery:
            gallery_urls = self._extract_gallery_urls(submission)

        return RedditPost(
            id=submission.id,
            title=submission.title or "",
            url=submission.url or "",
            permalink=f"https://reddit.com{submission.permalink}",
            score=submission.score,
            upvote_ratio=submission.upvote_ratio,
            num_comments=submission.num_comments,
            author=str(submission.author) if submission.author else "[deleted]",
            selftext=submission.selftext or "",
            created_utc=float(submission.created_utc),
            is_video=is_video,
            has_gallery=has_gallery,
            media_type=media_type,
            domain=getattr(submission, "domain", ""),
            gallery_urls=gallery_urls,
            image_url=image_url,
            video_url=video_url,
            gif_url=gif_url,
        )

    def _extract_gallery_urls(self, submission) -> List[str]:
        """Extract gallery urls from submission"""
        gallery_urls = []
        try:
            if hasattr(submission, "gallery_data") and hasattr(submission, "media_metadata"):
                for item in submission.gallery_data.get("items", []):
                    media_id = item.get("media_id")
                    if media_id in submission.media_metadata:
                        media_info = submission.media_metadata[media_id]

                        # Check for both Image and AnimatedImage types
                        if media_info.get("e") in ["Image", "AnimatedImage"]:
                            # Try s.gif first, then s.u
                            resolutions = media_info.get("s", {}).get("gif") or media_info.get(
                                "s", {}
                            ).get("u")
                            if resolutions:
                                url = resolutions.replace("&amp;", "&")

                                # Add reddit_gif tag for AnimatedImage to help downstream detection
                                if media_info.get("e") == "AnimatedImage":
                                    url = url + "#reddit_gif"

                                gallery_urls.append(url)
        except Exception as e:
            print(f"Gallery extraction error: {e}")

        return gallery_urls

    def _comment_to_comment(self, comment, post_id: str) -> RedditComment:
        """Convert PRAW comment to RedditComment."""
        # Determine parent_id and depth
        parent_id = None
        depth = 0
        is_root = True

        if hasattr(comment, "parent_id") and comment.parent_id:
            if comment.parent_id.startswith("t1_"):  # Comment parent
                parent_id = comment.parent_id[3:]
                is_root = False
                # Calculate depth by traversing up
                depth = self._calculate_comment_depth(comment)
            # If parent_id starts with 't3_', it's a top-level comment (parent_id = None)

        return RedditComment(
            id=comment.id,
            parent_id=parent_id,
            post_id=post_id,
            permalink=f"https://reddit.com{comment.permalink}",
            body=comment.body or "",
            score=comment.score,
            author=str(comment.author) if comment.author else "[deleted]",
            created_utc=float(comment.created_utc),
            depth=depth,
            is_root=is_root,
        )

    def _calculate_comment_depth(self, comment) -> int:
        """Calculate the depth of a comment in the thread."""
        depth = 0
        current = comment

        while hasattr(current, "parent") and current.parent():
            parent = current.parent()
            if isinstance(parent, praw.models.Comment):  # type: ignore
                depth += 1
                current = parent
            else:
                break  # Reached the submission

        return depth

    def scrape_post_by_url(
        self, url: str, comment_limit: Optional[int] = None
    ) -> tuple[List[RedditPost], List[RedditComment]]:
        """Scrape a single post by its Reddit URL."""
        print(f"Fetching post from URL: {url}")

        try:
            submission = self.reddit.submission(url=url)
            post = self._submission_to_post(submission)
            print(f"Found post: {post.title}")
        except Exception as e:
            raise ValueError(f"Failed to fetch post from URL: {e}")

        comments = []
        if comment_limit != 0:
            comments = self.scrape_comments([post.id], comment_limit)

        print(f"Scrape complete: 1 post, {len(comments)} comments")
        return [post], comments

    @staticmethod
    def extract_subreddit_from_url(url: str) -> str:
        """Extract the subreddit name from a Reddit URL."""
        match = re.search(r"/r/([^/]+)", url)
        if match:
            return match.group(1)
        raise ValueError(
            f"Could not extract subreddit from URL: {url}\n"
            "Expected format: https://www.reddit.com/r/SUBREDDIT/comments/..."
        )

    def scrape_subreddit(
        self,
        post_limit: int = 100,
        comment_limit: Optional[int] = None,
        sort: str = "new",
        time_filter: str = "all",
    ) -> tuple[List[RedditPost], List[RedditComment]]:
        """Scrape both posts and comments from subreddit."""
        print(f"Starting scrape of r/{self.subreddit}")

        # Scrape posts
        posts = self.scrape_posts(
            limit=post_limit, sort=sort, time_filter=time_filter
        )  # Pass time_filter

        # Scrape comments if requested
        comments = []
        if comment_limit != 0:  # None means get all
            post_ids = [post.id for post in posts]
            comments = self.scrape_comments(post_ids, comment_limit)

        print(f"Scrape complete: {len(posts)} posts, {len(comments)} comments")
        return posts, comments
