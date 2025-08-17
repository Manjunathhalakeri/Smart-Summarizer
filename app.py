import streamlit as st
import requests
import json

API_URL = "http://localhost:8000"
DEFAULT_USER = "default"

st.set_page_config(layout="wide", page_title="Smart Summarizer from URLs", page_icon=":robot_face:")

# --- Custom CSS for style and compact URL inputs ---
st.markdown("""
    <style>
    .main-title {
        font-size: 3rem;
        font-weight: bold;
        color: #4F8BF9;
        text-align: center;
        margin-bottom: 0.5em;
        letter-spacing: 2px;
        font-family: 'Segoe UI', 'Arial', sans-serif;
        text-shadow: 1px 1px 8px #dbeafe;
    }
    .subtitle {
        font-size: 1.3rem;
        color: #22223b;
        text-align: center;
        margin-bottom: 2em;
        font-family: 'Segoe UI', 'Arial', sans-serif;
    }
    .stButton>button {
        background-color: #4F8BF9;
        color: white;
        font-weight: bold;
        border-radius: 8px;
        border: none;
        padding: 0.5em 1.5em;
        margin: 0.5em 0;
        transition: background 0.2s;
    }
    .stButton>button:hover {
        background-color: #22223b;
        color: #fff;
    }
    .compact-url input {
        font-size: 0.9rem !important;
        padding: 0.2em 0.5em !important;
        height: 2.2em !important;
        border-radius: 6px !important;
        width: 100% !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- Main Title ---
st.markdown('<div class="main-title">🤖 Smart Summarizer from URLs</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Scrape, summarize, and ask questions about any web content in seconds!</div>', unsafe_allow_html=True)

# --- Compact URL Inputs ---
st.subheader("🔗 Enter up to 3 URLs")
url_cols = st.columns([1, 1, 1])
with url_cols[0]:
    url1 = st.text_input("URL 1", placeholder="https://example.com", key="url1", label_visibility="collapsed")
with url_cols[1]:
    url2 = st.text_input("URL 2", placeholder="https://another.com", key="url2", label_visibility="collapsed")
with url_cols[2]:
    url3 = st.text_input("URL 3", placeholder="https://third.com", key="url3", label_visibility="collapsed")

# Apply compact style to URL inputs
st.markdown("""
    <style>
    div[data-testid="stTextInput"] input {
        font-size: 0.9rem !important;
        padding: 0.2em 0.5em !important;
        height: 2.2em !important;
        border-radius: 6px !important;
        width: 100% !important;
    }
    </style>
""", unsafe_allow_html=True)

if st.button("🚀 Scrape & Index"):
    urls = [u for u in [url1, url2, url3] if u]
    if urls:
        resp = requests.post(f"{API_URL}/scrape", json={"urls": urls}, headers={"X-User": DEFAULT_USER})
        st.success(resp.json().get("message", "Scraping started!"))
    else:
        st.warning("Please enter at least one URL.")

st.markdown("---")

# --- Two columns for Ask a Question and Get Summary ---
ask_col, summary_col = st.columns(2)

with ask_col:
    st.subheader("💬 Ask a Question")
    question = st.text_input("Your question about these URLs", placeholder="e.g. What is the main topic of these pages?", key="question")
    if st.button("🤔 Get Answer"):
        resp = requests.post(f"{API_URL}/ask", json={"question": question}, headers={"X-User": DEFAULT_USER})
        result = resp.json()
        st.write("**Answer:**", result.get("answer", "No answer found."))
        sources = result.get("sources", [])
        if sources:
            with st.expander("Show sources"):
                for s in sources:
                    st.markdown(f"- [{s.get('title') or s.get('url')}]({s.get('url')})")

with summary_col:
    st.subheader("📝 Get Summary")
    summary_urls = []
    if url1:
        if st.checkbox(f"Summary for URL 1: {url1}", key="sum1"):
            summary_urls.append(url1)
    if url2:
        if st.checkbox(f"Summary for URL 2: {url2}", key="sum2"):
            summary_urls.append(url2)
    if url3:
        if st.checkbox(f"Summary for URL 3: {url3}", key="sum3"):
            summary_urls.append(url3)
    if st.checkbox("Summary for ALL URLs", key="sumall"):
        summary_urls = [u for u in [url1, url2, url3] if u]
    if st.button("📄 Show Summary"):
        if summary_urls:
            resp = requests.post(f"{API_URL}/summary", json={"urls": summary_urls}, headers={"X-User": DEFAULT_USER})
            st.write("**Summary:**", resp.json().get("summary", "No summary found."))
        else:
            st.warning("Select at least one URL for summary.")

# --- Footer ---
st.markdown(
    "<hr style='margin-top:2em;margin-bottom:1em;'>"
    "<div style='text-align:center; color:#888;'>"
    "Made with ❤️ using Streamlit & FastAPI"
    "</div>",
    unsafe_allow_html=True
)

st.markdown("---")
st.subheader("🗂️ Manage Pages")
cols = st.columns([1,1,1,2])
with cols[0]:
    if st.button("🔄 Refresh List"):
        st.session_state["refresh_pages"] = True
with cols[1]:
    if st.button("🧹 Reset Session"):
        try:
            r = requests.post(f"{API_URL}/reset-session")
            st.success(r.json().get("status", "Reset"))
        except Exception as e:
            st.error(str(e))

if st.session_state.get("refresh_pages") or True:
    try:
        pages = requests.get(f"{API_URL}/pages", headers={"X-User": DEFAULT_USER}).json().get("pages", [])
    except Exception as e:
        pages = []
        st.error(str(e))

if pages:
    for p in pages:
        with st.container():
            c1, c2, c3, c4 = st.columns([4,2,2,2])
            with c1:
                st.write(p.get("title") or "(no title)")
                st.caption(p.get("url"))
            with c2:
                if st.button("♻️ Rescrape", key=f"res_{p['id']}"):
                    requests.post(f"{API_URL}/rescrape/{p['id']}", headers={"X-User": DEFAULT_USER})
                    st.toast("Rescrape started")
            with c3:
                if st.button("🗑️ Delete", key=f"del_{p['id']}"):
                    requests.delete(f"{API_URL}/pages/{p['id']}", headers={"X-User": DEFAULT_USER})
                    st.toast("Deleted")
            with c4:
                pass
else:
    st.info("No pages yet. Scrape some URLs above.")