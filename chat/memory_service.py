"""
AIRA Memory Service - Optimized for fast startup
"""
import os
import json
import logging
import pickle
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)

FAISS_DIR = Path(settings.BASE_DIR) / 'faiss_indexes'
FAISS_DIR.mkdir(exist_ok=True)

# ── Lazy embedder — only loads when actually needed ────
_embedder = None
_embedder_loading = False

def embedder():
    global _embedder, _embedder_loading
    if _embedder is not None:
        return _embedder
    if _embedder_loading:
        return None
    try:
        _embedder_loading = True
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Embedder loaded OK")
    except Exception as e:
        logger.warning(f"Embedder not available: {e}")
        _embedder = None
    finally:
        _embedder_loading = False
    return _embedder


# ── FAISS Vector Store ─────────────────────────────────

def get_user_index_path(user_id: int, index_name: str = 'memory') -> Path:
    user_dir = FAISS_DIR / f'user_{user_id}'
    user_dir.mkdir(exist_ok=True)
    return user_dir / f'{index_name}.pkl'


def save_to_faiss(user_id: int, texts: list, metadatas: list, index_name: str = 'memory'):
    """
    Save texts to user's FAISS vector store.
    texts: list of strings to embed
    metadatas: list of dicts with info about each text
    """
    try:
        import faiss
        import numpy as np

        model = embedder()
        if not model:
            return False

        # Generate embeddings
        embeddings = model.encode(texts, convert_to_numpy=True)
        embeddings = embeddings.astype('float32')

        index_path = get_user_index_path(user_id, index_name)

        # Load existing or create new
        if index_path.exists():
            with open(index_path, 'rb') as f:
                data = pickle.load(f)
            index      = data['index']
            all_texts  = data['texts']
            all_metas  = data['metadatas']
        else:
            dim   = embeddings.shape[1]
            index = faiss.IndexFlatL2(dim)
            all_texts = []
            all_metas = []

        # Add new embeddings
        index.add(embeddings)
        all_texts.extend(texts)
        all_metas.extend(metadatas)

        # Save
        with open(index_path, 'wb') as f:
            pickle.dump({
                'index':     index,
                'texts':     all_texts,
                'metadatas': all_metas,
            }, f)

        return True

    except Exception as e:
        logger.error(f"FAISS save error: {e}")
        return False


