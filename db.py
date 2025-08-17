import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()


# Database connection settings (env-configurable with sensible defaults)
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "testdb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

VECTOR_DIM = 1536  # OpenAI text-embedding-3-small dimension

def get_connection():
    """
    Create a new PostgreSQL connection.
    """
    return psycopg2.connect(**DB_CONFIG)


def ensure_schema():
    """
    Ensure required tables and the pgvector extension exist.
    - web_content1: stores scraped pages
    - web_content_embedding: stores chunk embeddings as pgvector
    """
    conn = get_connection()
    cur = conn.cursor()
    # Enable pgvector
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    # Users table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_key TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Ensure a default user for legacy rows
    cur.execute("INSERT INTO users (user_key) VALUES ('default') ON CONFLICT (user_key) DO NOTHING;")
    # Pages table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS web_content1 (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Backfill user_id for legacy rows
    cur.execute("""
        UPDATE web_content1 SET user_id = (SELECT id FROM users WHERE user_key = 'default')
        WHERE user_id IS NULL;
    """)
    # Embeddings table with ON DELETE CASCADE and ivfflat index
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS web_content_embedding (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            page_id INT REFERENCES web_content1(id) ON DELETE CASCADE,
            chunk TEXT NOT NULL,
            embedding vector({VECTOR_DIM}),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Ensure unique index on url for ON CONFLICT support (add if table pre-existed)
    # Replace per-URL unique index with scoped per-user unique index
    # Drop old index if exists
    cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'web_content1_url_key'
            ) THEN
                BEGIN
                    EXECUTE 'DROP INDEX IF EXISTS web_content1_url_key';
                EXCEPTION WHEN others THEN NULL; END;
            END IF;
        END$$;
    """)
    # Deduplicate by (user_id,url)
    cur.execute(
        """
        WITH ranked AS (
            SELECT id, user_id, url,
                   ROW_NUMBER() OVER (PARTITION BY user_id, url ORDER BY created_at DESC, id DESC) AS rn
            FROM web_content1
        )
        DELETE FROM web_content_embedding e
        USING ranked r
        WHERE e.page_id = r.id AND r.rn > 1;
        """
    )
    cur.execute(
        """
        DELETE FROM web_content1 w
        USING (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY user_id, url ORDER BY created_at DESC, id DESC) AS rn
                FROM web_content1
            ) t WHERE rn > 1
        ) d
        WHERE w.id = d.id;
        """
    )
    # Create composite unique index
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS web_content1_user_url_uniq ON web_content1 (user_id, url);")

    # Create index for ANN search if not exists
    cur.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'web_content_embedding_embedding_idx'
            ) THEN
                CREATE INDEX web_content_embedding_embedding_idx
                ON web_content_embedding USING ivfflat (embedding vector_l2_ops)
                WITH (lists = 100);
            END IF;
        END$$;
        """
    )
    conn.commit()
    cur.close()
    conn.close()

def get_or_create_user(user_key: Optional[str]) -> int:
    """Return user id for given user_key, creating if not exists. Defaults to 'default'."""
    key = user_key or 'default'
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_key) VALUES (%s) ON CONFLICT (user_key) DO NOTHING;", (key,))
    cur.execute("SELECT id FROM users WHERE user_key = %s;", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return int(row[0])


def insert_scraped_data(data: List[Dict[str, str]], *, user_key: Optional[str] = None):
    """
    Insert scraped website data into Postgres.
    data should be a list of dicts with keys: 'url', 'content', optional 'title'.
    Upserts by URL to avoid duplicates.
    """
    # Filter out invalid or empty records
    valid_data = [item for item in data if item.get("url") and item.get("content") and item["content"].strip()]
    if not valid_data:
        print("No valid data to insert into web_content table.")
        return
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor()
    for item in valid_data:
        cur.execute(
            """
            INSERT INTO web_content1 (user_id, url, title, content)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, url) DO UPDATE
            SET title = EXCLUDED.title,
                content = EXCLUDED.content,
                created_at = CURRENT_TIMESTAMP
            """,
            (user_id, item.get("url"), item.get("title"), item.get("content"))
        )
    conn.commit()
    cur.close()
    conn.close()
    print(f"Upserted {len(valid_data)} records into web_content1 table.")

def fetch_all_data() -> List[Dict]:
    """
    Fetch all records from web_content table.
    """
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM web_content1 ORDER BY created_at DESC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def fetch_all_pages(user_key: Optional[str] = None) -> List[Dict]:
    """
    Fetch all pages (id, url, title, content) from web_content1 table.
    """
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, url, title, content FROM web_content1 WHERE user_id = %s ORDER BY created_at DESC;", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def fetch_pages_meta(user_key: Optional[str] = None) -> List[Dict]:
    """Fetch lightweight page metadata for listing scoped to user."""
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, url, title, created_at FROM web_content1 WHERE user_id = %s ORDER BY created_at DESC;", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def insert_embedding(page_id: int, chunk: str, embedding: list, *, user_key: Optional[str] = None):
    """
    Insert a chunk and its embedding for a given page into web_content_embedding table.
    Stores embeddings using pgvector.
    """
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor()
    # Convert Python list to pgvector literal
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    cur.execute(
        """
        INSERT INTO web_content_embedding (user_id, page_id, chunk, embedding)
        VALUES (%s, %s, %s, %s::vector)
        """,
        (user_id, page_id, chunk, embedding_str)
    )
    conn.commit()
    cur.close()
    conn.close()

def search_similar_chunks(query_embedding: list, limit: int = 5, *, user_key: Optional[str] = None) -> list:
    """
    Search for similar chunks in web_content_embedding table, joined with web_content1 for url and title.
    Uses pgvector similarity search. Accepts query_embedding as a Python list.
    """
    # Convert embedding to string for pgvector
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT e.*, w.url, w.title, (e.embedding <=> %s::vector) AS distance
        FROM web_content_embedding e
        JOIN web_content1 w ON e.page_id = w.id
        WHERE e.user_id = %s
        ORDER BY distance
        LIMIT %s;
        """,
        (embedding_str, user_id, limit)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def delete_embeddings_for_page(page_id: int, *, user_key: Optional[str] = None) -> None:
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM web_content_embedding WHERE page_id = %s AND user_id = %s", (page_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def delete_page(page_id: int, *, user_key: Optional[str] = None) -> None:
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM web_content1 WHERE id = %s AND user_id = %s", (page_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def fetch_url_by_id(page_id: int, *, user_key: Optional[str] = None) -> Optional[str]:
    user_id = get_or_create_user(user_key)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT url FROM web_content1 WHERE id = %s AND user_id = %s", (page_id, user_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def flush_database():
    conn = get_connection()
    cur = conn.cursor()
    # Delete everything
    cur.execute("TRUNCATE TABLE web_content1 CASCADE;")
    cur.execute("TRUNCATE TABLE web_content_embedding CASCADE;")
    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    # Example usage
    sample_data = [
        {"url": "https://example.com", "content": "This is test content."},
        {"url": "https://example.org", "content": "Another page content."},
    ]
    insert_scraped_data(sample_data)
    print(fetch_all_data())
