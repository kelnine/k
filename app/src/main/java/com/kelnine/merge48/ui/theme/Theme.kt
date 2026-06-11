package com.kelnine.merge48.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

val SolanaPurple = Color(0xFF9945FF)
val SolanaGreen = Color(0xFF14F195)
val NightTop = Color(0xFF1B1138)
val NightBottom = Color(0xFF070410)
val NightBackground = Color(0xFF0E0B1A)
val BoardBackground = Color(0xFF161028)
val EmptyCell = Color(0xFF241B40)
val TextPrimary = Color(0xFFF4F1FA)
val TextDim = Color(0xFF9D93B8)
val TextOnTile = Color(0xFF06130C)

/** App-wide background: deep violet night fading to near-black. */
val AppBackgroundBrush = Brush.verticalGradient(listOf(NightTop, NightBottom))

/** Signature gradient used for the title, primary buttons and accents. */
val SignatureBrush = Brush.horizontalGradient(listOf(SolanaPurple, Color(0xFF7C6BFF), SolanaGreen))

val PurpleButtonBrush = Brush.horizontalGradient(listOf(Color(0xFF7B2FF7), Color(0xFFA855F7)))
val GreenButtonBrush = Brush.horizontalGradient(listOf(Color(0xFF0BC97D), SolanaGreen))
val DisabledButtonBrush = Brush.horizontalGradient(listOf(Color(0xFF2A2342), Color(0xFF2A2342)))

/**
 * Two-tone tile gradients climbing the Solana spectrum: deep violet for the
 * small tiles, electric purple through blue and teal mid-game, neon green
 * at the top end.
 */
fun tileBrushColors(value: Int): List<Color> = when (value) {
    2 -> listOf(Color(0xFF332A5C), Color(0xFF413473))
    4 -> listOf(Color(0xFF44348A), Color(0xFF5540A6))
    8 -> listOf(Color(0xFF5F3DC4), Color(0xFF7950E8))
    16 -> listOf(Color(0xFF7A3FF2), Color(0xFF9945FF))
    32 -> listOf(Color(0xFF9945FF), Color(0xFFB45CFF))
    64 -> listOf(Color(0xFFA94FFF), Color(0xFFD06BFF))
    128 -> listOf(Color(0xFF8A5CF6), Color(0xFF6486F8))
    256 -> listOf(Color(0xFF5E7DF7), Color(0xFF3FA9E8))
    512 -> listOf(Color(0xFF31B5CF), Color(0xFF21D3B1))
    1024 -> listOf(Color(0xFF18DBA0), Color(0xFF14F195))
    2048 -> listOf(Color(0xFF14F195), Color(0xFF8CFFCB))
    else -> listOf(Color(0xFFFFC83C), Color(0xFFFFE08A)) // beyond 2048: gold
}

/** Glow color for the soft shadow under big tiles. */
fun tileGlowColor(value: Int): Color = when {
    value >= 4096 -> Color(0xFFFFC83C)
    value >= 512 -> SolanaGreen
    value >= 32 -> SolanaPurple
    else -> Color.Transparent
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
