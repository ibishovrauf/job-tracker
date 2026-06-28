"""Lazy-loaded sentence-transformer encoder with MPS/CUDA/CPU auto-detection.

All heavy imports happen inside ``_get_model()`` so the rest of the app never
pays the torch startup cost unless ``embed-refresh`` or ``/matches`` is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

_model: SentenceTransformer | None = None
_device: str | None = None


def _pick_device() -> str:
    """Choose the best available compute device."""
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_device() -> str:
    """Return the device string that will be / was used."""
    global _device
    if _device is None:
        _device = _pick_device()
    return _device


def _get_model() -> SentenceTransformer:
    """Lazily load the model on first call."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        device = get_device()
        _model = SentenceTransformer(MODEL_NAME, device=device)
    return _model


def encode(texts: list[str], batch_size: int = 256, show_progress: bool = True) -> np.ndarray:
    """Encode a list of strings into L2-normalized float32 vectors.

    Args:
        texts: Cleaned title strings.
        batch_size: Encoding batch size.
        show_progress: Show tqdm progress bar.

    Returns:
        ndarray of shape ``(len(texts), EMBED_DIM)`` with dtype float32,
        each row L2-normalized.
    """
    model = _get_model()
    embeddings: np.ndarray = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
    )
    return embeddings.astype(np.float32)
