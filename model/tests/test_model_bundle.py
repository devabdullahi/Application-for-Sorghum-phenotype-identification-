"""The structural merge keeps each network's INT8 outputs bit-identical (ADR-0012).

Needs TensorFlow (the `export` extra); skipped in the light environment.
"""

import numpy as np
import pytest

tf = pytest.importorskip("tensorflow")
keras = pytest.importorskip("keras")

from sorghum_model.export import convert_to_int8  # noqa: E402
from sorghum_model.model_bundle import merge_models, verify_merged_outputs  # noqa: E402

SIZE_PX = 8


def _tiny_model(classes: int, seed: int) -> bytes:
    """A small conv net with the phone model's interface: uint8 image in, float logits out."""
    keras.utils.set_random_seed(seed)
    inputs = keras.Input((SIZE_PX, SIZE_PX, 3), name="image")
    x = keras.layers.Rescaling(1 / 127.5, offset=-1)(inputs)
    # Non-zero biases: the converter drops an all-zero Dense bias, and the TF 2.17 reference
    # FULLY_CONNECTED kernel then crashes on the omitted input, with or without a merge.
    bias = keras.initializers.RandomNormal(stddev=0.1, seed=seed)
    x = keras.layers.Conv2D(4, 3, activation="relu", bias_initializer=bias)(x)
    x = keras.layers.GlobalAveragePooling2D()(x)
    outputs = keras.layers.Dense(classes, bias_initializer=bias)(x)
    representative = np.random.default_rng(seed).integers(0, 256, (16, SIZE_PX, SIZE_PX, 3)).astype(np.uint8)
    return convert_to_int8(keras.Model(inputs, outputs), representative)


@pytest.fixture(scope="module")
def sources() -> tuple[bytes, bytes]:
    return _tiny_model(classes=3, seed=1), _tiny_model(classes=2, seed=2)


def _images(count: int) -> np.ndarray:
    return np.random.default_rng(7).integers(0, 256, (count, SIZE_PX, SIZE_PX, 3), dtype=np.uint8)


def test_merged_outputs_are_the_sources_outputs_in_order(sources):
    merged = merge_models(*sources, secondary_name_prefix="second/")

    verify_merged_outputs(merged, list(sources), _images(5))

    interpreter = tf.lite.Interpreter(model_content=merged)
    shapes = [list(output["shape"]) for output in interpreter.get_output_details()]
    assert shapes == [[1, 3], [1, 2]]
    assert len(interpreter.get_input_details()) == 1


def test_secondary_tensor_names_are_prefixed(sources):
    merged = merge_models(*sources, secondary_name_prefix="second/")

    names = [output["name"] for output in tf.lite.Interpreter(model_content=merged).get_output_details()]
    assert names[1].startswith("second/") and not names[0].startswith("second/")


def test_verification_fails_when_an_output_belongs_to_another_model(sources):
    swapped = merge_models(sources[1], sources[0], secondary_name_prefix="second/")

    with pytest.raises(ValueError, match="shape"):
        verify_merged_outputs(swapped, list(sources), _images(2))


def test_refuses_inputs_of_different_shape(sources):
    keras.utils.set_random_seed(3)
    inputs = keras.Input((SIZE_PX * 2, SIZE_PX * 2, 3), name="image")
    pooled = keras.layers.GlobalAveragePooling2D()(keras.layers.Rescaling(1 / 255)(inputs))
    outputs = keras.layers.Dense(2, bias_initializer="ones")(pooled)
    representative = np.zeros((4, SIZE_PX * 2, SIZE_PX * 2, 3), dtype=np.uint8)
    other = convert_to_int8(keras.Model(inputs, outputs), representative)

    with pytest.raises(ValueError, match="inputs differ"):
        merge_models(sources[0], other, secondary_name_prefix="second/")
