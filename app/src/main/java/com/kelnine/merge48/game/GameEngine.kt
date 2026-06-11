package com.kelnine.merge48.game

import java.util.concurrent.atomic.AtomicInteger
import kotlin.random.Random

enum class Direction { LEFT, RIGHT, UP, DOWN }

/**
 * A tile with a stable identity. Ids survive moves so the UI can animate
 * each tile sliding from its old cell to its new one; a merge keeps the id
 * of the tile that travelled, making the slide-and-pop visible.
 */
data class Tile(val id: Int, val value: Int, val row: Int, val col: Int)

data class TileBoard(val tiles: List<Tile>) {

    /** Row-major 16-cell snapshot (0 = empty), convenient for logic/tests. */
    fun grid(): List<Int> {
        val cells = MutableList(SIZE * SIZE) { 0 }
        tiles.forEach { cells[it.row * SIZE + it.col] = it.value }
        return cells
    }

    operator fun get(row: Int, col: Int): Int =
        tiles.firstOrNull { it.row == row && it.col == col }?.value ?: 0

    val emptyCells: List<Pair<Int, Int>>
        get() {
            val occupied = tiles.map { it.row to it.col }.toSet()
            return (0 until SIZE).flatMap { row ->
                (0 until SIZE).map { col -> row to col }
            }.filter { it !in occupied }
        }

    val maxTile: Int get() = tiles.maxOfOrNull { it.value } ?: 0

    companion object {
        const val SIZE = 4
        fun empty() = TileBoard(emptyList())
    }
}

data class MoveOutcome(
    val board: TileBoard,
    val gainedScore: Int,
    val moved: Boolean,
    /** Ids of tiles that are the result of a merge this move (for pop FX). */
    val mergedIds: Set<Int>
)

object GameEngine {

    private val idCounter = AtomicInteger(0)
    private fun nextId() = idCounter.incrementAndGet()

    fun newBoard(random: Random = Random.Default): TileBoard {
        var board = TileBoard.empty()
        repeat(2) { board = spawnTile(board, random) }
        return board
    }

    /** Adds a random tile (90% a 2, 10% a 4) on an empty cell. */
    fun spawnTile(board: TileBoard, random: Random = Random.Default): TileBoard {
        val empty = board.emptyCells
        if (empty.isEmpty()) return board
        val (row, col) = empty[random.nextInt(empty.size)]
        val value = if (random.nextInt(10) == 0) 4 else 2
        return TileBoard(board.tiles + Tile(nextId(), value, row, col))
    }

    fun move(board: TileBoard, direction: Direction): MoveOutcome {
        var gained = 0
        var moved = false
        val mergedIds = mutableSetOf<Int>()
        val newTiles = mutableListOf<Tile>()

        for (line in 0 until TileBoard.SIZE) {
            val lineTiles = tilesInLine(board, line, direction)
            var slot = 0
            var i = 0
            while (i < lineTiles.size) {
                val current = lineTiles[i]
                val partner = lineTiles.getOrNull(i + 1)
                val (row, col) = cellAt(line, slot, direction)
                if (partner != null && partner.value == current.value) {
                    // Merge: the trailing tile's id survives so the UI shows
                    // it sliding onto the leading tile before popping.
                    val merged = Tile(partner.id, current.value * 2, row, col)
                    newTiles += merged
                    mergedIds += merged.id
                    gained += merged.value
                    moved = true
                    i += 2
                } else {
                    if (row != current.row || col != current.col) moved = true
                    newTiles += current.copy(row = row, col = col)
                    i++
                }
                slot++
            }
        }

        return MoveOutcome(TileBoard(newTiles), gained, moved, mergedIds)
    }

    fun isGameOver(board: TileBoard): Boolean {
        if (board.emptyCells.isNotEmpty()) return false
        for (row in 0 until TileBoard.SIZE) {
            for (col in 0 until TileBoard.SIZE) {
                val value = board[row, col]
                if (col + 1 < TileBoard.SIZE && board[row, col + 1] == value) return false
                if (row + 1 < TileBoard.SIZE && board[row + 1, col] == value) return false
            }
        }
        return true
    }

    /**
     * Paid "Second Chance": clears the smallest tiles from a locked board so
     * the run can continue, keeping the player's big merges intact.
     */
    fun secondChance(board: TileBoard, tilesToClear: Int = 8): TileBoard =
        TileBoard(board.tiles.sortedBy { it.value }.drop(tilesToClear))

    /** Tiles of one row/column ordered leading-edge first for [direction]. */
    private fun tilesInLine(board: TileBoard, line: Int, direction: Direction): List<Tile> =
        when (direction) {
            Direction.LEFT -> board.tiles.filter { it.row == line }.sortedBy { it.col }
            Direction.RIGHT -> board.tiles.filter { it.row == line }.sortedByDescending { it.col }
            Direction.UP -> board.tiles.filter { it.col == line }.sortedBy { it.row }
            Direction.DOWN -> board.tiles.filter { it.col == line }.sortedByDescending { it.row }
        }

    /** The (row, col) of the Nth slot from the leading edge of a line. */
    private fun cellAt(line: Int, slot: Int, direction: Direction): Pair<Int, Int> =
        when (direction) {
            Direction.LEFT -> line to slot
            Direction.RIGHT -> line to (TileBoard.SIZE - 1 - slot)
            Direction.UP -> slot to line
            Direction.DOWN -> (TileBoard.SIZE - 1 - slot) to line
        }
}
