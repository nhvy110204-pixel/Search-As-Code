from typing import List, Dict, Any, Optional
import random
import re

def cluster(
    items: List[Any],
    vectors: List[List[float]],
    n_clusters: int = 5
) -> List[List[Any]]:
    """K-means clustering in pure Python (no dependencies, sandbox friendly)."""
    if not items or not vectors or len(items) != len(vectors):
        return [items] if items else []
    
    n_clusters = min(n_clusters, len(items))
    if n_clusters <= 1:
        return [items]

    # Initialize centroids randomly from points
    centroids = random.sample(vectors, n_clusters)
    dim = len(vectors[0])

    for _ in range(10):  # Run for 10 iterations to group search hits
        clusters = [[] for _ in range(n_clusters)]
        cluster_items = [[] for _ in range(n_clusters)]

        for item, vec in zip(items, vectors):
            min_dist = float("inf")
            best_idx = 0
            for idx, centroid in enumerate(centroids):
                # Euclidean distance squared
                dist = sum((x - y) ** 2 for x, y in zip(vec, centroid))
                if dist < min_dist:
                    min_dist = dist
                    best_idx = idx
            clusters[best_idx].append(vec)
            cluster_items[best_idx].append(item)

        # Update centroids
        new_centroids = []
        for idx, cluster_vecs in enumerate(clusters):
            if not cluster_vecs:
                new_centroids.append(centroids[idx])
                continue
            mean_vec = [sum(pt[d] for pt in cluster_vecs) / len(cluster_vecs) for d in range(dim)]
            new_centroids.append(mean_vec)
        centroids = new_centroids

    return [c for c in cluster_items if c]

def chunk(
    text: str,
    strategy: str = "paragraph",   # "sentence" | "paragraph" | "fixed"
    size: int = 512
) -> List[str]:
    """Split text into chunks based on selected strategy."""
    if not text:
        return []
        
    if strategy == "fixed":
        return [text[i:i+size] for i in range(0, len(text), size)]
        
    elif strategy == "sentence":
        sentences = re.split(r'(?<=[.!?]) +', text.strip())
        chunks = []
        current = []
        current_len = 0
        for s in sentences:
            if current_len + len(s) > size:
                if current:
                    chunks.append(" ".join(current))
                current = [s]
                current_len = len(s)
            else:
                current.append(s)
                current_len += len(s) + 1
        if current:
            chunks.append(" ".join(current))
        return chunks
        
    else:  # strategy == "paragraph"
        paragraphs = text.split("\n\n")
        chunks = []
        current = []
        current_len = 0
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            if current_len + len(p) > size:
                if current:
                    chunks.append("\n\n".join(current))
                # If paragraph exceeds size, split it into sentence chunks
                if len(p) > size:
                    chunks.extend(chunk(p, strategy="sentence", size=size))
                    current = []
                    current_len = 0
                else:
                    current = [p]
                    current_len = len(p)
            else:
                current.append(p)
                current_len += len(p) + 2
        if current:
            chunks.append("\n\n".join(current))
        return chunks

def parse_field(
    hit: Any,
    field: str   # "published_date" | "severity" | "cve_id" | ...
) -> Any:
    """Extract and normalize specific CVE or metadata fields from a search hit."""
    if isinstance(hit, dict):
        content = hit.get("content", "")
        metadata = hit.get("metadata", {})
    else:
        content = getattr(hit, "content", "")
        metadata = getattr(hit, "metadata", {})

    if field in metadata:
        return metadata[field]

    search_text = f"{content} {str(metadata)}"
    
    if field == "cve_id":
        match = re.search(r"(CVE-\d{4}-\d{4,7})", search_text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
            
    elif field == "severity":
        match = re.search(r"\b(critical|high|medium|low|info)\b", search_text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
            
    elif field == "published_date":
        match = re.search(r"(\d{4}-\d{2}-\d{2})", search_text)
        if match:
            return match.group(1)
            
    return None
