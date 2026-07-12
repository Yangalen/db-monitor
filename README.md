# Oracle 数据库监控系统 — Ubuntu 部署指南 (小白最快路径)

> 基于 Ubuntu 22.04 LTS, 从零到可用, 约 50 分钟

## 文件清单

| 文件 | 说明 | 执行阶段 |
|------|------|----------|
| `01-system-init.sh` | 系统初始化脚本 | Stage 1 |
| `02-install-docker.sh` | Docker 安装脚本 | Stage 2 |
| `03-docker-compose.yml` | InfluxDB + Grafana 编排文件 | Stage 3 |
| `04-config.env` | 采集脚本配置文件 (需修改) | Stage 4 |
| `05-collector.py` | Python 采集脚本 (核心代码) | Stage 5 |
| `06-oracle-monitor.service` | systemd 服务文件 | Stage 5 |
| `07-deploy-collector.sh` | 采集脚本部署脚本 | Stage 5 |
| `08-verify.sh` | 验证脚本 | Stage 6 |

---

## Stage 1: 系统初始化 (5 分钟)

```bash
# 上传文件到服务器后执行
sudo bash 01-system-init.sh
```

**做了什么**: 更新 apt → 安装基础工具 (curl/wget/vim/python3 等) → 设置时区 → 创建 `/opt/oracle-monitor` 工作目录

---

## Stage 2: 安装 Docker (10 分钟)

```bash
sudo bash 02-install-docker.sh
```

**做了什么**: 官方一键脚本安装 Docker Engine + Compose 插件 → 启动 Docker 服务 → 设置开机自启 → 当前用户加入 docker 组

**注意**: 脚本执行完后需要**退出重新登录**, 才能免 sudo 使用 docker

验证:
```bash
docker --version          # 应显示 Docker version 24.x.x
docker compose version    # 应显示 Docker Compose version v2.x.x
```

---

## Stage 3: 启动 InfluxDB + Grafana (5 分钟)

```bash
# 1. 复制 docker-compose.yml 到工作目录
cp 03-docker-compose.yml /opt/oracle-monitor/

# 2. 启动 (后台运行)
cd /opt/oracle-monitor
docker compose up -d

# 3. 查看容器状态
docker ps
```

**预期输出**: 两个容器都是 Up 状态
```
monitor-influxdb    ...   Up   0.0.0.0:8086->8086/tcp
monitor-grafana     ...   Up   0.0.0.0:3000->3000/tcp
```

**访问验证**:
- InfluxDB: `http://服务器IP:8086` → 账号 `admin` / 密码 `influxadmin123`
- Grafana: `http://服务器IP:3000` → 账号 `admin` / 密码 `grafana123`

**关键信息** (后续要用):
| 参数 | 值 |
|------|-----|
| InfluxDB Token | `my-super-secret-token-1234567890` |
| InfluxDB Org | `myorg` |
| InfluxDB Bucket | `oracle_metrics` |

---

## Stage 4: Python 环境 + 配置文件 (5 分钟)

```bash
# 1. 复制配置文件到工作目录
cp 04-config.env /opt/oracle-monitor/scripts/config.env

# 2. 修改配置 (改成你的 Oracle 实际信息!)
vim /opt/oracle-monitor/scripts/config.env
```

**必须修改的配置项**:
```env
ORACLE_HOST=192.168.1.100        ← 改成你的 Oracle 服务器 IP
ORACLE_PORT=1521                  ← Oracle 端口, 默认 1521
ORACLE_SERVICE=ORCLPDB1           ← 改成你的 Oracle 服务名
ORACLE_USER=monitor_user          ← 监控专用账号
ORACLE_PASSWORD=YourPass123       ← 监控账号密码
```

---

## Stage 5: 部署采集脚本 (15 分钟)

```bash
# 1. 复制脚本和服务文件
cp 05-collector.py /opt/oracle-monitor/scripts/
cp 06-oracle-monitor.service /opt/oracle-monitor/scripts/

# 2. 一键部署 (创建 venv + 安装依赖 + 注册 systemd 服务)
sudo bash 07-deploy-collector.sh
```

**做了什么**:
1. 创建 Python 虚拟环境 `/opt/oracle-monitor/scripts/venv`
2. 安装依赖: `oracledb` + `influxdb-client` + `APScheduler`
3. 注册 systemd 服务, 开机自启 + 崩溃自动重启
4. 启动服务

**常用运维命令**:
```bash
# 查看服务状态
systemctl status oracle-monitor

# 实时查看日志
journalctl -u oracle-monitor -f

# 查看采集日志文件
tail -f /opt/oracle-monitor/logs/collector.log

# 重启 / 停止
systemctl restart oracle-monitor
systemctl stop oracle-monitor
```

