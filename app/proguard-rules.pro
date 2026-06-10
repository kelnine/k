# Mobile Wallet Adapter uses reflection-free JSON-RPC over local websockets,
# but keep its classes intact if minification is ever enabled.
-keep class com.solana.mobilewalletadapter.** { *; }
