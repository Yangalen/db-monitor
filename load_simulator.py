#!/usr/bin/env python3
"""数据库负载模拟器

模拟应用程序对 Oracle 和 MySQL 数据库的访问，
生成 INSERT / UPDATE / DELETE / SELECT 等真实负载，
让监控系统采集到丰富的性能数据。

用法:
    python load_simulator.py                         # 默认运行5分钟，4个并发线程
    python load_simulator.py --duration 600          # 运行10分钟
    python load_simulator.py --workers 8             # 8个并发工作线程
    python load_simulator.py --db oracle             # 只模拟Oracle
    python load_simulator.py --db mysql              # 只模拟MySQL
    python load_simulator.py --duration 0            # 无限运行（Ctrl+C停止）
    python load_simulator.py --init-only             # 只初始化测试表，不运行负载
"""

import argparse
import random
import string
import sys
import threading
import time
from datetime import datetime


# ─── 数据库连接配置 ──────────────────────────────────────

ORACLE_CONFIG = {
    "host": "localhost",
    "port": 1521,
    "service": "XE",
    "user": "C##MONITOR",
    "password": "Monitor123",
}

MYSQL_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "monitor",
    "password": "Monitor123!",
    "database": "testdb",
}

# 统计计数器
stats_lock = threading.Lock()
stats = {
    "oracle": {"insert": 0, "select": 0, "update": 0, "delete": 0, "errors": 0},
    "mysql": {"insert": 0, "select": 0, "update": 0, "delete": 0, "errors": 0},
}

running = True


