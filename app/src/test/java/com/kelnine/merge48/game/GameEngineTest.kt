package com.kelnine.merge48.game

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class GameEngineTest {

    /** Builds a board from a row-major grid; ids are the cell indices. */
    private fun board(vararg cells: Int): TileBoard {
        require(cells.size == 16)
        return TileBoard(
            cells.withIndex()
                .filter { it.value != 0 }
                .map { (i, v) -> Tile(id = 1000 + i, value = v, row = i / 4, col = i % 4) }
        )
    }

    @Test
    fun `new board has exactly two tiles`() {
        val board = GameEngine.newBoard(Random(42))
        assertEquals(2, board.tiles.size)
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
        assertEquals(listOf(4, 4, 0, 0), result.board.grid().take(4))
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
        assertEquals(listOf(4, 4, 0, 0), result.board.grid().take(4))
        assertEquals(8, result.gainedScore)
        assertEquals(2, result.mergedIds.size)
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
        assertEquals(listOf(0, 0, 0, 4), result.board.grid().take(4))
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
        assertTrue(result.mergedIds.isEmpty())
    }

    @Test
    fun `sliding tiles keep their identity for animation`() {
        val before = board(
            0, 0, 0, 2,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        val originalId = before.tiles.single().id
        val result = GameEngine.move(before, Direction.LEFT)
        val after = result.board.tiles.single()
        assertEquals(originalId, after.id)
        assertEquals(0, after.col)
        assertEquals(0, after.row)
    }

    @Test
    fun `merge keeps the travelling tile's id and flags it merged`() {
        val before = board(
            2, 0, 0, 2,
            0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        // LEFT: leading tile is at col 0, trailing tile at col 3 travels.
        val travellingId = before.tiles.first { it.col == 3 }.id
        val result = GameEngine.move(before, Direction.LEFT)
        val merged = result.board.tiles.single()
        assertEquals(4, merged.value)
        assertEquals(travellingId, merged.id)
        assertEquals(setOf(travellingId), result.mergedIds)
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
    fun `second chance clears the eight smallest tiles`() {
        val locked = board(
            2, 4, 2, 4,
            8, 16, 8, 16,
            32, 64, 32, 64,
            128, 256, 128, 256
        )
        val revived = GameEngine.secondChance(locked)
        assertEquals(8, revived.tiles.size)
        // The big tiles survive…
        assertTrue(revived.grid().containsAll(listOf(32, 64, 128, 256)))
        // …and every small tile (2s, 4s, 8s, 16s) is gone.
        assertTrue(revived.tiles.none { it.value in listOf(2, 4, 8, 16) })
        assertFalse(GameEngine.isGameOver(revived))
    }

    @Test
    fun `spawn fills exactly one empty cell with 2 or 4`() {
        val before = TileBoard.empty()
        val after = GameEngine.spawnTile(before, Random(7))
        assertEquals(1, after.tiles.size)
        assertTrue(after.tiles.single().value == 2 || after.tiles.single().value == 4)
    }

    @Test
    fun `spawned tiles get unique ids`() {
        var board = TileBoard.empty()
        repeat(10) { board = GameEngine.spawnTile(board) }
        assertEquals(10, board.tiles.map { it.id }.distinct().size)
    }
}
