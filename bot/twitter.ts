import { TwitterApi } from 'twitter-api-v2'
import { TWITTER, BOT_DRY_RUN } from './config'

let _client: TwitterApi | null = null

function client(): TwitterApi {
  if (!_client) {
    _client = new TwitterApi({
      appKey: TWITTER.appKey,
      appSecret: TWITTER.appSecret,
      accessToken: TWITTER.accessToken,
      accessSecret: TWITTER.accessSecret,
    })
  }
  return _client
}

export async function postTweet(text: string, replyToId?: string): Promise<string> {
  if (BOT_DRY_RUN) {
    console.log('\n[DRY RUN] ─────────────────────────────')
    console.log(text)
    if (replyToId) console.log(`  (reply to ${replyToId})`)
    console.log('─────────────────────────────────────\n')
    return `dry-${Date.now()}`
  }

  const params: { text: string; reply?: { in_reply_to_tweet_id: string } } = { text }
  if (replyToId) {
    params.reply = { in_reply_to_tweet_id: replyToId }
  }

  const { data } = await client().v2.tweet(params)
  return data.id
}
