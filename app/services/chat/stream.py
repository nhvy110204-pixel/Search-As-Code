"""Main chat streaming service - orchestrates all components."""

import logging
import uuid
import time
import tempfile
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from blake3 import blake3
from pathlib import Path
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.core.database import SessionLocal
from app.core.logger import service_boundary
from app.models.chat_stream_run import ChatStreamRun
from app.models.user import User
from app.observability.metrics import record_chat_stream_started
from app.core.langfuse_tracing import get_langfuse_callback
from app.repositories.chat_message import ChatMessageRepository
from app.repositories.chat_stream_run import ChatStreamRunRepository
from app.schemas.dto.chat import ChatStreamRequest, PreparedChatStream
from app.services.chat.idempotency import ChatStreamIdempotencyHandler
from app.services.chat.outcome import ChatStreamOutcomeHandler
from app.services.chat.preparer import ChatStreamPreparer
from app.services.chat.providers import ChatCompletionProvider, OpenAIChatCompletionProvider
from app.services.chat.streamer import ChatStreamer
from app.services.chat.validators import ChatStreamValidator
from app.shared.enums import ChatStreamStatus
from app.graph.graphs.agent_graph import agent_graph
from app.models.chat_session import ChatSession
from app.services.chat.stream_state import stream_state_manager

from app.services.chat.semantic_cache import semantic_cache
from app.tasks.chat_tasks import save_semantic_cache
from app.services.core.redis_service import redis_cache_service

logger = logging.getLogger(__name__)


