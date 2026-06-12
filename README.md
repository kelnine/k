# Merge48 — a 2048 merge game for the Solana dApp Store

Merge48 is a native Android puzzle game built for **Solana Seeker** (and Saga).
Swipe to slide tiles; equal tiles merge. Chase the 2048 tile, then connect your
Solana wallet via **Mobile Wallet Adapter** and cryptographically sign your
high score.

- **Stack:** Kotlin · Jetpack Compose · Mobile Wallet Adapter (`clientlib-ktx` 2.1.1) · `web3-solana` + `rpc-core` for payments
- **Package:** `com.kelnine.merge48` · minSdk 26 · targetSdk 35
- **No backend, no ads, no tracking** — scores live on-device; wallet signing is local via MWA.
- **Monetized** with crypto-native in-app purchases paid in SOL directly to your wallet (the dApp Store takes **0% fees**).

## Monetization — IMPORTANT setup

All purchases are plain SOL transfers from the player's wallet **to your
wallet**, signed and submitted by their wallet app via MWA. Before shipping:

1. Open `app/src/main/java/com/kelnine/merge48/payments/Payments.kt`.
2. Set `DEV_WALLET_ADDRESS` to your wallet's public address (copy it from
   Phantom/Solflare). **Until you do, the store buttons show a setup
   reminder and never charge anyone.**
3. Optionally swap `RPC_URL` for a dedicated endpoint (Helius/QuickNode free
   tiers) — the public mainnet RPC is rate-limited.

| Product | Price | What the player gets |
|---|---|---|
| Second Chance | 0.005 SOL | On game over: clears the 8 smallest tiles, run continues (consumable — this is the core earner) |
| Pro Unlock | 0.05 SOL | Permanent Undo button (persisted on-device) |
| Trophy NFT | 0.01 SOL fee (+ ~0.012 SOL on-chain rent) | A real 1-of-1 Metaplex NFT titled "Merge48 Trophy · &lt;score&gt;", minted to the player's wallet, with a 5% royalty to you on secondary sales |
| Tip the Dev | 0.01 SOL | Goodwill |

Prices are constants in `Payments.kt` — tune freely. Notes:

- Unlocks are stored in app prefs, so clearing app data forgets a Pro
  purchase. A v2 could restore it by scanning the buyer's transfer history
  to your address on-chain.
- The app unlocks when the wallet returns a transaction signature
  (submission), without waiting for finalization — a fair UX tradeoff for
  sub-cent risk. Add a `getSignatureStatuses` confirmation loop if you want
  stricter behavior.

### How the NFT mint works (no backend)

`nft/NftMinter.kt` builds the whole mint in one transaction signed only by
the player's wallet: mint fee transfer → `createAccountWithSeed` (the mint
address derives from the player's key + a unique seed, so no mint-keypair
co-signer is needed) → `initializeMint` → create ATA → `mintTo` → Metaplex
`CreateMetadataAccountV3` → `CreateMasterEditionV3` (locks supply at 1).
The Metaplex instruction encoding is covered by golden unit tests whose
expected bytes were generated with the official JS SDK.

The NFT's off-chain metadata is served from this repo:
`nft/trophy.json` + `nft/trophy.png` via raw.githubusercontent.com — so
**the repo must stay public**, and the files must exist on `main`. For
something sturdier, upload both to Arweave/Irys or NFT.Storage and change
`NFT_METADATA_URI` in `Payments.kt`. The player's score is embedded in the
on-chain NFT name (32-byte limit), so the shared JSON works for every mint.

> **Optional art upgrade:** AI-generated versions of the trophy and a
> banner hero image were created in your Higgsfield account (see chat).
> To use them: save the trophy image over `nft/trophy.png` (512×512 or
> 1024×1024), and composite the banner art behind the title text in
> `dapp-store/media/banner.png` (1200×600).

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
├── wallet/WalletViewModel.kt  # MWA connect / sign-score / purchases
├── payments/Payments.kt       # YOUR WALLET ADDRESS + product catalog/prices
├── payments/SolanaRpc.kt      # Minimal JSON-RPC client (blockhash fetch)
├── ui/GameScreen.kt           # Animated board (sliding/merging tiles), store buttons, overlays
├── ui/theme/Theme.kt          # Gradient tile palette, glow colors, signature brushes
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
