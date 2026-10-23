"""The `traits-vN.json` file that ships next to `traits-vN.tflite`.

`shared/` reads it at load time to preprocess input, find each head's output, map the species
head to a `SpeciesEstimate` and apply temperatures. Keys are camelCase because Kotlin parses
them. Anything `shared/` needs to decide must be in here, never hard-coded on a platform.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from sorghum_model.species_classes import SPECIES_CLASSES

METADATA_SCHEMA_VERSION = 1
SPECIES_HEAD_ID = "species"

# Preprocessing contract with `shared/`: crop the largest centred square, then resize with
# bilinear filtering (antialiased when shrinking) to the input size. Fixtures are stored
# already at input size so parity tests check the tensor, not the resize.
RESIZE_METHOD = "centerSquareCropThenBilinear"


@dataclass(frozen=True)
class InputQuantization:
    """How `shared/` turns a 0-255 pixel value into the model's uint8 input: q = v / scale + zeroPoint."""

    scale: float
    zero_point: int


def model_file_names(version: int) -> tuple[str, str]:
    """Returns the model and metadata file names; both carry the same N."""
    if version < 1:
        raise ValueError("model version must be at least 1")
    return f"traits-v{version}.tflite", f"traits-v{version}.json"


def build_metadata(
    *,
    version: int,
    created_on: str,
    input_size_px: int,
    input_quantization: InputQuantization,
    species_output_index: int,
    temperature: float,
    sorghum_threshold: float,
    evaluation: dict,
    quantization_parity: dict,
    training_data: dict,
    ship_bar: dict,
    below_bar: bool,
    backbone: str,
) -> dict:
    """Assembles the metadata document and validates it before returning.

    `below_bar` is true only for a diagnostic export made with `--allow-below-bar`; such a
    model must not ship. `ship_bar` holds the bar's values and any missed checks.
    """
    model_file, _ = model_file_names(version)
    metadata = {
        "schemaVersion": METADATA_SCHEMA_VERSION,
        "modelVersion": version,
        "modelFile": model_file,
        "createdOn": created_on,
        "backbone": f"{backbone} (ImageNet weights)",
        "input": {
            "widthPx": input_size_px,
            "heightPx": input_size_px,
            "channelOrder": "RGB",
            "colorSpace": "sRGB",
            "dtype": "uint8",
            "pixelValueRange": [0, 255],
            "quantization": {
                "scale": input_quantization.scale,
                "zeroPoint": input_quantization.zero_point,
            },
            "resize": RESIZE_METHOD,
        },
        "heads": {
            SPECIES_HEAD_ID: {
                "outputIndex": species_output_index,
                "output": "logits",
                "classes": [{"id": c.name, "group": c.group.value} for c in SPECIES_CLASSES],
                "temperature": temperature,
                "sorghumThreshold": sorghum_threshold,
                "evaluation": evaluation,
                "quantizationParity": quantization_parity,
            }
        },
        # Learned trait heads are added here in later versions (ADR-0004); none exist yet.
        "traits": [],
        "trainingData": training_data,
        "belowBar": below_bar,
        "shipBar": ship_bar,
    }
    validate_metadata(metadata)
    return metadata


def validate_metadata(metadata: dict) -> None:
    """Raises ValueError if the document would be refused by `shared/` or is inconsistent."""
    if metadata.get("schemaVersion") != METADATA_SCHEMA_VERSION:
        raise ValueError(f"schemaVersion must be {METADATA_SCHEMA_VERSION}")
    version = metadata.get("modelVersion")
    if not isinstance(version, int) or metadata.get("modelFile") != model_file_names(version)[0]:
        raise ValueError("modelFile must be traits-v{modelVersion}.tflite")

    species = metadata["heads"][SPECIES_HEAD_ID]
    class_ids = [c["id"] for c in species["classes"]]
    if len(class_ids) != len(set(class_ids)):
        raise ValueError("species class ids must be unique")
    if not any(c["group"] == "sorghum" for c in species["classes"]):
        raise ValueError("species head needs a sorghum class")
    if not species["temperature"] > 0:
        raise ValueError("temperature must be positive")
    if not 0 < species["sorghumThreshold"] < 1:
        raise ValueError("sorghumThreshold must be in (0, 1)")
    if metadata["input"]["quantization"]["scale"] <= 0:
        raise ValueError("input quantization scale must be positive")


def write_metadata(metadata: dict, path: Path) -> None:
    """Writes validated metadata with sorted keys, so diffs between versions are readable."""
    validate_metadata(metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