def log(msg):
    """带时间戳的日志输出"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ─── Oracle 负载模拟 ─────────────────────────────────────

def init_oracle():
    """在 Oracle 中创建测试表并插入初始数据"""
    import oracledb

    dsn = f"{ORACLE_CONFIG['host']}:{ORACLE_CONFIG['port']}/{ORACLE_CONFIG['service']}"
    conn = oracledb.connect(
        user=ORACLE_CONFIG["user"],
        password=ORACLE_CONFIG["password"],
        dsn=dsn,
    )
    cur = conn.cursor()

    # 创建主表
    cur.execute(
        """
        BEGIN
            EXECUTE IMMEDIATE 'DROP TABLE load_test_orders CASCADE CONSTRAINTS';
        EXCEPTION
            WHEN OTHERS THEN NULL;
        END;
        """
    )
    cur.execute(
        """
        CREATE TABLE load_test_orders (
            id          NUMBER PRIMARY KEY,
            customer    VARCHAR2(100),
            email       VARCHAR2(200),
            product     VARCHAR2(100),
            amount      NUMBER(10,2),
            quantity    NUMBER,
            status      VARCHAR2(20) DEFAULT 'PENDING',
            region      VARCHAR2(50),
            created_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
            updated_at  TIMESTAMP DEFAULT SYSTIMESTAMP,
            description VARCHAR2(500)
        )
        """
    )

    # 创建索引
    cur.execute("CREATE INDEX idx_orders_status ON load_test_orders(status)")
    cur.execute("CREATE INDEX idx_orders_region ON load_test_orders(region)")
    cur.execute("CREATE INDEX idx_orders_created ON load_test_orders(created_at)")

    # 创建序列
    cur.execute(
        """
        BEGIN
            EXECUTE IMMEDIATE 'DROP SEQUENCE orders_seq';
        EXCEPTION
            WHEN OTHERS THEN NULL;
        END;
        """
    )
    cur.execute("CREATE SEQUENCE orders_seq START WITH 1 INCREMENT BY 1")

    # 插入初始数据 500 条
    regions = ["华北", "华东", "华南", "华中", "西南", "西北", "东北"]
    products = ["数据库授权", "技术支持", "云服务", "培训课程", "咨询服务", "硬件设备"]
    statuses = ["PENDING", "PROCESSING", "COMPLETED", "CANCELLED"]
    customers = ["张三", "李四", "王五", "赵六", "陈七", "周八", "吴九", "郑十"]

    log("[Oracle] 插入初始数据 500 条...")
    for i in range(1, 501):
        customer = random.choice(customers)
        cur.execute(
            """
            INSERT INTO load_test_orders
                (id, customer, email, product, amount, quantity, status, region, description)
            VALUES (orders_seq.NEXTVAL, :1, :2, :3, :4, :5, :6, :7, :8)
            """,
            (
                customer,
                f"{customer.lower()}@example.com",
                random.choice(products),
                round(random.uniform(100, 50000), 2),
                random.randint(1, 100),
                random.choice(statuses),
                random.choice(regions),
                f"订单描述-{i}-{random.choice(string.ascii_letters)}",
            ),
        )
        if i % 100 == 0:
            conn.commit()
            log(f"  [Oracle] 已插入 {i}/500 条")

    conn.commit()

    # 创建日志表（用于 JOIN 查询）
    cur.execute(
        """
        BEGIN
            EXECUTE IMMEDIATE 'DROP TABLE load_test_logs';
        EXCEPTION
            WHEN OTHERS THEN NULL;
        END;
        """
    )
    cur.execute(
        """
        CREATE TABLE load_test_logs (
            id          NUMBER PRIMARY KEY,
            order_id    NUMBER,
            action      VARCHAR2(50),
            operator    VARCHAR2(50),
            log_time    TIMESTAMP DEFAULT SYSTIMESTAMP,
            note        VARCHAR2(300)
        )
        """
    )

    # 为日志表插入数据
    actions = ["创建", "审核", "发货", "签收", "退款", "修改"]
    for i in range(1, 201):
        cur.execute(
            """
            INSERT INTO load_test_logs (id, order_id, action, operator, note)
            VALUES (:1, :2, :3, :4, :5)
            """,
            (
                i,
                random.randint(1, 500),
                random.choice(actions),
                f"operator_{random.randint(1, 10)}",
                f"操作备注-{i}",
            ),
        )
    conn.commit()

    # 统计
    cur.execute("SELECT COUNT(*) FROM load_test_orders")
    count = cur.fetchone()[0]
    log(f"[Oracle] 初始化完成: load_test_orders {count} 条, load_test_logs 200 条")

    cur.close()
    conn.close()


def oracle_worker(worker_id, duration):
    """Oracle 工作线程 — 模拟混合 OLTP 负载"""
    import oracledb

    global running

    dsn = f"{ORACLE_CONFIG['host']}:{ORACLE_CONFIG['port']}/{ORACLE_CONFIG['service']}"
    conn = oracledb.connect(
        user=ORACLE_CONFIG["user"],
        password=ORACLE_CONFIG["password"],
        dsn=dsn,
    )
    cur = conn.cursor()
    db_key = "oracle"

    regions = ["华北", "华东", "华南", "华中", "西南", "西北", "东北"]
    products = ["数据库授权", "技术支持", "云服务", "培训课程", "咨询服务", "硬件设备"]
    statuses = ["PENDING", "PROCESSING", "COMPLETED", "CANCELLED"]
    customers = ["张三", "李四", "王五", "赵六", "陈七", "周八", "吴九", "郑十"]
    actions = ["创建", "审核", "发货", "签收", "退款", "修改"]

    start_time = time.time()
    op_count = 0

    log(f"[Oracle-W{worker_id}] 工作线程启动")

    while running:
        if duration > 0 and (time.time() - start_time) > duration:
            break

        try:
            op = random.choices(
                ["insert", "select", "update", "delete", "aggregate", "join"],
                weights=[20, 35, 20, 5, 10, 10],
            )[0]
            op_count += 1

            if op == "insert":
                # 插入新订单
                customer = random.choice(customers)
                cur.execute(
                    """
                    INSERT INTO load_test_orders
                        (id, customer, email, product, amount, quantity, status, region, description)
                    VALUES (orders_seq.NEXTVAL, :1, :2, :3, :4, :5, :6, :7, :8)
                    """,
                    (
                        customer,
                        f"{customer.lower()}@example.com",
                        random.choice(products),
                        round(random.uniform(100, 50000), 2),
                        random.randint(1, 100),
                        random.choice(statuses),
                        random.choice(regions),
                        f"W{worker_id}-订单-{op_count}",
                    ),
                )
                conn.commit()
                with stats_lock:
                    stats[db_key]["insert"] += 1

            elif op == "select":
                # 按条件查询
                if random.random() < 0.5:
                    # 主键查询
                    oid = random.randint(1, 500)
                    cur.execute(
                        "SELECT * FROM load_test_orders WHERE id = :1", (oid,)
                    )
                else:
                    # 范围查询
                    region = random.choice(regions)
                    cur.execute(
                        "SELECT * FROM load_test_orders WHERE region = :1 AND ROWNUM <= 10",
                        (region,),
                    )
                cur.fetchall()
                with stats_lock:
                    stats[db_key]["select"] += 1

            elif op == "update":
                # 更新订单状态
                oid = random.randint(1, 500)
                new_status = random.choice(statuses)
                cur.execute(
                    "UPDATE load_test_orders SET status = :1, updated_at = SYSTIMESTAMP WHERE id = :2",
                    (new_status, oid),
                )
                conn.commit()
                with stats_lock:
                    stats[db_key]["update"] += 1

            elif op == "delete":
                # 删除旧订单（只删 id > 500 的，保护初始数据）
                cur.execute(
                    "DELETE FROM load_test_orders WHERE id > 500 AND ROWNUM = 1"
                )
                conn.commit()
                with stats_lock:
                    stats[db_key]["delete"] += 1

            elif op == "aggregate":
                # 聚合统计查询
                query_type = random.randint(0, 2)
                if query_type == 0:
                    cur.execute(
                        "SELECT status, COUNT(*), SUM(amount) FROM load_test_orders GROUP BY status"
                    )
                elif query_type == 1:
                    cur.execute(
                        "SELECT region, COUNT(*), AVG(amount) FROM load_test_orders GROUP BY region ORDER BY COUNT(*) DESC"
                    )
                else:
                    cur.execute(
                        "SELECT product, COUNT(*), SUM(quantity) FROM load_test_orders GROUP BY product"
                    )
                cur.fetchall()
                with stats_lock:
                    stats[db_key]["select"] += 1

            elif op == "join":
                # JOIN 查询
                oid = random.randint(1, 200)
                cur.execute(
                    """
                    SELECT o.customer, o.product, o.amount, l.action, l.operator
                    FROM load_test_orders o
                    JOIN load_test_logs l ON o.id = l.order_id
                    WHERE o.id = :1
                    """,
                    (oid,),
                )
                cur.fetchall()
                with stats_lock:
                    stats[db_key]["select"] += 1

            # 随机休眠，模拟真实应用间隔
            time.sleep(random.uniform(0.05, 0.3))

        except Exception as e:
            with stats_lock:
                stats[db_key]["errors"] += 1
            log(f"[Oracle-W{worker_id}] 错误: {e}")
            time.sleep(1)

    cur.close()
    conn.close()
    log(f"[Oracle-W{worker_id}] 工作线程结束 (共执行 {op_count} 次操作)")


# ─── MySQL 负载模拟 ──────────────────────────────────────

def init_mysql():
    """在 MySQL 中创建测试表并插入初始数据"""
    import pymysql

    conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"],
        connect_timeout=10,
    )
    cur = conn.cursor()

    # 创建主表
    cur.execute("DROP TABLE IF EXISTS load_test_orders")
    cur.execute(
        """
        CREATE TABLE load_test_orders (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            customer    VARCHAR(100),
            email       VARCHAR(200),
            product     VARCHAR(100),
            amount      DECIMAL(10,2),
            quantity    INT,
            status      VARCHAR(20) DEFAULT 'PENDING',
            region      VARCHAR(50),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            description VARCHAR(500)
        ) ENGINE=InnoDB
        """
    )

    # 创建索引
    cur.execute("CREATE INDEX idx_orders_status ON load_test_orders(status)")
    cur.execute("CREATE INDEX idx_orders_region ON load_test_orders(region)")
    cur.execute("CREATE INDEX idx_orders_created ON load_test_orders(created_at)")

    # 插入初始数据 500 条
    regions = ["华北", "华东", "华南", "华中", "西南", "西北", "东北"]
    products = ["数据库授权", "技术支持", "云服务", "培训课程", "咨询服务", "硬件设备"]
    statuses = ["PENDING", "PROCESSING", "COMPLETED", "CANCELLED"]
    customers = ["张三", "李四", "王五", "赵六", "陈七", "周八", "吴九", "郑十"]

    log("[MySQL] 插入初始数据 500 条...")
    for i in range(1, 501):
        customer = random.choice(customers)
        cur.execute(
            """
            INSERT INTO load_test_orders
                (customer, email, product, amount, quantity, status, region, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                customer,
                f"{customer.lower()}@example.com",
                random.choice(products),
                round(random.uniform(100, 50000), 2),
                random.randint(1, 100),
                random.choice(statuses),
                random.choice(regions),
                f"订单描述-{i}-{random.choice(string.ascii_letters)}",
            ),
        )
        if i % 100 == 0:
            conn.commit()
            log(f"  [MySQL] 已插入 {i}/500 条")

    conn.commit()

    # 创建日志表
    cur.execute("DROP TABLE IF EXISTS load_test_logs")
    cur.execute(
        """
        CREATE TABLE load_test_logs (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            order_id    INT,
            action      VARCHAR(50),
            operator    VARCHAR(50),
            log_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            note        VARCHAR(300),
            INDEX idx_log_order (order_id)
        ) ENGINE=InnoDB
        """
    )

    actions = ["创建", "审核", "发货", "签收", "退款", "修改"]
    for i in range(1, 201):
        cur.execute(
            """
            INSERT INTO load_test_logs (order_id, action, operator, note)
            VALUES (%s, %s, %s, %s)
            """,
            (
                random.randint(1, 500),
                random.choice(actions),
                f"operator_{random.randint(1, 10)}",
                f"操作备注-{i}",
            ),
        )
    conn.commit()

    # 统计
    cur.execute("SELECT COUNT(*) FROM load_test_orders")
    count = cur.fetchone()[0]
    log(f"[MySQL] 初始化完成: load_test_orders {count} 条, load_test_logs 200 条")

    cur.close()
    conn.close()


