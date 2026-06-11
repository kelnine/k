package com.kelnine.merge48.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kelnine.merge48.game.Direction
import com.kelnine.merge48.game.GameViewModel
import com.kelnine.merge48.game.Tile
import com.kelnine.merge48.game.TileBoard
import com.kelnine.merge48.payments.PaymentsConfig
import com.kelnine.merge48.payments.Product
import com.kelnine.merge48.ui.theme.AppBackgroundBrush
import com.kelnine.merge48.ui.theme.BoardBackground
import com.kelnine.merge48.ui.theme.DisabledButtonBrush
import com.kelnine.merge48.ui.theme.EmptyCell
import com.kelnine.merge48.ui.theme.GreenButtonBrush
import com.kelnine.merge48.ui.theme.NightBottom
import com.kelnine.merge48.ui.theme.PurpleButtonBrush
import com.kelnine.merge48.ui.theme.SignatureBrush
import com.kelnine.merge48.ui.theme.SolanaGreen
import com.kelnine.merge48.ui.theme.SolanaPurple
import com.kelnine.merge48.ui.theme.TextDim
import com.kelnine.merge48.ui.theme.TextOnTile
import com.kelnine.merge48.ui.theme.TextPrimary
import com.kelnine.merge48.ui.theme.tileBrushColors
import com.kelnine.merge48.ui.theme.tileGlowColor
import com.kelnine.merge48.ui.theme.tileTextColor
import com.kelnine.merge48.wallet.WalletViewModel
import kotlin.math.abs
import kotlinx.coroutines.delay

private const val SWIPE_THRESHOLD_PX = 60f
private const val SLIDE_MILLIS = 130

