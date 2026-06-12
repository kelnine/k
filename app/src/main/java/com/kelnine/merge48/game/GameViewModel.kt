package com.kelnine.merge48.game

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

data class GameUiState(
    val board: TileBoard = TileBoard.empty(),
    val score: Int = 0,
    val bestScore: Int = 0,
    val isGameOver: Boolean = false,
    val hasWon: Boolean = false,
    val canUndo: Boolean = false,
    /** Cells where merges just landed, for particle bursts. */
    val mergedCells: List<Pair<Int, Int>> = emptyList(),
    /** Monotonic id so the UI can replay a burst per move. */
    val mergeBurstId: Int = 0
)

class GameViewModel(application: Application) : AndroidViewModel(application) {

    private val prefs =
        application.getSharedPreferences("merge48", Context.MODE_PRIVATE)

    private val _state = MutableStateFlow(
        GameUiState(
            board = GameEngine.newBoard(),
            bestScore = prefs.getInt(KEY_BEST_SCORE, 0)
        )
    )
    val state: StateFlow<GameUiState> = _state.asStateFlow()

    // Board and score before the most recent move, for the Pro undo feature.
    private var undoSnapshot: Pair<TileBoard, Int>? = null

    fun newGame() {
        undoSnapshot = null
        _state.update {
            it.copy(
                board = GameEngine.newBoard(),
                score = 0,
                isGameOver = false,
                hasWon = false,
                canUndo = false
            )
        }
    }

    fun onSwipe(direction: Direction) {
        val current = _state.value
        if (current.isGameOver) return

        val result = GameEngine.move(current.board, direction)
        if (!result.moved) return

        undoSnapshot = current.board to current.score
        val boardWithSpawn = GameEngine.spawnTile(result.board)
        val newScore = current.score + result.gainedScore
        val newBest = maxOf(newScore, current.bestScore)
        if (newBest > current.bestScore) {
            prefs.edit().putInt(KEY_BEST_SCORE, newBest).apply()
        }

        val mergedCells = result.board.tiles
            .filter { it.id in result.mergedIds }
            .map { it.row to it.col }

        _state.update {
            it.copy(
                board = boardWithSpawn,
                score = newScore,
                bestScore = newBest,
                isGameOver = GameEngine.isGameOver(boardWithSpawn),
                hasWon = it.hasWon || boardWithSpawn.maxTile >= 2048,
                canUndo = true,
                mergedCells = mergedCells,
                mergeBurstId = if (mergedCells.isEmpty()) it.mergeBurstId
                else it.mergeBurstId + 1
            )
        }
    }

    /** Pro feature: reverts the last move (one step). */
    fun undo() {
        val (board, score) = undoSnapshot ?: return
        undoSnapshot = null
        _state.update {
            it.copy(
                board = board,
                score = score,
                isGameOver = false,
                canUndo = false
            )
        }
    }

    /** Applied after a successful Second Chance purchase. */
    fun applySecondChance() {
        undoSnapshot = null
        _state.update {
            it.copy(
                board = GameEngine.secondChance(it.board),
                isGameOver = false,
                canUndo = false
            )
        }
    }

    private companion object {
        const val KEY_BEST_SCORE = "best_score"
    }
}
