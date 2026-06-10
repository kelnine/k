package com.kelnine.merge48.game

import kotlin.random.Random

enum class Direction { LEFT, RIGHT, UP, DOWN }

/**
 * Immutable 4x4 board. Cells hold tile values (2, 4, 8, ...) or 0 when empty.
 * Index layout is row-major: index = row * 4 + col.
 */
data class Board(val cells: List<Int>) {
    init {
        require(cells.size == SIZE * SIZE) { "Board must have ${SIZE * SIZE} cells" }
    }

    operator fun get(row: Int, col: Int): Int = cells[row * SIZE + col]

    val emptyIndices: List<Int> get() = cells.indices.filter { cells[it] == 0 }

    val maxTile: Int get() = cells.max()

    companion object {
        const val SIZE = 4
        fun empty() = Board(List(SIZE * SIZE) { 0 })
    }
}

data class MoveResult(val board: Board, val gainedScore: Int, val moved: Boolean)

object GameEngine {

    fun newBoard(random: Random = Random.Default): Board {
        var board = Board.empty()
        repeat(2) { board = spawnTile(board, random) }
        return board
    }

    /** Adds a random tile (90% a 2, 10% a 4) on an empty cell. */
    fun spawnTile(board: Board, random: Random = Random.Default): Board {
        val empty = board.emptyIndices
        if (empty.isEmpty()) return board
        val index = empty[random.nextInt(empty.size)]
        val value = if (random.nextInt(10) == 0) 4 else 2
        return Board(board.cells.toMutableList().also { it[index] = value })
    }

    fun move(board: Board, direction: Direction): MoveResult {
        var gained = 0
        val newCells = MutableList(Board.SIZE * Board.SIZE) { 0 }

        for (line in 0 until Board.SIZE) {
            val indices = lineIndices(line, direction)
            val (mergedLine, lineScore) = slideAndMerge(indices.map { board.cells[it] })
            gained += lineScore
            indices.forEachIndexed { i, cellIndex -> newCells[cellIndex] = mergedLine[i] }
        }

        val newBoard = Board(newCells)
        return MoveResult(newBoard, gained, newBoard != board)
    }

    fun isGameOver(board: Board): Boolean {
        if (board.emptyIndices.isNotEmpty()) return false
        for (row in 0 until Board.SIZE) {
            for (col in 0 until Board.SIZE) {
                val value = board[row, col]
                if (col + 1 < Board.SIZE && board[row, col + 1] == value) return false
                if (row + 1 < Board.SIZE && board[row + 1, col] == value) return false
            }
        }
        return true
    }

    /**
     * Cell indices of one line (row or column), ordered so that sliding
     * "towards index 0" matches the given direction.
     */
    private fun lineIndices(line: Int, direction: Direction): List<Int> = when (direction) {
        Direction.LEFT -> (0 until Board.SIZE).map { col -> line * Board.SIZE + col }
        Direction.RIGHT -> (Board.SIZE - 1 downTo 0).map { col -> line * Board.SIZE + col }
        Direction.UP -> (0 until Board.SIZE).map { row -> row * Board.SIZE + line }
        Direction.DOWN -> (Board.SIZE - 1 downTo 0).map { row -> row * Board.SIZE + line }
    }

    /** Classic 2048 rule: compact, then merge each adjacent equal pair once. */
    private fun slideAndMerge(line: List<Int>): Pair<List<Int>, Int> {
        val tiles = line.filter { it != 0 }
        val result = mutableListOf<Int>()
        var score = 0
        var i = 0
        while (i < tiles.size) {
            if (i + 1 < tiles.size && tiles[i] == tiles[i + 1]) {
                val merged = tiles[i] * 2
                result.add(merged)
                score += merged
                i += 2
            } else {
                result.add(tiles[i])
                i++
            }
        }
        while (result.size < Board.SIZE) result.add(0)
        return result to score
    }
}
