package com.kelnine.merge48.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.kelnine.merge48.game.Board
import com.kelnine.merge48.game.Direction
import com.kelnine.merge48.game.GameViewModel
import com.kelnine.merge48.ui.theme.BoardBackground
import com.kelnine.merge48.ui.theme.EmptyCell
import com.kelnine.merge48.ui.theme.NightBackground
import com.kelnine.merge48.ui.theme.SolanaGreen
import com.kelnine.merge48.ui.theme.SolanaPurple
import com.kelnine.merge48.ui.theme.TextPrimary
import com.kelnine.merge48.ui.theme.tileColor
import com.kelnine.merge48.ui.theme.tileTextColor
import com.kelnine.merge48.wallet.WalletViewModel
import kotlin.math.abs

private const val SWIPE_THRESHOLD_PX = 60f

@Composable
fun GameScreen(
    onConnectWallet: (WalletViewModel) -> Unit,
    onSignScore: (WalletViewModel, Int) -> Unit,
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

    Scaffold(
        containerColor = NightBackground,
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Header(
                score = gameState.score,
                best = gameState.bestScore
            )

            Spacer(Modifier.height(12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                OutlinedButton(
                    onClick = { gameViewModel.newGame() },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("New Game")
                }
                if (walletState.connected) {
                    OutlinedButton(
                        onClick = { walletViewModel.disconnect() },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(WalletViewModel.shorten(walletState.address.orEmpty()))
                    }
                } else {
                    Button(
                        onClick = { onConnectWallet(walletViewModel) },
                        enabled = !walletState.inProgress,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(containerColor = SolanaPurple)
                    ) {
                        Text("Connect Wallet")
                    }
                }
            }

            Spacer(Modifier.height(16.dp))

            Box(contentAlignment = Alignment.Center) {
                GameBoard(
                    board = gameState.board,
                    onSwipe = gameViewModel::onSwipe
                )
                if (gameState.isGameOver) {
                    GameOverOverlay(
                        score = gameState.score,
                        walletConnected = walletState.connected,
                        signingInProgress = walletState.inProgress,
                        onNewGame = gameViewModel::newGame,
                        onSignScore = { onSignScore(walletViewModel, gameState.score) }
                    )
                }
            }

            Spacer(Modifier.height(16.dp))

            if (gameState.hasWon) {
                Text(
                    text = "You reached 2048! Keep merging…",
                    color = SolanaGreen,
                    fontWeight = FontWeight.Bold
                )
                Spacer(Modifier.height(8.dp))
            }

            Text(
                text = "Swipe to merge tiles. Connect your Solana wallet to sign your high score.",
                color = TextPrimary.copy(alpha = 0.6f),
                fontSize = 13.sp,
                textAlign = TextAlign.Center
            )
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
            color = TextPrimary,
            fontSize = 32.sp,
            fontWeight = FontWeight.ExtraBold,
            modifier = Modifier.weight(1f)
        )
        ScoreChip(label = "SCORE", value = score)
        Spacer(Modifier.weight(0.1f))
        ScoreChip(label = "BEST", value = best)
    }
}

@Composable
private fun ScoreChip(label: String, value: Int) {
    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(BoardBackground)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(label, color = SolanaGreen, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Text("$value", color = TextPrimary, fontSize = 18.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun GameBoard(board: Board, onSwipe: (Direction) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clip(RoundedCornerShape(16.dp))
            .background(BoardBackground)
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
            .padding(8.dp)
    ) {
        for (row in 0 until Board.SIZE) {
            Row(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            ) {
                for (col in 0 until Board.SIZE) {
                    Tile(value = board[row, col])
                }
            }
        }
    }
}

@Composable
private fun RowScope.Tile(value: Int) {
    val color by animateColorAsState(
        targetValue = if (value == 0) EmptyCell else tileColor(value),
        label = "tileColor"
    )
    Box(
        modifier = Modifier
            .weight(1f)
            .fillMaxHeight()
            .padding(4.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(color),
        contentAlignment = Alignment.Center
    ) {
        if (value != 0) {
            Text(
                text = "$value",
                color = tileTextColor(value),
                fontWeight = FontWeight.ExtraBold,
                fontSize = when {
                    value < 100 -> 28.sp
                    value < 1000 -> 24.sp
                    else -> 19.sp
                }
            )
        }
    }
}

@Composable
private fun GameOverOverlay(
    score: Int,
    walletConnected: Boolean,
    signingInProgress: Boolean,
    onNewGame: () -> Unit,
    onSignScore: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .clip(RoundedCornerShape(16.dp))
            .background(NightBackground.copy(alpha = 0.88f))
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "Game Over",
            color = TextPrimary,
            fontSize = 30.sp,
            fontWeight = FontWeight.ExtraBold
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Final score: $score",
            color = SolanaGreen,
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold
        )
        Spacer(Modifier.height(24.dp))
        Button(
            onClick = onNewGame,
            colors = ButtonDefaults.buttonColors(containerColor = SolanaPurple)
        ) {
            Text("Play Again")
        }
        if (walletConnected) {
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onSignScore,
                enabled = !signingInProgress
            ) {
                Text(if (signingInProgress) "Waiting for wallet…" else "Sign score with wallet")
            }
        }
    }
}
