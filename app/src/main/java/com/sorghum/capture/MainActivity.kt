package com.sorghum.capture

import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import com.sorghum.capture.ui.HomeScreen

/** Single activity: everything happens in [HomeScreen]. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // The camera fills the whole screen, behind transparent system bars. Dark styles keep
        // their icons light over the preview whatever the system theme is.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        setContent {
            // Dark throughout, to match the camera and the light system bar icons.
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface { HomeScreen() }
            }
        }
    }
}
