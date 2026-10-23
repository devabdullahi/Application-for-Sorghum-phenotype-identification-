import numpy as np

from sorghum_model.quantization import (
    LOGIT_PARITY_MAX_DELTA_KEY,
    LOGIT_STEP_KEY,
    LogitTolerance,
    logit_quantization_step,
    logit_tolerance_fields,
    measured_logit_tolerance,
    quantize_input,
)


def test_ties_round_half_up_like_kotlin_round_to_int():
    # With scale 2, pixel 1 is 0.5, 3 is 1.5 and 5 is 2.5. np.round gives 0, 2, 2; Kotlin's
    # roundToInt (and shared/) gives 1, 2, 3.
    image = np.array([1, 3, 5, 255], dtype=np.uint8)
    assert quantize_input(image, scale=2.0, zero_point=0).tolist() == [1, 2, 3, 128]


def test_quantized_input_is_clipped_to_uint8():
    image = np.array([0, 255], dtype=np.uint8)
    assert quantize_input(image, scale=0.5, zero_point=-10).tolist() == [0, 255]


def _tensor(index, dtype, scale):
    return {"index": index, "dtype": dtype, "quantization": (scale, 0),
            "quantization_parameters": {"scales": np.array([scale]), "zero_points": np.array([0])}}


def test_int8_output_uses_its_own_scale():
    output = _tensor(5, np.int8, 0.125)
    tolerance = logit_quantization_step(output, [output], [])
    assert (tolerance.key, tolerance.value) == (LOGIT_STEP_KEY, 0.125)


def test_float_output_uses_the_scale_of_the_int8_tensor_feeding_dequantize():
    output = _tensor(9, np.float32, 0.0)
    producer = _tensor(8, np.int8, 0.0625)
    operations = [
        {"op_name": "FULLY_CONNECTED", "inputs": [3, 4], "outputs": [8]},
        {"op_name": "DEQUANTIZE", "inputs": [8], "outputs": [9]},
    ]
    tolerance = logit_quantization_step(output, [producer, output], operations)
    assert (tolerance.key, tolerance.value) == (LOGIT_STEP_KEY, 0.0625)
    assert "DEQUANTIZE" in tolerance.source


def test_float_output_without_int8_producer_falls_back_to_the_measured_delta():
    output = _tensor(9, np.float32, 0.0)
    assert logit_quantization_step(output, [output], [{"op_name": "SOFTMAX", "inputs": [1], "outputs": [9]}]) is None
    tolerance = measured_logit_tolerance(np.array([[1.0, 2.0]]), np.array([[1.25, 1.5]]))
    assert (tolerance.key, tolerance.value) == (LOGIT_PARITY_MAX_DELTA_KEY, 0.5)


def test_expected_json_always_has_a_top_level_logit_step():
    step = logit_tolerance_fields(LogitTolerance(LOGIT_STEP_KEY, 0.0625, "scale"))
    assert step == {"logitStep": 0.0625, "logitToleranceSource": "scale"}
    measured = logit_tolerance_fields(LogitTolerance(LOGIT_PARITY_MAX_DELTA_KEY, 0.4, "measured"))
    assert measured == {"logitStep": 0.4, "logitParityMaxDelta": 0.4, "logitToleranceSource": "measured"}
