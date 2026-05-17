import uuid
import logging
import os
import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from starlette.responses import JSONResponse
from contextlib import asynccontextmanager

# 引入刚刚封装的本地模块
from backend.consul import consul_lifespan
from backend.auth import token_auth_middleware, handle_user_login_db, get_client_real_ip, check_redis_health
from backend.db import mysql_pool
from backend.agent import DeepSeekAgent, ExamQuestion
from backend.ocr_tool import ocr_tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="PDF AI 助手后端 (带鉴权功能)")

# --- 1. Redis 初始化与配置 ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ACCESS_TOKEN_EXPIRE = int(os.getenv("ACCESS_TOKEN_EXPIRE", "1800"))  # 30分钟
WHITE_LIST = {"/api/login", "/docs", "/openapi.json"}  # 无需鉴权的接口

try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
except redis.ConnectionError:
    logger.warning("Redis 不可用，鉴权功能将失效")
    r = None

    # --- 2. 优雅启停生命周期管理 (Lifespan) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 【启动时触发】
    logger.info("🚀 FastAPI 正在启动...")
    if mysql_pool:
        logger.info("📊 MySQL 线程安全连接池已就绪")
    else:
        logger.error("🚨 MySQL 连接池未正常初始化，请检查 backend/db.py 配置！")
        
    yield  # 这里是分割线，上面是启动执行，下面是关闭执行
    
    # 【关闭时触发】
    logger.info("🛑 FastAPI 正在关闭，准备释放全局资源...")
    if mysql_pool:
        mysql_pool.close()
        logger.info("✅ MySQL 连接池已安全关闭并释放所有活动连接")

# --- 3. 初始化 FastAPI 实例 ---
app = FastAPI(
    title="AI 知识库系统后端 API",
    description="基于 FastAPI + Redis集群 + MySQL 的分布式高并发网关",
    version="1.0.0",
    lifespan=lifespan
)

# --- 2. 跨域配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 5. 挂载全局 Token & 智能设备指纹鉴权中间件 ---
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # 直接调用 auth 模块中封装的分布式认证拦截器
    return await token_auth_middleware(request, call_next)

# --- 4. 请求体定义 ---

class LoginRequest(BaseModel):
    phone: str
    fingerprint: str # 前端生成的设备指纹

class OCRRequest(BaseModel):
    image_base64: str

class QuestionRequest(BaseModel):
    context: str
    question: Optional[str] = None 

class JudgeRequest(BaseModel):
    question_text: str
    user_answer: str
    correct_answer: str

# 初始化 Agent
agent = DeepSeekAgent()

# --- 5. 接口实现 ---
@app.get("/health", summary="系统健康检查 (免密白名单)")
async def health_check():
    """供云服务器负载均衡或运维看护判定实例是否存活"""
    redis_healthy = check_redis_health()
    mysql_healthy = mysql_pool is not None
    
    status_code = 200 if (redis_healthy and mysql_healthy) else 500
    return {
        "status": "healthy" if status_code == 200 else "unhealthy",
        "components": {
            "redis_cluster": "OK" if redis_healthy else "FAIL",
            "mysql_pool": "OK" if mysql_healthy else "FAIL"
        }
    }

@app.post("/api/login", summary="用户一键免操作登录/自动注册")
async def login(request: Request):
    """
    接收前端传入的手机号和设备指纹：
    1. 解析 Nginx 转发的真实客户端 IP
    2. 自动进行查库与安全审计注册
    3. 联动 Redis 集群颁发分布式 Token
    """
    body = await request.json()
    phone = body.get("phone")
    fingerprint = body.get("fingerprint")
    
    # 获取经过代理洗白后的真实 IP
    real_ip = get_client_real_ip(request)
    
    # 调用 auth 模块处理核心逻辑
    token = handle_user_login_db(phone=phone, fingerprint=fingerprint, real_ip=real_ip)
    
    return {
        "code": 200,
        "message": "登录成功",
        "data": {
            "token": token
        }
    }

@app.get("/api/user/info", summary="获取当前登录用户信息 (受保护接口)")
async def get_user_info(request: Request):
    """
    通过了全局中间件的请求，可以直接从 request.state 中安全取出 phone
    """
    # 这里的 user_phone 是由 auth_middleware 成功解析后注入的
    current_user_phone = request.state.user_phone
    
    return {
        "code": 200,
        "data": {
            "phone": current_user_phone,
            "role": "user"
        }
    }

@app.post("/api/ocr")
async def handle_ocr(req: OCRRequest, request: Request):
    logger.info("用户 %s 调用 OCR", request.state.user_phone)

    if not req.image_base64:
        raise HTTPException(status_code=400, detail="未接收到图片数据")

    result = ocr_tool.recognize_base64(req.image_base64)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/api/chat-or-generate")
async def chat_or_generate(req: QuestionRequest):
    try:
        result = agent.generate_question(req.context, req.question)
        if isinstance(result, ExamQuestion):
            return {"type": "exam", "data": result.model_dump()}
        return {"type": "chat", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/judge")
async def judge_answer(req: JudgeRequest):
    try:
        feedback = agent.judge(req.question_text, req.user_answer, req.correct_answer)
        return {"feedback": feedback}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)