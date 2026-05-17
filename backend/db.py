
import os
import logging
import pymysql
from dbutils.pooled_db import PooledDB

logger = logging.getLogger(__name__)

# --- 从环境变量或默认值中读取 MySQL 配置 ---
MYSQL_HOST = os.getenv("MYSQL_HOST", "124.222.104.94")  # 默认指向服务器 C 的内网 IP
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "wdd_819815*") # ⚠️替换为你的真实强密码
MYSQL_DB = os.getenv("MYSQL_DB", "knowledge_base")

# --- 初始化生产级线程安全连接池 ---
try:
    mysql_pool = PooledDB(
        creator=pymysql,
        maxconnections=20,    # 连接池允许的最大连接数
        mincached=5,          # 初始化时连接池中至少创建的空闲连接数
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor  # 默认返回 Dict 格式，方便前端转为 JSON
    )
    logger.info("✅ MySQL 数据库连接池初始化成功")
except Exception as e:
    logger.critical(f"❌ MySQL 数据库连接池初始化失败: {e}")
    mysql_pool = None


def get_mysql_conn():
    """
    从连接池中获取一个可用的数据库连接。
    使用完毕后必须在调用的地方执行 conn.close() 将连接归还给池子！
    """
    if mysql_pool is None:
        raise RuntimeError("数据库连接池未初始化或连接失败")
    return mysql_pool.connection()


def execute_query(sql: str, args: tuple = ()) -> list:
    """快捷方法：执行 SELECT 查询，自动管理连接生命周期"""
    conn = get_mysql_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, args)
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"SQL 查询异常: {e}, SQL: {sql}")
        raise e
    finally:
        cursor.close()
        conn.close()


def execute_update(sql: str, args: tuple = ()) -> int:
    """快捷方法：执行 INSERT/UPDATE/DELETE，自动事务提交并释放连接"""
    conn = get_mysql_conn()
    cursor = conn.cursor()
    try:
        affected_rows = cursor.execute(sql, args)
        conn.commit()
        return affected_rows
    except Exception as e:
        conn.rollback()
        logger.error(f"SQL 更新异常: {e}, SQL: {sql}")
        raise e
    finally:
        cursor.close()
        conn.close()