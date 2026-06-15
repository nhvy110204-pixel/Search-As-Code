import gzip
import logging

logger = logging.getLogger(__name__)


def compress_data(data: bytes, compression_level: int = 6) -> bytes:
    if not data:
        return data
    
    try:
        compressed = gzip.compress(data, compresslevel=compression_level)
        logger.debug(f"Compressed {len(data)} bytes to {len(compressed)} bytes (ratio: {len(compressed)/len(data):.2%})")
        return compressed
    except Exception as e:
        logger.error(f"Compression failed: {str(e)}")
        raise


def decompress_data(data: bytes) -> bytes:
    if not data:
        return data
    
    try:
        decompressed = gzip.decompress(data)
        logger.debug(f"Decompressed {len(data)} bytes to {len(decompressed)} bytes")
        return decompressed
    except Exception as e:
        logger.error(f"Decompression failed: {str(e)}")
        raise


def get_compression_ratio(original_size: int, compressed_size: int) -> float:
    if original_size == 0:
        return 0.0
    return compressed_size / original_size
