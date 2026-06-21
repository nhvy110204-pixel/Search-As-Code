import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.sdk import sdk
from app.sdk.types import SearchHit, ExtractionResult

# 1. Test utilities
def test_sdk_utilities():
    # Test flatten
    assert sdk.flatten([[1, 2], [3], [4, 5]]) == [1, 2, 3, 4, 5]
    
    # Test unique
    assert sdk.unique([1, 2, 2, 3, 1, 4]) == [1, 2, 3, 4]
    assert sdk.unique([{"a": 1}, {"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    # Test join_result_fields
    hits = [
        SearchHit(id="1", title="T1", content="Content one"),
        SearchHit(id="2", title="T2", content="Content two")
    ]
    assert sdk.join_result_fields(hits, separator=" | ") == "Content one | Content two"
    
    # Test summarize
    text = "This is a very long text that we want to summarize using our simple character truncation helper."
    assert sdk.summarize(text, max_chars=10) == "This is a ..."

    # Test infer_vendor & official_vendor_advisory
    assert sdk.infer_vendor("This is a vulnerability in Apple Kernel.") == "apple"
    assert sdk.official_vendor_advisory("https://support.apple.com/en-us/HT213841") is True
    assert sdk.official_vendor_advisory("https://malicious-site.com/exploit") is False

# 2. Test transform primitives
def test_sdk_transforms():
    # Test chunk
    text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
    chunks = sdk.chunk(text, strategy="paragraph", size=20)
    assert len(chunks) == 3
    assert chunks[0] == "Paragraph 1"
    
    # Test parse_field
    hit = SearchHit(
        id="cve-123",
        title="CVE Info",
        content="Severity is CRITICAL, CVE-2023-38606 is verified. Published on 2023-07-24."
    )
    assert sdk.parse_field(hit, "cve_id") == "CVE-2023-38606"
    assert sdk.parse_field(hit, "severity") == "critical"
    assert sdk.parse_field(hit, "published_date") == "2023-07-24"

    # Test K-Means clustering (pure python)
    items = ["A", "B", "C", "D"]
    vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]]
    clusters = sdk.cluster(items, vectors, n_clusters=2)
    assert len(clusters) == 2
    # Check that similar vectors are grouped together
    assert ("A" in clusters[0] and "B" in clusters[0]) or ("A" in clusters[1] and "B" in clusters[1])

# 3. Test low-level processing primitives
def test_sdk_processing():
    # Test rank
    hits = [
        SearchHit(id="1", content="H1", score=0.5),
        SearchHit(id="2", content="H2", score=0.9),
        SearchHit(id="3", content="H3", score=0.7)
    ]
    ranked = sdk.rank(hits, top_k=2)
    assert len(ranked) == 2
    assert ranked[0].id == "2"
    assert ranked[1].id == "3"

    # Test dedupe
    items = [{"url": "abc", "val": 1}, {"url": "def", "val": 2}, {"url": "abc", "val": 3}]
    deduped = sdk.dedupe(items, key="url")
    assert len(deduped) == 2
    assert deduped[0]["val"] == 1
    assert deduped[1]["val"] == 2

@pytest.mark.anyio
@patch("app.core.qdrant.qdrant_manager.search_vectors")
@patch("app.rag.embeddings.manager.EmbeddingManager.get_provider")
async def test_sdk_low_level_retrieval(mock_get_provider, mock_search_vectors, tmp_path):
    # Mock embedding provider
    mock_provider = MagicMock()
    mock_provider.embed_text = MagicMock(return_value=[0.1, 0.2, 0.3])
    mock_get_provider.return_value = mock_provider

    # Mock Qdrant results
    mock_search_vectors.return_value = [
        {
            "embedding_id": "cve-1",
            "score": 0.99,
            "payload": {
                "title": "Mock CVE Title",
                "content": "Mock CVE content detail",
                "url": "https://example.com/cve-1",
                "document_id": "doc-123",
                "project_id": "proj-456",
                "chunk_index": 0
            }
        }
    ]

    # Test retrieve (index source)
    hits = await sdk.retrieve("CVE-2023-38606 apple kernel", source="index", limit=2)
    assert len(hits) == 1
    assert hits[0].id == "cve-1"
    assert "Mock CVE Title" in hits[0].title

    # Test that source="web" redirects to "index"
    hits_web = await sdk.retrieve("CVE-2023-38606 apple kernel", source="web", limit=2)
    assert len(hits_web) == 1
    assert hits_web[0].id == "cve-1"

    # Test fanout
    variants = [
        "CVE {q} details",
        "{q} kernel vulnerability"
    ]
    with patch("app.sdk.low_level.retrieval.retrieve", new_callable=AsyncMock) as mock_ret:
        mock_ret.return_value = [SearchHit(id="fan-1", title="F1", content="C1")]
        fanout_hits = await sdk.fanout(base_query="CVE-2023-38606", variants=variants)
        assert len(fanout_hits) > 0
        unique_ids = [h.id for h in fanout_hits]
        assert len(unique_ids) == len(set(unique_ids))

@pytest.mark.anyio
@patch("app.rag.embeddings.manager.EmbeddingManager.get_provider")
async def test_sdk_low_level_embed(mock_get_provider):
    # Mock embedding provider
    mock_provider = MagicMock()
    mock_provider.embed_texts = MagicMock(return_value=[[0.1, 0.2, 0.3]])
    mock_get_provider.return_value = mock_provider

    res = await sdk.embed(["test text"])
    assert res == [[0.1, 0.2, 0.3]]
    mock_provider.embed_texts.assert_called_once_with(["test text"])

# 4. Test high-level abstractions with LLM mocks
@pytest.mark.anyio
@patch("openai.resources.chat.completions.AsyncCompletions.create", new_callable=AsyncMock)
async def test_sdk_high_level_llm(mock_chat_create):
    # Mock OpenAI response for extract_single / query_llm
    mock_choice = MagicMock()
    mock_choice.message.content = '{"cve": "CVE-2023-38606", "vendor": "Apple"}'
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_chat_create.return_value = mock_resp

    # Test query_llm
    res_query = await sdk.llm.query_llm("test prompt")
    assert "CVE-2023-38606" in res_query

    # Test extract_many
    items = [{"raw_text": "Apple kernel CVE-2023-38606 patched in iOS 16.6"}]
    schema = {"type": "object", "properties": {"cve": {"type": "string"}}}
    extracted = await sdk.llm.extract_many(items, "Extract CVE info", schema=schema)
    assert len(extracted) == 1
    assert extracted[0]["matches"] is True
    assert extracted[0]["data"]["cve"] == "CVE-2023-38606"

@pytest.mark.anyio
@patch("app.sdk.low_level.retrieval.retrieve", new_callable=AsyncMock)
@patch("app.sdk.high_level.llm.LLMSDK.query_llm", new_callable=AsyncMock)
async def test_sdk_high_level_search(mock_query_llm, mock_retrieve):
    # Mock LLM query refinement
    mock_query_llm.return_value = "apple support CVE-2023-38606"

    # Mock retrieve output
    mock_hit = SearchHit(
        id="cve-1",
        title="Mock CVE Title",
        content="Mock CVE content detail",
        url="https://example.com/cve-1"
    )
    mock_retrieve.return_value = [mock_hit]

    # Test web_many
    queries = [{"query": "CVE-2023-38606"}, {"query": "apple kernel exploit"}]
    many_results = await sdk.search.web_many(queries, limit_per_query=2)
    assert len(many_results) == 2
    assert len(many_results[0]) > 0
    assert many_results[0][0].id == "cve-1"

    # Test deep_search
    deep_results = await sdk.search.deep_search("CVE-2023-38606", depth=2)
    assert len(deep_results) > 0
    assert deep_results[0].id == "cve-1"
    # Refinement LLM call is invoked
    mock_query_llm.assert_called_once()
