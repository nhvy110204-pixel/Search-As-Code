from typing import List, Any, Dict
from app.sdk.types import SearchHit

def join_result_fields(hits: List[SearchHit], field: str = "content", separator: str = "\n\n") -> str:
    """Joins a specific field of hits together into a single string."""
    values = []
    for hit in hits:
        if isinstance(hit, dict):
            val = hit.get(field, "")
        elif hasattr(hit, field):
            val = getattr(hit, field)
        else:
            val = ""
        if val:
            values.append(str(val))
    return separator.join(values)

def flatten(lst: List[List[Any]]) -> List[Any]:
    """Flattens a list of lists into a 1D list."""
    flat_list = []
    for sublist in lst:
        if isinstance(sublist, list):
            flat_list.extend(sublist)
        else:
            flat_list.append(sublist)
    return flat_list

def unique(lst: List[Any]) -> List[Any]:
    """Deduplicates a list while preserving original ordering."""
    seen = set()
    result = []
    for item in lst:
        # If item is not hashable, we fallback to string comparison
        try:
            h = item
            is_new = h not in seen
            if is_new:
                seen.add(h)
        except TypeError:
            h = str(item)
            is_new = h not in seen
            if is_new:
                seen.add(h)
        if is_new:
            result.append(item)
    return result

def summarize(text: str, max_chars: int = 500) -> str:
    """Returns a simple truncated summary of a given string."""
    if not text:
        return ""
    text_clean = " ".join(text.strip().split())
    if len(text_clean) <= max_chars:
        return text_clean
    return text_clean[:max_chars] + "..."

def infer_vendor(text: str) -> str:
    """Helper tool to infer the product vendor name from text signatures (CVE specific utility)."""
    if not text:
        return "unknown"
    import re
    # Simple regex heuristics to look for vendor signatures
    text_lower = text.lower()
    vendors = ["microsoft", "apple", "google", "linux", "cisco", "oracle", "apache", "nginx", "adobe", "ibm", "intel", "amd"]
    for v in vendors:
        if v in text_lower:
            return v
    # Look for "vendor: name" or "by name"
    match = re.search(r"(?:vendor|company|product by)\s*:\s*([\w\-]+)", text_lower)
    if match:
        return match.group(1)
    return "unknown"

def official_vendor_advisory(url: str) -> bool:
    """Determines whether a source URL is from an official vendor advisory domain (CVE specific utility)."""
    if not url:
        return False
    url_lower = url.lower()
    official_domains = [
        "microsoft.com", "apple.com", "google.com", "cisco.com", "oracle.com",
        "redhat.com", "ubuntu.com", "debian.org", "apache.org", "nginx.org",
        "adobe.com", "ibm.com", "intel.com", "amd.com", "nvd.nist.gov", "cve.org"
    ]
    return any(domain in url_lower for domain in official_domains)
