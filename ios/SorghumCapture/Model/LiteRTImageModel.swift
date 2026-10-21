import Foundation
import Shared
import TensorFlowLite

/// The shared `ImageModel` port on iOS, backed by LiteRT (TensorFlow Lite).
///
/// It only loads the `.tflite` file and runs the interpreter: the shared core builds the input
/// tensor and reads the outputs (ADR-0004). Not thread-safe; the capture flow checks one photo
/// at a time, so calls never overlap.
final class LiteRTImageModel: NSObject, ImageModel {
    private let interpreter: Interpreter

    /// Throws if the file is missing, not a valid model, or its tensors cannot be allocated.
    init(modelPath: String) throws {
        interpreter = try Interpreter(modelPath: modelPath)
        try interpreter.allocateTensors()
        super.init()
    }

    /// Returns every output as floats, dequantizing quantized outputs. On an interpreter error it
    /// returns no outputs, which the shared core reports as "species check unavailable".
    func run(inputTensor: KotlinByteArray) -> [KotlinFloatArray] {
        do {
            try interpreter.copy(data(of: inputTensor), toInputAt: 0)
            try interpreter.invoke()
            return try (0..<interpreter.outputTensorCount).map { try floats(of: interpreter.output(at: $0)) }
        } catch {
            return []
        }
    }

    private func data(of bytes: KotlinByteArray) -> Data {
        var data = Data(count: Int(bytes.size))
        data.withUnsafeMutableBytes { buffer in
            let target = buffer.bindMemory(to: Int8.self)
            for index in 0..<Int(bytes.size) {
                target[index] = bytes.get(index: Int32(index))
            }
        }
        return data
    }

    private func floats(of tensor: Tensor) -> KotlinFloatArray {
        let values: [Float]
        switch tensor.dataType {
        case .float32:
            values = tensor.data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        case .uInt8:
            values = dequantized(tensor.data.map { Int($0) }, tensor.quantizationParameters)
        default:
            // The species model exports float logits (model/sorghum_model/export.py). Any other
            // type returns no values, which the shared core reports as "species check unavailable".
            values = []
        }
        let result = KotlinFloatArray(size: Int32(values.count))
        for (index, value) in values.enumerated() {
            result.set(index: Int32(index), value: value)
        }
        return result
    }

    /// real = scale * (q - zeroPoint), the TensorFlow Lite quantization formula.
    private func dequantized(_ quantized: [Int], _ parameters: QuantizationParameters?) -> [Float] {
        guard let parameters else { return quantized.map(Float.init) }
        return quantized.map { parameters.scale * Float($0 - parameters.zeroPoint) }
    }
}
