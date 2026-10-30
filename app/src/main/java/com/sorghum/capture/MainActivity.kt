package com.sorghum.capture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import com.sorghum.capture.ui.HomeScreen

/** Single activity: everything happens in [HomeScreen]. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            // Dark throughout: the camera fills the Capture tab, and the dark platform theme
            // draws light status bar icons that would vanish on a light background.
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface { HomeScreen() }
            }
        }
    }
}
