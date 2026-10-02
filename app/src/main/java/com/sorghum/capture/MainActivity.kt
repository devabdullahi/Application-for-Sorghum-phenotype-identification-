package com.sorghum.capture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import com.sorghum.capture.ui.CaptureApp

/** Single-screen app: everything happens in [CaptureApp]. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface { CaptureApp() }
            }
        }
    }
}
