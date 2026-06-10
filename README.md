# Merge48 — a 2048 merge game for the Solana dApp Store

Merge48 is a native Android puzzle game built for **Solana Seeker** (and Saga).
Swipe to slide tiles; equal tiles merge. Chase the 2048 tile, then connect your
Solana wallet via **Mobile Wallet Adapter** and cryptographically sign your
high score.

- **Stack:** Kotlin · Jetpack Compose · Mobile Wallet Adapter (`clientlib-ktx` 2.1.1)
- **Package:** `com.kelnine.merge48` · minSdk 26 · targetSdk 35
- **No backend, no ads, no tracking** — scores live on-device; wallet signing is local via MWA.

| | |
|---|---|
| Icon | `dapp-store/media/icon-512.png` |
| Banner | `dapp-store/media/banner.png` |
| Screenshots | `dapp-store/media/screenshot-{1..4}.png` *(mock renders — replace with real captures before submitting)* |

## Project layout

```
app/src/main/java/com/kelnine/merge48/
├── MainActivity.kt            # ActivityResultSender + Compose entry point
├── game/GameEngine.kt         # Pure 2048 logic (unit-tested)
├── game/GameViewModel.kt      # Game state + best-score persistence
├── wallet/WalletViewModel.kt  # MWA connect / disconnect / sign-score
├── ui/GameScreen.kt           # Board, swipe gestures, game-over overlay
└── ui/theme/Theme.kt          # Solana-flavored dark theme & tile palette
dapp-store/                    # dApp Store publishing config + media assets
```

## Build

Requires JDK 17+ and the Android SDK (Android Studio is easiest).

```bash
./gradlew :app:testDebugUnitTest   # run game-logic unit tests
./gradlew :app:assembleDebug       # debug APK
./gradlew :app:assembleRelease     # release APK (set up signing first, see below)
```

Install on a device/emulator: `adb install app/build/outputs/apk/debug/app-debug.apk`

To test wallet flows without real funds, install Solana Mobile's
[fakewallet](https://github.com/solana-mobile/mobile-wallet-adapter/tree/main/android/fakewallet)
app, or use Phantom/Solflare. The wallet adapter targets **mainnet**
(change `Solana.Mainnet` to `Solana.Devnet` in `WalletViewModel.kt` for devnet).

### Release signing

The dApp Store requires a signed release APK. Generate a keystore once and
**keep it safe** — every future update must be signed with the same key:

```bash
keytool -genkeypair -v -keystore merge48-release.jks -keyalg RSA \
  -keysize 2048 -validity 10000 -alias merge48
```

Then add a `signingConfig` to `app/build.gradle.kts` (or sign via Android
Studio's *Build → Generate Signed App Bundle / APK*, choosing **APK** —
the dApp Store takes APKs, not AABs).

## Publish to the Solana dApp Store

Full docs: <https://docs.solanamobile.com/dapp-publishing/intro>

1. **Prep assets** — replace the placeholder screenshots in
   `dapp-store/media/` with real device captures (1080px+ wide), and fill in
   the `publisher` section of `dapp-store/config.yaml`.
2. **Copy the APK** to `dapp-store/files/app-release.apk`.
3. **Mint the on-chain entries** (the CLI fills the empty `address` fields;
   fees are paid in SOL from your publisher keypair):

   ```bash
   cd dapp-store
   npx @solana-mobile/dapp-store-cli init
   npx @solana-mobile/dapp-store-cli create publisher -k <keypair.json>
   npx @solana-mobile/dapp-store-cli create app -k <keypair.json>
   npx @solana-mobile/dapp-store-cli create release -k <keypair.json> -b <path-to-android-sdk-build-tools>
   ```

4. **Submit for review:**

   ```bash
   npx @solana-mobile/dapp-store-cli publish submit -k <keypair.json> --requestor-is-authorized --complies-with-solana-dapp-store-policies
   ```

5. For updates: bump `versionCode`/`versionName`, rebuild, then
   `create release` + `publish update`.

## How the wallet integration works

- **Connect Wallet** calls `MobileWalletAdapter.connect()`, which opens the
  user's MWA-compatible wallet for authorization and returns the authorized
  account. The address is shown Base58-encoded in the top bar.
- **Sign score with wallet** (on the game-over screen) calls
  `signMessagesDetached()` with a message like
  `"Merge48 score attestation: <score> points, ts=<unix-ms>"`. The wallet
  returns an Ed25519 signature — proof the score claim came from that
  address. No transaction is sent and no fees are paid.

## License

MIT — see [LICENSE](LICENSE). Game concept inspired by Gabriele Cirulli's
open-source 2048.
