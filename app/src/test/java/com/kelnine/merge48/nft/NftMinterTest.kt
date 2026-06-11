package com.kelnine.merge48.nft

import com.solana.programs.AssociatedTokenProgram
import com.solana.programs.TokenProgram
import com.solana.publickey.ProgramDerivedAddress
import com.solana.publickey.SolanaPublicKey
import com.solana.transaction.TransactionInstruction
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Golden tests: every expected value below was generated with the official
 * JS SDKs (@solana/web3.js 1.95.8 + @metaplex-foundation/mpl-token-metadata
 * 2.13.0) for identical inputs, so the Kotlin encoding is verified
 * byte-for-byte against Metaplex's reference implementation.
 */
class NftMinterTest {

    private val payer = SolanaPublicKey(ByteArray(32) { 1 })
    private val dev = SolanaPublicKey(ByteArray(32) { 2 })
    private val seed = "m48-trophy-12345"

    private val mint get() = NftMinter.deriveWithSeed(payer, seed, TokenProgram.PROGRAM_ID)

    @Test
    fun `createWithSeed address matches web3js derivation`() {
        assertEquals("GDGkB1zUqqStzkugsqzBJWe7kLXXmovkHA2t8s1U7adv", mint.base58())
    }

    @Test
    fun `metadata and edition PDAs match Metaplex derivation`() = runBlocking {
        assertEquals(
            "HCfHUU4TG88a1Z16QhbKvbEZnVFsxCCjVh8UUukuTrcM",
            NftMinter.metadataPda(mint).base58()
        )
        assertEquals(
            "6TsS8BwHDZsevs8XYEcVFByBFyuegtzkUdvNup8MERgi",
            NftMinter.editionPda(mint).base58()
        )
    }

    @Test
    fun `associated token account matches web3js derivation`() = runBlocking {
        val ata = ProgramDerivedAddress.find(
            listOf(payer.bytes, TokenProgram.PROGRAM_ID.bytes, mint.bytes),
            AssociatedTokenProgram.PROGRAM_ID
        ).getOrThrow()
        assertEquals("EUTniNWCrQVu64ZE3kfmyeUywjKy6TufXcAr2pTzhNgv", ata.base58())
    }

    @Test
    fun `createAccountWithSeed encodes like SystemProgram bincode layout`() {
        val ix = NftMinter.createAccountWithSeed(payer, mint, seed, 1_461_600)
        assertEquals("11111111111111111111111111111111", ix.programId.base58())
        assertEquals(
            "030000000101010101010101010101010101010101010101010101010101010101" +
                "01010110000000000000006d34382d74726f7068792d3132333435604d1600000" +
                "00000520000000000000006ddf6e1d765a193d9cbe146ceeb79ac1cb485ed5f5b" +
                "37913a8cf5857eff00a9",
            ix.data.toHex()
        )
        assertEquals(
            listOf(
                Triple(payer.base58(), true, true),
                Triple(mint.base58(), false, true)
            ),
            ix.accountTriples()
        )
    }

    @Test
    fun `createMetadataAccountV3 matches mpl-token-metadata bytes`() = runBlocking {
        val ix = NftMinter.createMetadataV3(
            NftMinter.metadataPda(mint), mint, payer,
            name = "Merge48 Trophy · 12345",
            symbol = "M48",
            uri = "https://raw.githubusercontent.com/kelnine/k/main/nft/trophy.json",
            creator = dev
        )
        assertEquals("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s", ix.programId.base58())
        assertEquals(
            "21170000004d6572676534382054726f70687920c2b7203132333435030000004" +
                "d34384000000068747470733a2f2f7261772e67697468756275736572636f6e74" +
                "656e742e636f6d2f6b656c6e696e652f6b2f6d61696e2f6e66742f74726f70687" +
                "92e6a736f6ef4010101000000020202020202020202020202020202020202020202" +
                "0202020202020202020202006400000100",
            ix.data.toHex()
        )
        assertEquals(
            listOf(
                Triple(NftMinter.metadataPda(mint).base58(), false, true),
                Triple(mint.base58(), false, false),
                Triple(payer.base58(), true, false),
                Triple(payer.base58(), true, true),
                Triple(payer.base58(), false, false),
                Triple("11111111111111111111111111111111", false, false)
            ),
            ix.accountTriples()
        )
    }

    @Test
    fun `createMasterEditionV3 matches mpl-token-metadata bytes`() = runBlocking {
        val ix = NftMinter.createMasterEditionV3(
            NftMinter.editionPda(mint), mint, NftMinter.metadataPda(mint), payer
        )
        assertEquals("11010000000000000000", ix.data.toHex())
        assertEquals(
            listOf(
                Triple(NftMinter.editionPda(mint).base58(), false, true),
                Triple(mint.base58(), false, true),
                Triple(payer.base58(), true, false),
                Triple(payer.base58(), true, false),
                Triple(payer.base58(), true, true),
                Triple(NftMinter.metadataPda(mint).base58(), false, true),
                Triple("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", false, false),
                Triple("11111111111111111111111111111111", false, false)
            ),
            ix.accountTriples()
        )
    }

    @Test
    fun `full mint transaction serializes with expected instruction count`() = runBlocking {
        val tx = NftMinter.buildMintTrophyTransaction(
            payer = payer,
            score = 12345,
            blockhash = "GHtXQBsoZHVnNFa9YevAzFr17DJjgHXk3ycTKD5xD3Zi",
            mintRentLamports = 1_461_600,
            feeReceiver = dev,
            feeLamports = 10_000_000
        )
        val bytes = tx.serialize()
        // 1 required signature (payer only) — the createAccountWithSeed
        // technique means no mint keypair co-signer is needed.
        assertEquals(1, bytes[0].toInt())
    }

    @Test
    fun `trophy name stays within the 32-byte on-chain limit`() {
        assertEquals(true, NftMinter.trophyName(Int.MAX_VALUE).encodeToByteArray().size <= 32)
        assertEquals(true, NftMinter.trophySeed(Int.MAX_VALUE).length <= 32)
    }

    private fun ByteArray.toHex() = joinToString("") { "%02x".format(it) }

    private fun TransactionInstruction.accountTriples() =
        accounts.map { Triple(it.publicKey.base58(), it.isSigner, it.isWritable) }
}
