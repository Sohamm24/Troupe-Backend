import os
import numpy as np
from io import BytesIO
from PIL import Image as PILImage
from fastapi import HTTPException

_model = None
_processor = None

def _load_model():
    global _model, _processor
    if _model is None:
        import torch
        from transformers import CLIPProcessor, CLIPVisionModelWithProjection

        # Load ONLY the vision encoder — smaller than full CLIPModel
        # (~350MB → ~90MB after INT8 quantization)
        model = CLIPVisionModelWithProjection.from_pretrained(
            "openai/clip-vit-base-patch32"
        )

        # INT8 dynamic quantization — runs on CPU, no extra libraries needed
        # Quantizes linear layers only (safe for ViT, no accuracy loss for inference)
        _model = torch.quantization.quantize_dynamic(
            model,
            {torch.nn.Linear},
            dtype=torch.qint8
        )
        _model.eval()

        _processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    return _model, _processor


def get_image_embedding(image_bytes: bytes) -> list[float]:
    """
    512-dim L2-normalised CLIP image embedding.
    Uses only the vision encoder (not full CLIP) + INT8 quantization.
    RAM: ~120MB loaded. Cold start: ~5s. Per-image: ~300ms on CPU.
    """
    try:
        import torch
        model, processor = _load_model()

        pil_img = PILImage.open(BytesIO(image_bytes)).convert("RGB")
        inputs = processor(images=pil_img, return_tensors="pt")

        with torch.no_grad():
            outputs = model(**inputs)
            # image_embeds is already the projected 512-dim vector
            embedding = outputs.image_embeds.squeeze()

        vec = embedding.numpy().astype(np.float32)
        vec = vec / (np.linalg.norm(vec) + 1e-9)
        return vec.tolist()

    except Exception as e:
        raise HTTPException(502, f"Embedding failed: {e}")