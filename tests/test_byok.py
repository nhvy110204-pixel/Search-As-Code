import pytest
import uuid
import json
from unittest.mock import patch, MagicMock, AsyncMock
from app.core.encryption import encrypt_api_keys, decrypt_api_keys
from app.core.llm_factory import get_llm_client
from app.config.settings import settings
from app.services.chat.stream import ChatStreamService
from app.models.chat_session import ChatSession
from app.models.user import User
from app.schemas.dto.chat import PreparedChatStream

def test_encryption_decryption_success():
    keys = {"openai": "sk-proj-test1234", "anthropic": "sk-ant-test5678"}
    
    # 1. Encrypt keys
    encrypted = encrypt_api_keys(keys)
    assert isinstance(encrypted, str)
    assert len(encrypted) > 0
    
    # 2. Decrypt keys
    decrypted = decrypt_api_keys(encrypted)
    assert decrypted == keys

def test_decryption_empty_and_invalid():
    # Empty input
    assert decrypt_api_keys("") == {}
    assert decrypt_api_keys(None) == {}
    # Invalid key
    assert decrypt_api_keys("not-encrypted-payload") == {}

@patch("app.core.llm_factory.settings")
def test_llm_factory_routing(mock_settings):
    # Setup global settings mocks
    mock_settings.CHAT_MODEL_NAME = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "global-openai-key"
    mock_settings.LITELLM_PROXY_URL = "http://litellm-proxy"
    mock_settings.LITELLM_PROXY_KEY = "proxy-key"

    # Scenario A: User BYOK key is provided
    config_byok = {"configurable": {"user_api_keys": {"openai": "user-key-123"}}}
    client_byok = get_llm_client(config_byok)
    assert client_byok.openai_api_key.get_secret_value() == "user-key-123"
    assert client_byok.openai_api_base is None

    # Scenario B: User key is absent, but platform LiteLLM Proxy is configured
    config_proxy = {"configurable": {}}
    client_proxy = get_llm_client(config_proxy)
    assert client_proxy.openai_api_key.get_secret_value() == "proxy-key"
    assert client_proxy.openai_api_base == "http://litellm-proxy"

    # Scenario C: Both user key and proxy config are missing
    mock_settings.LITELLM_PROXY_URL = None
    mock_settings.LITELLM_PROXY_KEY = None
    config_fallback = {}
    client_fallback = get_llm_client(config_fallback)
    assert client_fallback.openai_api_key.get_secret_value() == "global-openai-key"
    assert client_fallback.openai_api_base is None

@pytest.mark.anyio
@patch("app.services.core.redis_service.redis_cache_service.redis")
@patch("app.graph.graphs.agent_graph.agent_graph.aget_state", new_callable=AsyncMock)
@patch("app.graph.graphs.agent_graph.agent_graph.astream_events")
async def test_stream_sac_events_injects_byok_keys(mock_astream_events, mock_aget_state, mock_redis):
    # Setup mock stream generator
    async def mock_events_generator(*args, **kwargs):
        # Capture config parameter passed to astream_events to inspect configurable key injection
        config_passed = kwargs.get("config", {})
        assert "user_api_keys" in config_passed.get("configurable", {})
        assert config_passed["configurable"]["user_api_keys"] == {"openai": "my-secret-user-key"}
        yield {"event": "on_chain_start", "metadata": {"langgraph_node": "planner"}, "data": {}}
        
    mock_astream_events.side_effect = mock_events_generator
    
    # Mock final state
    mock_state_obj = MagicMock()
    mock_state_obj.values = {"final_answer": "Answer", "total_tokens": 10}
    mock_aget_state.return_value = mock_state_obj

    # Prepare stream request
    prepared = PreparedChatStream(
        run_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_message_id=uuid.uuid4(),
        assistant_message_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "Hello"}]
    )

    # Encrypt user api key
    user_keys = {"openai": "my-secret-user-key"}
    encrypted_keys = encrypt_api_keys(user_keys)

    # Mock DB Session & lookup
    mock_db = MagicMock()
    mock_session_factory = MagicMock()
    mock_db_session = MagicMock()
    mock_session_factory.return_value = mock_db_session
    
    mock_chat_session = MagicMock()
    mock_chat_session.project_id = uuid.uuid4()
    
    mock_user = MagicMock()
    mock_user.id = prepared.user_id
    mock_user.encrypted_custom_api_keys = encrypted_keys
    
    # Setup DB sequence
    mock_db_session.query().filter().first.side_effect = [mock_chat_session, mock_user]

    service = ChatStreamService(db=mock_db, session_factory=mock_session_factory)
    service.outcome = MagicMock()

    async def is_disconnected():
        return False

    # Collect events to trigger generator run
    events = []
    async for event in service.stream_events(prepared, is_disconnected):
        events.append(event)

    # Ensure generator ran successfully and checked user_api_keys injection
    assert len(events) > 0
