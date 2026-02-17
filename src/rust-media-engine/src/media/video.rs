use crate::media::ConversionResult;
use std::path::Path;
use tokio::fs;
use url::Url;

const DASH_NAMESPACE: &str = "urn:mpeg:dash:schema:mpd:2011";
const DASH_TIMEOUT_SECS: u64 = 15;

/// Resolved video and audio stream URLs from a v.redd.it video.
pub struct DashStreams {
    pub video_url: Option<String>,
    pub audio_url: Option<String>,
}

/// Get the best video and audio streams for a v.redd.it URL.
/// Mirrors Python VideoHandler._get_best_streams exactly:
///   1. Try DASHPlaylist.mpd first and parse it
///   2. Fall back to probing direct quality URLs + audio discovery
pub async fn get_best_streams(
    client: &reqwest::Client,
    video_url: &str,
) -> DashStreams {
    // Only handle v.redd.it base URLs (not direct .mp4/.mpd files)
    if video_url.contains("v.redd.it")
        && !video_url.ends_with(".mp4")
        && !video_url.ends_with(".mpd")
    {
        let base_url = video_url.trim_end_matches('/');
        let dash_url = format!("{}/DASHPlaylist.mpd", base_url);

        // Try DASH manifest first (like Python)
        if url_exists(client, &dash_url).await {
            log::debug!("Found DASH manifest: {}", dash_url);
            if let Some(streams) = parse_dash_playlist(client, &dash_url).await {
                return streams;
            }
        }

        // Fall back to direct quality URL probing (like Python)
        let qualities = ["DASH_1080.mp4", "DASH_720.mp4", "DASH_480.mp4"];
        for quality in qualities {
            let test_url = format!("{}/{}", base_url, quality);
            if url_exists(client, &test_url).await {
                let audio_url = find_audio_stream(client, &test_url).await;
                return DashStreams {
                    video_url: Some(test_url),
                    audio_url,
                };
            }
        }

        return DashStreams {
            video_url: None,
            audio_url: None,
        };
    }

    // If URL ends with .mpd or contains DASHPlaylist, parse it directly
    if video_url.ends_with(".mpd") || video_url.contains("DASHPlaylist") {
        if let Some(streams) = parse_dash_playlist(client, video_url).await {
            return streams;
        }
    }

    // Direct video URL, no audio
    DashStreams {
        video_url: Some(video_url.to_string()),
        audio_url: None,
    }
}

/// Parse a DASH manifest and extract best video and audio stream URLs.
/// Mirrors Python VideoHandler._parse_dash_playlist.
async fn parse_dash_playlist(
    client: &reqwest::Client,
    dash_url: &str,
) -> Option<DashStreams> {
    let response = client
        .get(dash_url)
        .timeout(std::time::Duration::from_secs(DASH_TIMEOUT_SECS))
        .send()
        .await
        .ok()?;

    if !response.status().is_success() {
        return None;
    }

    let content = response.text().await.ok()?;
    let doc = roxmltree::Document::parse(&content).ok()?;

    let base_url = get_base_url(dash_url);

    let mut video_streams: Vec<(u32, String)> = Vec::new();
    let mut audio_streams: Vec<String> = Vec::new();

    // Find all AdaptationSet elements (with namespace)
    for node in doc.descendants() {
        if node.tag_name().name() == "AdaptationSet"
            && node.tag_name().namespace() == Some(DASH_NAMESPACE)
        {
            let content_type = node
                .attribute("contentType")
                .unwrap_or("")
                .to_lowercase();

            // Find Representation elements within this AdaptationSet
            for child in node.descendants() {
                if child.tag_name().name() == "Representation"
                    && child.tag_name().namespace() == Some(DASH_NAMESPACE)
                {
                    if let Some(media_url) = extract_media_url(&child, &base_url) {
                        if content_type.contains("video") {
                            let height = child
                                .attribute("height")
                                .and_then(|h| h.parse::<u32>().ok())
                                .unwrap_or(480);
                            video_streams.push((height, media_url));
                        } else if content_type.contains("audio") {
                            audio_streams.push(media_url);
                        }
                    }
                }
            }
        }
    }

    // Pick best video (highest resolution) and first audio
    let best_video = video_streams
        .iter()
        .max_by_key(|(height, _)| *height)
        .map(|(_, url)| url.clone());

    let best_audio = audio_streams.into_iter().next();

    log::debug!(
        "DASH parsed - video: {:?}, audio: {:?}",
        best_video,
        best_audio
    );

    Some(DashStreams {
        video_url: best_video,
        audio_url: best_audio,
    })
}

