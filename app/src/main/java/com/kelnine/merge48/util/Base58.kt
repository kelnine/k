package com.kelnine.merge48.util

/** Minimal Base58 encoder (Bitcoin/Solana alphabet) for display purposes. */
object Base58 {
    private const val ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

    fun encode(input: ByteArray): String {
        if (input.isEmpty()) return ""

        var leadingZeros = 0
        while (leadingZeros < input.size && input[leadingZeros].toInt() == 0) {
            leadingZeros++
        }

        // Big-number division in base 256 -> base 58
        val digits = input.copyOf()
        val encoded = StringBuilder()
        var start = leadingZeros
        while (start < digits.size) {
            var remainder = 0
            for (i in start until digits.size) {
                val value = (digits[i].toInt() and 0xFF) + remainder * 256
                digits[i] = (value / 58).toByte()
                remainder = value % 58
            }
            encoded.append(ALPHABET[remainder])
            if (digits[start].toInt() == 0) start++
        }

        repeat(leadingZeros) { encoded.append(ALPHABET[0]) }
        return encoded.reverse().toString()
    }
}
