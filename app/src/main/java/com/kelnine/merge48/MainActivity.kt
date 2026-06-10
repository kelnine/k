package com.kelnine.merge48

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.kelnine.merge48.ui.GameScreen
import com.kelnine.merge48.ui.theme.Merge48Theme
import com.solana.mobilewalletadapter.clientlib.ActivityResultSender

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Must be created before the activity reaches RESUMED state.
        val activityResultSender = ActivityResultSender(this)

        setContent {
            Merge48Theme {
                GameScreen(
                    onConnectWallet = { walletViewModel ->
                        walletViewModel.connect(activityResultSender)
                    },
                    onSignScore = { walletViewModel, score ->
                        walletViewModel.signScore(activityResultSender, score)
                    }
                )
            }
        }
    }
}
