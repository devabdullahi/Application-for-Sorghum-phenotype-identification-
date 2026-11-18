package com.sorghum.capture.ui

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp

/** Size of the round glass buttons in the screen corners. */
internal val GLASS_BUTTON_SIZE = 52.dp

/** Outer size of the shutter button. */
internal val SHUTTER_SIZE = 76.dp

/** Distance from the safe drawing area's edges to the corner buttons and the shutter. */
internal val CAMERA_CONTROLS_EDGE_PADDING = 20.dp

/** Space between the top bar's buttons and the viewfinder, and under the zoom label. */
internal val CAMERA_BAR_GAP = 12.dp

/**
 * Extra bottom padding for the bottom corner buttons, so their centres line up with the
 * shutter's, which is larger.
 */
internal val BOTTOM_CORNER_BUTTON_LIFT = (SHUTTER_SIZE - GLASS_BUTTON_SIZE) / 2

/** iPhone camera yellow, for controls that are on (flash) and the focus square. */
internal val CAMERA_ACCENT_COLOR = Color(0xFFFFD60A)

/**
 * A "liquid glass" surface for controls that float over the camera: a translucent tint, a
 * bright rim catching light from the top, and a soft highlight.
 *
 * Compose cannot blur what is behind an element, and the camera preview is a separate surface
 * that could not be sampled anyway, so the glass is suggested by tint and highlights only.
 */
internal fun Modifier.liquidGlass(shape: Shape): Modifier = this
    // No drop shadow: it would show through the translucent fill as a grey smudge.
    .clip(shape)
    .background(Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.30f), Color.White.copy(alpha = 0.10f))))
    .background(Color.Black.copy(alpha = 0.18f))
    .border(
        width = 1.dp,
        brush = Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.65f), Color.White.copy(alpha = 0.12f))),
        shape = shape,
    )

/**
 * A round glass button with a white icon. [isActive] tints the icon yellow, as the iPhone
 * camera does for a control that is on.
 */
@Composable
internal fun GlassCircleButton(
    @DrawableRes icon: Int,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    isActive: Boolean = false,
    isEnabled: Boolean = true,
) {
    IconButton(
        onClick = onClick,
        enabled = isEnabled,
        colors = IconButtonDefaults.iconButtonColors(
            contentColor = if (isActive) CAMERA_ACCENT_COLOR else Color.White,
            disabledContentColor = Color.White.copy(alpha = 0.4f),
        ),
        modifier = modifier.size(GLASS_BUTTON_SIZE).liquidGlass(CircleShape),
    ) {
        Icon(painterResource(icon), contentDescription = contentDescription)
    }
}

/** The iPhone-style shutter: a white disc inside a white ring. Dimmed while disabled. */
@Composable
internal fun ShutterButton(onClick: () -> Unit, contentDescription: String, isEnabled: Boolean, modifier: Modifier = Modifier) {
    IconButton(
        onClick = onClick,
        enabled = isEnabled,
        modifier = modifier
            .size(SHUTTER_SIZE)
            .alpha(if (isEnabled) 1f else 0.5f)
            .semantics { this.contentDescription = contentDescription },
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.size(SHUTTER_SIZE).border(4.dp, Color.White, CircleShape),
        ) {
            Box(Modifier.size(SHUTTER_SIZE - 16.dp).clip(CircleShape).background(Color.White))
        }
    }
}
