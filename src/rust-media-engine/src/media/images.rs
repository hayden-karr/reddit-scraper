use crate::media::ConversionResult;
use rgb::FromSlice;
use std::path::Path;
use tokio::fs;

pub async fn convert_bytes_to_avif(
    image_bytes: Vec<u8>,
    output_path: String,
    quality: u8,
) -> Result<ConversionResult, Box<dyn std::error::Error + Send + Sync>> {
    let original_size = image_bytes.len() as u64;

    // Ensure output directory exists
    let path = Path::new(&output_path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).await?;
    }

    // Convert to AVIF in memory using ravif
    let converted_bytes = tokio::task::spawn_blocking(move || {
        // Load image from bytes
        let img = image::load_from_memory(&image_bytes)?;

        // Convert to RGB8 (AVIF requirement)
        let rgb_image = img.to_rgb8();
        let (width, height) = rgb_image.dimensions();

        // Convert flat byte array to RGB pixel array
        let rgb_pixels: &[rgb::RGB8] = rgb_image.as_raw().as_slice().as_rgb();

        // Create encoder with quality
        let encoder = ravif::Encoder::new()
            .with_quality(quality as f32)
            .with_speed(6); // Good balance of speed vs compression

        // Encode to AVIF
        let avif_data =
            encoder.encode_rgb(ravif::Img::new(rgb_pixels, width as usize, height as usize))?;

        Ok::<Vec<u8>, Box<dyn std::error::Error + Send + Sync>>(avif_data.avif_file)
    })
    .await??;

    // Write to disk
    fs::write(&output_path, &converted_bytes).await?;
    let converted_size = converted_bytes.len() as u64;

    Ok(ConversionResult {
        success: true,
        output_path: Some(output_path),
        original_size,
        converted_size,
        error: None,
    })
}
