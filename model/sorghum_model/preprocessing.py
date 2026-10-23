"""Turns a photo file into the model's input pixels. Training, export and fixtures all use this.

This is the training side of the preprocessing contract in `metadata.RESIZE_METHOD`;
`shared/` implements the device side. A golden test in `shared/` compares the two on the
exported fixtures.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def load_model_input(path: Path, size_px: int) -> np.ndarray:
    """Returns an upright `size_px` x `size_px` x 3 uint8 RGB array.

    Steps: apply the EXIF orientation (phone photos are often stored sideways), crop the
    largest centred square, then resize with bilinear filtering. Pillow widens the bilinear
    kernel when shrinking, which antialiases the downscale.
    """
    with Image.open(path) as image:
        upright = ImageOps.exif_transpose(image).convert("RGB")
    return square_and_resize(upright, size_px)


def square_and_resize(image: Image.Image, size_px: int) -> np.ndarray:
    """Centre-crops an RGB image to a square and resizes it to `size_px`."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    square = image.crop((left, top, left + side, top + side))
    resized = square.resize((size_px, size_px), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.uint8)
