package com.kelnine.merge48.wallet

import android.app.Application
import android.content.Context
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.kelnine.merge48.payments.PaymentsConfig
import com.kelnine.merge48.payments.Product
import com.kelnine.merge48.payments.SolanaRpc
import com.kelnine.merge48.util.Base58
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.solana.mobilewalletadapter.clientlib.ConnectionIdentity
import com.solana.mobilewalletadapter.clientlib.MobileWalletAdapter
import com.solana.mobilewalletadapter.clientlib.Solana
import com.solana.mobilewalletadapter.clientlib.TransactionResult
import com.solana.programs.SystemProgram
import com.solana.publickey.SolanaPublicKey
import com.solana.transaction.Message
import com.solana.transaction.Transaction
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class WalletUiState(
    val address: String? = null,
    val inProgress: Boolean = false,
    val statusMessage: String? = null,
    val proUnlocked: Boolean = false
) {
    val connected: Boolean get() = address != null
}

class WalletViewModel(application: Application) : AndroidViewModel(application) {

    private val prefs =
        application.getSharedPreferences("merge48_wallet", Context.MODE_PRIVATE)

    private val walletAdapter = MobileWalletAdapter(
        connectionIdentity = ConnectionIdentity(
            identityUri = Uri.parse("https://github.com/kelnine/k"),
            iconUri = Uri.parse("icon.png"),
            identityName = "Merge48"
        )
    ).apply {
        blockchain = Solana.Mainnet
    }

    private val _state = MutableStateFlow(
        WalletUiState(proUnlocked = prefs.getBoolean(KEY_PRO_UNLOCKED, false))
    )
    val state: StateFlow<WalletUiState> = _state.asStateFlow()

    fun connect(sender: ActivityResultSender) {
        if (_state.value.inProgress) return
        viewModelScope.launch {
            _state.update { it.copy(inProgress = true, statusMessage = null) }
            when (val result = walletAdapter.connect(sender)) {
                is TransactionResult.Success -> {
                    val publicKey = result.authResult.accounts.firstOrNull()?.publicKey
                    val address = publicKey?.let { Base58.encode(it) }
                    _state.update {
                        it.copy(
                            address = address,
                            inProgress = false,
                            statusMessage = address?.let { a ->
                                "Connected: ${shorten(a)}"
                            } ?: "Wallet returned no account"
                        )
                    }
                }
                is TransactionResult.NoWalletFound -> _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "No MWA-compatible wallet found on this device"
                    )
                }
                is TransactionResult.Failure -> _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "Connection failed: ${result.e.message ?: result.message}"
                    )
                }
            }
        }
    }

    fun disconnect() {
        walletAdapter.authToken = null
        _state.update {
            WalletUiState(
                statusMessage = "Wallet disconnected",
                proUnlocked = it.proUnlocked
            )
        }
    }

    /**
     * Sends [Product.lamports] SOL from the player's wallet to the developer
     * wallet via a System Program transfer, signed and submitted by the
     * user's wallet app. Runs [onPurchased] once the wallet returns a
     * transaction signature.
     */
    fun purchase(sender: ActivityResultSender, product: Product, onPurchased: () -> Unit = {}) {
        if (_state.value.inProgress) return
        if (PaymentsConfig.DEV_WALLET_ADDRESS.isBlank()) {
            _state.update {
                it.copy(statusMessage = "Store not configured yet (set DEV_WALLET_ADDRESS)")
            }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(inProgress = true, statusMessage = null) }

            val blockhash = try {
                SolanaRpc.latestBlockhash(PaymentsConfig.RPC_URL)
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "Network error fetching blockhash: ${e.message}"
                    )
                }
                return@launch
            }

            val result = walletAdapter.transact(sender) { authResult ->
                val payer = SolanaPublicKey(authResult.accounts.first().publicKey)
                val transferInstruction = SystemProgram.transfer(
                    payer,
                    SolanaPublicKey.from(PaymentsConfig.DEV_WALLET_ADDRESS),
                    product.lamports
                )
                val message = Message.Builder()
                    .addInstruction(transferInstruction)
                    .setRecentBlockhash(blockhash)
                    .build()
                signAndSendTransactions(arrayOf(Transaction(message).serialize()))
            }

            when (result) {
                is TransactionResult.Success -> {
                    val signature = result.payload.signatures.firstOrNull()
                    if (signature != null) {
                        if (product == Product.PRO_UNLOCK) {
                            prefs.edit().putBoolean(KEY_PRO_UNLOCKED, true).apply()
                        }
                        _state.update {
                            it.copy(
                                inProgress = false,
                                proUnlocked = it.proUnlocked || product == Product.PRO_UNLOCK,
                                statusMessage =
                                    "${product.displayName} ✓ tx ${shorten(Base58.encode(signature))}"
                            )
                        }
                        onPurchased()
                    } else {
                        _state.update {
                            it.copy(
                                inProgress = false,
                                statusMessage = "Wallet returned no transaction signature"
                            )
                        }
                    }
                }
                is TransactionResult.NoWalletFound -> _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "No MWA-compatible wallet found on this device"
                    )
                }
                is TransactionResult.Failure -> _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "Payment failed: ${result.e.message ?: result.message}"
                    )
                }
            }
        }
    }

    /**
     * Asks the connected wallet to sign a message attesting the player's
     * score, proving ownership of the address at that moment.
     */
    fun signScore(sender: ActivityResultSender, score: Int) {
        if (_state.value.inProgress) return
        viewModelScope.launch {
            _state.update { it.copy(inProgress = true, statusMessage = null) }
            val message =
                "Merge48 score attestation: $score points, ts=${System.currentTimeMillis()}"
            val result = walletAdapter.transact(sender) { authResult ->
                val account = authResult.accounts.first().publicKey
                signMessagesDetached(
                    arrayOf(message.encodeToByteArray()),
                    arrayOf(account)
                )
            }
            when (result) {
                is TransactionResult.Success -> {
                    val signature = result.payload.messages
                        .firstOrNull()?.signatures?.firstOrNull()
                    _state.update {
                        it.copy(
                            inProgress = false,
                            statusMessage = signature?.let { sig ->
                                "Score signed! Signature ${shorten(Base58.encode(sig))}"
                            } ?: "Wallet returned no signature"
                        )
                    }
                }
                is TransactionResult.NoWalletFound -> _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "No MWA-compatible wallet found on this device"
                    )
                }
                is TransactionResult.Failure -> _state.update {
                    it.copy(
                        inProgress = false,
                        statusMessage = "Signing failed: ${result.e.message ?: result.message}"
                    )
                }
            }
        }
    }

    fun consumeStatusMessage() {
        _state.update { it.copy(statusMessage = null) }
    }

    companion object {
        private const val KEY_PRO_UNLOCKED = "pro_unlocked"

        fun shorten(address: String): String =
            if (address.length <= 10) address
            else "${address.take(4)}…${address.takeLast(4)}"
    }
}
