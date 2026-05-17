import os
import sys
import uuid
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from redis.cluster import RedisCluster,ClusterNode
import redis  # 👈 必须单独把基础 redis 库导进来！

# 引入刚刚解耦出去的数据库连接获取函数
from backend.db import get_mysql_conn

logger = logging.getLogger(__name__)

# 在你本地电脑的环境变量中，配置一个 IS_LOCAL = true
# 这样你本地跑的时候就会走 127.0.0.1 找隧道；而部署到线上 B 机器时，会自动去连 C 机器内网
if os.getenv("IS_LOCAL") == "true":
    REDIS_URL = "redis://:wdd_819815!@127.0.0.1:6379/0"
else:
    REDIS_URL = "redis://:wdd_819815!@172.17.0.11:6379/0"

# --- 1. 配置区 ---
# REDIS_URL = os.getenv("REDIS_URL", "redis://:wdd_819815!@172.17.0.11:6379/0")  # 指向服务器 C 的 Redis 集群
ACCESS_TOKEN_EXPIRE = int(os.getenv("ACCESS_TOKEN_EXPIRE", "1800"))  # 30分钟
WHITE_LIST = {"/api/login", "/health", "/docs", "/openapi.json"}

# --- 2. 初始化 Redis 集群 ---
# 1. 确保 IS_LOCAL 定义在最前面
IS_LOCAL = os.getenv("IS_LOCAL", "false") == "true"

# 2. 根据环境决定节点和参数
# 🌟【大招】直接通过判断系统和盘符路径，100% 确认是不是你的本地电脑
is_windows = sys.platform.startswith("win")
has_local_path = os.path.exists("D:/vscode")

# 只要满足其中一个，就强制认定为本地开发环境，拒绝让它跑去线上内网
is_windows = sys.platform.startswith("win")
has_local_path = os.path.exists("D:/vscode")

if is_windows or has_local_path:
    IS_LOCAL = True
    logger.info("🔌 [本地强启] 检测到本地环境，切换为单节点隧道直连模式...")
else:
    IS_LOCAL = False
    logger.info("🚀 [线上生产] 正在通过内网连接 Redis 集群...")

try:
    if IS_LOCAL:
        # 🌟【核心改动】本地开发通过隧道时，用普通 Redis 客户端，避开集群重定向的坑
        redis_cluster = redis.Redis(
            host='127.0.0.1',
            port=6379,
            password="wdd_819815!",  # 👈 填入你真实的 Redis 密码
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True
        )
    else:
        # 线上生产环境，依然保持高大上的集群连接
        nodes = [ClusterNode('172.17.0.11', 6379)]
        redis_cluster = RedisCluster(
            startup_nodes=nodes, 
            password="wdd_819815!", 
            decode_responses=True,
            skip_full_coverage_check=False
        )
    
    # 验证是否真的连通
    redis_cluster.ping()
    logger.info("✅ Redis 连接测试成功！数据通道已彻底打通。")

except Exception as e:
    if IS_LOCAL:
        logger.warning(f"⚠️ 本地隧道模式连接受限 (不影响主服务启动): {e}")
    else:
        logger.error(f"❌ 线上环境 Redis 彻底连接失败: {e}")


def _auth_key(token: str) -> str:
    return f"auth:access:{token}"


def get_client_real_ip(request: Request) -> str:
    """获取用户的真实外网 IP，适配 Nginx 反向代理"""
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip
    return request.client.host if request.client else "127.0.0.1"


def handle_user_login_db(phone: str, fingerprint: str, real_ip: str) -> str:
    """
    处理登录核心业务逻辑：
    1. 查询 MySQL 手机号是否存在
    2. 不存在则自动将（手机号 + 真实IP）存入 MySQL
    3. 存在则更新最新登录指纹
    4. 联动 Redis 集群生成分布式 Token 并在其内部滑动续期
    """
    # 🌟 加上这行，把全局的隧道/集群连接对象传给函数内部的变量名
    redis_conn = redis_cluster

    if redis_conn is None:
        raise HTTPException(status_code=503, detail="认证集群暂时不可用")

    # 统一从连接池中获取一个可用的连接
    conn = get_mysql_conn()
    cursor = conn.cursor()
    try:
        # Step 1: 查询手机号是否存在
        sql_check = "SELECT id FROM users WHERE phone = %s LIMIT 1"
        cursor.execute(sql_check, (phone,))
        user = cursor.fetchone()

        if not user:
            # Step 2: 用户不存在 -> 执行自动注册，存入手机号和真实请求 IP
            logger.info(f"📝 发现新用户，正在自动注册: {phone}, 注册IP: {real_ip}")
            sql_insert = "INSERT INTO users (phone, register_ip, last_fingerprint) VALUES (%s, %s, %s)"
            cursor.execute(sql_insert, (phone, real_ip, fingerprint))
            conn.commit()
        else:
            # Step 3: 用户已存在 -> 顺手更新其最新的设备指纹
            sql_update = "UPDATE users SET last_fingerprint = %s WHERE phone = %s"
            cursor.execute(sql_update, (fingerprint, phone))
            conn.commit()

        # Step 4: 联动 Redis 集群分发加密 Token 凭证
        access_token = uuid.uuid4().hex
        val = f"{phone}|{fingerprint}"
        redis_conn.setex(_auth_key(access_token), ACCESS_TOKEN_EXPIRE, val)
        return access_token

    except Exception as e:
        conn.rollback()  # 发生任何异常立即回滚事务
        logger.error(f"❌ 登录事务或 Redis 调度失败: {e}")
        raise HTTPException(status_code=500, detail="服务器登录注册异常，请稍后重试")
    finally:
        # 严格关闭游标，并将连接完璧归赵返回给连接池
        cursor.close()
        conn.close()


def check_redis_health() -> bool:
    """供 server 入口做维度的健康探测使用"""
    if redis_conn is None: 
        return False
    try:
        redis_conn.ping()
        return True
    except: 
        return False


async def token_auth_middleware(request: Request, call_next):
    """
    FastAPI 全局请求拦截中间件：
    - 白名单免验
    - 解析 Authorization 并在 Redis 集群进行防多端挤占校验
    - 动态对有效 Token 进行滑动续期
    """
    path = request.url.path
    if path in WHITE_LIST:
        return await call_next(request)

    if redis_conn is None:
        return JSONResponse(status_code=503, content={"detail": "认证集群暂时不可用"})

    token = request.headers.get("Authorization")
    fingerprint = request.headers.get("X-Device-Fingerprint")

    if not token or not fingerprint:
        return JSONResponse(status_code=401, content={"detail": "鉴权信息不全，请传入 Token 和指纹"})

    # 从集群分布式节点中高效获取登录信息
    stored_data = redis_conn.get(_auth_key(token))
    if not stored_data:
        return JSONResponse(status_code=401, content={"detail": "登录状态已失效，请重新登录"})

    try:
        phone, saved_fp = stored_data.split("|", 1)
    except ValueError:
        return JSONResponse(status_code=401, content={"detail": "Token 格式异常"})

    # 一旦设备指纹不匹配，证明账号被顶掉或者发生了跨端异常风险
    if fingerprint != saved_fp:
        return JSONResponse(status_code=403, content={"detail": "账号在其他设备登录或指纹不匹配"})

    # 集群滑动续期
    redis_conn.expire(_auth_key(token), ACCESS_TOKEN_EXPIRE)
    
    # 注入到上下文，让后续业务路由可以直接通过 request.state.user_phone 识别人
    request.state.user_phone = phone
    return await call_next(request)