use pyo3::prelude::*;
use pyo3_async_runtimes::tokio::future_into_py;
use std::sync::Arc;
use tokio::fs;
use tokio_retry::Retry;
use tokio_retry::strategy::{ExponentialBackoff, jitter};

mod media;
use media::{gifs, images, video};

#[derive(Debug, Clone)]
#[pyclass]
pub struct MediaTask {
    #[pyo3(get, set)]
    pub url: String,
    #[pyo3(get, set)]
    pub item_id: String,
    #[pyo3(get, set)]
    pub media_type: String,
    #[pyo3(get, set)]
    pub output_path: String,
}

#[pymethods]
impl MediaTask {
    #[new]
    fn new() -> Self {
        Self {
            url: String::new(),
            item_id: String::new(),
            media_type: String::new(),
            output_path: String::new(),
        }
    }
}

#[derive(Debug)]
#[pyclass]
pub struct MediaResult {
    #[pyo3(get)]
    pub success: bool,
    #[pyo3(get)]
    pub item_id: String,
    #[pyo3(get)]
    pub output_path: Option<String>,
    #[pyo3(get)]
    pub original_size: u64,
    #[pyo3(get)]
    pub converted_size: u64,
    #[pyo3(get)]
    pub error: Option<String>,
}

#[pyclass]
pub struct RustMediaEngine {
    client: reqwest::Client,
}

#[pymethods]
impl RustMediaEngine {
    #[new]
    fn new() -> PyResult<Self> {
        // Initialize Rust logging
        let _ = env_logger::Builder::from_env(
            env_logger::Env::default().default_filter_or("rust_media_engine=info"),
        )
        .try_init();

        let client = reqwest::Client::builder()
            .user_agent("RedditScraper-Rust/1.0")
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "Failed to create client: {}",
                    e
                ))
            })?;

        log::info!("Rust media engine initialized");
        Ok(Self { client })
    }

    // Main function: download and convert regular media
    fn process_media_batch<'a>(
        &self,
        py: Python<'a>,
        tasks: Vec<MediaTask>,
        max_concurrent: usize,
    ) -> PyResult<Bound<'a, PyAny>> {
        let client = self.client.clone();

        future_into_py(py, async move {
            log::info!(
                "Starting batch processing of {} media items (max concurrent: {})",
                tasks.len(),
                max_concurrent
            );

            let semaphore = Arc::new(tokio::sync::Semaphore::new(max_concurrent));
            let mut handles = Vec::new();

            for task in tasks {
                let client = client.clone();
                let semaphore = semaphore.clone();

                let handle = tokio::spawn(async move {
                    let _permit = semaphore.acquire().await.unwrap();
                    process_single_media(client, task).await
                });

                handles.push(handle);
            }

            let mut results = Vec::new();
            for handle in handles {
                match handle.await {
                    Ok(result) => results.push(result),
                    Err(e) => {
                        log::error!("Task spawn error: {}", e);
                        results.push(MediaResult {
                            success: false,
                            item_id: "unknown".to_string(),
                            output_path: None,
                            original_size: 0,
                            converted_size: 0,
                            error: Some(format!("Task error: {}", e)),
                        })
                    }
                }
            }

            let successful = results.iter().filter(|r| r.success).count();
            log::info!(
                "Batch processing complete: {}/{} successful",
                successful,
                results.len()
            );

            Ok(results)
        })
    }
}

