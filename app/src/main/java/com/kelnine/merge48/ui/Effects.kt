package com.kelnine.merge48.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import com.kelnine.merge48.ui.theme.NightBottom
import com.kelnine.merge48.ui.theme.NightTop
import com.kelnine.merge48.ui.theme.SolanaGreen
import com.kelnine.merge48.ui.theme.SolanaPurple
import androidx.compose.ui.unit.Dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random
import kotlinx.coroutines.delay

private class Star(val x: Float, val y: Float, val radius: Float, val phase: Float)

/**
 * Living backdrop: night gradient, two aurora blobs slowly drifting in
 * opposite directions, and a field of gently twinkling stars.
 */
@Composable
fun AuroraBackground(modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "aurora")
    val drift by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(24_000, easing = LinearEasing), RepeatMode.Reverse),
        label = "drift"
    )
    val twinkle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(6_000, easing = LinearEasing), RepeatMode.Restart),
        label = "twinkle"
    )
    val stars = remember {
        val random = Random(48)
        List(70) {
            Star(
                x = random.nextFloat(),
                y = random.nextFloat(),
                radius = 0.6f + random.nextFloat() * 1.7f,
                phase = random.nextFloat()
            )
        }
    }

    Canvas(modifier.fillMaxSize()) {
        drawRect(Brush.verticalGradient(listOf(NightTop, NightBottom)))

        val w = size.width
        val h = size.height

        drawCircle(
            brush = Brush.radialGradient(
                listOf(SolanaPurple.copy(alpha = 0.22f), Color.Transparent),
                center = Offset(w * (0.15f + 0.25f * drift), h * (0.10f + 0.15f * drift)),
                radius = w * 0.75f
            ),
            radius = w * 0.75f,
            center = Offset(w * (0.15f + 0.25f * drift), h * (0.10f + 0.15f * drift))
        )
        drawCircle(
            brush = Brush.radialGradient(
                listOf(SolanaGreen.copy(alpha = 0.10f), Color.Transparent),
                center = Offset(w * (0.95f - 0.30f * drift), h * (0.80f - 0.20f * drift)),
                radius = w * 0.65f
            ),
            radius = w * 0.65f,
            center = Offset(w * (0.95f - 0.30f * drift), h * (0.80f - 0.20f * drift))
        )

        stars.forEach { star ->
            val alpha = 0.18f + 0.45f *
                (0.5f + 0.5f * sin(2f * PI.toFloat() * (twinkle + star.phase)))
            drawCircle(
                color = Color.White.copy(alpha = alpha),
                radius = star.radius,
                center = Offset(star.x * w, star.y * h)
            )
        }
    }
}

/**
 * Purple/green sparks that explode outward from cells where merges just
 * landed. Replays whenever [burstId] changes; waits for the tile slide
 * to finish so the burst happens at the moment of the merge pop.
 */
@Composable
fun MergeBursts(
    burstId: Int,
    cells: List<Pair<Int, Int>>,
    cellSize: Dp,
    gap: Dp,
    slideMillis: Int,
    modifier: Modifier = Modifier
) {
    val progress = remember { Animatable(1f) }
    LaunchedEffect(burstId) {
        if (burstId > 0 && cells.isNotEmpty()) {
            progress.snapTo(0f)
            delay(slideMillis.toLong())
            progress.animateTo(1f, tween(420, easing = FastOutLinearInEasing))
        }
    }

    val t = progress.value
    if (t > 0f && t < 1f && cells.isNotEmpty()) {
        Canvas(modifier.fillMaxSize()) {
            val cellPx = cellSize.toPx()
            val gapPx = gap.toPx()
            cells.forEachIndexed { cellIndex, (row, col) ->
                val centerX = gapPx + (cellPx + gapPx) * col + cellPx / 2f
                val centerY = gapPx + (cellPx + gapPx) * row + cellPx / 2f
                repeat(12) { i ->
                    val angle = (i / 12f + cellIndex * 0.07f) * 2f * PI.toFloat()
                    val distance = t * cellPx * 0.85f
                    drawCircle(
                        color = if (i % 2 == 0) SolanaGreen else SolanaPurple,
                        radius = (1f - t) * 7f + 1f,
                        center = Offset(
                            centerX + cos(angle) * distance,
                            centerY + sin(angle) * distance
                        ),
                        alpha = (1f - t).coerceIn(0f, 1f)
                    )
                }
            }
        }
    }
}
