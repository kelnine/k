package com.kelnine.merge48.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val SolanaPurple = Color(0xFF9945FF)
val SolanaGreen = Color(0xFF14F195)
val NightBackground = Color(0xFF0E0B1A)
val BoardBackground = Color(0xFF1D1633)
val EmptyCell = Color(0xFF2A2147)
val TextPrimary = Color(0xFFF4F1FA)
val TextOnTile = Color(0xFF0E0B1A)

/** Tile fill colors, walking the Solana purple -> green gradient as values grow. */
fun tileColor(value: Int): Color = when (value) {
    2 -> Color(0xFF3D2E66)
    4 -> Color(0xFF4D3580)
    8 -> Color(0xFF6239A8)
    16 -> Color(0xFF7B3FD1)
    32 -> Color(0xFF9945FF)
    64 -> Color(0xFFB05CF0)
    128 -> Color(0xFF8E6BE8)
    256 -> Color(0xFF5F8BD9)
    512 -> Color(0xFF35AFC2)
    1024 -> Color(0xFF1FD0A8)
    2048 -> Color(0xFF14F195)
    else -> Color(0xFF0BC97D)
}

fun tileTextColor(value: Int): Color =
    if (value >= 512) TextOnTile else TextPrimary

private val DarkColors = darkColorScheme(
    primary = SolanaPurple,
    secondary = SolanaGreen,
    background = NightBackground,
    surface = BoardBackground,
    onPrimary = TextPrimary,
    onSecondary = TextOnTile,
    onBackground = TextPrimary,
    onSurface = TextPrimary
)

@Composable
fun Merge48Theme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColors,
        content = content
    )
}