// Core processing function
async fn process_single_media(client: reqwest::Client, task: MediaTask) -> MediaResult {
    // Check if file already exists (skip if so)
    let output_path = std::path::Path::new(&task.output_path);
    if output_path.exists() {
        let file_size = match fs::metadata(output_path).await {
            Ok(metadata) => metadata.len(),
            Err(_) => 0,
        };
        log::debug!(
            "Skipping existing file: {} ({})",
            task.item_id,
            task.output_path
        );
        return MediaResult {
            success: true,
            item_id: task.item_id,
            output_path: Some(task.output_path.clone()),
            original_size: 0,
            converted_size: file_size,
            error: None,
        };
    }

    // Ensure output directory exists
    if let Some(parent) = output_path.parent() {
        if let Err(e) = fs::create_dir_all(parent).await {
            return MediaResult {
                success: false,
                item_id: task.item_id,
                output_path: None,
                original_size: 0,
                converted_size: 0,
                error: Some(format!("Failed to create directory: {}", e)),
            };
        }
    }

    // For v.redd.it videos, use DASH manifest parsing (same as Python path)
    if task.media_type == "video" && task.url.contains("v.redd.it") {
        log::debug!("Processing v.redd.it video {} via DASH", task.item_id);

        let webm_path = format!(
            "{}.webm",
            task.output_path
                .trim_end_matches(".webm")
                .trim_end_matches(".mp4")
        );

        // Use the same stream discovery as Python: DASH manifest first, then fallback
        let streams = video::get_best_streams(&client, &task.url).await;

        let video_stream = match streams.video_url {
            Some(url) => {
                log::info!("Found video stream for {}: {}", task.item_id, url);
                url
            }
            None => {
                return MediaResult {
                    success: false,
                    item_id: task.item_id,
                    output_path: None,
                    original_size: 0,
                    converted_size: 0,
                    error: Some("No video stream found".to_string()),
                };
            }
        };

        if let Some(ref audio) = streams.audio_url {
            log::info!("Found audio stream for {}: {}", task.item_id, audio);
        } else {
            log::info!("No audio stream for {}", task.item_id);
        }

        match video::process_video_streams(video_stream, streams.audio_url, webm_path).await {
            Ok(conv_result) => {
                if conv_result.success {
                    log::info!(
                        "Successfully processed {}: {} bytes",
                        task.item_id,
                        conv_result.converted_size
                    );
                }
                return MediaResult {
                    success: conv_result.success,
                    item_id: task.item_id,
                    output_path: conv_result.output_path,
                    original_size: 0,
                    converted_size: conv_result.converted_size,
                    error: conv_result.error,
                };
            }
            Err(e) => {
                return MediaResult {
                    success: false,
                    item_id: task.item_id,
                    output_path: None,
                    original_size: 0,
                    converted_size: 0,
                    error: Some(format!("Video processing failed: {}", e)),
                };
            }
        }
    }

    // Download to memory with retry logic (for non-v.redd.it media)
    let retry_strategy = ExponentialBackoff::from_millis(500).map(jitter).take(3); // 3 retries with exponential backoff

    let download_client = client.clone();
    let download_url = task.url.clone();
    let download_item_id = task.item_id.clone();

    let bytes = match Retry::spawn(retry_strategy, move || {
        let client = download_client.clone();
        let url = download_url.clone();
        let item_id = download_item_id.clone();

        async move {
            log::debug!("Download attempt: {} for item {}", url, item_id);

            let response = client.get(&url).send().await.map_err(|e| {
                log::warn!("Download request failed for {}: {}", item_id, e);
                e
            })?;

            let status = response.status();
            if !status.is_success() {
                log::warn!("HTTP error {} for {}", status, item_id);

                // Only retry on server errors and rate limits
                if status.is_server_error() || status.as_u16() == 429 {
                    return Err(response.error_for_status().unwrap_err());
                }

                // Don't retry on client errors (403, 404, etc) - fail immediately
                return Err(response.error_for_status().unwrap_err());
            }

            response.bytes().await.map_err(|e| {
                log::warn!("Failed to read bytes for {}: {}", item_id, e);
                e
            })
        }
    })
    .await
    {
        Ok(bytes) => {
            log::debug!("Downloaded {} bytes for {}", bytes.len(), task.item_id);
            bytes
        }
        Err(e) => {
            log::error!("Download failed after retries for {}: {}", task.item_id, e);
            return MediaResult {
                success: false,
                item_id: task.item_id,
                output_path: None,
                original_size: 0,
                converted_size: 0,
                error: Some(format!("Download failed: {}", e)),
            };
        }
    };

    let original_size = bytes.len() as u64;

    // Process based on media type
    log::debug!("Processing {} as {}", task.item_id, task.media_type);
    let result = match task.media_type.as_str() {
        "image" => {
            let avif_path = format!("{}.avif", task.output_path.trim_end_matches(".avif"));
            log::debug!("Converting image {} to AVIF (lossless)", task.item_id);
            images::convert_bytes_to_avif(bytes.to_vec(), avif_path, 100).await
        }
        "gif" => {
            let webm_path = format!("{}.webm", task.output_path.trim_end_matches(".webm"));
            log::debug!("Converting GIF {} to WebM", task.item_id);
            gifs::convert_bytes_to_webm(bytes.to_vec(), webm_path).await
        }
        "video" => {
            // v.redd.it videos are handled above before the download step.
            // This branch handles direct video downloads (non-Reddit streams).
            let mp4_path = format!("{}.mp4", task.output_path.trim_end_matches(".mp4"));
            match fs::write(&mp4_path, &bytes).await {
                Ok(_) => Ok(media::ConversionResult {
                    success: true,
                    output_path: Some(mp4_path),
                    original_size,
                    converted_size: bytes.len() as u64,
                    error: None,
                }),
                Err(e) => Ok(media::ConversionResult {
                    success: false,
                    output_path: None,
                    original_size,
                    converted_size: 0,
                    error: Some(format!("Failed to write video: {}", e)),
                }),
            }
        }
        _ => Ok(media::ConversionResult {
            success: false,
            output_path: None,
            original_size,
            converted_size: 0,
            error: Some(format!("Unsupported media type: {}", task.media_type)),
        }),
    };

    match result {
        Ok(conv_result) => {
            if conv_result.success {
                log::info!(
                    "Successfully processed {}: {} bytes -> {} bytes",
                    task.item_id,
                    original_size,
                    conv_result.converted_size
                );
            } else {
                log::error!(
                    "Processing failed for {}: {:?}",
                    task.item_id,
                    conv_result.error
                );
            }
            MediaResult {
                success: conv_result.success,
                item_id: task.item_id,
                output_path: conv_result.output_path,
                original_size,
                converted_size: conv_result.converted_size,
                error: conv_result.error,
            }
        }
        Err(e) => {
            log::error!("Processing error for {}: {}", task.item_id, e);
            MediaResult {
                success: false,
                item_id: task.item_id,
                output_path: None,
                original_size,
                converted_size: 0,
                error: Some(format!("Processing error: {}", e)),
            }
        }
    }
}

#[pymodule]
fn rust_media_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MediaTask>()?;
    m.add_class::<MediaResult>()?;
    m.add_class::<RustMediaEngine>()?;
    Ok(())
}
