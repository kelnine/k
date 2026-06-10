package com.kelnine.merge48.wallet

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.kelnine.merge48.util.Base58
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender
import com.solana.mobilewalletadapter.clientlib.ConnectionIdentity
import com.solana.mobilewalletadapter.clientlib.MobileWalletAdapter
import com.solana.mobilewalletadapter.clientlib.Solana
import com.solana.mobilewalletadapter.clientlib.TransactionResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class WalletUiState(
    val address: String? = null,
    val inProgress: Boolean = false,
    val statusMessage: String? = null
) {
    val connected: Boolean get() = address != null
}

class WalletViewModel : ViewModel() {

    private val walletAdapter = MobileWalletAdapter(
        connectionIdentity = ConnectionIdentity(
            identityUri = Uri.parse("https://github.com/kelnine/k"),
            iconUri = Uri.parse("icon.png"),
            identityName = "Merge48"
        )
    ).apply {
        blockchain = Solana.Mainnet
    }

    private val _state = MutableStateFlow(WalletUiState())
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
        _state.update { WalletUiState(statusMessage = "Wallet disconnected") }
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
        fun shorten(address: String): String =
            if (address.length <= 10) address
            else "${address.take(4)}…${address.takeLast(4)}"
    }
}
