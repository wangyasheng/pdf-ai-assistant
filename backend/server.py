import uuid
import logging
import os
import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from starlette.responses import JSONResponse

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

# --- 2. 跨域配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def _auth_key(token: str) -> str:
    return f"auth:access:{token}"


# --- 3. 全局 Token 鉴权中间件 ---
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if path in WHITE_LIST:
        return await call_next(request)

    if r is None:
        return JSONResponse(status_code=503, content={"detail": "认证服务不可用"})

    token = request.headers.get("Authorization")
    fingerprint = request.headers.get("X-Device-Fingerprint")

    if not token or not fingerprint:
        return JSONResponse(status_code=401, content={"detail": "鉴权信息不全，请传入 Token 和指纹"})

    stored_data = r.get(_auth_key(token))
    if not stored_data:
        return JSONResponse(status_code=401, content={"detail": "登录已失效"})

    try:
        phone, saved_fp = stored_data.split("|", 1)
    except ValueError:
        return JSONResponse(status_code=401, content={"detail": "Token 格式异常"})

    if fingerprint != saved_fp:
        return JSONResponse(status_code=403, content={"detail": "账号在其他设备登录或指纹不匹配"})

    # 滑动续期
    r.expire(_auth_key(token), ACCESS_TOKEN_EXPIRE)

    request.state.user_phone = phone
    return await call_next(request)

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

@app.post("/api/login")
async def handle_login(req: LoginRequest):
    if r is None:
        raise HTTPException(status_code=503, detail="认证服务不可用")

    access_token = uuid.uuid4().hex
    val = f"{req.phone}|{req.fingerprint}"
    r.setex(_auth_key(access_token), ACCESS_TOKEN_EXPIRE, val)

    return {"success": True, "token": access_token, "msg": "登录成功，欢迎使用 PDF AI 助手"}

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