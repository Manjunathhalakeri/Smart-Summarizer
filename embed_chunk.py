import tiktoken
from openai import OpenAI
import os
import db  # your existing db.py, NOT psycopg2 directly
from dotenv import load_dotenv
load_dotenv()

client = OpenAI()
MODEL_NAME = "text-embedding-3-small"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start = end - overlap
    return chunks

def embed_and_store_all():
    user_key = os.getenv("APP_USER_KEY")
    pages = db.fetch_all_pages(user_key=user_key)  # get {id, url, content} from your scraper table
    print(f"Fetched {len(pages)} pages from DB.")
    for page in pages:
        print(f"Processing page id={page['id']} url={page['url']}")
        chunks = chunk_text(page['content'])
        print(f"  Split into {len(chunks)} chunks.")
        for i, chunk in enumerate(chunks):
            resp = client.embeddings.create(model=MODEL_NAME, input=chunk)
            embedding = resp.data[0].embedding
            print(f"    Embedding type: {type(embedding)}, length: {len(embedding)}, first 5: {embedding[:5] if embedding else 'EMPTY'}")
            try:
                db.insert_embedding(page['id'], chunk, embedding, user_key=user_key)
                print(f"    Inserted embedding for page {page['id']} chunk {i+1}/{len(chunks)} (length={len(chunk)})")
            except Exception as e:
                print(f"    ERROR inserting embedding for page {page['id']} chunk {i+1}: {e}")
    print("All embeddings inserted.")

if __name__ == "__main__":
    embed_and_store_all()
