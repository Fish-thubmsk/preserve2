# preserve2 — 超星图书馆座位自动预约脚本

本项目是一个基于 Python 的**单次执行**脚本，用于在预约开放时间附近自动尝试预约用户预设的一组座位。

> **免责声明**：本脚本仅面向单一用户账号使用，旨在辅助用户按照图书馆规定的流程进行预约，**不用于刷号、批量抢占资源或任何形式的攻击性行为**。使用者需自行遵守学校及图书馆的各项规定。

---

## 功能概述

- 按优先级列表依次尝试预约指定座位，一旦成功立即停止
- 自动从页面提取 `enc` 参数，无需手动计算
- 支持通过 `config/config.yml` 配置目标日期、时间段、座位列表
- 敏感信息（Cookie）通过 `.env` 管理，不提交到代码仓库
- 完善的日志记录（控制台 + 文件）

---

## 快速开始

### 1. 安装依赖

```bash
pip install requests pyyaml python-dotenv
```

### 2. 配置文件

```bash
# 复制配置示例
cp config/config.example.yml config/config.yml
cp .env.example .env
```

**编辑 `config/config.yml`**，填写你的图书馆座位参数：

```yaml
# 预约明天的座位
target_date_mode: "tomorrow"

# 预约时间段（图书馆营业时间内选择）
time_range:
  start: "08:00"
  end: "22:30"

# 按优先级排列的座位号列表
seat_ids:
  - "014"
  - "015"
  - "016"

# 区域参数（从浏览器操作时的 URL/请求中获取）
area:
  fid_enc: "4a18e12602b24c8c"
  dept_id_enc: "4a18e12602b24c8c"
  room_id: 13481
  first_level_name: "郑东校区"
  second_level_name: "3楼"
  third_level_name: "西阅览区"
```

**编辑 `.env`**，填入从浏览器复制的 Cookie：

```dotenv
CX_COOKIE="JSESSIONID=xxxxx; route=xxxxx; fid=499; _uid=YOUR_UID; ..."
```

> **如何获取 Cookie？**
> 1. 在 Chrome 中登录超星图书馆座位系统
> 2. 按 F12 打开开发者工具 → Network 标签
> 3. 随意点击一个页面操作，找到任意请求
> 4. 在 Headers 中找到 `Cookie` 字段，复制完整值

### 3. 运行脚本

```bash
python reserve_once.py
```

可选参数：

```bash
python reserve_once.py --config path/to/config.yml --env path/to/.env
```

### 4. 配置定时任务（可选）

**Linux / macOS（cron）**：

```bash
crontab -e
```

```cron
# 每天 20:00 整执行（预约开放时间）
0 20 * * * cd /path/to/preserve2 && python reserve_once.py >> /path/to/preserve2/reserve.log 2>&1
```

**Windows（任务计划程序）**：
在任务计划程序中新建基本任务，触发时间设为每天 20:00，操作选择运行 `python reserve_once.py`。

---

## 项目结构

```
preserve2/
├── reserve_once.py          # 主入口脚本
├── config/
│   ├── config.example.yml   # 配置文件示例（提交到仓库）
│   └── config.yml           # 实际配置文件（不提交，已 gitignore）
├── lib/
│   ├── __init__.py
│   ├── client.py            # HTTP 客户端（封装请求发送）
│   ├── reservation.py       # 预约逻辑（流程控制）
│   └── logger.py            # 日志工具
├── .env.example             # 环境变量示例（提交到仓库）
├── .env                     # 实际敏感信息（不提交，已 gitignore）
├── .gitignore
├── docs/
│   └── auto_reserve_spec.md # 需求说明书
├── 分析报告.md               # 抓包数据分析报告
└── README.md
```

---

## 异常处理

| 场景 | 脚本行为 |
|------|---------|
| Cookie 失效 | 输出明确错误信息，退出码 2，**不**自动重试 |
| 座位已被占用 | 自动尝试下一个候选座位 |
| 所有座位失败 | 记录失败摘要，退出码 1 |
| 网络异常 | 记录错误，跳过当前座位，继续尝试 |
| 配置文件缺失 | 输出错误信息，退出码 1 |

---

## 注意事项

1. **Cookie 有效期约 7 天**，需定期更新 `.env` 中的 `CX_COOKIE`
2. 预约开放时间通常为**前一天 20:00**，建议将 cron 设置为 20:00 执行
3. 预约成功后，请务必在**预约开始时间后 30 分钟内**到达图书馆扫码签到，否则计为违约
4. 每 15 天内累计 3 次违约将暂停 7 天预约功能
5. 若需预约特殊区域（如研讨间），请注意单次预约时长限制（2 小时）

---

## 如何获取 fid_enc / room_id 等参数？

1. 打开浏览器，登录图书馆座位预约系统
2. 选择你常用的区域和房间
3. 在开发者工具 Network 标签中，观察 `/data/apps/seat/room/list` 请求
4. 从 URL 参数中获取 `deptIdEnc`（即 `fid_enc`）
5. 从 `/front/third/apps/seat/select?id=XXXXX` URL 中获取 `room_id`

---

## 后续扩展方向（v1 未实现）

- 自动登录（用户名/密码 + 验证码处理）
- 内建定时调度（无需外部 cron）
- 预约成功后的签到提醒（邮件/IM）
- Web 控制面板
