"""Runs BioCLIP 2 zero-shot over REVIEW_PROMPTS. Needs the `review` extra (PyTorch, open_clip).

The weights (imageomics/bioclip-2, a CLIP ViT-L/14, about 1.7 GB) are fetched from Hugging
Face on first use into HF_HOME; point HF_HOME at the data drive, not the system disk.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image

from sorghum_model.label_review import REVIEW_PROMPTS

BIOCLIP_2_MODEL = "hf-hub:imageomics/bioclip-2"

# The prompt wording of the BioCLIP papers' zero-shot evaluation.
PROMPT_TEMPLATE = "a photo of {}."


class BioclipClassifier:
    """Scores images against REVIEW_PROMPTS. Not thread-safe; one instance per process."""

    def __init__(self) -> None:
        self._device = "mps" if torch.backends.mps.is_available() else "cpu"
        model, _, preprocess = open_clip.create_model_and_transforms(BIOCLIP_2_MODEL)
        self._model = model.to(self._device).eval()
        self._preprocess = preprocess
        tokenizer = open_clip.get_tokenizer(BIOCLIP_2_MODEL)
        with torch.no_grad():
            tokens = tokenizer([PROMPT_TEMPLATE.format(p.text) for p in REVIEW_PROMPTS])
            text = self._model.encode_text(tokens.to(self._device))
        # Prompts are fixed, so their embeddings are computed once.
        self._text_features = text / text.norm(dim=-1, keepdim=True)

    def __call__(self, image_paths: Sequence[Path]) -> np.ndarray:
        """Probabilities over REVIEW_PROMPTS, one row per image."""
        images = []
        for path in image_paths:
            with Image.open(path) as image:
                images.append(self._preprocess(image.convert("RGB")))
        with torch.no_grad():
            features = self._model.encode_image(torch.stack(images).to(self._device))
            features = features / features.norm(dim=-1, keepdim=True)
            logits = self._model.logit_scale.exp() * features @ self._text_features.T
            return logits.softmax(dim=-1).float().cpu().numpy()
