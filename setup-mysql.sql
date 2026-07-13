-- 设置 root 密码
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'Root123!';
FLUSH PRIVILEGES;

-- 创建监控用户
CREATE USER 'monitor'@'localhost' IDENTIFIED BY 'Monitor123!';
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'monitor'@'localhost';
FLUSH PRIVILEGES;

-- 创建测试数据库和表
CREATE DATABASE IF NOT EXISTS testdb;
USE testdb;
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO users (name, email) VALUES
('zhangsan', 'zhangsan@test.com'),
('lisi', 'lisi@test.com'),
('wangwu', 'wangwu@test.com'),
('zhaoliu', 'zhaoliu@test.com'),
('qianqi', 'qianqi@test.com');

-- 验证
SELECT user, host, plugin FROM mysql.user WHERE user='root';
SELECT user, host FROM mysql.user WHERE user='monitor';
SELECT COUNT(*) AS user_count FROM testdb.users;
