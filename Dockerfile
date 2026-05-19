FROM python:3.10-slim

WORKDIR /app

# ================= 🚀 核心修复：把下面这两行换源命令插进去 =================
# 将 Debian/Ubuntu 的官方源直接替换为腾讯云/阿里云镜像源（看你服务器厂商，通用推荐阿里云）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# =========================================================================

# 这时候再跑你的这行系统库安装，只要 10 秒钟就能全部瞬间下完！
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

CMD ["sleep", "infinity"]
