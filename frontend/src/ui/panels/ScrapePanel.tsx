import React, { useState } from 'react'
import { API_URL } from '../App'

export function ScrapePanel() {
  const [url1, setUrl1] = useState('')
  const [url2, setUrl2] = useState('')
  const [url3, setUrl3] = useState('')
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [user, setUser] = useState('default')

  const submit = async () => {
    const urls = [url1, url2, url3].filter(Boolean)
    if (!urls.length) { setMsg('Please enter at least one URL.'); return }
    setLoading(true)
    setMsg(null)
    try {
      const r = await fetch(`${API_URL}/scrape`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify({ urls }),
      })
      const j = await r.json()
      setMsg(j.message || 'Scraping started')
    } catch (e: any) {
      setMsg(e?.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="h2">Scrape & Index</h2>
      <p className="muted">Enter up to three URLs. Scraping runs in the background.</p>
      <div className="grid">
        <input placeholder="user (tenant)" value={user} onChange={e => setUser(e.target.value)} />
      </div>
      <div className="grid">
        <input placeholder="https://example.com" value={url1} onChange={e => setUrl1(e.target.value)} />
        <input placeholder="https://another.com" value={url2} onChange={e => setUrl2(e.target.value)} />
        <input placeholder="https://third.com" value={url3} onChange={e => setUrl3(e.target.value)} />
      </div>
      <div style={{ height: 10 }} />
      <div className="row" style={{ gap: 10 }}>
        <button className="button" onClick={submit} disabled={loading}>{loading ? 'Starting…' : 'Scrape & Index'}</button>
      </div>
      {msg && <p className="muted" style={{ marginTop: 10 }}>{msg}</p>}
    </div>
  )
}


