import React, { useMemo, useState } from 'react'
import { AskPanel } from './panels/AskPanel'
import { ScrapePanel } from './panels/ScrapePanel'
import { SummaryPanel } from './panels/SummaryPanel'
import { ManagePanel } from './panels/ManagePanel'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

type TabKey = 'scrape' | 'ask' | 'summary' | 'manage'

export function App() {
  const [tab, setTab] = useState<TabKey>('scrape')

  const tabs: { key: TabKey; label: string; emoji: string }[] = useMemo(
    () => [
      { key: 'scrape', label: 'Scrape & Index', emoji: '🚀' },
      { key: 'ask', label: 'Ask', emoji: '💬' },
      { key: 'summary', label: 'Summary', emoji: '📝' },
      { key: 'manage', label: 'Manage', emoji: '🗂️' },
    ],
    []
  )

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand brand-large">
          <div className="brand-badge">Σ</div>
          <div>
            <div>Smart</div>
            <div>Summarizer</div>
          </div>
        </div>
        <nav className="side-nav">
          {tabs.map(t => (
            <button
              key={t.key}
              className={`side-tab ${tab === t.key ? 'active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              <span className="side-emoji" aria-hidden>{t.emoji}</span>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="side-footer muted small">API: {API_URL}</div>
      </aside>

      <main className="content">
        <div className="content-hero">
          <div>
            <h1 className="hero-title">{tabs.find(x => x.key === tab)?.label}</h1>
            <p className="hero-sub">Full-width, production-ready interface for scraping, retrieval, and generation.</p>
          </div>
          <div className="hero-chips">
            <span className="chip">FastAPI</span>
            <span className="chip">pgvector</span>
            <span className="chip">OpenAI</span>
            <span className="chip">React</span>
          </div>
        </div>

        <section className="content-grid">
          <div className="card xl">
            {tab === 'scrape' && <ScrapePanel />}
            {tab === 'ask' && <AskPanel />}
            {tab === 'summary' && <SummaryPanel />}
            {tab === 'manage' && <ManagePanel />}
          </div>
          <div className="card info">
            <h2 className="h2">How it works</h2>
            <p className="muted">
              Provide URLs to scrape and index. Ask questions or generate summaries powered by
              retrieval-augmented generation. Manage entries at any time.
            </p>
            <div className="row" style={{ gap: 8, marginTop: 10 }}>
              <span className="chip">Scalable</span>
              <span className="chip">Responsive</span>
              <span className="chip">Modern UI</span>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}


