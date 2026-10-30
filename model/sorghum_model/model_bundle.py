"""Packs two separately exported INT8 models into one `.tflite` file with one output per model.

`traits-vN.tflite` is one LiteRT model that the phones run once per photo. Each head is
addressed by its `outputIndex` (ADR-0006, CLAUDE.md "ImageModel"). The basic-race output
(basic-race-v1, #37) was fine-tuned with its own copy of the backbone, so it cannot be a head
on the species backbone. traits-v3 therefore holds both networks side by side, reading the same
uint8 input tensor (ADR-0012).

The merge is structural. It copies every tensor, buffer and operator of both models into one
subgraph and does not re-convert or re-quantize anything. Each output is therefore
bit-identical to the model it came from, and the evaluation recorded for each model still
holds. Re-converting a combined Keras model would re-calibrate the activation ranges of both
networks on a new representative set, which would change both models' INT8 outputs and void
their locked test results. `verify_merged_outputs` checks the bit-identity on real photos.

Needs TensorFlow (`export` extra) for the flatbuffer schema and the interpreter.
"""

from collections.abc import Sequence

import numpy as np
import tensorflow as tf
from tensorflow.lite.python import schema_py_generated as schema
from tensorflow.lite.tools import flatbuffer_utils

# Only the main subgraph is run by the interpreter; models with control flow carry more, and
# merging those would need their subgraph indices remapped too.
_SUPPORTED_SUBGRAPH_COUNT = 1


def merge_models(primary: bytes, secondary: bytes, secondary_name_prefix: str) -> bytes:
    """One model whose outputs are the primary's outputs, then the secondary's, in order.

    Both models must have exactly one subgraph and one input of the same type, shape and
    quantization. The secondary's operators read the primary's input tensor. Tensor names
    of the secondary get `secondary_name_prefix`, so names stay unique. The primary's
    metadata (runtime version, conversion metadata) is kept. Its signature is extended with
    the secondary's outputs, named `output_<k>` after the primary's.

    Raises ValueError for models this merge cannot combine safely.
    """
    merged = schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(primary, 0))
    other = schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(secondary, 0))
    for name, model in (("primary", merged), ("secondary", other)):
        if len(model.subgraphs) != _SUPPORTED_SUBGRAPH_COUNT:
            raise ValueError(f"{name} model has {len(model.subgraphs)} subgraphs; only single-subgraph models merge")
        if len(model.subgraphs[0].inputs) != 1:
            raise ValueError(f"{name} model has {len(model.subgraphs[0].inputs)} inputs; expected one image input")
        if any(buffer.offset for buffer in model.buffers):
            raise ValueError(f"{name} model stores buffers outside the flatbuffer; not supported")

    graph, other_graph = merged.subgraphs[0], other.subgraphs[0]
    primary_input = int(graph.inputs[0])
    secondary_input = int(other_graph.inputs[0])
    _require_same_input(graph.tensors[primary_input], other_graph.tensors[secondary_input])

    opcode_index = _merge_operator_codes(merged, other)
    buffer_index = _append_buffers(merged, other)

    tensor_index = {secondary_input: primary_input}
    for index, tensor in enumerate(other_graph.tensors):
        if index == secondary_input:
            continue
        tensor.name = secondary_name_prefix.encode() + (tensor.name or b"")
        tensor.buffer = buffer_index[tensor.buffer]
        tensor_index[index] = len(graph.tensors)
        graph.tensors.append(tensor)

    def remap(indices) -> list[int]:
        # -1 marks an omitted optional input and stays -1.
        return [] if indices is None else [index if index < 0 else tensor_index[int(index)] for index in indices]

    for operator in other_graph.operators:
        operator.opcodeIndex = opcode_index[operator.opcodeIndex]
        operator.inputs = remap(operator.inputs)
        operator.outputs = remap(operator.outputs)
        operator.intermediates = remap(operator.intermediates) or None
        # Appended after the primary's operators, so execution order stays topological.
        graph.operators.append(operator)

    primary_output_count = len(graph.outputs)
    secondary_outputs = remap(other_graph.outputs)
    graph.outputs = list(graph.outputs) + secondary_outputs
    _extend_signature(merged, secondary_outputs, primary_output_count)
    return bytes(flatbuffer_utils.convert_object_to_bytearray(merged))


