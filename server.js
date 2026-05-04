import express from 'express'
import Anthropic from '@anthropic-ai/sdk'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import 'dotenv/config'

const __dirname = dirname(fileURLToPath(import.meta.url))
const app = express()
app.use(express.json())

const client = new Anthropic()

const SYSTEM_PROMPT = `You are AutoReelsAI, an elite viral content creator for TikTok, Instagram Reels, and YouTube Shorts.

Your task: generate a COMPLETE viral content package as a single JSON object.

CRITICAL: Return ONLY valid JSON. No markdown, no code fences, no explanation. Just the raw JSON object.

Required JSON structure:
{
  "hook": "attention-grabbing 0-3 second hook line",
  "script": "complete 15-30 second punchy script",
  "voiceover": "AI voice optimized script — use ... for pauses, CAPS for emphasis",
  "scenes": [
    {
      "id": 1,
      "name": "Hook",
      "visual": "description of what to show on screen",
      "textOverlay": "BIG BOLD TEXT SHOWN ON SCREEN",
      "subtext": "smaller supporting caption text",
      "duration": 3,
      "theme": "gradient"
    }
  ],
  "caption": "scroll-stopping Instagram/TikTok caption with CTA",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
  "viralStrategy": "why this will perform well and what emotion/trigger it hits",
  "variations": [
    {"tone": "Aggressive", "hook": "alternative hook", "targetAudience": "who this targets"},
    {"tone": "Chill", "hook": "alternative hook", "targetAudience": "who this targets"},
    {"tone": "Storytime", "hook": "alternative hook", "targetAudience": "who this targets"}
  ],
  "musicVibes": "suggested music genre, energy level, and BPM range"
}

Scene themes — pick the best per scene:
- "gradient"  → deep purple-to-indigo gradient (default, premium feel)
- "dark"      → pure black with white text (clean, minimal)
- "vibrant"   → purple-to-pink gradient (hype, energy)
- "fire"      → orange-to-red gradient (urgency, motivation)
- "neon"      → dark bg with green-cyan accents (tech, crypto)
- "minimal"   → white background, dark text (calm, lifestyle)

Scene flow (include 4–6 scenes):
  Scene 1: Hook visual — grab attention instantly
  Scene 2: Problem/Intrigue — create tension or curiosity
  Scene 3: Solution/Value — deliver the goods
  Scene 4: Example/Demo/Story — make it real
  Scene 5: CTA — tell them what to do

STYLE RULES:
- Write like a real person, not a teacher
- Bold, confident, slightly edgy tone
- No filler phrases, no fluff
- Short punchy sentences (max 8 words each)
- Prioritize retention and watch time
- Make every word earn its place`

app.post('/api/generate', async (req, res) => {
  const { topic, platform = 'all', tone = 'auto' } = req.body

  if (!topic?.trim()) {
    return res.status(400).json({ error: 'Topic is required' })
  }

  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')

  try {
    const stream = client.messages.stream({
      model: 'claude-opus-4-7',
      max_tokens: 4096,
      thinking: { type: 'adaptive' },
      system: [
        {
          type: 'text',
          text: SYSTEM_PROMPT,
          cache_control: { type: 'ephemeral' }
        }
      ],
      messages: [
        {
          role: 'user',
          content: `Generate a viral content package for: "${topic}"
Platform: ${platform}
Tone preference: ${tone}

Return the complete JSON now.`
        }
      ]
    })

    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
        res.write(`data: ${JSON.stringify({ text: event.delta.text })}\n\n`)
      }
    }

    res.write('data: [DONE]\n\n')
    res.end()
  } catch (err) {
    console.error('Generation error:', err.message)
    res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`)
    res.end()
  }
})

if (process.env.NODE_ENV === 'production') {
  app.use(express.static(join(__dirname, 'client/dist')))
  app.get('*', (_req, res) => {
    res.sendFile(join(__dirname, 'client/dist/index.html'))
  })
}

const PORT = process.env.PORT || 3000
app.listen(PORT, () => {
  console.log(`AutoReelsAI server running on http://localhost:${PORT}`)
})
