// Virtualized Scroll with Absolute Positioning
//
// Every chunk is position:absolute with a calculated top offset.
// A height map tracks all chunk heights (measured or estimated).
// ResizeObserver updates the map as media loads, and anchor-based
// scroll correction prevents visual jumps. This is the same
// fundamental approach used by react-window, tanstack-virtual,
// and production social media feeds.

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const POSTS_PER_CHUNK = 10;
const BUFFER_CHUNKS = 3;
const DATA_CACHE_MAX = 15;
const PREFETCH_AHEAD = 2;
const INITIAL_HEIGHT_ESTIMATE = 3000;
const PADDING_TOP = 32;
const PADDING_BOTTOM = 32;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let totalChunks = 0;
let commentsCache = {};
let chunkDataCache = new Map();

// Virtual scroll state
let heights = []; // heights[i] = height of chunk i (0-indexed)
let offsets = []; // offsets[i] = top position of chunk i
let totalHeight = 0;
let renderedWrappers = new Map(); // chunkIndex -> DOM element
let isUpdating = false;
let updateQueued = false;

let scrollContainer, postsContainer;
let resizeObserver;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function addToDataCache(chunkNum, posts) {
  if (chunkDataCache.has(chunkNum)) chunkDataCache.delete(chunkNum);
  chunkDataCache.set(chunkNum, posts);
  while (chunkDataCache.size > DATA_CACHE_MAX) {
    const oldest = chunkDataCache.keys().next().value;
    chunkDataCache.delete(oldest);
  }
}

function getFromDataCache(chunkNum) {
  if (!chunkDataCache.has(chunkNum)) return null;
  const data = chunkDataCache.get(chunkNum);
  chunkDataCache.delete(chunkNum);
  chunkDataCache.set(chunkNum, data);
  return data;
}

// ---------------------------------------------------------------------------
// Offset calculation
// ---------------------------------------------------------------------------

function recalcOffsets() {
  offsets = new Array(totalChunks + 1);
  offsets[0] = PADDING_TOP;
  for (let i = 0; i < totalChunks; i++) {
    offsets[i + 1] = offsets[i] + heights[i];
  }
  totalHeight = offsets[totalChunks] + PADDING_BOTTOM;
}

function findChunkAtOffset(y) {
  if (totalChunks === 0) return 0;
  let lo = 0,
    hi = totalChunks - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (offsets[mid + 1] <= y) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo;
}

// ---------------------------------------------------------------------------
// Layout correction (called by ResizeObserver)
// ---------------------------------------------------------------------------

function applyLayoutCorrection() {
  // Anchor: the chunk the user is currently looking at
  const scrollTop = scrollContainer.scrollTop;
  const anchorIdx = findChunkAtOffset(scrollTop);
  const anchorRelOffset = scrollTop - offsets[anchorIdx];

  recalcOffsets();
  postsContainer.style.height = totalHeight + "px";

  // Reposition all rendered wrappers
  for (const [idx, wrapper] of renderedWrappers) {
    wrapper.style.top = offsets[idx] + "px";
  }

  // Correct scroll so the anchor chunk stays at the same visual position
  const corrected = offsets[anchorIdx] + anchorRelOffset;
  if (Math.abs(scrollContainer.scrollTop - corrected) > 1) {
    scrollContainer.scrollTop = corrected;
  }
}

// ---------------------------------------------------------------------------
// ResizeObserver
// ---------------------------------------------------------------------------

