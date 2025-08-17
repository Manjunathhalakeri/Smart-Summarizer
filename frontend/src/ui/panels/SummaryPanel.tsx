import React, { useEffect, useState } from 'react'
import { API_URL } from '../App'

type PageMeta = { id: number; url: string; title?: string }

export function SummaryPanel() {
  const [pages, setPages] = useState<PageMeta[]>([])
  const [selected, setSelected] = useState<Record<number, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState('')
  const [user, setUser] = useState('default')

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_URL}/pages`, { headers: { 'X-User': user } })
        const j = await r.json()
        setPages(j.pages || [])
      } catch {}
    })()
  }, [user])

  const toggle = (id: number) => setSelected(s => ({ ...s, [id]: !s[id] }))

  const summarize = async () => {
    const urls = pages.filter(p => selected[p.id]).map(p => p.url)
    if (!urls.length) return
    setLoading(true)
    setSummary('')
    try {
      const r = await fetch(`${API_URL}/summary`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify({ urls }),
      })
      const j = await r.json()
      setSummary(j.summary || '')
    } catch {
      setSummary('Request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="h2">Get Summary</h2>
      <p className="muted">Select one or more pages to summarize.</p>
      <div className="grid" style={{ marginBottom: 8 }}>
        <input placeholder="user (tenant)" value={user} onChange={e => setUser(e.target.value)} />
      </div>
      <div className="list">
        {pages.map(p => (
          <label key={p.id} className="list-item">
            <div>
              <div className="item-title">{p.title || '(no title)'} </div>
              <div className="item-sub">{p.url}</div>
            </div>
            <input type="checkbox" checked={!!selected[p.id]} onChange={() => toggle(p.id)} />
          </label>
        ))}
      </div>
      <div style={{ height: 10 }} />
      <button className="button" onClick={summarize} disabled={loading}>{loading ? 'Summarizing…' : 'Show Summary'}</button>
      {!!summary && <div style={{ marginTop: 12 }} className="answer">{summary}</div>}
    </div>
  )
}