class ChatStreamService:

    def __init__(
        self,
        db: Session,
        provider: ChatCompletionProvider | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
    ):
        self.db = db
        self.session_factory = session_factory

        if provider is None:
            try:
                self.provider = OpenAIChatCompletionProvider()
            except Exception as exc:
                logger.error("Failed to initialize OpenAI provider: %s", exc)
                raise RuntimeError("Failed to initialize chat provider. Check API key configuration.") from exc
        else:
            self.provider = provider

        self.stream_run_repo = ChatStreamRunRepository(db)
        self.message_repo = ChatMessageRepository(db)

        self.validator = ChatStreamValidator(self.stream_run_repo)
        self.idempotency = ChatStreamIdempotencyHandler(self.stream_run_repo, self.message_repo)
        self.preparer = ChatStreamPreparer(db)
        self.streamer = ChatStreamer(self.provider)
        self.outcome = ChatStreamOutcomeHandler(session_factory, self.stream_run_repo)

    @service_boundary("Prepare Chat Stream")
    async def prepare_stream(self, payload: ChatStreamRequest, user: User) -> PreparedChatStream:
        content = payload.message.strip()
        self.validator.validate_message(content)

        idempotent_run = self.idempotency.get_idempotent_run(user.id, payload.client_request_id)
        if idempotent_run:
            self.idempotency.validate_idempotent_payload(
                idempotent_run,
                payload.session_id,
                payload.parent_id,
                content,
            )
            replay_data = self.idempotency.prepare_idempotent_response(idempotent_run)
            return self._create_prepared_stream_for_replay(
                idempotent_run,
                replay_data,
            )

        self.validator.enforce_rate_limits(user.id)

        # Tải ChatSession để xác định project_id và kiểm tra quyền sở hữu
        chat_session = self.db.query(ChatSession).filter(ChatSession.id == payload.session_id).first()
        if not chat_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found"
            )
        if chat_session.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chat session does not belong to user"
            )
        project_id = chat_session.project_id

        # Kiểm tra Semantic Cache (Lock và đọc cache)
        
        query_hash = blake3(content.encode("utf-8")).hexdigest()
        cached_answer, lock_acquired = await semantic_cache.get_or_lock(content, project_id=str(project_id))
        
        if cached_answer:
            # Cache Hit: Tạo nhanh tin nhắn ở trạng thái COMPLETED trong DB
            user_message, assistant_message = self.preparer.prepare_messages_for_cache_hit(
                payload.session_id,
                payload.parent_id,
                content,
                user.id,
                cached_answer["content"]
            )
            
            run = self._create_stream_run_for_cache_hit(
                user.id,
                payload.session_id,
                payload.client_request_id,
                user_message.id,
                assistant_message.id,
                content,
                payload.parent_id,
            )
            
            logger.info(
                f"Semantic Cache Hit hoàn tất: session_id={payload.session_id}, user_id={user.id}"
            )
            
            return PreparedChatStream(
                run_id=run.id,
                user_id=user.id,
                project_id=project_id,
                session_id=payload.session_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                messages=[],
                client_request_id=payload.client_request_id,
                replay_content=cached_answer["content"],
                replay_prompt_tokens=cached_answer.get("prompt_tokens", 0),
                replay_completion_tokens=cached_answer.get("completion_tokens", 0),
                query_hash=query_hash
            )

        user_message, assistant_message = self.preparer.prepare_messages(
            payload.session_id,
            payload.parent_id,
            content,
            user.id,
        )

        messages = self.preparer.build_provider_messages(payload.session_id, content)

        run = self._create_stream_run(
            user.id,
            payload.session_id,
            payload.client_request_id,
            user_message.id,
            assistant_message.id,
            content,
            payload.parent_id,
        )

        record_chat_stream_started()
        logger.info(
            "chat stream started run_id=%s session_id=%s user_id=%s client_request_id=%s",
            run.id,
            payload.session_id,
            user.id,
            payload.client_request_id,
        )

        return PreparedChatStream(
            run_id=run.id,
            user_id=user.id,
            project_id=project_id,
            session_id=payload.session_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            messages=messages,
            client_request_id=payload.client_request_id,
            query_hash=query_hash if lock_acquired else None
        )

    async def stream_events(
        self,
        prepared: PreparedChatStream,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict[str, str]]:
        if prepared.replay_content is not None:
            yield self.streamer._create_event(
                1,
                "message.done",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "content": prepared.replay_content,
                    "prompt_tokens": prepared.replay_prompt_tokens,
                    "completion_tokens": prepared.replay_completion_tokens,
                },
            )
            return

        # Look up project_id and encrypted_custom_api_keys
        project_id = None
        encrypted_keys = None
        db_session = self.session_factory()
        try:
            session_obj = db_session.query(ChatSession).filter(ChatSession.id == prepared.session_id).first()
            if session_obj:
                project_id = str(session_obj.project_id)
            user_obj = db_session.query(User).filter(User.id == prepared.user_id).first()
            if user_obj:
                encrypted_keys = user_obj.encrypted_custom_api_keys
        except Exception as e:
            logger.error(f"Failed to fetch chat session/user in stream_sac_events: {e}")
        finally:
            db_session.close()

        from app.core.encryption import decrypt_api_keys
        from app.models.user import User
        decrypted_keys = decrypt_api_keys(encrypted_keys)

        if not project_id:
            yield self.streamer._create_event(
                1,
                "error",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "code": "invalid_session",
                    "message": "Chat session does not have an associated project."
                }
            )
            return

        started_at = time.perf_counter()
        event_id = 1
        content_parts: list[str] = []

        # Yield message.created
        yield self.streamer._create_event(
            event_id,
            "message.created",
            {"message_id": str(prepared.assistant_message_id)}
        )
        event_id += 1

        # Establish state dir
        state_dir = Path(tempfile.gettempdir()) / "sac_states" / str(prepared.run_id)
        state_dir.mkdir(parents=True, exist_ok=True)

        # Build initial AgentState
        directive_text = ""
        if prepared.messages:
            directive_text = prepared.messages[-1].get("content", "")
        else:
            directive_text = "Analyze project sources"

        initial_state = {
            "task_id": str(prepared.run_id),
            "directive": directive_text,
            "state_dir": str(state_dir),
            "project_id": project_id,
            "user_id": str(prepared.user_id),
            "turns": [],
            "current_turn": 0,
            "max_turns": 10,
            "messages": [],
            "total_sdk_calls": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "is_complete": False
        }

        # Keep track of when nodes start to calculate duration_ms
        node_start_times = {}

        # Initialize Langfuse callback handler
        langfuse_callback = get_langfuse_callback(
            user_id=prepared.user_id,
            session_id=prepared.session_id,
            trace_id=prepared.run_id,
            project_id=project_id,
            assistant_message_id=prepared.assistant_message_id
        )

        try:
            # Run LangGraph using astream_events
            async for event in agent_graph.astream_events(
                initial_state,
                version="v1",
                config={
                    "configurable": {
                        "thread_id": str(prepared.session_id),
                        "user_api_keys": decrypted_keys
                    },
                    "callbacks": [langfuse_callback] if langfuse_callback else []
                }
            ):
                # Check for remote cancellation flag and connection disconnects
                if await is_disconnected() or stream_state_manager.is_cancelled(prepared.run_id):
                    logger.info(f"Ngắt luồng stream SaC Agent sớm do nhận được tín hiệu hủy: run_id={prepared.run_id}")
                    # Mark failed in DB
                    self.outcome.mark_failed(
                        prepared,
                        "".join(content_parts),
                        "cancelled",
                        "Stream cancelled by user",
                        started_at,
                        None
                    )
                    yield self.streamer._create_event(
                        event_id,
                        "error",
                        {
                            "message_id": str(prepared.assistant_message_id),
                            "code": "cancelled",
                            "message": "Stream cancelled by user",
                        }
                    )
                    return

                event_name = event.get("event")
                meta = event.get("metadata", {})
                node_name = meta.get("langgraph_node")

                # Track node starts
                if event_name == "on_chain_start" and node_name:
                    node_start_times[node_name] = time.perf_counter()
                    if node_name == "planner":
                        yield self.streamer._create_event(
                            event_id,
                            "agent.plan",
                            {"message_id": str(prepared.assistant_message_id), "status": "started"}
                        )
                        event_id += 1
                    elif node_name == "reasoner":
                        yield self.streamer._create_event(
                            event_id,
                            "agent.code",
                            {"message_id": str(prepared.assistant_message_id), "status": "started"}
                        )
                        event_id += 1
                    elif node_name == "executor":
                        yield self.streamer._create_event(
                            event_id,
                            "agent.executing",
                            {"message_id": str(prepared.assistant_message_id), "status": "started"}
                        )
                        event_id += 1
                    elif node_name == "citation_validator":
                        yield self.streamer._create_event(
                            event_id,
                            "agent.validating_citations",
                            {"message_id": str(prepared.assistant_message_id), "status": "started"}
                        )
                        event_id += 1

                # Track node ends to retrieve final node outputs and calculate durations
                elif event_name == "on_chain_end" and node_name:
                    start_time = node_start_times.get(node_name, time.perf_counter())
                    duration_ms = int((time.perf_counter() - start_time) * 1000)

                    output_data = event.get("data", {}).get("output", {})
                    if isinstance(output_data, dict):
                        if node_name == "planner":
                            messages = output_data.get("messages", [])
                            plan_text = ""
                            if messages:
                                plan_text = getattr(messages[-1], "content", str(messages[-1]))
                            yield self.streamer._create_event(
                                event_id,
                                "agent.plan",
                                {
                                    "message_id": str(prepared.assistant_message_id),
                                    "status": "completed",
                                    "plan": plan_text,
                                    "duration_ms": duration_ms
                                }
                            )
                            event_id += 1

                        elif node_name == "reasoner":
                            code_val = output_data.get("_pending_code") or ""
                            yield self.streamer._create_event(
                                event_id,
                                "agent.code",
                                {
                                    "message_id": str(prepared.assistant_message_id),
                                    "status": "completed",
                                    "code": code_val,
                                    "duration_ms": duration_ms
                                }
                            )
                            event_id += 1

                        elif node_name == "executor":
                            turns = output_data.get("turns", [])
                            stdout_val = ""
                            stderr_val = ""
                            exit_code = 0
                            if turns:
                                last_turn = turns[-1]
                                stdout_val = last_turn.get("stdout", "")
                                stderr_val = last_turn.get("stderr", "")
                                exit_code = last_turn.get("returncode", 0)

                            yield self.streamer._create_event(
                                event_id,
                                "agent.sandbox_output",
                                {
                                    "message_id": str(prepared.assistant_message_id),
                                    "stdout": stdout_val,
                                    "stderr": stderr_val,
                                    "exit_code": exit_code,
                                    "duration_ms": duration_ms
                                }
                            )
                            event_id += 1

                        elif node_name == "execution_validator":
                            turns = output_data.get("turns", [])
                            if turns and turns[-1].get("returncode", 0) != 0:
                                last_turn = turns[-1]
                                retry_cnt = len(turns)
                                err_val = last_turn.get("stderr", "Unknown sandbox error")
                                yield self.streamer._create_event(
                                    event_id,
                                    "agent.debugging",
                                    {
                                        "message_id": str(prepared.assistant_message_id),
                                        "retry_count": retry_cnt,
                                        "error": err_val
                                    }
                                )
                                event_id += 1

                        elif node_name == "citation_validator":
                            unverified = output_data.get("unverified_claims")
                            if unverified:
                                yield self.streamer._create_event(
                                    event_id,
                                    "agent.debugging",
                                    {
                                        "message_id": str(prepared.assistant_message_id),
                                        "retry_count": output_data.get("citation_retry_counter", 1),
                                        "error": f"Invalid citations detected: {unverified}. Retrying finalizer node..."
                                    }
                                )
                                event_id += 1

                # Token-level LLM streaming events from the finalizer node
                elif event_name == "on_llm_stream" and node_name == "finalizer":
                    chunk_text = event.get("data", {}).get("chunk", "")
                    if hasattr(chunk_text, "content"):
                        chunk_text = chunk_text.content
                    elif isinstance(chunk_text, dict):
                        chunk_text = chunk_text.get("content", "")

                    if chunk_text:
                        content_parts.append(chunk_text)
                        yield self.streamer._create_event(
                            event_id,
                            "message.delta",
                            {"message_id": str(prepared.assistant_message_id), "content": chunk_text}
                        )
                        event_id += 1

            # Fetch the final state of the graph to log outcome and return final answer
            final_state = await agent_graph.aget_state(
                config={
                    "configurable": {
                        "thread_id": str(prepared.session_id),
                        "user_api_keys": decrypted_keys
                    }
                }
            )
            final_answer = final_state.values.get("final_answer") or "".join(content_parts)

            # Read citations if generated
            citations = []
            results_file = state_dir / "final_results.json"
            if results_file.exists():
                try:
                    import json
                    results_data = json.loads(results_file.read_text())
                    citations = results_data.get("evidence", [])
                except Exception:
                    pass

            # Mark complete in database
            prompt_tokens = final_state.values.get("total_tokens", 0)
            completion_tokens = 0
            first_delta_at = node_start_times.get("finalizer")

            self.outcome.mark_completed(
                prepared,
                final_answer,
                prompt_tokens,
                completion_tokens,
                started_at,
                first_delta_at
            )

            # Yield final message.done event
            yield self.streamer._create_event(
                event_id,
                "message.done",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "content": final_answer,
                    "citations": citations,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens
                }
            )

        except Exception as exc:
            logger.exception("Error in stream_sac_events: %s", exc)
            self.outcome.mark_failed(
                prepared,
                "".join(content_parts),
                "agent_failure",
                str(exc),
                started_at,
                None
            )
            yield self.streamer._create_event(
                event_id,
                "error",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "code": "agent_failure",
                    "message": f"Agent failed while processing: {str(exc)}",
                }
            )

        finally:
            # Clean up active run from Redis
            try:
                r = redis_cache_service.redis
                if r is not None:
                    active_key = f"chat:active:{prepared.user_id}"
                    r.zrem(active_key, str(prepared.run_id))
            except Exception as e:
                logger.warning("Failed to remove active run from Redis: %s", e)

            # Clean up temp state directory
            if state_dir.exists():
                try:
                    shutil.rmtree(state_dir, ignore_errors=True)
                except Exception:
                    pass

    def _create_stream_run(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        client_request_id: str | None,
        user_message_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        content: str,
        parent_id: uuid.UUID | None,
    ) -> ChatStreamRun:
        run = ChatStreamRun(
            user_id=user_id,
            session_id=session_id,
            client_request_id=client_request_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status=ChatStreamStatus.STREAMING,
            model_name=settings.CHAT_MODEL_NAME,
            metadata_=self.idempotency.create_run_metadata(content, parent_id),
        )
        self.db.add(run)
        self.db.flush()
        self.db.refresh(run)

        # Register in Redis rate limiter sliding windows
        try:
            r = redis_cache_service.redis
            if r is not None:
                now_ts = datetime.now(timezone.utc).timestamp()
                run_id_str = str(run.id)

                # Register in active concurrent streams ZSET
                expire_ts = now_ts + settings.CHAT_STREAM_TOTAL_TIMEOUT_SECONDS
                active_key = f"chat:active:{user_id}"
                r.zadd(active_key, {run_id_str: expire_ts})
                r.expire(active_key, settings.CHAT_STREAM_TOTAL_TIMEOUT_SECONDS)

                # Increment per-minute request limit
                minute_key = f"chat:minute:{user_id}"
                r.zadd(minute_key, {run_id_str: now_ts})
                r.expire(minute_key, 60)

                # Increment daily limit
                daily_key = f"chat:daily:{user_id}"
                r.zadd(daily_key, {run_id_str: now_ts})
                r.expire(daily_key, 86400)
        except Exception as e:
            logger.warning("Failed to register active chat run in Redis: %s", e)

        return run

    def _create_stream_run_for_cache_hit(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        client_request_id: str | None,
        user_message_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        content: str,
        parent_id: uuid.UUID | None,
    ) -> ChatStreamRun:
        """Tạo đối tượng ChatStreamRun ở trạng thái COMPLETED khi trúng Semantic Cache."""
        run = ChatStreamRun(
            user_id=user_id,
            session_id=session_id,
            client_request_id=client_request_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status=ChatStreamStatus.COMPLETED,
            model_name=settings.CHAT_MODEL_NAME,
            metadata_=self.idempotency.create_run_metadata(content, parent_id),
            completed_at=datetime.now(timezone.utc),
            duration_ms=0,
        )
        self.db.add(run)
        self.db.flush()
        self.db.refresh(run)

        # Register in Redis rate limiter sliding windows (excluding active concurrent limits)
        try:
            r = redis_cache_service.redis
            if r is not None:
                now_ts = datetime.now(timezone.utc).timestamp()
                run_id_str = str(run.id)

                # Increment per-minute request limit
                minute_key = f"chat:minute:{user_id}"
                r.zadd(minute_key, {run_id_str: now_ts})
                r.expire(minute_key, 60)

                # Increment daily limit
                daily_key = f"chat:daily:{user_id}"
                r.zadd(daily_key, {run_id_str: now_ts})
                r.expire(daily_key, 86400)
        except Exception as e:
            logger.warning("Failed to register cache-hit chat run in Redis: %s", e)

        return run

    def _create_prepared_stream_for_replay(
        self,
        run: ChatStreamRun,
        replay_data: dict,
    ) -> PreparedChatStream:
        return PreparedChatStream(
            run_id=run.id,
            user_id=run.user_id,
            project_id=run.session.project_id if run.session else None,
            session_id=run.session_id,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
            messages=[],
            client_request_id=run.client_request_id,
            replay_content=replay_data.get("replay_content"),
            replay_prompt_tokens=replay_data.get("replay_prompt_tokens", 0),
            replay_completion_tokens=replay_data.get("replay_completion_tokens", 0),
        )
