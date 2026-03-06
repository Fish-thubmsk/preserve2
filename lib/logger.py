"""
lib/logger.py - 日志工具模块
"""
import logging
import sys
from pathlib import Path


def setup_logger(level: str = "INFO", log_file: str = "") -> logging.Logger:
    """
    初始化并返回应用日志器。

    :param level: 日志级别字符串，如 "INFO", "DEBUG"
    :param log_file: 日志输出文件路径，留空则只输出到控制台
    :return: 配置好的 Logger 实例
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger("reserve")
    logger.setLevel(numeric_level)
    logger.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器（可选）
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
