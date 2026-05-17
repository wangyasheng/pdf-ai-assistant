import os
import socket
import logging
import httpx
from fastapi import FastAPI
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# --- 配置区 ---
SERVICE_NAME = "pdf-ai-backend"
SERVICE_PORT = 8000
CONSUL_HOST = os.getenv("CONSUL_HOST", "172.17.0.11")
CONSUL_URL = f"http://{CONSUL_HOST}:8500/v1/agent/service"

def get_host_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

CURRENT_IP = get_host_ip()
SERVICE_ID = f"{SERVICE_NAME}-{CURRENT_IP}-{SERVICE_PORT}"

@asynccontextmanager
async def consul_lifespan(app: FastAPI):
    """管理服务在 Consul 中的注册与注销"""
    async with httpx.AsyncClient() as client:
        registration_data = {
            "ID": SERVICE_ID,
            "Name": SERVICE_NAME,
            "Address": CURRENT_IP,
            "Port": SERVICE_PORT,
            "Check": {
                "HTTP": f"http://{CURRENT_IP}:{SERVICE_PORT}/health",
                "Interval": "10s",
                "Timeout": "5s",
                "DeregisterCriticalServiceAfter": "30s"
            }
        }
        try:
            await client.put(f"{CONSUL_URL}/register", json=registration_data)
            logger.info(f"🚀 服务已成功注册到 Consul: {SERVICE_ID}")
        except Exception as e:
            logger.error(f"❌ 注册 Consul 失败: {e}")

    yield  # 运行中

    async with httpx.AsyncClient() as client:
        try:
            await client.put(f"{CONSUL_URL}/deregister/{SERVICE_ID}")
            logger.info(f"🛑 服务已从 Consul 注销: {SERVICE_ID}")
        except Exception as e:
            logger.warning(f"⚠️ 从 Consul 注销失败: {e}")