import { useState } from 'react'
import InputForm from './components/InputForm'
import ContentDisplay from './components/ContentDisplay'
import VideoStudio from './components/VideoStudio'

export default function App() {
  const [generating, setGenerating] = useState(false)
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState('')
  const [activeTab, setActiveTab] = useState('content')

  const generate = async ({ topic, platform, tone }) => {
    setGenerating(true)
    setContent(null)
    setError(null)
    setProgress('')

    try {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, platform, tone })
      })

      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.error || 'Server error')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const lines = decoder.decode(value).split('\n')
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()

          if (data === '[DONE]') {
            // Strip any accidental markdown fences and parse
            const clean = accumulated
              .replace(/^```(?:json)?\s*/i, '')
              .replace(/\s*```$/i, '')
              .trim()
            try {
              setContent(JSON.parse(clean))
              setActiveTab('content')
            } catch {
              setError('Could not parse the generated content. Please try again.')
            }
            break
          }

          try {
            const parsed = JSON.parse(data)
            if (parsed.error) { setError(parsed.error); break }
            if (parsed.text) {
              accumulated += parsed.text
              // Show last 80 chars as live progress hint
              setProgress(accumulated.slice(-80))
            }
          } catch { /* partial chunk, ignore */ }
        }
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">🎬</span>
            <span className="logo-text">AutoReels<span className="logo-accent">AI</span></span>
          </div>
          <p className="tagline">Turn any idea into a viral short-form content package</p>
        </div>
      </header>

      <main className="main">
        <InputForm onGenerate={generate} generating={generating} />

        {generating && (
          <div className="generating-card">
            <div className="spinner-ring" />
            <div className="generating-text">
              <p className="generating-title">Crafting your viral package…</p>
              {progress && <p className="generating-preview">{progress}</p>}
            </div>
          </div>
        )}

        {error && (
          <div className="error-card">
            <span className="error-icon">⚠️</span>
            <p>{error}</p>
          </div>
        )}

        {content && (
          <div className="results-section">
            <div className="tab-bar">
              <button
                className={`tab-btn ${activeTab === 'content' ? 'active' : ''}`}
                onClick={() => setActiveTab('content')}
              >
                📝 Content Package
              </button>
              <button
                className={`tab-btn ${activeTab === 'video' ? 'active' : ''}`}
                onClick={() => setActiveTab('video')}
              >
                🎬 Video Studio
              </button>
            </div>

            {activeTab === 'content' && <ContentDisplay content={content} />}
            {activeTab === 'video' && (
              <VideoStudio scenes={content.scenes} voiceover={content.voiceover} />
            )}
          </div>
        )}
      </main>

      <footer className="footer">
        <p>Powered by Claude AI · AutoReelsAI</p>
      </footer>
    </div>
  )
}
