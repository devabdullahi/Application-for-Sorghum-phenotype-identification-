import CoreMotion
import Shared
import XCTest
@testable import SorghumCapture

/// Core Motion gravity points toward the earth; the shared convention is Android's (pointing up).
final class TiltConversionTests: XCTestCase {
    private let tolerance: Float = 0.01

    func testFlatScreenUpIsLevel() {
        let tilt = deviceTilt(fromCoreMotionGravity: CMAcceleration(x: 0, y: 0, z: -1))

        XCTAssertEqual(tilt.pitchDegrees, 0, accuracy: tolerance)
        XCTAssertEqual(tilt.rollDegrees, 0, accuracy: tolerance)
    }

    func testRaisingTheTopEdgeGivesPositivePitch() {
        // Top edge up 10°: gravity now pulls partly toward the bottom edge (-y).
        let radians = 10 * Double.pi / 180
        let tilt = deviceTilt(fromCoreMotionGravity: CMAcceleration(x: 0, y: -sin(radians), z: -cos(radians)))

        XCTAssertEqual(tilt.pitchDegrees, 10, accuracy: tolerance)
        XCTAssertEqual(tilt.rollDegrees, 0, accuracy: tolerance)
    }

    func testRaisingTheRightEdgeGivesPositiveRoll() {
        let radians = 8 * Double.pi / 180
        let tilt = deviceTilt(fromCoreMotionGravity: CMAcceleration(x: -sin(radians), y: 0, z: -cos(radians)))

        XCTAssertEqual(tilt.rollDegrees, 8, accuracy: tolerance)
    }

    func testFaceDownIsNotLevel() {
        let tilt = deviceTilt(fromCoreMotionGravity: CMAcceleration(x: 0, y: 0, z: 1))

        XCTAssertGreaterThan(abs(tilt.pitchDegrees), 90)
    }
}
