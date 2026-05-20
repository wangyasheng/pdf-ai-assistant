FROM python:3.10-slim

WORKDIR /app

# ================= 🚀 真正安全的 Debian 12 换源写法 =================
# 使用 Base64 或 Here-Doc (<<'EOF') 写入多行，绝对不会因为换行符导致 Dockerfile 解析失败
RUN cat << 'EOF' > /etc/apt/sources.list.d/debian.sources
Types: deb
URIs: http://mirrors.aliyun.com/debian/
Suites: bookworm bookworm-updates bookworm-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://mirrors.aliyun.com/debian-security
Suites: bookworm-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF

# 清空旧文件，确保不留下干扰
RUN echo "" > /etc/apt/sources.list
# =========================================================================

# 接下来是执行你的系统库安装（此时已百分百走阿里云镜像源）
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