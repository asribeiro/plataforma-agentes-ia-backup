import json
import redis
from typing import Dict, Any
from backend.redis_client import get_redis_client

redis_client = get_redis_client()

def publish_message_event(message_data: Dict[str, Any]):
    """Publica um evento de mensagem no Redis"""
    try:
        redis_client.publish('chat_messages', json.dumps(message_data))
    except Exception as e:
        print(f"Erro ao publicar mensagem no Redis: {e}")
