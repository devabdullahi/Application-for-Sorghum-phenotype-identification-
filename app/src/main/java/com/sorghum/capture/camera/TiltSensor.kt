package com.sorghum.capture.camera

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import com.sorghum.capture.guidance.DeviceTilt
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/** Thrown when the device has neither a gravity sensor nor an accelerometer. */
class TiltSensorUnavailableException : IllegalStateException(
    "Device has no gravity sensor or accelerometer; level guidance is impossible"
)

/**
 * Reports how far the phone is from lying flat, using the device's motion sensors.
 * This is the same idea as the level in the iOS Camera app.
 */
class TiltSensor(context: Context) {

    private val sensorManager = context.getSystemService(SensorManager::class.java)

    /**
     * Emits a [DeviceTilt] for every sensor reading while collected, and unregisters the
     * sensor listener when collection stops, so the sensor never runs in the background.
     *
     * Fails with [TiltSensorUnavailableException] if the device has no usable sensor.
     */
    fun tiltUpdates(): Flow<DeviceTilt> = callbackFlow {
        // TYPE_GRAVITY is the accelerometer with hand shake filtered out by the OS. Fall back to
        // the raw accelerometer on the rare devices without it; readings are noisier but usable.
        val sensor = sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY)
            ?: sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        if (sensor == null) {
            close(TiltSensorUnavailableException())
            return@callbackFlow
        }

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent) {
                val (x, y, z) = event.values
                trySend(DeviceTilt.fromGravity(x, y, z))
            }

            override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) = Unit
        }

        // SENSOR_DELAY_UI (~16 readings per second) is plenty for on-screen guidance and
        // uses less battery than the faster rates.
        sensorManager.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_UI)
        awaitClose { sensorManager.unregisterListener(listener) }
    }
}