def verify_merged_outputs(merged: bytes, sources: Sequence[bytes], images: np.ndarray) -> None:
    """Raises ValueError unless output k of `merged` equals the output of `sources[k]`
    bit for bit, on every one of the (n, size, size, 3) uint8 `images`.

    Run with the reference kernels (no delegate), as the export's expected outputs are.
    """
    merged_runner = _Runner(merged)
    if merged_runner.output_count != len(sources):
        raise ValueError(f"merged model has {merged_runner.output_count} outputs for {len(sources)} source models")
    source_runners = [_Runner(source) for source in sources]
    for image_index, image in enumerate(images):
        merged_outputs = merged_runner.outputs(image)
        for output_index, runner in enumerate(source_runners):
            (expected,) = runner.outputs(image)
            actual = merged_outputs[output_index]
            if actual.shape != expected.shape:
                raise ValueError(f"output {output_index} has shape {actual.shape}, its source model {expected.shape}")
            if not np.array_equal(actual, expected):
                raise ValueError(
                    f"output {output_index} differs from its source model on image {image_index}: "
                    f"largest difference {np.abs(actual - expected).max()}"
                )


class _Runner:
    """Raw uint8 in, every output out, reference kernels (as `export.TfliteRunner`)."""

    def __init__(self, model_bytes: bytes) -> None:
        self._interpreter = tf.lite.Interpreter(
            model_content=model_bytes,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
        )
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]
        self._outputs = self._interpreter.get_output_details()
        self.output_count = len(self._outputs)

    def outputs(self, image: np.ndarray) -> list[np.ndarray]:
        self._interpreter.set_tensor(self._input["index"], image[np.newaxis])
        self._interpreter.invoke()
        return [self._interpreter.get_tensor(output["index"])[0].copy() for output in self._outputs]


def _require_same_input(primary: schema.TensorT, secondary: schema.TensorT) -> None:
    """Both networks read one tensor, so they must agree on what its bytes mean."""
    if primary.type != secondary.type or list(primary.shape) != list(secondary.shape):
        raise ValueError(
            f"inputs differ: type {primary.type} shape {list(primary.shape)} "
            f"vs type {secondary.type} shape {list(secondary.shape)}"
        )
    if _quantization_of(primary) != _quantization_of(secondary):
        raise ValueError(f"input quantization differs: {_quantization_of(primary)} vs {_quantization_of(secondary)}")


def _quantization_of(tensor: schema.TensorT) -> tuple:
    quantization = tensor.quantization
    if quantization is None or quantization.scale is None:
        return ()
    return (tuple(float(s) for s in quantization.scale), tuple(int(z) for z in quantization.zeroPoint))


def _merge_operator_codes(merged: schema.ModelT, other: schema.ModelT) -> dict[int, int]:
    """Secondary opcode index -> merged index, reusing identical operator codes."""
    def key(code: schema.OperatorCodeT) -> tuple:
        return (code.builtinCode, code.deprecatedBuiltinCode, code.customCode, code.version)

    existing = {key(code): index for index, code in enumerate(merged.operatorCodes)}
    mapping = {}
    for index, code in enumerate(other.operatorCodes):
        if key(code) not in existing:
            existing[key(code)] = len(merged.operatorCodes)
            merged.operatorCodes.append(code)
        mapping[index] = existing[key(code)]
    return mapping


def _append_buffers(merged: schema.ModelT, other: schema.ModelT) -> dict[int, int]:
    """Appends the secondary buffers its tensors use; returns secondary -> merged index.

    Buffer 0 is the schema's empty sentinel that tensors without constant data point to, so it
    maps to the merged model's own buffer 0. The secondary's metadata buffers are not copied.
    """
    mapping = {0: 0}
    for tensor in other.subgraphs[0].tensors:
        if tensor.buffer in mapping:
            continue
        mapping[tensor.buffer] = len(merged.buffers)
        merged.buffers.append(other.buffers[tensor.buffer])
    return mapping


def _extend_signature(merged: schema.ModelT, secondary_outputs: list[int], primary_output_count: int) -> None:
    """Adds the secondary outputs to the primary's signature, so signature runners see them too."""
    for signature in merged.signatureDefs or []:
        for offset, tensor_index in enumerate(secondary_outputs):
            output = schema.TensorMapT()
            output.name = f"output_{primary_output_count + offset}".encode()
            output.tensorIndex = tensor_index
            signature.outputs.append(output)
