import os
import db
from openai import OpenAI
from dotenv import load_dotenv
from db import search_similar_chunks, ensure_schema
load_dotenv()



client = OpenAI()
MODEL_EMBED = "text-embedding-3-small"
MODEL_LLM = "gpt-4o-mini"  # or gpt-4o if you have access

def embed_query(query: str):
    resp = client.embeddings.create(model=MODEL_EMBED, input=query)
    return resp.data[0].embedding

def retrieve_context(query_embedding, top_k=5):
    user_key = os.getenv("APP_USER_KEY")
    results = db.search_similar_chunks(query_embedding, limit=top_k, user_key=user_key)
    # combine chunks into a single context block
    context = "\n\n".join([r["chunk"] for r in results])
    sources = [
        {
            "url": r.get("url"),
            "title": r.get("title"),
            "distance": r.get("distance"),
            "chunk_preview": (r.get("chunk") or "")[:200]
        }
        for r in results
    ]
    return context, sources

def answer_question(question: str, debug: bool = False):
    steps = {}
    # 1. Embed user question
    q_embedding = embed_query(question)
    if debug:
        steps["embedding_len"] = len(q_embedding)
        steps["embedding_preview"] = q_embedding[:8]
    # 2. Retrieve relevant chunks
    context, sources = retrieve_context(q_embedding)
    steps["topk"] = len(sources)
    steps["retrieved_sources"] = sources
    # 3. Build prompt
    prompt = f"""You are an assistant. Use the following context to answer the question.

Context:
{context}

Question:
{question}

Answer in a clear and concise way, citing URLs when helpful.
"""
    steps["prompt_preview"] = prompt[:800]
    # 4. Call LLM
    resp = client.chat.completions.create(
        model=MODEL_LLM,
        messages=[{"role": "system", "content": "You are a helpful assistant."},
                  {"role": "user", "content": prompt}],
        temperature=0.2
    )
    answer = resp.choices[0].message.content
    if debug:
        return {"answer": answer, "trace": steps}, sources
    return answer, sources

def rag_answer(question: str, debug: bool = False):
    # Ensure schema exists (no-op if already created)
    try:
        ensure_schema()
    except Exception:
        pass
    answer, sources = answer_question(question, debug=debug)
    if isinstance(answer, dict):
        return {"answer": answer.get("answer"), "sources": sources, "trace": answer.get("trace")}
    return {"answer": answer, "sources": sources}

def summarize_urls(urls: list):
    # Fetch all chunks for the given URLs
    from db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    # Get all chunks for the selected URLs
    format_strings = ','.join(['%s'] * len(urls))
    cur.execute(
        f"""
        SELECT e.chunk, w.url
        FROM web_content_embedding e
        JOIN web_content1 w ON e.page_id = w.id
        WHERE w.url IN ({format_strings})
        """,
        tuple(urls)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return "No content found for the selected URLs."

    # Combine all chunks for summary
    all_chunks = "\n\n".join([row[0] for row in rows])
    # Use OpenAI to summarize
    from openai import OpenAI
    client = OpenAI()
    prompt = f"Summarize the following content in a clear and concise way:\n\n{all_chunks}"
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are a helpful summarizer."},
                  {"role": "user", "content": prompt}],
        temperature=0.2
    )
    summary = resp.choices[0].message.content
    return summary

if __name__ == "__main__":
    q = "What does the website say about its privacy policy?"
    ans, src = answer_question(q)
    print("Answer:\n", ans)
    print("\nSources:")
    for s in src:
        print(f"- {s['title']} ({s['url']})")
