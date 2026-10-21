import CoreMotion
import Shared

/// Reports how far the phone is from lying flat, using Core Motion's gravity vector.
///
/// See `deviceTilt(fromCoreMotionGravity:)` for the axis conversion. Units do not matter because
/// only angles are taken. Flat screen-up reads (0, 0) and a raised top edge reads positive pitch.
final class TiltSensor {
    private let motionManager = CMMotionManager()

    /// Readings per second. Guidance only needs to feel responsive, not track fast motion.
    private static let updatesPerSecond = 30.0

    var isAvailable: Bool { motionManager.isDeviceMotionAvailable }

    /// Starts delivering tilt readings on the main thread, each with a monotonic timestamp in ms.
    func start(onTilt: @escaping (DeviceTilt, Int64) -> Void) {
        guard isAvailable else { return }
        motionManager.deviceMotionUpdateInterval = 1 / Self.updatesPerSecond
        motionManager.startDeviceMotionUpdates(to: .main) { motion, _ in
            guard let gravity = motion?.gravity else { return }
            onTilt(deviceTilt(fromCoreMotionGravity: gravity), monotonicMillis())
        }
    }

    func stop() {
        motionManager.stopDeviceMotionUpdates()
    }
}

/// Converts Core Motion's gravity (toward the earth) to the shared tilt convention, which
/// expects the reaction to gravity (pointing up), by flipping every axis.
func deviceTilt(fromCoreMotionGravity gravity: CMAcceleration) -> DeviceTilt {
    DeviceTilt.companion.fromGravity(x: Float(-gravity.x), y: Float(-gravity.y), z: Float(-gravity.z))
}

/// Milliseconds since boot. Monotonic, like Android's SystemClock.elapsedRealtime, so the
/// shared steady-hold timer is unaffected by clock changes.
func monotonicMillis() -> Int64 {
    Int64(ProcessInfo.processInfo.systemUptime * 1000)
}
