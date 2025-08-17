import React, { useState } from 'react'
import { API_URL } from '../App'

type Source = { url?: string; title?: string }

export function AskPanel() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState('')
  const [sources, setSources] = useState<Source[]>([])
  const [debug, setDebug] = useState(false)
  const [trace, setTrace] = useState<any | null>(null)
  const [user, setUser] = useState('default')

  const ask = async () => {
    if (!q.trim()) return
    setLoading(true)
    setAnswer('')
    setSources([])
    try {
      const r = await fetch(`${API_URL}/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify({ question: q, debug }),
      })
      const j = await r.json()
      setAnswer(j.answer || '')
      setSources(Array.isArray(j.sources) ? j.sources : [])
      setTrace(j.trace || null)
    } catch (e) {
      setAnswer('Request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="h2">Ask a Question</h2>
      <p className="muted">Ask about the content you scraped.</p>
      <div className="grid" style={{ marginBottom: 8 }}>
        <input placeholder="user (tenant)" value={user} onChange={e => setUser(e.target.value)} />
      </div>
      <textarea placeholder="e.g. What is the main topic?" value={q} onChange={e => setQ(e.target.value)} />
      <div className="row" style={{ gap: 8, margin: '8px 0' }}>
        <label className="row" style={{ gap: 6 }}>
          <input type="checkbox" checked={debug} onChange={e => setDebug(e.target.checked)} /> Debug
        </label>
      </div>
      <div style={{ height: 10 }} />
      <button className="button" onClick={ask} disabled={loading}>{loading ? 'Thinking…' : 'Get Answer'}</button>

      {!!answer && (
        <div style={{ marginTop: 16 }}>
          <div className="answer">{answer}</div>
          {!!sources?.length && (
            <div className="sources">
              <div className="muted small">Sources</div>
              <ul>
                {sources.map((s, i) => (
                  <li key={i}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a></li>
                ))}
              </ul>
            </div>
          )}
          {trace && (
            <details style={{ marginTop: 8 }}>
              <summary>Debug trace</summary>
              <pre className="answer" style={{ marginTop: 8 }}>{JSON.stringify(trace, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}


