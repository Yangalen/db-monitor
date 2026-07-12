#!/bin/bash
# ============================================================
# Stage 2: 安装 Docker Engine + Docker Compose
# 功能: 官方一键脚本安装 Docker, 验证版本
# 用法: sudo bash 02-install-docker.sh
# ============================================================

set -e

echo "===== [1/4] 一键安装 Docker ====="
curl -fsSL https://get.docker.com | sh

echo "===== [2/4] 启动 Docker 并设置开机自启 ====="
systemctl start docker
systemctl enable docker

echo "===== [3/4] 将当前用户加入 docker 组 (免 sudo) ====="
USER_NAME=$(who am i | awk '{print $1}')
if [ -z "$USER_NAME" ]; then
    USER_NAME="$SUDO_USER"
fi
if [ -n "$USER_NAME" ] && [ "$USER_NAME" != "root" ]; then
    usermod -aG docker "$USER_NAME"
    echo "已将 $USER_NAME 加入 docker 组 (重新登录后生效)"
else
    echo "当前为 root 用户, 跳过"
fi

echo "===== [4/4] 验证安装 ====="
echo "--- Docker 版本 ---"
docker --version
echo "--- Docker Compose 版本 ---"
docker compose version
echo "--- Docker 服务状态 ---"
systemctl is-active docker

echo ""
echo "========================================"
echo "  Stage 2 完成! Docker 已就绪"
echo "========================================"
echo ""
echo "  提示: 如果当前用户加入了 docker 组,"
echo "        请退出并重新登录后才能免 sudo 使用 docker"
echo "========================================"
