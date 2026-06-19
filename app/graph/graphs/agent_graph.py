import os
import sys
from langgraph.checkpoint.redis import RedisSaver
from langgraph.checkpoint.memory import MemorySaver
from app.config.settings import settings
from app.graph.builders.graph_builder import build_agent_graph

# Tự động chuyển đổi checkpoint saver dựa trên môi trường để hỗ trợ kiểm thử đơn vị ngoại tuyến
if "pytest" in sys.modules or os.getenv("APP_ENV") == "test" or settings.APP_ENV == "test":
    saver = MemorySaver()
else:
    redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    saver = RedisSaver(redis_url=redis_url)

# Biên dịch đồ thị agent cuối cùng với checkpointer được bật
agent_graph = build_agent_graph(checkpointer=saver)
