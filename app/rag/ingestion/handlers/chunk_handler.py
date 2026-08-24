import uuid
from uuid import UUID
from typing import Dict, Any, List
import re
try:
    import blake3
except ImportError:
    import hashlib
    class _Blake3Shim:
        def __init__(self, data: bytes = b""):
            self._h = hashlib.sha256(data)
        def update(self, data: bytes):
            self._h.update(data)
        def hexdigest(self):
            return self._h.hexdigest()
        def digest(self):
            return self._h.digest()
    class _Blake3ModuleShim:
        @staticmethod
        def blake3(data: bytes = b""):
            return _Blake3Shim(data)
    blake3 = _Blake3ModuleShim()
import logging
import numpy as np
from app.observability.metrics import track_step_duration
from app.rag.embeddings.providers.async_openai_provider import AsyncOpenAIEmbeddingProvider

logger = logging.getLogger(__name__)


class SemanticChunker:
    def __init__(
        self,
        max_chunk_size: int = 1000,
        chunk_overlap: int = 200,
        min_chunk_size: int = 100,
        similarity_percentile: float = 25.0,
        batch_size: int = 100
    ):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.similarity_percentile = similarity_percentile
        self.batch_size = batch_size
        self.embedding_provider = AsyncOpenAIEmbeddingProvider()
    
    async def chunk(self, markdown: str) -> List[Dict[str, Any]]:
        if not markdown:
            return []

        sentences = self._split_into_sentences(markdown)
        
        if not sentences:
            return []
        
        embeddings = await self._get_embeddings_batch(sentences)
        
        dynamic_threshold = self._calculate_dynamic_threshold(embeddings)
        logger.info(f"Dynamic similarity threshold: {dynamic_threshold:.4f} (percentile: {self.similarity_percentile})")
        
        chunks = self._group_by_similarity(sentences, embeddings, dynamic_threshold)
        
        chunks = self._apply_size_constraints(chunks)
        
        return chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:

        paragraphs = re.split(r"\n\n+", text.strip())
        sentences = []
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            sentence_splits = re.split(r'(?<=[.!?])\s+', para)
            for sent in sentence_splits:
                sent = sent.strip()
                if sent:
                    sentences.append(sent)
        
        return sentences
    
    async def _get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        all_embeddings = []
        
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            embeddings = await self.embedding_provider.embed_texts(batch)
            all_embeddings.extend(embeddings)
        
        return all_embeddings
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        vec1_np = np.array(vec1)
        vec2_np = np.array(vec2)
        
        dot_product = np.dot(vec1_np, vec2_np)
        norm1 = np.linalg.norm(vec1_np)
        norm2 = np.linalg.norm(vec2_np)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def _calculate_dynamic_threshold(self, embeddings: List[List[float]]) -> float:
        if len(embeddings) < 2:
            return 0.75
        
        consecutive_similarities = []
        for i in range(len(embeddings) - 1):
            similarity = self._cosine_similarity(embeddings[i], embeddings[i + 1])
            consecutive_similarities.append(similarity)
        
        if not consecutive_similarities:
            return 0.75
        
        threshold = np.percentile(consecutive_similarities, self.similarity_percentile)
        
        threshold = max(0.1, min(0.9, threshold))
        
        return threshold
    
    def _group_by_similarity(self, sentences: List[str], embeddings: List[List[float]], threshold: float) -> List[Dict[str, Any]]:
        if not sentences:
            return []
        
        chunks = []
        current_chunk_sentences = [sentences[0]]
        current_chunk_text = sentences[0]
        
        for i in range(1, len(sentences)):
            current_sentence = sentences[i]
            current_embedding = embeddings[i]
            prev_embedding = embeddings[i - 1]
            
            similarity = self._cosine_similarity(current_embedding, prev_embedding)
            
            potential_size = len(current_chunk_text) + len(current_sentence) + 2 
            if (similarity < threshold and 
                len(current_chunk_text) >= self.min_chunk_size) or \
               (potential_size > self.max_chunk_size and 
                len(current_chunk_text) >= self.min_chunk_size):
                
                chunks.append({
                    "content": current_chunk_text.strip(),
                    "header": "",
                })
                
                current_chunk_sentences = [current_sentence]
                current_chunk_text = current_sentence
            else:
                current_chunk_sentences.append(current_sentence)
                current_chunk_text += " " + current_sentence
        
        if current_chunk_text.strip():
            chunks.append({
                "content": current_chunk_text.strip(),
                "header": "",
            })
        
        return chunks
    
    def _apply_size_constraints(self, chunks: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not chunks:
            return []
        
        valid_chunks = []
        for chunk in chunks:
            if len(chunk["content"]) >= self.min_chunk_size:
                valid_chunks.append(chunk)
        
        if not valid_chunks and chunks:
            return chunks
        
        if len(valid_chunks) <= 1:
            return valid_chunks
        
        overlapped = []
        for i, chunk in enumerate(valid_chunks):
            content = chunk["content"]
            
            if i > 0 and self.chunk_overlap > 0: 
                prev_content = valid_chunks[i - 1]["content"]
                words = prev_content.split()
                overlap_words = words[-self.chunk_overlap:] if len(words) > self.chunk_overlap else words
                overlap_text = " ".join(overlap_words)
                content = overlap_text + " " + content
            
            overlapped.append({
                "content": content,
                "header": chunk["header"],
            })
        
        return overlapped


@track_step_duration("chunk")
async def chunk_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:

    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    if not document.markdown_content:
        raise ValueError(f"Document {document_id} has no markdown content")
    
    chunker = SemanticChunker(
        max_chunk_size=1000,
        chunk_overlap=200,
        min_chunk_size=100,
        similarity_percentile=25.0,
        batch_size=100
    )
    
    raw_chunks = await chunker.chunk(document.markdown_content)
    
    if not raw_chunks:
        logger.warning(f"No chunks generated for document {document_id}")
        return {"chunk_count": 0, "chunk_hashes": []}
    
    chunk_data_list = []
    chunk_hashes = []
    
    for idx, raw_chunk in enumerate(raw_chunks):
        hasher = blake3.blake3()
        hasher.update(raw_chunk["content"].encode('utf-8'))
        chunk_hash = hasher.hexdigest()
        
        # 4-tier Chunk Fingerprint: guarantees deterministic uniqueness per document slot
        fingerprint_hasher = blake3.blake3()
        fingerprint_hasher.update(f"{document_id}:{idx}:{chunk_hash}".encode('utf-8'))
        chunk_fingerprint = fingerprint_hasher.hexdigest()
        
        chunk_hashes.append(chunk_hash)
        embedding_id = uuid.uuid4()

        chunk_data = {
            "document_id": str(document_id),
            "chunk_index": idx,
            "content": raw_chunk["content"],
            "chunk_hash": chunk_hash,
            "embedding_id": str(embedding_id),
            "embed_status": "pending",
            "chunk_source": "auto",
            "meta_data": {
                "chunk_fingerprint": chunk_fingerprint,
            },
        }
        
        chunk_data_list.append(chunk_data)
    
    pipeline_state.chunk_hashes = chunk_hashes
    pipeline_state.expected_chunk_count = len(chunk_data_list)
    pipeline_state.chunk.metadata["chunk_data_list"] = chunk_data_list
    
    logger.info(
        f"Generated {len(chunk_data_list)} chunks for document {document_id} "
        f"(expected_chunk_count={pipeline_state.expected_chunk_count})"
    )
    
    return {
        "chunk_count": len(chunk_data_list),
        "expected_chunk_count": len(chunk_data_list),
        "chunk_hashes": chunk_hashes,
        "chunk_data_list": chunk_data_list,
    }