def mysql_worker(worker_id, duration):
    """MySQL 工作线程 — 模拟混合 OLTP 负载"""
    import pymysql

    global running

    conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"],
        connect_timeout=10,
    )
    cur = conn.cursor()
    db_key = "mysql"

    regions = ["华北", "华东", "华南", "华中", "西南", "西北", "东北"]
    products = ["数据库授权", "技术支持", "云服务", "培训课程", "咨询服务", "硬件设备"]
    statuses = ["PENDING", "PROCESSING", "COMPLETED", "CANCELLED"]
    customers = ["张三", "李四", "王五", "赵六", "陈七", "周八", "吴九", "郑十"]
    actions = ["创建", "审核", "发货", "签收", "退款", "修改"]

    start_time = time.time()
    op_count = 0

    log(f"[MySQL-W{worker_id}] 工作线程启动")

    while running:
        if duration > 0 and (time.time() - start_time) > duration:
            break

        try:
            op = random.choices(
                ["insert", "select", "update", "delete", "aggregate", "join"],
                weights=[20, 35, 20, 5, 10, 10],
            )[0]
            op_count += 1

            if op == "insert":
                customer = random.choice(customers)
                cur.execute(
                    """
                    INSERT INTO load_test_orders
                        (customer, email, product, amount, quantity, status, region, description)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        customer,
                        f"{customer.lower()}@example.com",
                        random.choice(products),
                        round(random.uniform(100, 50000), 2),
                        random.randint(1, 100),
                        random.choice(statuses),
                        random.choice(regions),
                        f"W{worker_id}-订单-{op_count}",
                    ),
                )
                conn.commit()
                with stats_lock:
                    stats[db_key]["insert"] += 1

            elif op == "select":
                if random.random() < 0.5:
                    oid = random.randint(1, 500)
                    cur.execute("SELECT * FROM load_test_orders WHERE id = %s", (oid,))
                else:
                    region = random.choice(regions)
                    cur.execute(
                        "SELECT * FROM load_test_orders WHERE region = %s LIMIT 10",
                        (region,),
                    )
                cur.fetchall()
                with stats_lock:
                    stats[db_key]["select"] += 1

            elif op == "update":
                oid = random.randint(1, 500)
                new_status = random.choice(statuses)
                cur.execute(
                    "UPDATE load_test_orders SET status = %s WHERE id = %s",
                    (new_status, oid),
                )
                conn.commit()
                with stats_lock:
                    stats[db_key]["update"] += 1

            elif op == "delete":
                cur.execute(
                    "DELETE FROM load_test_orders WHERE id > 500 LIMIT 1"
                )
                conn.commit()
                with stats_lock:
                    stats[db_key]["delete"] += 1

            elif op == "aggregate":
                query_type = random.randint(0, 2)
                if query_type == 0:
                    cur.execute(
                        "SELECT status, COUNT(*), SUM(amount) FROM load_test_orders GROUP BY status"
                    )
                elif query_type == 1:
                    cur.execute(
                        "SELECT region, COUNT(*), AVG(amount) FROM load_test_orders GROUP BY region ORDER BY COUNT(*) DESC"
                    )
                else:
                    cur.execute(
                        "SELECT product, COUNT(*), SUM(quantity) FROM load_test_orders GROUP BY product"
                    )
                cur.fetchall()
                with stats_lock:
                    stats[db_key]["select"] += 1

            elif op == "join":
                oid = random.randint(1, 200)
                cur.execute(
                    """
                    SELECT o.customer, o.product, o.amount, l.action, l.operator
                    FROM load_test_orders o
                    JOIN load_test_logs l ON o.id = l.order_id
                    WHERE o.id = %s
                    """,
                    (oid,),
                )
                cur.fetchall()
                with stats_lock:
                    stats[db_key]["select"] += 1

            time.sleep(random.uniform(0.05, 0.3))

        except Exception as e:
            with stats_lock:
                stats[db_key]["errors"] += 1
            log(f"[MySQL-W{worker_id}] 错误: {e}")
            time.sleep(1)
            # 重连
            try:
                conn.ping(reconnect=True)
            except Exception:
                conn.close()
                conn = pymysql.connect(
                    host=MYSQL_CONFIG["host"],
                    port=MYSQL_CONFIG["port"],
                    user=MYSQL_CONFIG["user"],
                    password=MYSQL_CONFIG["password"],
                    database=MYSQL_CONFIG["database"],
                    connect_timeout=10,
                )
                cur = conn.cursor()

    cur.close()
    conn.close()
    log(f"[MySQL-W{worker_id}] 工作线程结束 (共执行 {op_count} 次操作)")


# ─── 统计报告 ────────────────────────────────────────────

def print_stats():
    """打印当前统计"""
    with stats_lock:
        for db in ["oracle", "mysql"]:
            s = stats[db]
            total = s["insert"] + s["select"] + s["update"] + s["delete"]
            log(
                f"[{db.upper()}] 总操作: {total} | "
                f"INSERT: {s['insert']} SELECT: {s['select']} "
                f"UPDATE: {s['update']} DELETE: {s['delete']} 错误: {s['errors']}"
            )


# ─── 主入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="数据库负载模拟器")
    parser.add_argument(
        "--duration", type=int, default=300,
        help="运行时长(秒)，0=无限运行 (默认: 300)"
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="每个数据库的并发工作线程数 (默认: 4)"
    )
    parser.add_argument(
        "--db", choices=["oracle", "mysql", "both"], default="both",
        help="模拟哪个数据库 (默认: both)"
    )
    parser.add_argument(
        "--init-only", action="store_true",
        help="只初始化测试表，不运行负载"
    )
    parser.add_argument(
        "--no-init", action="store_true",
        help="跳过初始化（表已存在时使用）"
    )
    args = parser.parse_args()

    global running

    log("=" * 60)
    log("数据库负载模拟器启动")
    log(f"  数据库: {args.db} | 工作线程: {args.workers}/DB | "
        f"时长: {'无限' if args.duration == 0 else f'{args.duration}秒'}")
    log("=" * 60)

    # 初始化
    if not args.no_init:
        if args.db in ("oracle", "both"):
            log("[Oracle] 初始化测试表...")
            try:
                init_oracle()
            except Exception as e:
                log(f"[Oracle] 初始化失败: {e}")
                if args.init_only:
                    sys.exit(1)

        if args.db in ("mysql", "both"):
            log("[MySQL] 初始化测试表...")
            try:
                init_mysql()
            except Exception as e:
                log(f"[MySQL] 初始化失败: {e}")
                if args.init_only:
                    sys.exit(1)

    if args.init_only:
        log("初始化完成，--init-only 模式退出")
        return

    # 启动工作线程
    threads = []

    if args.db in ("oracle", "both"):
        for i in range(args.workers):
            t = threading.Thread(target=oracle_worker, args=(i + 1, args.duration))
            t.start()
            threads.append(t)

    if args.db in ("mysql", "both"):
        for i in range(args.workers):
            t = threading.Thread(target=mysql_worker, args=(i + 1, args.duration))
            t.start()
            threads.append(t)

    # 主循环：定期打印统计
    report_interval = 30
    last_report = time.time()

    try:
        while running:
            time.sleep(1)
            if time.time() - last_report >= report_interval:
                print_stats()
                last_report = time.time()

            # 检查所有线程是否结束
            if args.duration > 0:
                alive = any(t.is_alive() for t in threads)
                if not alive:
                    break

    except KeyboardInterrupt:
        log("\n收到中断信号，正在停止...")
        running = False

    # 等待所有线程结束
    for t in threads:
        t.join(timeout=10)

    log("=" * 60)
    log("最终统计:")
    print_stats()
    log("负载模拟结束")
    log("=" * 60)


if __name__ == "__main__":
    main()
