package com.kelnine.merge48.game

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

data class GameUiState(
    val board: Board = Board.empty(),
    val score: Int = 0,
    val bestScore: Int = 0,
    val isGameOver: Boolean = false,
    val hasWon: Boolean = false
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

    fun newGame() {
        _state.update {
            it.copy(
                board = GameEngine.newBoard(),
                score = 0,
                isGameOver = false,
                hasWon = false
            )
        }
    }

    fun onSwipe(direction: Direction) {
        val current = _state.value
        if (current.isGameOver) return

        val result = GameEngine.move(current.board, direction)
        if (!result.moved) return

        val boardWithSpawn = GameEngine.spawnTile(result.board)
        val newScore = current.score + result.gainedScore
        val newBest = maxOf(newScore, current.bestScore)
        if (newBest > current.bestScore) {
            prefs.edit().putInt(KEY_BEST_SCORE, newBest).apply()
        }

        _state.update {
            it.copy(
                board = boardWithSpawn,
                score = newScore,
                bestScore = newBest,
                isGameOver = GameEngine.isGameOver(boardWithSpawn),
                hasWon = it.hasWon || boardWithSpawn.maxTile >= 2048
            )
        }
    }

    private companion object {
        const val KEY_BEST_SCORE = "best_score"
    }
}
