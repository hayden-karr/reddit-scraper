use crate::media::{ConversionResult, gifs, images};

pub async fn process_gallery_items(
    gallery_items: Vec<(Vec<u8>, String, String)>, // (bytes, media_type, output_path)
) -> Result<Vec<ConversionResult>, Box<dyn std::error::Error + Send + Sync>> {
    let mut results = Vec::new();

    // Process items in order to maintain gallery sequence
    for (bytes, media_type, output_path) in gallery_items {
        let original_size = bytes.len() as u64;

        let result = match media_type.as_str() {
            "image" => {
                let avif_path = format!("{}.avif", output_path);
                images::convert_bytes_to_avif(bytes, avif_path, 80).await
            }
            "gif" => {
                let webm_path = format!("{}.webm", output_path);
                gifs::convert_bytes_to_webm(bytes, webm_path).await
            }
            _ => Ok(ConversionResult {
                success: false,
                output_path: None,
                original_size,
                converted_size: 0,
                error: Some(format!("Unsupported media type: {}", media_type)),
            }),
        };

        match result {
            Ok(r) => results.push(r),
            Err(e) => results.push(ConversionResult {
                success: false,
                output_path: None,
                original_size,
                converted_size: 0,
                error: Some(format!("Processing error: {}", e)),
            }),
        }
    }

    Ok(results)
}
