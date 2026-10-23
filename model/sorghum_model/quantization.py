"""INT8 details the phones must reproduce: input rounding and the logit quantization step.

Kept free of TensorFlow so the rules are unit-tested in the light environment; `export.py`
passes in what the TFLite interpreter reports.
"""

from dataclasses import dataclass

import numpy as np


def quantize_input(image: np.ndarray, scale: float, zero_point: int) -> np.ndarray:
    """Turns 0-255 pixels into the model's uint8 input: q = v / scale + zeroPoint.

    Rounds half up, floor(x + 0.5), not numpy's half-to-even `np.round`: `shared/`
    (SpeciesGate.kt) uses Kotlin's `roundToInt`, which rounds ties towards positive infinity.
    With the usual scale of 1 every pixel is an exact tie candidate, so half-to-even would
    give a different tensor on some pixels and break the parity fixtures. The arithmetic stays
    in float32, like Kotlin's Float.
    """
    scaled = image.astype(np.float32) / np.float32(scale) + np.float32(zero_point)
    return np.clip(np.floor(scaled + np.float32(0.5)), 0, 255).astype(np.uint8)


@dataclass(frozen=True)
class LogitTolerance:
    """How finely the INT8 model can resolve a logit, for the parity tests' tolerance.

    Attributes:
        key: the expected.json key it is written under. "logitStep" is a quantization step
            read from the model; "logitParityMaxDelta" is the largest |float - INT8| logit
            difference measured on the test split, used when the model has no int8 logit
            tensor.
        value: the step or the delta, in logit units.
        source: which tensor or measurement the value came from, for the reader.
    """

    key: str
    value: float
    source: str


LOGIT_STEP_KEY = "logitStep"
LOGIT_PARITY_MAX_DELTA_KEY = "logitParityMaxDelta"

_INTEGER_TYPES = ("int8", "uint8")


def logit_quantization_step(
    output_detail: dict, tensor_details: list[dict], operations: list[dict]
) -> LogitTolerance | None:
    """The species output's quantization step, or None when no int8 tensor carries the logits.

    An int8 output has its own scale. A float output exported from an INT8 model is produced
    by a DEQUANTIZE op whose int8 input holds the logits; that input's scale is the step.
    Arguments use the dict shapes of tf.lite.Interpreter's get_output_details(),
    get_tensor_details() and _get_ops_details().
    """
    if _is_integer(output_detail) and _scale(output_detail) > 0:
        return LogitTolerance(LOGIT_STEP_KEY, _scale(output_detail), "int8 output tensor scale")

    tensors = {detail["index"]: detail for detail in tensor_details}
    for operation in operations:
        if operation.get("op_name") != "DEQUANTIZE":
            continue
        if output_detail["index"] not in list(operation.get("outputs", [])):
            continue
        for input_index in operation.get("inputs", []):
            producer = tensors.get(int(input_index))
            if producer is not None and _is_integer(producer) and _scale(producer) > 0:
                return LogitTolerance(
                    LOGIT_STEP_KEY, _scale(producer), "scale of the int8 input to DEQUANTIZE"
                )
    return None


def measured_logit_tolerance(float_logits: np.ndarray, int8_logits: np.ndarray) -> LogitTolerance:
    """The fallback when the model has no int8 logit tensor: the largest test-split delta."""
    return LogitTolerance(
        LOGIT_PARITY_MAX_DELTA_KEY,
        float(np.abs(float_logits - int8_logits).max()),
        "largest |float - INT8| logit difference on the test split",
    )


def _is_integer(detail: dict) -> bool:
    dtype = detail.get("dtype")
    return getattr(dtype, "__name__", str(dtype)) in _INTEGER_TYPES


def _scale(detail: dict) -> float:
    parameters = detail.get("quantization_parameters") or {}
    scales = parameters.get("scales")
    if scales is not None and len(scales) == 1:
        return float(scales[0])
    quantization = detail.get("quantization") or (0.0, 0)
    return float(quantization[0])
