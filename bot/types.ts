export type Side = 'bull' | 'bear'
export type BreakType = 'BOS' | 'CHoCH'

export interface Signal {
  id: string
  symbol: string
  tf: string
  side: Side
  breakType: BreakType
  level: number
  entry: number
  stop: number
  t1: number
  t2: number
  t3: number
  obTop: number
  obBottom: number
  breakBar: number
  detectedAt: string
}

export interface Trade {
  signal: Signal
  tweetId: string
  openedAt: string
  t1Hit: boolean
  t2Hit: boolean
  t3Hit: boolean
  t1TweetId?: string
  t2TweetId?: string
  exitPrice: number | null
  exitReason: 't3' | 'stop' | null
  exitTweetId?: string
  closed: boolean
}

export interface BotState {
  seenSignalIds: string[]
  openTrades: Trade[]
  closedTrades: Trade[]
}
