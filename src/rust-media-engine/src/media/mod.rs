pub mod galleries;
pub mod gifs;
pub mod images;
pub mod video;

#[derive(Debug)]
pub struct ConversionResult {
    pub success: bool,
    pub output_path: Option<String>,
    pub original_size: u64,
    pub converted_size: u64,
    pub error: Option<String>,
}