function initResizeObserver() {
  resizeObserver = new ResizeObserver((entries) => {
    let changed = false;
    for (const entry of entries) {
      const idx = parseInt(entry.target.dataset.chunkIndex);
      // Skip empty wrappers (data still loading)
      if (entry.target.childElementCount === 0) continue;
      const newHeight =
        entry.borderBoxSize?.[0]?.blockSize ?? entry.target.offsetHeight;
      if (Math.abs(heights[idx] - newHeight) > 1) {
        heights[idx] = newHeight;
        changed = true;
      }
    }
    if (changed) {
      applyLayoutCorrection();
    }
  });
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchTotalChunks() {
  try {
    const response = await fetch("/api/chunks/count");
    const data = await response.json();
    totalChunks = data.count;
  } catch (error) {
    console.error("Error fetching total chunks:", error);
  }
}

async function fetchChunk(chunkNum) {
  try {
    const response = await fetch(`/api/chunks/${chunkNum}`);
    const data = await response.json();
    const posts = data.posts || [];
    addToDataCache(chunkNum, posts);
    return posts;
  } catch (error) {
    console.error(`Error fetching chunk ${chunkNum}:`, error);
    return [];
  }
}

async function fetchComments(postId) {
  if (commentsCache[postId]) return commentsCache[postId];
  try {
    const response = await fetch(`/api/comments/${postId}`);
    const data = await response.json();
    commentsCache[postId] = data.comments;
    return data.comments;
  } catch (error) {
    console.error(`Error fetching comments for ${postId}:`, error);
    return [];
  }
}

// ---------------------------------------------------------------------------
// Post / Media / Comment rendering
// ---------------------------------------------------------------------------

function renderMedia(media) {
  if (!media || media.type === "none") return "";

  switch (media.type) {
    case "image":
      return `<div class="media-container"><img src="/media/${media.image.filename}" alt="Post image" loading="lazy" onclick="openLightbox(this)"></div>`;

    case "video":
      return `<div class="media-container"><video controls preload="metadata"><source src="/media/${media.video.filename}"></video></div>`;

    case "gif":
      return `<div class="media-container"><video autoplay loop muted playsinline preload="auto" onclick="openLightbox(this)"><source src="/media/${media.gif.filename}"></video></div>`;

    case "gallery": {
      const galleryId = "gallery-" + Math.random().toString(36).slice(2, 9);
      const itemsHtml = media.gallery.items
        .map((item, index) => {
          const mediaEl =
            item.type === "gif"
              ? `<video autoplay loop muted playsinline preload="auto" onclick="openLightbox(this)"><source src="/media/${item.filename}"></video>`
              : `<img src="/media/${item.filename}" alt="Gallery image ${index + 1}" loading="lazy" onclick="openLightbox(this)">`;
          return `<div class="gallery-item${index === 0 ? " active" : ""}" data-index="${index}">${mediaEl}</div>`;
        })
        .join("");

      const dotsHtml = media.gallery.items
        .map(
          (_, index) =>
            `<span class="gallery-dot ${index === 0 ? "active" : ""}" data-index="${index}"></span>`,
        )
        .join("");

      return `
                <div class="media-container gallery-carousel" id="${galleryId}" data-current="0">
                    <div class="gallery-items">${itemsHtml}</div>
                    ${
                      media.gallery.items.length > 1
                        ? `
                        <button class="gallery-nav gallery-prev" onclick="navigateGallery('${galleryId}', -1)">&lsaquo;</button>
                        <button class="gallery-nav gallery-next" onclick="navigateGallery('${galleryId}', 1)">&rsaquo;</button>
                        <div class="gallery-dots">${dotsHtml}</div>
                    `
                        : ""
                    }
                </div>
            `;
    }
    default:
      return "";
  }
}

function navigateGallery(galleryId, direction) {
  const gallery = document.getElementById(galleryId);
  if (!gallery) return;

  const items = gallery.querySelectorAll(".gallery-item");
  const dots = gallery.querySelectorAll(".gallery-dot");
  const current = parseInt(gallery.dataset.current);
  const total = items.length;

  let newIndex = current + direction;
  if (newIndex < 0) newIndex = total - 1;
  if (newIndex >= total) newIndex = 0;

  const currentVideo = items[current].querySelector("video");
  if (currentVideo) {
    currentVideo.pause();
    currentVideo.currentTime = 0;
  }

  items[current].classList.remove("active");
  dots[current].classList.remove("active");

  items[newIndex].classList.add("active");
  dots[newIndex].classList.add("active");

  const newVideo = items[newIndex].querySelector("video");
  if (newVideo) {
    newVideo.currentTime = 0;
    newVideo.play().catch(() => {});
  }

  gallery.dataset.current = newIndex;
}

function renderComment(comment) {
  const commentMedia =
    comment.image_type !== "none"
      ? `<div class="media-container"><img src="/media/${comment.image}" alt="Comment media" loading="lazy" onclick="openLightbox(this)"></div>`
      : "";

  const replies =
    comment.replies && comment.replies.length > 0
      ? `<div class="replies">${comment.replies.map(renderComment).join("")}</div>`
      : "";

  return `
        <div class="comment">
            <div class="comment-text">${escapeHtml(comment.text)}</div>
            ${commentMedia}
            ${replies}
        </div>
    `;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function toggleComments(postId, button) {
  const postActions = button.parentElement;
  const commentsSection = postActions.nextElementSibling;

  if (
    !commentsSection ||
    !commentsSection.classList.contains("comments-section")
  )
    return;

  if (
    commentsSection.style.display === "none" ||
    !commentsSection.style.display
  ) {
    if (!commentsSection.hasChildNodes()) {
      button.textContent = "Loading...";
      const comments = await fetchComments(postId);
      if (comments.length > 0) {
        commentsSection.innerHTML = comments.map(renderComment).join("");
      } else {
        commentsSection.innerHTML = '<p class="comment">No comments</p>';
      }
    }
    commentsSection.style.display = "block";
    button.textContent = "Hide Comments";
  } else {
    commentsSection.style.display = "none";
    button.textContent = `Show Comments (${commentsSection.childElementCount})`;
  }
}

function renderPost(post) {
  const postDiv = document.createElement("div");
  postDiv.className = "post";
  postDiv.dataset.postId = post.id;

  const mediaHtml = renderMedia(post.media);
  const commentsButton =
    post.commentCount > 0
      ? `<button class="comments-toggle" onclick="toggleComments('${post.id}', this)">Show Comments (${post.commentCount})</button>`
      : "";

  postDiv.innerHTML = `
        <h2 class="post-title">${escapeHtml(post.title)}</h2>
        <div class="post-meta">${post.created_time}</div>
        ${post.text ? `<div class="post-text">${escapeHtml(post.text)}</div>` : ""}
        ${mediaHtml}
        <div class="post-actions">${commentsButton}</div>
        <div class="comments-section" style="display: none;"></div>
    `;

  return postDiv;
}

// ---------------------------------------------------------------------------
// Chunk management
// ---------------------------------------------------------------------------

function renderChunkToDOM(chunkIndex) {
  if (renderedWrappers.has(chunkIndex)) return;

  const chunkNum = chunkIndex + 1;
  const posts = getFromDataCache(chunkNum);

  const wrapper = document.createElement("div");
  wrapper.className = "chunk-wrapper";
  wrapper.dataset.chunkIndex = String(chunkIndex);
  wrapper.style.position = "absolute";
  wrapper.style.top = offsets[chunkIndex] + "px";
  wrapper.style.left = "0";
  wrapper.style.right = "0";

  if (posts && posts.length > 0) {
    posts.forEach((post) => wrapper.appendChild(renderPost(post)));
  }

  postsContainer.appendChild(wrapper);
  renderedWrappers.set(chunkIndex, wrapper);
  resizeObserver.observe(wrapper);
}

function unloadChunk(chunkIndex) {
  const wrapper = renderedWrappers.get(chunkIndex);
  if (!wrapper) return;

  // Capture final measured height
  const measured = wrapper.offsetHeight;
  if (measured > 0) {
    heights[chunkIndex] = measured;
  }

  wrapper.querySelectorAll("video").forEach((v) => v.pause());
  resizeObserver.unobserve(wrapper);
  wrapper.remove();
  renderedWrappers.delete(chunkIndex);
}

// ---------------------------------------------------------------------------
// Window update
// ---------------------------------------------------------------------------

async function updateWindow() {
  if (isUpdating) {
    updateQueued = true;
    return;
  }
  isUpdating = true;

  try {
    const scrollTop = scrollContainer.scrollTop;
    const viewportHeight = scrollContainer.clientHeight;

    const firstVisible = findChunkAtOffset(scrollTop);
    const lastVisible = findChunkAtOffset(scrollTop + viewportHeight);

    const windowStart = Math.max(0, firstVisible - BUFFER_CHUNKS);
    const windowEnd = Math.min(totalChunks - 1, lastVisible + BUFFER_CHUNKS);

    // Unload chunks outside the window
    for (const [idx] of [...renderedWrappers]) {
      if (idx < windowStart || idx > windowEnd) {
        unloadChunk(idx);
      }
    }

    // Collect chunks that need data fetched
    const toFetch = [];
    for (let i = windowStart; i <= windowEnd; i++) {
      if (!renderedWrappers.has(i) && !getFromDataCache(i + 1)) {
        toFetch.push(i + 1); // API uses 1-based chunk numbers
      }
    }

    // Fetch all needed data in parallel
    if (toFetch.length > 0) {
      await Promise.all(toFetch.map((chunkNum) => fetchChunk(chunkNum)));
    }

    // Render all chunks in the window
    for (let i = windowStart; i <= windowEnd; i++) {
      renderChunkToDOM(i);
    }

    // Prefetch data beyond the window (fire-and-forget)
    for (let i = 1; i <= PREFETCH_AHEAD; i++) {
      const target = windowEnd + i;
      if (target < totalChunks && !chunkDataCache.has(target + 1)) {
        fetchChunk(target + 1);
      }
    }
  } finally {
    isUpdating = false;
  }

  if (updateQueued) {
    updateQueued = false;
    await updateWindow();
  }
}

// ---------------------------------------------------------------------------
// Scroll handling
// ---------------------------------------------------------------------------

let scrollRAF = null;

function handleScroll() {
  if (scrollRAF) return;
  scrollRAF = requestAnimationFrame(() => {
    scrollRAF = null;
    updateWindow();
  });
}

// ---------------------------------------------------------------------------
// Lightbox
// ---------------------------------------------------------------------------

function openLightbox(element) {
  const lightbox = document.getElementById("lightbox");
  const lightboxContent = document.getElementById("lightbox-content");

  const clone = element.cloneNode(true);
  clone.removeAttribute("onclick");

  if (clone.tagName === "VIDEO") {
    clone.controls = true;
    clone.style.cursor = "default";
  }

  lightboxContent.innerHTML = "";
  lightboxContent.appendChild(clone);
  lightbox.classList.add("active");
  document.body.style.overflow = "hidden";
}

function closeLightbox() {
  const lightbox = document.getElementById("lightbox");
  lightbox.classList.remove("active");
  document.body.style.overflow = "auto";
  lightbox.querySelectorAll("video").forEach((video) => video.pause());
}

document.addEventListener("DOMContentLoaded", () => {
  const lightbox = document.getElementById("lightbox");
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox) closeLightbox();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
  });
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  scrollContainer = document.getElementById("virtual-scroll-container");
  postsContainer = document.getElementById("posts-container");
  document.getElementById("loading").textContent = "Loading...";

  initResizeObserver();

  await fetchTotalChunks();

  if (totalChunks === 0) {
    document.getElementById("loading").textContent = "No posts found";
    return;
  }

  // Initialize height map with estimates
  heights = new Array(totalChunks).fill(INITIAL_HEIGHT_ESTIMATE);
  recalcOffsets();

  // Set container height so the scrollbar reflects total content
  postsContainer.style.height = totalHeight + "px";

  // Listen for scroll
  scrollContainer.addEventListener("scroll", handleScroll, { passive: true });

  // Render initial window
  await updateWindow();

  document.getElementById("loading").style.display = "none";
}

init();
