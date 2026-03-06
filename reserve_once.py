#!/usr/bin/env python3
"""
reserve_once.py - 超星图书馆座位自动预约脚本（单次执行入口）

用法：
    python reserve_once.py [--config config/config.yml] [--env .env]

说明：
    - 本脚本执行「一轮」完整的自动预约尝试，定时调度由操作系统负责（cron / 任务计划）。
    - 认证信息（Cookie）从 .env 文件读取，业务配置从 config.yml 读取。
    - 预约开放时间通常为前一天 20:00，建议将本脚本设置为在 20:00 左右运行。

使用前准备：
    1. 复制 config/config.example.yml → config/config.yml，按需修改
    2. 复制 .env.example → .env，填入从浏览器复制的 Cookie
    3. 安装依赖：pip install requests pyyaml python-dotenv

更多说明见 README.md。
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path


def load_env_file(env_file: str) -> None:
    """从 .env 文件加载环境变量（简单实现，也支持 python-dotenv）。"""
    env_path = Path(env_file)
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path)
    except ImportError:
        # python-dotenv 未安装，手动解析
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)


def load_config(config_file: str) -> dict:
    """加载 YAML 配置文件。"""
    try:
        import yaml  # type: ignore
    except ImportError:
        print(
            "[ERROR] 未找到 pyyaml 库，请运行：pip install pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)

    config_path = Path(config_file)
    if not config_path.exists():
        print(
            f"[ERROR] 配置文件 {config_file!r} 不存在。\n"
            "请复制 config/config.example.yml → config/config.yml 并按需修改。",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_target_date(cfg: dict) -> str:
    """根据配置计算目标预约日期，返回 YYYY-MM-DD 字符串。"""
    mode = cfg.get("target_date_mode", "tomorrow")
    if mode == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()
    elif mode == "date":
        target = cfg.get("target_date", "")
        if not target:
            print("[ERROR] target_date_mode 为 'date' 但未指定 target_date。", file=sys.stderr)
            sys.exit(1)
        return str(target)
    else:
        print(f"[ERROR] 未知的 target_date_mode：{mode!r}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="超星图书馆座位自动预约脚本（单次执行）"
    )
    parser.add_argument(
        "--config",
        default="config/config.yml",
        help="配置文件路径（默认：config/config.yml）",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="环境变量文件路径（默认：.env）",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. 加载配置
    # ------------------------------------------------------------------
    load_env_file(args.env)
    cfg = load_config(args.config)

    # ------------------------------------------------------------------
    # 2. 初始化日志
    # ------------------------------------------------------------------
    from lib.logger import setup_logger

    log_cfg = cfg.get("logging", {})
    logger = setup_logger(
        level=log_cfg.get("level", "INFO"),
        log_file=log_cfg.get("file", ""),
    )

    logger.info("=== 超星座位自动预约脚本启动 ===")

    # ------------------------------------------------------------------
    # 3. 读取 Cookie
    # ------------------------------------------------------------------
    cookie_str = os.environ.get("CX_COOKIE", "").strip()
    if not cookie_str:
        logger.error(
            "未找到 CX_COOKIE 环境变量。\n"
            "请复制 .env.example → .env，并填入从浏览器复制的 Cookie 字符串。"
        )
        return 1

    # ------------------------------------------------------------------
    # 4. 解析业务配置
    # ------------------------------------------------------------------
    target_day = resolve_target_date(cfg)

    time_range = cfg.get("time_range", {})
    start_time = time_range.get("start", "08:00")
    end_time = time_range.get("end", "22:30")

    area = cfg.get("area", {})
    fid_enc = area.get("fid_enc", "")
    dept_id_enc = area.get("dept_id_enc", "")
    room_id = int(area.get("room_id", 0))

    seat_ids: list = cfg.get("seat_ids", [])
    # 规范化为字符串列表
    seat_ids = [str(s) for s in seat_ids]

    behavior = cfg.get("behavior", {})
    max_seats = int(behavior.get("max_seats_to_try", 5))
    interval = float(behavior.get("interval_seconds_between_seats", 0.5))
    req_timeout = int(behavior.get("request_timeout", 15))

    if not fid_enc or not dept_id_enc or not room_id:
        logger.error(
            "area 配置不完整（fid_enc / dept_id_enc / room_id 不能为空）。"
            "请检查 config/config.yml。"
        )
        return 1

    if not seat_ids:
        logger.error("seat_ids 列表为空，请在 config/config.yml 中配置目标座位号。")
        return 1

    logger.info(
        "目标：日期=%s 时间=%s-%s 房间=%s 座位列表=%s",
        target_day,
        start_time,
        end_time,
        room_id,
        seat_ids[:max_seats],
    )

    # ------------------------------------------------------------------
    # 5. 执行预约
    # ------------------------------------------------------------------
    from lib.client import AuthError
    from lib.reservation import ReservationConfig, ReservationSession

    res_cfg = ReservationConfig(
        cookie=cookie_str,
        fid_enc=fid_enc,
        dept_id_enc=dept_id_enc,
        room_id=room_id,
        first_level_name=area.get("first_level_name", ""),
        second_level_name=area.get("second_level_name", ""),
        third_level_name=area.get("third_level_name", ""),
        day=target_day,
        start_time=start_time,
        end_time=end_time,
        seat_ids=seat_ids,
        max_seats_to_try=max_seats,
        interval_seconds=interval,
        request_timeout=req_timeout,
    )

    session = ReservationSession(res_cfg)

    try:
        result = session.run()
    except AuthError as exc:
        logger.error(
            "登录态失效，无法继续预约。\n%s\n"
            "解决方法：在浏览器中重新登录图书馆座位系统，然后更新 .env 文件中的 CX_COOKIE。",
            exc,
        )
        return 2
    except KeyboardInterrupt:
        logger.info("用户中断，退出。")
        return 130
    except Exception as exc:
        logger.exception("预约过程中发生未预期错误：%s", exc)
        return 3

    # ------------------------------------------------------------------
    # 6. 输出结果摘要
    # ------------------------------------------------------------------
    if result:
        logger.info(
            "【预约成功】座位=%s 预约ID=%s 日期=%s 时间段=%s-%s",
            result.seat_num,
            result.reserve_id,
            target_day,
            start_time,
            end_time,
        )
        logger.info(
            "⚠️  提醒：请在预约开始后 30 分钟内到达图书馆扫码签到，"
            "否则将被记录为违约。"
        )
        return 0
    else:
        logger.warning(
            "【预约失败】所有候选座位均预约失败。\n"
            "可能原因：座位已被他人占用、系统未开放预约、Cookie 失效等。"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
