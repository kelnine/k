package com.kelnine.merge48.payments

/**
 * Monetization configuration.
 *
 * IMPORTANT: set [DEV_WALLET_ADDRESS] to YOUR wallet's public address before
 * shipping — this is where all payments and tips are sent. While it is blank,
 * the store buttons show a setup reminder instead of charging anyone.
 */
object PaymentsConfig {
    // TODO: your Solana wallet address (base58), e.g. from Phantom/Solflare.
    const val DEV_WALLET_ADDRESS = ""

    // Public RPC is fine for testing; use a dedicated endpoint (e.g. Helius,
    // QuickNode, Triton free tiers) for production traffic.
    const val RPC_URL = "https://api.mainnet-beta.solana.com"
}

private const val LAMPORTS_PER_SOL = 1_000_000_000L

enum class Product(
    val displayName: String,
    val lamports: Long,
    val priceLabel: String
) {
    /** Consumable: clears the 8 smallest tiles so a lost game can continue. */
    SECOND_CHANCE("Second Chance", (0.005 * LAMPORTS_PER_SOL).toLong(), "0.005 SOL"),

    /** One-time unlock: enables the Undo button forever. */
    PRO_UNLOCK("Pro Unlock", (0.05 * LAMPORTS_PER_SOL).toLong(), "0.05 SOL"),

    /** Just a thank-you to the developer. */
    TIP("Tip the Dev", (0.01 * LAMPORTS_PER_SOL).toLong(), "0.01 SOL")
}
