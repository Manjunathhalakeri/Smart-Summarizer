import React, { useEffect, useState } from 'react'
import { API_URL } from '../App'

type PageMeta = { id: number; url: string; title?: string; created_at?: string }

export function ManagePanel() {
  const [pages, setPages] = useState<PageMeta[]>([])
  const [loading, setLoading] = useState(false)
  const [user, setUser] = useState('default')
  const load = async () => {
    try {
      const r = await fetch(`${API_URL}/pages`, { headers: { 'X-User': user } })
      const j = await r.json()
      setPages(j.pages || [])
    } catch {}
  }
  useEffect(() => { load() }, [user])

  const rescrape = async (id: number) => {
    setLoading(true)
    await fetch(`${API_URL}/rescrape/${id}`, { method: 'POST', headers: { 'X-User': user } })
    setLoading(false)
  }
  const remove = async (id: number) => {
    setLoading(true)
    await fetch(`${API_URL}/pages/${id}`, { method: 'DELETE', headers: { 'X-User': user } })
    await load()
    setLoading(false)
  }
  const reset = async () => {
    setLoading(true)
    await fetch(`${API_URL}/reset-session`, { method: 'POST' })
    await load()
    setLoading(false)
  }

  return (
    <div>
      <h2 className="h2">Manage Pages</h2>
      <p className="muted">Rescrape, delete, or reset your dataset.</p>
      <div className="row" style={{ gap: 8, marginBottom: 10 }}>
        <input style={{ maxWidth: 240 }} placeholder="user (tenant)" value={user} onChange={e => setUser(e.target.value)} />
        <button className="button secondary" onClick={load} disabled={loading}>Refresh</button>
        <button className="button ghost" onClick={reset} disabled={loading}>Reset Session</button>
      </div>
      <div className="list">
        {pages.map(p => (
          <div key={p.id} className="list-item">
            <div>
              <div className="item-title">{p.title || '(no title)'} </div>
              <div className="item-sub">{p.url}</div>
            </div>
            <div className="row" style={{ gap: 6 }}>
              <button className="button secondary" onClick={() => rescrape(p.id)} disabled={loading}>Rescrape</button>
              <button className="button ghost" onClick={() => remove(p.id)} disabled={loading}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}