@Composable
fun GameScreen(
    onConnectWallet: (WalletViewModel) -> Unit,
    onSignScore: (WalletViewModel, Int) -> Unit,
    onPurchase: (WalletViewModel, Product, () -> Unit) -> Unit,
    onMintTrophy: (WalletViewModel, Int) -> Unit,
    gameViewModel: GameViewModel = viewModel(),
    walletViewModel: WalletViewModel = viewModel()
) {
    val gameState by gameViewModel.state.collectAsState()
    val walletState by walletViewModel.state.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(walletState.statusMessage) {
        walletState.statusMessage?.let { message ->
            snackbarHostState.showSnackbar(message)
            walletViewModel.consumeStatusMessage()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(AppBackgroundBrush)
    ) {
        Scaffold(
            containerColor = Color.Transparent,
            snackbarHost = { SnackbarHost(snackbarHostState) }
        ) { padding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Header(score = gameState.score, best = gameState.bestScore)

                Spacer(Modifier.height(14.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    OutlineButton(
                        text = "New Game",
                        onClick = { gameViewModel.newGame() },
                        modifier = Modifier.weight(1f)
                    )
                    if (walletState.connected) {
                        OutlineButton(
                            text = WalletViewModel.shorten(walletState.address.orEmpty()),
                            onClick = { walletViewModel.disconnect() },
                            modifier = Modifier.weight(1f)
                        )
                    } else {
                        GradientButton(
                            text = "Connect Wallet",
                            onClick = { onConnectWallet(walletViewModel) },
                            enabled = !walletState.inProgress,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                if (walletState.connected) {
                    Spacer(Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        if (walletState.proUnlocked) {
                            OutlineButton(
                                text = "Undo",
                                onClick = gameViewModel::undo,
                                enabled = gameState.canUndo,
                                modifier = Modifier.weight(1f)
                            )
                        } else {
                            OutlineButton(
                                text = "Go Pro · ${Product.PRO_UNLOCK.priceLabel}",
                                onClick = {
                                    onPurchase(walletViewModel, Product.PRO_UNLOCK) {}
                                },
                                enabled = !walletState.inProgress,
                                modifier = Modifier.weight(1f)
                            )
                        }
                        OutlineButton(
                            text = "Tip · ${Product.TIP.priceLabel}",
                            onClick = { onPurchase(walletViewModel, Product.TIP) {} },
                            enabled = !walletState.inProgress,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                Spacer(Modifier.height(18.dp))

                Box(contentAlignment = Alignment.Center) {
                    BoardGlow()
                    GameBoard(
                        board = gameState.board,
                        onSwipe = gameViewModel::onSwipe
                    )
                    GameOverOverlay(
                        visible = gameState.isGameOver,
                        score = gameState.score,
                        walletConnected = walletState.connected,
                        walletBusy = walletState.inProgress,
                        onNewGame = gameViewModel::newGame,
                        onSignScore = { onSignScore(walletViewModel, gameState.score) },
                        onSecondChance = {
                            onPurchase(walletViewModel, Product.SECOND_CHANCE) {
                                gameViewModel.applySecondChance()
                            }
                        },
                        onMintTrophy = { onMintTrophy(walletViewModel, gameState.score) }
                    )
                }

                Spacer(Modifier.height(18.dp))

                if (gameState.hasWon) {
                    WinBanner()
                    Spacer(Modifier.height(8.dp))
                }

                Text(
                    text = "Swipe to merge tiles. Connect your Solana wallet to sign your high score.",
                    color = TextDim,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center
                )
            }
        }
    }
}

@Composable
private fun Header(score: Int, best: Int) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = "Merge48",
            style = TextStyle(
                brush = SignatureBrush,
                fontSize = 34.sp,
                fontWeight = FontWeight.ExtraBold
            ),
            modifier = Modifier.weight(1f)
        )
        ScoreChip(label = "SCORE", value = score, pulseOnChange = true)
        Spacer(Modifier.size(8.dp))
        ScoreChip(label = "BEST", value = best, pulseOnChange = false)
    }
}

@Composable
private fun ScoreChip(label: String, value: Int, pulseOnChange: Boolean) {
    val scale = remember { Animatable(1f) }
    if (pulseOnChange) {
        LaunchedEffect(value) {
            if (value > 0) {
                scale.snapTo(1.12f)
                scale.animateTo(1f, spring(stiffness = Spring.StiffnessMedium))
            }
        }
    }
    Column(
        modifier = Modifier
            .graphicsLayer {
                scaleX = scale.value
                scaleY = scale.value
            }
            .clip(RoundedCornerShape(12.dp))
            .background(BoardBackground)
            .border(
                BorderStroke(1.dp, Brush.verticalGradient(
                    listOf(SolanaPurple.copy(alpha = 0.5f), Color.Transparent)
                )),
                RoundedCornerShape(12.dp)
            )
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(label, color = SolanaGreen, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Text("$value", color = TextPrimary, fontSize = 18.sp, fontWeight = FontWeight.Bold)
    }
}

/** Soft radial halo sitting behind the board. */
@Composable
private fun BoardGlow() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(0.92f)
            .background(
                Brush.radialGradient(
                    listOf(SolanaPurple.copy(alpha = 0.30f), Color.Transparent)
                )
            )
    )
}

@Composable
private fun GameBoard(board: TileBoard, onSwipe: (Direction) -> Unit) {
    BoxWithConstraints(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .shadow(18.dp, RoundedCornerShape(20.dp), spotColor = SolanaPurple)
            .clip(RoundedCornerShape(20.dp))
            .background(BoardBackground)
            .border(
                BorderStroke(1.dp, Brush.verticalGradient(
                    listOf(SolanaPurple.copy(alpha = 0.35f), Color.Transparent)
                )),
                RoundedCornerShape(20.dp)
            )
            .pointerInput(Unit) {
                var totalDrag = Offset.Zero
                detectDragGestures(
                    onDragStart = { totalDrag = Offset.Zero },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        totalDrag += dragAmount
                    },
                    onDragEnd = {
                        val (dx, dy) = totalDrag
                        val direction = when {
                            abs(dx) >= abs(dy) && abs(dx) > SWIPE_THRESHOLD_PX ->
                                if (dx > 0) Direction.RIGHT else Direction.LEFT
                            abs(dy) > abs(dx) && abs(dy) > SWIPE_THRESHOLD_PX ->
                                if (dy > 0) Direction.DOWN else Direction.UP
                            else -> null
                        }
                        direction?.let(onSwipe)
                    }
                )
            }
    ) {
        val gap = 8.dp
        val cellSize = (maxWidth - gap * (TileBoard.SIZE + 1)) / TileBoard.SIZE

        // Static empty-cell wells
        for (row in 0 until TileBoard.SIZE) {
            for (col in 0 until TileBoard.SIZE) {
                Box(
                    modifier = Modifier
                        .offset(
                            x = gap + (cellSize + gap) * col,
                            y = gap + (cellSize + gap) * row
                        )
                        .size(cellSize)
                        .clip(RoundedCornerShape(12.dp))
                        .background(EmptyCell)
                )
            }
        }

        // Live tiles, keyed by identity so they slide between cells
        board.tiles.forEach { tile ->
            key(tile.id) {
                TileView(tile = tile, cellSize = cellSize, gap = gap)
            }
        }
    }
}

@Composable
private fun TileView(tile: Tile, cellSize: Dp, gap: Dp) {
    val x by animateDpAsState(
        targetValue = gap + (cellSize + gap) * tile.col,
        animationSpec = tween(SLIDE_MILLIS, easing = FastOutSlowInEasing),
        label = "tileX"
    )
    val y by animateDpAsState(
        targetValue = gap + (cellSize + gap) * tile.row,
        animationSpec = tween(SLIDE_MILLIS, easing = FastOutSlowInEasing),
        label = "tileY"
    )

    val scale = remember { Animatable(0f) }
    var seenValue by remember { mutableIntStateOf(tile.value) }

    // Spawn: grow in with a bounce.
    LaunchedEffect(Unit) {
        scale.animateTo(
            1f,
            spring(
                dampingRatio = Spring.DampingRatioMediumBouncy,
                stiffness = Spring.StiffnessMediumLow
            )
        )
    }

    // Merge: once the slide lands, pop.
    LaunchedEffect(tile.value) {
        if (tile.value != seenValue) {
            seenValue = tile.value
            delay(SLIDE_MILLIS.toLong() - 40)
            scale.animateTo(1.18f, tween(70))
            scale.animateTo(1f, tween(90))
        }
    }

    val glow = tileGlowColor(tile.value)
    Box(
        modifier = Modifier
            .offset(x = x, y = y)
            .size(cellSize)
            .graphicsLayer {
                scaleX = scale.value
                scaleY = scale.value
            }
            .shadow(
                elevation = if (glow == Color.Transparent) 0.dp else 12.dp,
                shape = RoundedCornerShape(12.dp),
                ambientColor = glow,
                spotColor = glow
            )
            .clip(RoundedCornerShape(12.dp))
            .background(Brush.linearGradient(tileBrushColors(tile.value))),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = "${tile.value}",
            color = tileTextColor(tile.value),
            fontWeight = FontWeight.ExtraBold,
            fontSize = when {
                tile.value < 100 -> 30.sp
                tile.value < 1000 -> 25.sp
                else -> 20.sp
            }
        )
    }
}

@Composable
private fun WinBanner() {
    val pulse by rememberInfiniteTransition(label = "win").animateFloat(
        initialValue = 0.6f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "winAlpha"
    )
    Text(
        text = "You reached 2048! Keep merging…",
        style = TextStyle(
            brush = SignatureBrush,
            fontSize = 16.sp,
            fontWeight = FontWeight.Bold
        ),
        modifier = Modifier.graphicsLayer { alpha = pulse }
    )
}

@Composable
private fun GameOverOverlay(
    visible: Boolean,
    score: Int,
    walletConnected: Boolean,
    walletBusy: Boolean,
    onNewGame: () -> Unit,
    onSignScore: () -> Unit,
    onSecondChance: () -> Unit,
    onMintTrophy: () -> Unit
) {
    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(tween(250)) + scaleIn(initialScale = 0.92f, animationSpec = tween(250)),
        exit = fadeOut(tween(150))
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
                .clip(RoundedCornerShape(20.dp))
                .background(NightBottom.copy(alpha = 0.92f))
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(
                text = "Game Over",
                style = TextStyle(
                    brush = SignatureBrush,
                    fontSize = 32.sp,
                    fontWeight = FontWeight.ExtraBold
                )
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Final score: $score",
                color = SolanaGreen,
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(22.dp))
            GradientButton(
                text = "Play Again",
                onClick = onNewGame,
                modifier = Modifier.fillMaxWidth(0.72f)
            )
            if (walletConnected) {
                Spacer(Modifier.height(8.dp))
                GradientButton(
                    text = "Second Chance · ${Product.SECOND_CHANCE.priceLabel}",
                    onClick = onSecondChance,
                    enabled = !walletBusy,
                    brush = GreenButtonBrush,
                    textColor = TextOnTile,
                    modifier = Modifier.fillMaxWidth(0.72f)
                )
                Spacer(Modifier.height(8.dp))
                OutlineButton(
                    text = "Mint Trophy NFT · ${PaymentsConfig.TROPHY_MINT_PRICE_LABEL}",
                    onClick = onMintTrophy,
                    enabled = !walletBusy,
                    modifier = Modifier.fillMaxWidth(0.72f)
                )
                Spacer(Modifier.height(8.dp))
                OutlineButton(
                    text = if (walletBusy) "Waiting for wallet…" else "Sign score with wallet",
                    onClick = onSignScore,
                    enabled = !walletBusy,
                    modifier = Modifier.fillMaxWidth(0.72f)
                )
            }
        }
    }
}

@Composable
private fun GradientButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    brush: Brush = PurpleButtonBrush,
    textColor: Color = TextPrimary
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(if (enabled) brush else DisabledButtonBrush)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(vertical = 13.dp, horizontal = 12.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            color = if (enabled) textColor else TextDim,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp,
            maxLines = 1
        )
    }
}

@Composable
private fun OutlineButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .border(
                BorderStroke(
                    1.dp,
                    if (enabled) SignatureBrush
                    else Brush.horizontalGradient(listOf(TextDim, TextDim))
                ),
                RoundedCornerShape(14.dp)
            )
            .clickable(enabled = enabled, onClick = onClick)
            .padding(vertical = 13.dp, horizontal = 12.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            color = if (enabled) TextPrimary else TextDim,
            fontWeight = FontWeight.Bold,
            fontSize = 14.sp,
            maxLines = 1
        )
    }
}
