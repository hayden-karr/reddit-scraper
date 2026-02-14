use crate::media::ConversionResult;
use std::path::Path;
use tokio::fs;

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

    // Add video input (pass URL directly like Python version)
    cmd.args(["-i", &video_url]);

    // Add audio input if available
    if let Some(audio) = &audio_url {
        cmd.args(["-i", audio]);

        // Video + Audio encoding
        cmd.args([
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
            "-shortest", // Match shortest stream
        ]);
    } else {
        // Video-only encoding
        cmd.args([
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
            "-an", // No audio
        ]);
    }

    // Common settings
    cmd.args([
        "-avoid_negative_ts",
        "make_zero",
        "-fflags",
        "+genpts",
        "-threads",
        "0",
        "-y", // Overwrite
        &output_path,
    ]);

    let output = cmd.output().await?;

    if output.status.success() {
        let converted_size = fs::metadata(&output_path).await?.len();

        Ok(ConversionResult {
            success: true,
            output_path: Some(output_path),
            original_size: 0, // We don't know original size for URLs
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
