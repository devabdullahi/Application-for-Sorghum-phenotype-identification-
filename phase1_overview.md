# Plant Sample Capture

## High-Level Architecture (Offline, Android)

### 1. Purpose

The application helps a user photograph a cut sorghum sample (leaves or a whole plant) laid on a plain board, so every photo is taken the same way: phone held flat above the board, sample fully inside a predefined frame, image sharp and well exposed. Consistent photos make later phenotype measurements comparable.

**Everything runs on the device. The application makes no network requests.** Images never leave the device.

The system has two stages:

1. **Live guidance.** Read the phone's tilt and analyze preview frames in real time, and guide the user until the phone is level, the sample is inside the frame, and the phone is steady.
2. **Post-capture check.** Crop the full-resolution photo to the frame and reject it if it is blurry, too dark, has glare, or contains no sample.

This follows the approach of the iOS Camera level: guidance comes mostly from motion sensors, not from recognizing the object. The only image analysis is a cheap green-pixel check, which works because the samples are green and the board is not.

---

## 2. Components

```text
Android app (Kotlin, fully offline)
│
├── Live Guidance
│   ├── Camera            (CameraX: preview, analysis frames, still capture)
│   ├── Tilt Sensor       (gravity sensor → pitch and roll)
│   ├── Green Detector    (how much sample is in the frame, and whether it touches the frame edge)
│   ├── Target Frame      (where the sample should be; configurable)
│   ├── Guidance Evaluator(tilt + green coverage → one guidance state)
│   └── Capture Trigger   (state stayed aligned for N ms → capture)
│
├── Post-Capture Check
│   ├── Photo Cropper     (crop to target frame, rotate upright)
│   └── Photo Quality Checker (blur, darkness, glare, sample present)
│
├── Frame Mapping (target frame ↔ camera image coordinates, one place)
│
└── UI (Jetpack Compose)
```

There is no API client, backend, or HTTP layer.

---

## 3. Live Guidance

### 3.1 Camera

* Preview shown in a `PreviewView`.
* Low-resolution analysis frames. Frames are dropped when analysis falls behind (`STRATEGY_KEEP_ONLY_LATEST`) so guidance reflects the latest frame.
* Full-resolution still captured into memory (not to a file) on request.
* All three use cases share one CameraX viewport, so a point in the on-screen frame corresponds to the same point in analysis frames and in the still.

### 3.2 Tilt Sensor

Reads the gravity sensor (falls back to the accelerometer) and reports pitch and roll in degrees, where 0/0 means the phone is lying flat, screen up, camera pointing straight down at the board.

### 3.3 Green Detector

Classifies pixels inside the target frame as plant or background with the excess-green index (`2g − r − b` on chromatic coordinates). Outputs:

* Fraction of the frame covered by green.
* Fraction of the frame's edge band covered by green (sample cut off by the frame).

It is shared by live guidance (small frames) and post-capture (the cropped photo).

### 3.4 Target Frame

Drawn over the preview. Defined as a normalized rectangle of the preview (size and aspect ratio configurable), so the frame can be changed without touching detection code.

### 3.5 Guidance Evaluator

A pure function: tilt + green coverage + settings → one state. Checks run in fixed priority so the user gets one instruction at a time:

```text
1. Level:    TILT_TOP_DOWN, TILT_BOTTOM_DOWN, TILT_LEFT_DOWN, TILT_RIGHT_DOWN
2. Sample:   NO_SAMPLE, SAMPLE_CUT_OFF
3. Aligned → Capture Trigger decides HOLD_STEADY or READY
```

Level comes first because framing is meaningless while the phone is tilted.

### 3.6 Capture Trigger

Once everything is aligned, the state must stay aligned for a configurable time (default 800 ms) before it becomes `READY`. Any misalignment restarts the timer. `READY` captures automatically. Phase 1 has no manual capture button (the UI is kept deliberately minimal).

---

## 4. Post-Capture Check

```text
Full-res still (in memory)
        │
        ▼
Photo Cropper ──► cropped, upright photo
        │
        ▼
Photo Quality Checker ──► PhotoCheckResult
```

Runs off the UI thread with a progress indicator.

```kotlin
sealed interface PhotoCheckResult {
    data class Accepted(val photo: Bitmap) : PhotoCheckResult
    data class Rejected(val reason: RejectionReason) : PhotoCheckResult
}

enum class RejectionReason { NO_SAMPLE, TOO_DARK, GLARE, BLURRY }
```

* **NO_SAMPLE:** too little green in the cropped photo.
* **TOO_DARK:** mean brightness below threshold.
* **GLARE:** too many near-white pixels.
* **BLURRY:** variance of the Laplacian (a standard sharpness measure) below threshold.

The thresholds are starting values and must be tuned with real sample photos.

Specific reasons let the UI tell the user what to fix. On rejection, the user retakes the photo.

---

## 5. End-to-End Flow

```text
1. Grant camera permission, start camera, show target frame
          │
          ▼
2. Tilt Sensor + analysis frame ──► Green Detector
          │
          ▼
3. Guidance Evaluator ──► Capture Trigger ──► state ──► UI message
          │
          ▼
4. READY ──► capture full-res still
          │
          ▼
5. Photo Cropper ──► Photo Quality Checker ──► PhotoCheckResult
          │
     ┌────┴─────┐
  Rejected    Accepted
     │            │
     ▼            ▼
  Show reason,  Show cropped photo,
  retake        retake option
```

---

## 6. Offline and Privacy Requirements

* **No network access.** The manifest does not declare `INTERNET`, and explicitly removes it if a library tries to merge it in.
* **No analytics or crash-reporting SDKs.**
* **Photos stay in memory.** Nothing is written to storage or the gallery in phase 1.

---

## 7. Scope

### Included

* Camera preview with target frame
* Level guidance from the gravity sensor
* Green-pixel sample check
* Steady auto-capture and manual capture
* Crop to frame and quality check
* Result screen with rejection reasons

### Excluded from phase 1

* Network communication, accounts, analytics
* Saving or sharing photos
* Phenotype measurement
* Samples that are not green (e.g. mature panicles) — the green check would need to be replaced by a contrast check
* iOS

---

## 8. Known Limitations

* The green check assumes a plain, non-green board. A green board or a cluttered background will break it.
* Quality thresholds are initial guesses until tuned on real photos.
* Steadiness is inferred from the device staying level for the hold time; there is no gyroscope-based shake check yet.
