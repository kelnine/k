import { config as dotenv } from 'dotenv'
dotenv()

export const BOT_SYMBOLS = (process.env.BOT_SYMBOLS ?? 'BTCUSDT,ETHUSDT,SOLUSDT').split(',').map((s) => s.trim())
export const BOT_TF = (process.env.BOT_TF ?? '1h') as '1m' | '5m' | '15m' | '1h' | '4h' | '1d'
export const BOT_POLL_MS = parseInt(process.env.BOT_POLL_MS ?? '60000', 10)
export const BOT_SWING = parseInt(process.env.BOT_SWING ?? '5', 10)
export const BOT_CANDLES = parseInt(process.env.BOT_CANDLES ?? '300', 10)
export const BOT_T1_R = parseFloat(process.env.BOT_T1_R ?? '0.5')
export const BOT_T2_R = parseFloat(process.env.BOT_T2_R ?? '1.0')
export const BOT_T3_R = parseFloat(process.env.BOT_T3_R ?? '2.0')
export const BOT_STATE_FILE = process.env.BOT_STATE_FILE ?? './bot-state.json'
export const BOT_DRY_RUN = process.env.BOT_DRY_RUN !== 'false'
export const BOT_HASHTAGS = process.env.BOT_HASHTAGS ?? '#crypto #BTC #trading'

export const TWITTER = {
  appKey: process.env.TWITTER_APP_KEY ?? '',
  appSecret: process.env.TWITTER_APP_SECRET ?? '',
  accessToken: process.env.TWITTER_ACCESS_TOKEN ?? '',
  accessSecret: process.env.TWITTER_ACCESS_SECRET ?? '',
}