---

## Stage 6: 验证 + Grafana 仪表盘 (10 分钟)

```bash
bash 08-verify.sh
```

### Grafana 配置数据源

1. 浏览器打开 `http://服务器IP:3000`, 登录 `admin / grafana123`
2. 左侧菜单 → **Connections** → **Data sources** → **Add data source**
3. 选择 **InfluxDB**
4. 填写:
   - **Query Language**: Flux
   - **URL**: `http://influxdb:8086` (如果 Grafana 和 InfluxDB 在同一个 Docker 网络)
   - 或 `http://localhost:8086` (如果 Grafana 容器使用 host 网络)
   - **Organization**: `myorg`
   - **Token**: `my-super-secret-token-1234567890`
   - **Bucket**: `oracle_metrics`
5. 点击 **Save & Test**, 应显示 "Data source is working"

### 创建仪表盘面板

创建 Dashboard → 添加 Panel → 输入 Flux 查询:

**面板 1: 活跃会话数趋势**
```flux
from(bucket: "oracle_metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "oracle_sessions")
  |> filter(fn: (r) => r._field == "active")
```

**面板 2: 表空间使用率**
```flux
from(bucket: "oracle_metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "oracle_tablespace")
  |> filter(fn: (r) => r._field == "used_pct")
  |> group(columns: ["tablespace"])
```

**面板 3: Buffer Cache 命中率**
```flux
from(bucket: "oracle_metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "oracle_performance")
  |> filter(fn: (r) => r._field == "buffer_cache_hit_pct")
```

**面板 4: TOP 等待事件**
```flux
from(bucket: "oracle_metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "oracle_wait_events")
  |> filter(fn: (r) => r._field == "time_waited_ms")
  |> group(columns: ["event"])
  |> top(n: 5)
```

---

## 故障排查

### 问题: 采集脚本连不上 Oracle

```bash
# 1. 测试网络连通性
telnet 192.168.1.100 1521

# 2. 如果 telnet 不通, 检查 Oracle 服务器防火墙
# 在 Oracle 服务器上执行:
sudo firewall-cmd --add-port=1521/tcp --permanent
sudo firewall-cmd --reload

# 3. 如果是云服务器, 还需检查安全组规则

# 4. 手动测试连接
cd /opt/oracle-monitor/scripts
./venv/bin/python -c "
import oracledb
conn = oracledb.connect(user='monitor_user', password='YourPass123', dsn='192.168.1.100:1521/ORCLPDB1')
print('连接成功:', conn.version)
conn.close()
"
```

### 问题: InfluxDB 写入失败

```bash
# 1. 检查 InfluxDB 容器日志
docker logs monitor-influxdb

# 2. 验证 Token 是否正确
curl -H "Authorization: Token my-super-secret-token-1234567890" \
     http://localhost:8086/api/v2/buckets?org=myorg
```

### 问题: Grafana 数据源测试失败

```
确保 URL 填的是 http://influxdb:8086 (Docker 容器间通信)
而不是 http://localhost:8086 (除非用 host 网络模式)
```

### 问题: Docker 容器启动失败

```bash
# 查看详细日志
docker logs monitor-influxdb
docker logs monitor-grafana

# 如果端口被占用, 修改 docker-compose.yml 中的端口映射
# 如果磁盘空间不足: df -h
```

---

## 完整一键部署 (所有 Stage 顺序执行)

```bash
# 上传所有文件到 /tmp/oracle-monitor-deploy/

cd /tmp/oracle-monitor-deploy

# Stage 1
sudo bash 01-system-init.sh

# Stage 2 (执行后重新登录)
sudo bash 02-install-docker.sh
exit
# 重新 SSH 登录

# Stage 3
cp 03-docker-compose.yml /opt/oracle-monitor/
cd /opt/oracle-monitor && docker compose up -d

# Stage 4
cp /tmp/oracle-monitor-deploy/04-config.env /opt/oracle-monitor/scripts/config.env
vim /opt/oracle-monitor/scripts/config.env  # 修改 Oracle 连接信息

# Stage 5
cp /tmp/oracle-monitor-deploy/05-collector.py /opt/oracle-monitor/scripts/
cp /tmp/oracle-monitor-deploy/06-oracle-monitor.service /opt/oracle-monitor/scripts/
sudo bash /tmp/oracle-monitor-deploy/07-deploy-collector.sh

# Stage 6 验证
bash /tmp/oracle-monitor-deploy/08-verify.sh
```
