import pytest
from unittest.mock import AsyncMock, patch
from app.guardrails.alignment import build_proactive_refusal
from app.guardrails.redactor import redact_sensitive_data, redact_text, truncate_source_snippets
from app.guardrails.router import check_query_relevance

def test_build_proactive_refusal_empty():
    res = build_proactive_refusal([])
    assert "no documents uploaded" in res.lower()
    assert "What was checked:" in res

def test_build_proactive_refusal_files():
    res = build_proactive_refusal(["policy.pdf", "readme.md"])
    assert "policy.pdf" in res
    assert "readme.md" in res
    assert "Please ask questions related to the content" in res

def test_redact_sensitive_data_primitives():
    # Test DB password redaction
    db_url = "postgresql+psycopg://myuser:mypassword123@localhost:5432/mydb"
    assert "postgresql+psycopg://myuser:[REDACTED]@localhost:5432/mydb" in redact_text(db_url)

    # Test OpenAI API key redaction
    openai_key = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    assert "sk-proj-...[REDACTED]" in redact_text(openai_key)

    # Test Bearer token redaction
    bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
    assert "Bearer ...[REDACTED]" in redact_text(bearer)

def test_redact_sensitive_data_recursive():
    payload = {
        "api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",
        "nested": {
            "db_conn": "postgresql://dbuser:supersecretpass@localhost:5432/db",
            "safe_val": 42
        },
        "list_val": [
            "sk-proj-anotherkey12345",
            "just safe text"
        ]
    }
    redacted = redact_sensitive_data(payload)
    assert redacted["api_key"] == "sk-proj-...[REDACTED]"
    assert redacted["nested"]["db_conn"] == "postgresql://dbuser:[REDACTED]@localhost:5432/db"
    assert redacted["nested"]["safe_val"] == 42
    assert redacted["list_val"][0] == "sk-proj-...[REDACTED]"
    assert redacted["list_val"][1] == "just safe text"

def test_truncate_source_snippets():
    text = "A" * 1200
    truncated = truncate_source_snippets(text, max_chars=1000)
    assert len(truncated) < 1200
    assert "... [TRUNCATED - EXCEEDED 1000 CHARS LIMIT]" in truncated

@pytest.mark.anyio
async def test_check_query_relevance_empty_files():
    res = await check_query_relevance("What is the capital of France?", [])
    assert res is False

@pytest.mark.anyio
async def test_check_query_relevance_greeting():
    res = await check_query_relevance("Hello there!", ["policy.pdf"])
    assert res is False

@pytest.mark.anyio
async def test_check_query_relevance_in_scope():
    # Mock ChatOpenAI ainvoke
    mock_response = AsyncMock()
    mock_response.content = "IN_SCOPE"
    
    with patch("app.guardrails.router.ChatOpenAI") as mock_chat:
        mock_instance = mock_chat.return_value
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        
        res = await check_query_relevance("What is our security policy?", ["security_policy.pdf"])
        assert res is True
        
        # Verify it passed the right model and prompt structure
        mock_chat.assert_called_once()
        assert mock_chat.call_args[1]["model"] == "gpt-4o-mini"
        assert mock_chat.call_args[1]["temperature"] == 0.0

@pytest.mark.anyio
async def test_check_query_relevance_out_scope():
    # Mock ChatOpenAI ainvoke
    mock_response = AsyncMock()
    mock_response.content = "OUT_SCOPE"
    
    with patch("app.guardrails.router.ChatOpenAI") as mock_chat:
        mock_instance = mock_chat.return_value
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        
        res = await check_query_relevance("How do I make chocolate cake?", ["security_policy.pdf"])
        assert res is False
        
@pytest.mark.anyio
async def test_check_query_relevance_error_fallback():
    # Verify that if an exception occurs during the LLM call, we fail-open (return True)
    with patch("app.guardrails.router.ChatOpenAI") as mock_chat:
        mock_instance = mock_chat.return_value
        mock_instance.ainvoke = AsyncMock(side_effect=Exception("OpenAI timeout"))
        
        res = await check_query_relevance("Some query", ["security_policy.pdf"])
        assert res is True  # Fail-open fallback
