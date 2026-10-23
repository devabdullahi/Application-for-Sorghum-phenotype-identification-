"""Shared builders for tests."""

from sorghum_model.manifest import ImageRecord


def make_record(**overrides) -> ImageRecord:
    """A valid record; tests override only the fields they care about."""
    fields = {
        "image_path": "inaturalist/1.jpg",
        "class_name": "sorghum_bicolor",
        "source": "inaturalist",
        "source_id": "1",
        "group_id": "inaturalist-user-7",
        "license": "cc-by",
        "attribution": "(c) Someone, some rights reserved (CC BY)",
        "label_source": "inaturalist research-grade observation 10",
        "label_status": "verified",
        "labelled_on": "2025-08-01",
        "sha256": "a" * 64,
    }
    fields.update(overrides)
    return ImageRecord(**fields)
