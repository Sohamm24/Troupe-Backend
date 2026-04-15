import cv2
import numpy as np
from typing import Dict, List, Optional

def extract_hsv_histogram(image_bytes: bytes) -> Dict[str, List[float]]:
    """
    Extracts a normalized HSV histogram from image bytes using OpenCV.
    
    Step-by-step:
    1. Decode bytes to a BGR image.
    2. Convert the image from BGR to HSV color space.
    3. Calculate the 3D histogram for H, S, and V channels.
       - Recommended bin sizes: Hue=16, Saturation=8, Value=8.
       - HSV ranges: H: [0, 180], S: [0, 256], V: [0, 256].
    4. Flatten the 3D histogram into a 1D array.
    5. Normalize the histogram so that the sum of all bins is 1.0 (L1 normalization).
    6. Return as a dictionary under the 'hsv_histogram' key.
    """
    # 1. Decode bytes to OpenCV image (BGR format)
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise ValueError("Failed to decode image bytes. Image might be corrupt.")

    # 2. Convert to HSV
    hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 3. Calculate Histogram
    # Bins: 16 for Hue, 8 for Saturation, 8 for Value
    # This results in a 16 * 8 * 8 = 1024 element vector
    h_bins = 16
    s_bins = 8
    v_bins = 8
    hist_size = [h_bins, s_bins, v_bins]
    
    # Ranges: H is 0-180 in OpenCV, S and V are 0-255
    ranges = [0, 180, 0, 256, 0, 256]
    
    hist = cv2.calcHist([hsv_img], [0, 1, 2], None, hist_size, ranges)

    # 4 & 5. Flatten and Normalize
    # cv2.normalize with NORM_L1 ensures the sum of histogram bins is 1.0
    cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
    
    # Convert to a flat list for JSON storage
    hist_flat = hist.flatten().tolist()

    return {"hsv_histogram": hist_flat}

def compute_similarity(hist_a: List[float], hist_b: List[float]) -> float:
    """
    Computes the similarity score between two HSV histograms using Correlation.
    
    Returns a score between -1.0 and 1.0 (where 1.0 is a perfect match).
    Using cv2.compareHist with HISTCMP_CORREL.
    """
    # Convert lists back to numpy arrays for OpenCV
    arr_a = np.array(hist_a, dtype=np.float32)
    arr_b = np.array(hist_b, dtype=np.float32)
    
    # Correlation distance: 1.0 is perfect match, -1.0 is complete opposite
    score = cv2.compareHist(arr_a, arr_b, cv2.HISTCMP_CORREL)
    
    return float(score)
