package com.kelnine.merge48.nft

import com.kelnine.merge48.payments.PaymentsConfig
import com.solana.programs.AssociatedTokenProgram
import com.solana.programs.SystemProgram
import com.solana.programs.TokenProgram
import com.solana.publickey.ProgramDerivedAddress
import com.solana.publickey.SolanaPublicKey
import com.solana.transaction.AccountMeta
import com.solana.transaction.Message
import com.solana.transaction.Transaction
import com.solana.transaction.TransactionInstruction
import java.io.ByteArrayOutputStream
import java.security.MessageDigest

/**
 * Client-side Metaplex NFT minting, no backend required.
 *
 * Normally creating a mint account needs the new account's keypair as a
 * co-signer, which is awkward with Mobile Wallet Adapter. We avoid that with
 * `SystemProgram.createAccountWithSeed`: the mint address is derived from the
 * player's own key plus a unique seed, so the ENTIRE transaction is signed by
 * the player's wallet alone via signAndSendTransactions.
 *
 * The transaction mints a 1-of-1 NFT (decimals 0, supply 1, master edition
 * locks supply) titled with the player's score, optionally prepending a mint
 * fee transfer to the developer wallet.
 */
object NftMinter {

    val TOKEN_METADATA_PROGRAM_ID: SolanaPublicKey =
        SolanaPublicKey.from("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

    /** Size of an SPL Token mint account; rent for it is fetched via RPC. */
    const val MINT_ACCOUNT_SIZE = 82L

    const val NFT_SYMBOL = "M48"

    /** 5% royalty on secondary sales, paid to the creator (your wallet). */
    private const val ROYALTY_BASIS_POINTS = 500

    fun trophyName(score: Int) = "Merge48 Trophy · $score"

    /** Unique-per-mint seed; max 32 chars per System Program rules. */
    fun trophySeed(score: Int) =
        "m48-${System.currentTimeMillis().toString(36)}-$score".take(32)

    /** PublicKey.createWithSeed: sha256(base || seed || ownerProgram). */
    fun deriveWithSeed(
        base: SolanaPublicKey,
        seed: String,
        ownerProgram: SolanaPublicKey
    ): SolanaPublicKey {
        val digest = MessageDigest.getInstance("SHA-256")
        digest.update(base.bytes)
        digest.update(seed.encodeToByteArray())
        digest.update(ownerProgram.bytes)
        return SolanaPublicKey(digest.digest())
    }

    suspend fun buildMintTrophyTransaction(
        payer: SolanaPublicKey,
        score: Int,
        blockhash: String,
        mintRentLamports: Long,
        feeReceiver: SolanaPublicKey?,
        feeLamports: Long
    ): Transaction {
        val seed = trophySeed(score)
        val mint = deriveWithSeed(payer, seed, TokenProgram.PROGRAM_ID)
        val ata = ProgramDerivedAddress.find(
            listOf(payer.bytes, TokenProgram.PROGRAM_ID.bytes, mint.bytes),
            AssociatedTokenProgram.PROGRAM_ID
        ).getOrThrow()
        val metadataPda = metadataPda(mint)
        val editionPda = editionPda(mint)

        val instructions = buildList {
            if (feeReceiver != null && feeLamports > 0) {
                add(SystemProgram.transfer(payer, feeReceiver, feeLamports))
            }
            add(createAccountWithSeed(payer, mint, seed, mintRentLamports))
            add(TokenProgram.initializeMint(mint, 0, payer, payer))
            add(
                AssociatedTokenProgram.createAssociatedTokenAccount(
                    mint = mint,
                    associatedAccount = ata,
                    owner = payer,
                    payer = payer
                )
            )
            add(TokenProgram.mintTo(mint, ata, payer, 1))
            add(
                createMetadataV3(
                    metadataPda, mint, payer,
                    name = trophyName(score),
                    symbol = NFT_SYMBOL,
                    uri = PaymentsConfig.NFT_METADATA_URI,
                    creator = feeReceiver
                )
            )
            add(createMasterEditionV3(editionPda, mint, metadataPda, payer))
        }

        val message = Message.Builder()
            .apply { instructions.forEach { addInstruction(it) } }
            .setRecentBlockhash(blockhash)
            .build()
        return Transaction(message)
    }

    suspend fun metadataPda(mint: SolanaPublicKey): SolanaPublicKey =
        ProgramDerivedAddress.find(
            listOf("metadata".encodeToByteArray(), TOKEN_METADATA_PROGRAM_ID.bytes, mint.bytes),
            TOKEN_METADATA_PROGRAM_ID
        ).getOrThrow()

    suspend fun editionPda(mint: SolanaPublicKey): SolanaPublicKey =
        ProgramDerivedAddress.find(
            listOf(
                "metadata".encodeToByteArray(),
                TOKEN_METADATA_PROGRAM_ID.bytes,
                mint.bytes,
                "edition".encodeToByteArray()
            ),
            TOKEN_METADATA_PROGRAM_ID
        ).getOrThrow()

    /**
     * SystemProgram instruction 3 (CreateAccountWithSeed) with base == payer.
     * Note the bincode layout: the seed length is a u64, unlike Borsh strings.
     */
    fun createAccountWithSeed(
        payer: SolanaPublicKey,
        newAccount: SolanaPublicKey,
        seed: String,
        lamports: Long,
        space: Long = MINT_ACCOUNT_SIZE,
        ownerProgram: SolanaPublicKey = TokenProgram.PROGRAM_ID
    ): TransactionInstruction {
        val seedBytes = seed.encodeToByteArray()
        val data = LittleEndianWriter()
            .u32(3)
            .bytes(payer.bytes)
            .u64(seedBytes.size.toLong())
            .bytes(seedBytes)
            .u64(lamports)
            .u64(space)
            .bytes(ownerProgram.bytes)
            .toByteArray()
        return TransactionInstruction(
            SystemProgram.PROGRAM_ID,
            listOf(
                AccountMeta(payer, true, true),
                AccountMeta(newAccount, false, true)
            ),
            data
        )
    }

    /** Metaplex Token Metadata: CreateMetadataAccountV3 (discriminator 33). */
    fun createMetadataV3(
        metadataPda: SolanaPublicKey,
        mint: SolanaPublicKey,
        payer: SolanaPublicKey,
        name: String,
        symbol: String,
        uri: String,
        creator: SolanaPublicKey?
    ): TransactionInstruction {
        val data = LittleEndianWriter().apply {
            u8(33)
            borshString(name)
            borshString(symbol)
            borshString(uri)
            u16(ROYALTY_BASIS_POINTS)
            if (creator != null) {
                u8(1) // Option::Some
                u32(1) // Vec length
                bytes(creator.bytes)
                u8(0) // verified: false (creator isn't signing)
                u8(100) // share: 100%
            } else {
                u8(0) // Option::None
            }
            u8(0) // collection: None
            u8(0) // uses: None
            u8(1) // isMutable: true
            u8(0) // collectionDetails: None
        }.toByteArray()
        return TransactionInstruction(
            TOKEN_METADATA_PROGRAM_ID,
            listOf(
                AccountMeta(metadataPda, false, true),
                AccountMeta(mint, false, false),
                AccountMeta(payer, true, false), // mint authority
                AccountMeta(payer, true, true), // payer
                AccountMeta(payer, false, false), // update authority
                AccountMeta(SystemProgram.PROGRAM_ID, false, false)
            ),
            data
        )
    }

    /** Metaplex Token Metadata: CreateMasterEditionV3 (discriminator 17). */
    fun createMasterEditionV3(
        editionPda: SolanaPublicKey,
        mint: SolanaPublicKey,
        metadataPda: SolanaPublicKey,
        payer: SolanaPublicKey
    ): TransactionInstruction {
        val data = LittleEndianWriter().apply {
            u8(17)
            u8(1) // Option::Some
            u64(0) // maxSupply 0: supply locked at the single minted token
        }.toByteArray()
        return TransactionInstruction(
            TOKEN_METADATA_PROGRAM_ID,
            listOf(
                AccountMeta(editionPda, false, true),
                AccountMeta(mint, false, true),
                AccountMeta(payer, true, false), // update authority
                AccountMeta(payer, true, false), // mint authority
                AccountMeta(payer, true, true), // payer
                AccountMeta(metadataPda, false, true),
                AccountMeta(TokenProgram.PROGRAM_ID, false, false),
                AccountMeta(SystemProgram.PROGRAM_ID, false, false)
            ),
            data
        )
    }

    private class LittleEndianWriter {
        private val out = ByteArrayOutputStream()

        fun u8(v: Int) = apply { out.write(v and 0xFF) }
        fun u16(v: Int) = apply {
            out.write(v and 0xFF)
            out.write((v shr 8) and 0xFF)
        }

        fun u32(v: Int) = apply { repeat(4) { out.write((v shr (8 * it)) and 0xFF) } }
        fun u64(v: Long) = apply { repeat(8) { out.write(((v shr (8 * it)) and 0xFF).toInt()) } }
        fun bytes(b: ByteArray) = apply { out.write(b) }
        fun borshString(s: String) = apply {
            val b = s.encodeToByteArray()
            u32(b.size)
            bytes(b)
        }

        fun toByteArray(): ByteArray = out.toByteArray()
    }
}
