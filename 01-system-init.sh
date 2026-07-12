#!/bin/bash
# ============================================================
# Stage 1: Ubuntu 系统初始化
# 功能: 更新系统 + 安装基础工具 + 设置时区 + 创建工作目录
# 用法: sudo bash 01-system-init.sh
# ============================================================

set -e

echo "===== [1/4] 更新 apt 包索引 ====="
apt-get update -y

echo "===== [2/4] 安装基础工具 ====="
apt-get install -y \
    curl \
    wget \
    vim \
    unzip \
    git \
    telnet \
    net-tools \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    gnupg \
    lsb-release

echo "===== [3/4] 设置时区为东八区 ====="
timedatectl set-timezone Asia/Shanghai
echo "当前时间: $(date)"

echo "===== [4/4] 创建工作目录 ====="
WORK_DIR="/opt/oracle-monitor"
mkdir -p "$WORK_DIR/logs"
mkdir -p "$WORK_DIR/config"
mkdir -p "$WORK_DIR/scripts"

echo ""
echo "========================================"
echo "  Stage 1 完成! 工作目录: $WORK_DIR"
echo "========================================"
