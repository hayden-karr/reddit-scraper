use crate::{MediaItem, ProcessinResult};
use anyhow::Result;
use futures::{StreamExt, stream};
use std::collections::HashMap;
use std::path::PathBuf;

pub async fn process_media_batch(
    client: &reqwest::Client,
    subreddit: &str,
    media_items: Vec<MediaItem>,
    max_concurrent: usize,
) -> Result<ProcessingResult> {
    let mut success: HashMap<String, Vec<String>> = HashMap::new();
    let mut failed = Vec::new();
    let mut stats: HashMap<String, u64> = HashMap::new();

    // Process items concurrent with limit
    let results: Vec<_> = stream::iter(media_items)
        .map(|item| process_single_media(client, subreddit, item))
        .buffer_unordered(max_concurrent)
        .collect()
        .await;

    for result in results {
        match result {
            Ok(Some((category, path))) => {
                success
                    .entry(category.clone())
                    .or_insert_with(Vec::new)
                    .push(path);
                *stats.entry(format!("{}_success", category)).or_insert(0) += 1;
            }
            Ok(None) => {
                *stats.entry("skipped".to_string()).or_insert(0) += 1;
            }
            Err(url) => {
                failed.push(url);
                *stats.entry("failed".to_string()).or_insert(0) += 1;
            }
        }
    }

    Ok(ProcessinResult {
        success,
        failed,
        stats,
    })
}

async fn process_single_media(
    client: &reqwest::Client,
    subreddit: &str,
    item: MediaItem,
) -> Result<Option<(String, String)>, String> {
    match item.media_type.as_str() {
        "image" => process_image(client, subreddit, &item.url, &item.item_id)
            .await
            .map(|path| path.map(|p| ("images".to_string(), p)))
            .map_err(|_| item.url),
        "gif" => process_gif(client, subreddit, &item.url, &item.item_id)
            .await
            .map(|path| path.map(|p| ("gifs".to_string(), p)))
            .map_err(|_| item.url),
        "video" => process_video(client, subreddit, &item.url, &item.item_id)
            .await
            .map(|path| path.map(|p| ("videos".to_string(), p)))
            .map_err(|_| item.url),
        _ => Ok(None),
    }
}