def search_faiss(user_id: int, query: str, top_k: int = 5,
                 index_name: str = 'memory') -> list:
    """
    Search user's FAISS store for relevant context.
    Returns list of {text, metadata, score} dicts.
    """
    try:
        import faiss
        import numpy as np

        index_path = get_user_index_path(user_id, index_name)
        if not index_path.exists():
            return []

        model = embedder()
        if not model:
            return []

        with open(index_path, 'rb') as f:
            data = pickle.load(f)

        index     = data['index']
        all_texts = data['texts']
        all_metas = data['metadatas']

        if index.ntotal == 0:
            return []

        # Embed query
        query_vec = model.encode([query], convert_to_numpy=True).astype('float32')

        # Search
        k = min(top_k, index.ntotal)
        distances, indices = index.search(query_vec, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(all_texts):
                results.append({
                    'text':     all_texts[idx],
                    'metadata': all_metas[idx],
                    'score':    float(dist),
                })

        return results

    except Exception as e:
        logger.error(f"FAISS search error: {e}")
        return []


# ── Long-Term Memory ───────────────────────────────────

def save_message_to_memory(user_id: int, conv_id: int,
                            role: str, content: str):
    """Save a message to the user's long-term FAISS memory."""
    if len(content.strip()) < 10:
        return

    texts = [content]
    metas = [{
        'role':        role,
        'conv_id':     conv_id,
        'user_id':     user_id,
        'content_len': len(content),
    }]
    save_to_faiss(user_id, texts, metas, index_name='chat_memory')


def get_relevant_memory(user_id: int, query: str, top_k: int = 3) -> str:
    """
    Get relevant past conversation context for current query.
    Returns formatted string to inject into AI prompt.
    """
    results = search_faiss(user_id, query, top_k=top_k, index_name='chat_memory')
    if not results:
        return ""

    memory_text = "RELEVANT PAST CONTEXT (from previous conversations):\n"
    for r in results:
        role = r['metadata'].get('role', 'unknown')
        memory_text += f"- [{role}]: {r['text'][:300]}\n"

    return memory_text


# ── Knowledge Base RAG ─────────────────────────────────

def add_to_knowledge_base(user_id: int, title: str,
                           content: str, source: str = '') -> bool:
    """Add document to user's personal knowledge base."""
    from .models import KnowledgeBase

    # Chunk the content
    chunks = chunk_for_rag(content, chunk_size=500, overlap=50)

    texts = chunks
    metas = [{'title': title, 'source': source, 'chunk': i}
             for i in range(len(chunks))]

    success = save_to_faiss(user_id, texts, metas, index_name='knowledge_base')

    if success:
        KnowledgeBase.objects.create(
            user_id=user_id,
            title=title,
            content=content[:50000],
            source_file=source,
        )

    return success


def search_knowledge_base(user_id: int, query: str, top_k: int = 5) -> str:
    """
    RAG: Search user's knowledge base for relevant context.
    Returns formatted context string.
    """
    results = search_faiss(user_id, query, top_k=top_k,
                           index_name='knowledge_base')
    if not results:
        return ""

    context = "KNOWLEDGE BASE CONTEXT (from your uploaded documents):\n\n"
    for i, r in enumerate(results, 1):
        title  = r['metadata'].get('title', 'Document')
        source = r['metadata'].get('source', '')
        context += f"[{i}] From '{title}':\n{r['text']}\n\n"

    return context


# ── Semantic Search in Chat History ───────────────────

def semantic_search_history(user_id: int, query: str, top_k: int = 5) -> list:
    """
    Search through ALL user's chat history semantically.
    Returns list of relevant messages with context.
    """
    results = search_faiss(user_id, query, top_k=top_k,
                           index_name='chat_memory')
    return results


# ── User Personalization ───────────────────────────────

def extract_and_save_user_facts(user_id: int, conversation: list):
    """
    Analyze conversation to extract facts about the user.
    Save to UserMemory model for personalization.
    """
    from .models import UserMemory

    # Simple rule-based extraction
    facts = []
    for msg in conversation:
        if msg['role'] != 'user':
            continue
        content = msg['content'].lower()

        # Detect programming language preferences
        for lang in ['python', 'javascript', 'java', 'c++', 'typescript',
                     'rust', 'go', 'ruby', 'php', 'swift']:
            if f'i use {lang}' in content or f'i prefer {lang}' in content \
               or f'i like {lang}' in content or f'i love {lang}' in content:
                facts.append({
                    'memory':   f"User prefers {lang} programming language",
                    'category': 'programming',
                    'importance': 3,
                })

        # Detect framework preferences
        for fw in ['django', 'flask', 'fastapi', 'react', 'vue', 'angular',
                   'next.js', 'express', 'spring']:
            if fw in content and ('use' in content or 'prefer' in content
                                  or 'like' in content):
                facts.append({
                    'memory':   f"User works with {fw} framework",
                    'category': 'framework',
                    'importance': 2,
                })

        # Detect experience level
        if any(w in content for w in ['beginner', "i'm new", 'just started',
                                       'learning']):
            facts.append({
                'memory':   'User is a beginner/learning programmer',
                'category': 'experience',
                'importance': 4,
            })
        elif any(w in content for w in ['senior', 'expert', 'years of experience',
                                         'professional']):
            facts.append({
                'memory':   'User is an experienced/senior developer',
                'category': 'experience',
                'importance': 4,
            })

    # Save unique facts
    existing = set(UserMemory.objects.filter(user_id=user_id)
                   .values_list('memory', flat=True))
    for fact in facts:
        if fact['memory'] not in existing:
            UserMemory.objects.create(
                user_id=user_id,
                memory=fact['memory'],
                category=fact['category'],
                importance=fact['importance'],
            )


def get_user_personalization(user_id: int) -> str:
    """
    Get user's known preferences and facts for AI personalization.
    Returns formatted string to inject into system prompt.
    """
    from .models import UserMemory

    memories = UserMemory.objects.filter(
        user_id=user_id
    ).order_by('-importance', '-updated_at')[:10]

    if not memories:
        return ""

    persona = "USER PROFILE (personalize your responses accordingly):\n"
    for m in memories:
        persona += f"- {m.memory}\n"

    return persona


# ── RAG Pipeline ───────────────────────────────────────

def build_rag_context(user_id: int, query: str,
                       use_knowledge_base: bool = True,
                       use_memory: bool = True) -> str:
    """
    Full RAG pipeline: combine knowledge base + memory context.
    Returns context string to inject into AI prompt.
    """
    context_parts = []

    if use_knowledge_base:
        kb_context = search_knowledge_base(user_id, query)
        if kb_context:
            context_parts.append(kb_context)

    if use_memory:
        mem_context = get_relevant_memory(user_id, query)
        if mem_context:
            context_parts.append(mem_context)

    return "\n\n".join(context_parts)


# ── Document Comparison ────────────────────────────────

def compare_documents(doc1_text: str, doc2_text: str,
                       doc1_name: str, doc2_name: str) -> str:
    """
    Build comparison prompt for two documents.
    Returns formatted prompt string.
    """
    # Truncate if too large
    max_chars = 6000
    d1 = doc1_text[:max_chars]
    d2 = doc2_text[:max_chars]

    prompt = f"""Compare these two documents thoroughly:

{'='*50}
DOCUMENT 1: {doc1_name}
{'='*50}
{d1}

{'='*50}
DOCUMENT 2: {doc2_name}
{'='*50}
{d2}

{'='*50}

Please provide a detailed comparison covering:
1. 📋 Overview of each document
2. ✅ Similarities between the documents
3. ❌ Key differences
4. 📊 Unique content in each document
5. 💡 Summary and conclusion

Be thorough and specific in your comparison."""

    return prompt


# ── Helpers ────────────────────────────────────────────

def chunk_for_rag(text: str, chunk_size: int = 500,
                  overlap: int = 50) -> list:
    """Split text into overlapping chunks for RAG."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start  = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            # Break at sentence boundary
            bp = text.rfind('. ', start, end)
            if bp != -1:
                end = bp + 1
        chunks.append(text[start:end].strip())
        start = end - overlap

    return [c for c in chunks if c.strip()]