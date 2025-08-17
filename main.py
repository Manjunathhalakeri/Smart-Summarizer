from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from scrapper import main as scrapper_main
from rag import rag_answer
from rag import summarize_urls
from db import flush_database, ensure_schema, fetch_pages_meta, delete_page, delete_embeddings_for_page, fetch_url_by_id, get_or_create_user

app = FastAPI()

# CORS for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure DB schema on startup import
try:
    ensure_schema()
except Exception:
    pass

class UrlsRequest(BaseModel):
    urls: List[str]

class QuestionRequest(BaseModel):
    question: str
    debug: bool | None = False

@app.post("/scrape")
def scrape_urls(req: UrlsRequest, background_tasks: BackgroundTasks, request: Request):
    # Run scraping pipeline in background so UI can return immediately
    cli_args = ["--urls"] + req.urls
    # Propagate user via env var for the background job
    user_key = request.headers.get("X-User") or request.query_params.get("user") or "default"
    import os
    os.environ["APP_USER_KEY"] = user_key
    background_tasks.add_task(scrapper_main, cli_args)
    return {"message": f"Scraping started for {len(req.urls)} URLs."}

    # For now, just return a dummy response
    

@app.post("/ask")
def ask_question(req: QuestionRequest, request: Request):
    # Call your RAG pipeline here
    user_key = request.headers.get("X-User") or request.query_params.get("user") or "default"
    import os
    os.environ["APP_USER_KEY"] = user_key
    result = rag_answer(req.question, debug=bool(req.debug))
    return result

@app.post("/summary")
def get_summary(req: UrlsRequest):
    summary = summarize_urls(req.urls)
    return {"summary": summary}



@app.post("/reset-session")
def reset_session():
    flush_database()
    return {"status": "Database cleared"}


@app.get("/pages")
def list_pages(request: Request):
    user_key = request.headers.get("X-User") or request.query_params.get("user") or "default"
    return {"pages": fetch_pages_meta(user_key=user_key)}


class PageId(BaseModel):
    page_id: int


@app.delete("/pages/{page_id}")
def delete_page_and_embeddings(page_id: int, request: Request):
    user_key = request.headers.get("X-User") or request.query_params.get("user") or "default"
    delete_page(page_id, user_key=user_key)
    return {"status": "deleted", "page_id": page_id}


@app.post("/rescrape/{page_id}")
def rescrape_page(page_id: int, background_tasks: BackgroundTasks, request: Request):
    user_key = request.headers.get("X-User") or request.query_params.get("user") or "default"
    url: Optional[str] = fetch_url_by_id(page_id, user_key=user_key)
    if not url:
        return {"error": "Page not found"}
    # delete old embeddings; content will be upserted on scrape
    import os
    os.environ["APP_USER_KEY"] = user_key
    delete_embeddings_for_page(page_id, user_key=user_key)
    background_tasks.add_task(scrapper_main, ["--urls", url])
    return {"message": "Rescrape started", "page_id": page_id, "url": url}


