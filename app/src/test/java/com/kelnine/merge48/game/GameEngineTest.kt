package com.kelnine.merge48.game

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class GameEngineTest {

    private fun board(vararg cells: Int) = Board(cells.toList())

    @Test
    fun `new board has exactly two tiles`() {
        val board = GameEngine.newBoard(Random(42))
        assertEquals(2, board.cells.count { it != 0 })
    }

    @Test
    fun `move left compacts and merges a single pair once`() {
        val before = board(
            2, 2, 4, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        val result = GameEngine.move(before, Direction.LEFT)
        assertEquals(listOf(4, 4, 0, 0), result.board.cells.take(4))
        assertEquals(4, result.gainedScore)
        assertTrue(result.moved)
    }

    @Test
    fun `four equal tiles merge into two pairs not one`() {
        val before = board(
            2, 2, 2, 2,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        val result = GameEngine.move(before, Direction.LEFT)
        assertEquals(listOf(4, 4, 0, 0), result.board.cells.take(4))
        assertEquals(8, result.gainedScore)
    }

    @Test
    fun `move right merges towards the right edge`() {
        val before = board(
            0, 2, 0, 2,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        val result = GameEngine.move(before, Direction.RIGHT)
        assertEquals(listOf(0, 0, 0, 4), result.board.cells.take(4))
    }

    @Test
    fun `move up merges columns`() {
        val before = board(
            2, 0, 0, 0,
            2, 0, 0, 0,
            4, 0, 0, 0,
            0, 0, 0, 0
        )
        val result = GameEngine.move(before, Direction.UP)
        assertEquals(4, result.board[0, 0])
        assertEquals(4, result.board[1, 0])
        assertEquals(0, result.board[2, 0])
    }

    @Test
    fun `move down merges towards the bottom edge`() {
        val before = board(
            0, 4, 0, 0,
            0, 0, 0, 0,
            0, 4, 0, 0,
            0, 2, 0, 0
        )
        val result = GameEngine.move(before, Direction.DOWN)
        assertEquals(2, result.board[3, 1])
        assertEquals(8, result.board[2, 1])
    }

    @Test
    fun `no-op move reports moved=false`() {
        val before = board(
            2, 4, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        val result = GameEngine.move(before, Direction.LEFT)
        assertFalse(result.moved)
        assertEquals(0, result.gainedScore)
    }

    @Test
    fun `full board with no adjacent equals is game over`() {
        val board = board(
            2, 4, 2, 4,
            4, 2, 4, 2,
            2, 4, 2, 4,
            4, 2, 4, 2
        )
        assertTrue(GameEngine.isGameOver(board))
    }

    @Test
    fun `full board with an adjacent pair is not game over`() {
        val board = board(
            2, 2, 4, 8,
            4, 8, 16, 32,
            8, 16, 32, 64,
            16, 32, 64, 128
        )
        assertFalse(GameEngine.isGameOver(board))
    }

    @Test
    fun `spawn fills exactly one empty cell with 2 or 4`() {
        val before = Board.empty()
        val after = GameEngine.spawnTile(before, Random(7))
        val nonZero = after.cells.filter { it != 0 }
        assertEquals(1, nonZero.size)
        assertTrue(nonZero.first() == 2 || nonZero.first() == 4)
    }
}
