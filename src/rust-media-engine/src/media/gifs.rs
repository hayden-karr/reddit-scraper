use crate::media::ConversionResult;
use std::path::Path;
use tokio::fs;

pub async fn convert_bytes_to_webm(
    gif_bytes: Vec<u8>,
    output_path: String,
) -> Result<ConversionResult, Box<dyn std::error::Error + Send + Sync>> {
    let original_size = gif_bytes.len() as u64;

    // Ensure output directory exists
    let path = Path::new(&output_path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).await?;
    }

    // Create temporary input file for FFmpeg
    let temp_input = format!("{}.tmp.gif", output_path);
    fs::write(&temp_input, &gif_bytes).await?;

    // Convert GIF to WebM using FFmpeg
    let output = tokio::process::Command::new("ffmpeg")
        .args([
            "-i",
            &temp_input,
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "30",
            "-b:v",
            "0",
            "-an", // No audio
            "-loop",
            "0", // Infinite loop
            "-auto-alt-ref",
            "0", // Better looping
            "-lag-in-frames",
            "0", // No lag for better looping
            "-cpu-used",
            "4",
            "-row-mt",
            "1",
            "-threads",
            "4",
            "-y", // Overwrite output
            &output_path,
        ])
        .output()
        .await?;

    // Clean up temp file
    let _ = fs::remove_file(&temp_input).await;

    if output.status.success() {
        let converted_size = fs::metadata(&output_path).await?.len();

        Ok(ConversionResult {
            success: true,
            output_path: Some(output_path),
            original_size,
            converted_size,
            error: None,
        })
    } else {
        let error = String::from_utf8_lossy(&output.stderr);
        Ok(ConversionResult {
            success: false,
            output_path: None,
            original_size,
            converted_size: 0,
            error: Some(format!("FFmpeg error: {}", error)),
        })
    }
}