/// Extract media URL from a DASH Representation element.
/// Mirrors Python VideoHandler._extract_media_url.
fn extract_media_url(representation: &roxmltree::Node, base_url: &str) -> Option<String> {
    // First try BaseURL child element
    for child in representation.children() {
        if child.tag_name().name() == "BaseURL" {
            if let Some(text) = child.text() {
                let trimmed = text.trim();
                if !trimmed.is_empty() {
                    return join_url(base_url, trimmed);
                }
            }
        }
    }

    // Fall back to constructing from representation attributes
    let rep_id = representation.attribute("id").unwrap_or("");
    let height = representation.attribute("height");

    if rep_id.to_lowercase().contains("audio") {
        return join_url(base_url, "DASH_audio.mp4");
    } else if let Some(h) = height {
        return join_url(base_url, &format!("DASH_{}.mp4", h));
    }

    None
}

/// Get base URL from a DASH manifest URL (everything up to the last path segment).
/// Mirrors Python VideoHandler._get_base_url.
fn get_base_url(dash_url: &str) -> String {
    if let Ok(parsed) = Url::parse(dash_url) {
        let mut path_segments: Vec<&str> = parsed.path().split('/').collect();
        // Remove the last segment (the filename)
        if path_segments.len() > 1 {
            path_segments.pop();
        }
        let base_path = path_segments.join("/");
        format!("{}://{}{}/", parsed.scheme(), parsed.host_str().unwrap_or(""), base_path)
    } else {
        // Fallback: strip everything after the last /
        match dash_url.rfind('/') {
            Some(pos) => format!("{}/", &dash_url[..pos]),
            None => dash_url.to_string(),
        }
    }
}

/// Join a base URL with a relative path.
fn join_url(base: &str, relative: &str) -> Option<String> {
    if let Ok(base_parsed) = Url::parse(base) {
        base_parsed.join(relative).ok().map(|u| u.to_string())
    } else {
        // Simple fallback
        Some(format!("{}{}", base.trim_end_matches('/'), if relative.starts_with('/') { "" } else { "/" }).to_string()
            + relative)
    }
}

/// Find audio stream URL by probing known audio filenames.
/// Mirrors Python VideoHandler._find_audio_stream.
async fn find_audio_stream(client: &reqwest::Client, video_url: &str) -> Option<String> {
    if let Ok(parsed) = Url::parse(video_url) {
        let path = parsed.path();
        if path.contains("DASH_") {
            let base_path = path.split("DASH_").next()?;
            let base_url = format!(
                "{}://{}{}",
                parsed.scheme(),
                parsed.host_str().unwrap_or(""),
                base_path
            );

            let audio_formats = [
                "DASH_audio.mp4",
                "DASH_AUDIO_128.mp4",
                "DASH_128.mp4",
                "audio",
            ];

            for audio_format in audio_formats {
                let audio_url = format!("{}{}", base_url, audio_format);
                if url_exists(client, &audio_url).await {
                    log::debug!("Found audio stream: {}", audio_url);
                    return Some(audio_url);
                }
            }
        }
    }
    None
}

/// Check if a URL exists (HEAD request returns 200).
async fn url_exists(client: &reqwest::Client, url: &str) -> bool {
    match client
        .head(url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
    {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

/// Process video+audio streams with FFmpeg.
/// FFmpeg command matches Python VideoHandler._merge_sync / _convert_sync exactly.
pub async fn process_video_streams(
    video_url: String,
    audio_url: Option<String>,
    output_path: String,
) -> Result<ConversionResult, Box<dyn std::error::Error + Send + Sync>> {
    // Ensure output directory exists
    let path = Path::new(&output_path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).await?;
    }

    let mut cmd = tokio::process::Command::new("ffmpeg");

    if let Some(audio) = &audio_url {
        // Exact same command as Python _merge_sync
        cmd.args([
            "-i",
            &video_url,
            "-i",
            audio,
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "23",
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "2",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-shortest",
            "-threads",
            "0",
            "-y",
            &output_path,
        ]);
    } else {
        // Exact same command as Python _convert_sync
        cmd.args([
            "-i",
            &video_url,
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "23",
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "2",
            "-an",
            "-threads",
            "0",
            "-y",
            &output_path,
        ]);
    }

    let output = cmd.output().await?;

    if output.status.success() {
        let converted_size = fs::metadata(&output_path).await?.len();

        Ok(ConversionResult {
            success: true,
            output_path: Some(output_path),
            original_size: 0,
            converted_size,
            error: None,
        })
    } else {
        let error = String::from_utf8_lossy(&output.stderr);
        Ok(ConversionResult {
            success: false,
            output_path: None,
            original_size: 0,
            converted_size: 0,
            error: Some(format!("Video processing failed: {}", error)),
        })
    }
}
