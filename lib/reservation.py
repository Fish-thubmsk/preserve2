"""
lib/reservation.py - 自动预约逻辑
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import AuthError, ReservationClient

logger = logging.getLogger("reserve")


@dataclass
class ReservationConfig:
    """预约所需的全部配置参数（合并自 config.yml 与 .env）。"""

    # 认证
    cookie: str

    # 区域参数
    fid_enc: str
    dept_id_enc: str
    room_id: int
    first_level_name: str = ""
    second_level_name: str = ""
    third_level_name: str = ""

    # 日期与时间
    day: str = ""          # YYYY-MM-DD，由主程序在运行时填入
    start_time: str = "08:00"
    end_time: str = "22:30"

    # 座位列表（按优先级排列）
    seat_ids: List[str] = field(default_factory=list)

    # 行为参数
    max_seats_to_try: int = 5
    interval_seconds: float = 0.5
    request_timeout: int = 15


@dataclass
class AttemptResult:
    """单次座位预约尝试的结果。"""

    seat_num: str
    success: bool
    reserve_id: Optional[int] = None
    message: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class ReservationSession:
    """
    执行一轮自动预约流程。

    用法::

        cfg = ReservationConfig(cookie="...", fid_enc="...", ...)
        session = ReservationSession(cfg)
        final = session.run()
        if final:
            print("预约成功，座位：", final.seat_num)
    """

    def __init__(self, cfg: ReservationConfig) -> None:
        self._cfg = cfg
        self._client = ReservationClient(cfg.cookie, timeout=cfg.request_timeout)

    def run(self) -> Optional[AttemptResult]:
        """
        执行完整的预约流程，按优先级逐个尝试座位列表。

        :returns: 第一个成功的 AttemptResult；若全部失败则返回 None
        :raises AuthError: Cookie 失效，无法继续
        """
        cfg = self._cfg
        seats_to_try = cfg.seat_ids[: cfg.max_seats_to_try]

        if not seats_to_try:
            logger.error("seat_ids 列表为空，无座位可尝试")
            return None

        logger.info(
            "开始预约流程：日期=%s 时间=%s-%s 房间=%s 座位列表=%s",
            cfg.day,
            cfg.start_time,
            cfg.end_time,
            cfg.room_id,
            seats_to_try,
        )

        # 第一步：身份验证（可选，用于快速检测 Cookie 是否有效）
        try:
            self._client.verify_identity(cfg.fid_enc)
            logger.info("身份验证通过")
        except AuthError:
            raise
        except Exception as exc:
            logger.warning("身份验证请求异常（将继续执行）：%s", exc)

        for idx, seat_num in enumerate(seats_to_try):
            if idx > 0:
                logger.info("等待 %.1f 秒后尝试下一个座位…", cfg.interval_seconds)
                time.sleep(cfg.interval_seconds)

            result = self._attempt_seat(seat_num)
            if result.success:
                logger.info(
                    "✅ 预约成功！座位=%s 预约ID=%s",
                    result.seat_num,
                    result.reserve_id,
                )
                return result
            else:
                logger.info(
                    "❌ 座位 %s 预约失败：%s",
                    result.seat_num,
                    result.message,
                )

        logger.warning("所有 %d 个座位均预约失败，本轮执行结束", len(seats_to_try))
        return None

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------

    def _attempt_seat(self, seat_num: str) -> AttemptResult:
        """
        尝试预约指定座位。

        流程：
        1. 检查座位是否存在且可预约
        2. 获取 select 页面以取得 enc 参数
        3. 提交预约请求
        """
        cfg = self._cfg

        # 1. 检查座位状态
        try:
            check_resp = self._client.check_seat_exist(seat_num, cfg.room_id)
            if not check_resp.get("success"):
                return AttemptResult(
                    seat_num=seat_num,
                    success=False,
                    message=f"check/exist 接口返回失败：{check_resp}",
                    raw_response=check_resp,
                )
            exist_count = check_resp.get("data", {}).get("existCount", -1)
            if exist_count != 0:
                return AttemptResult(
                    seat_num=seat_num,
                    success=False,
                    message=f"座位已有 {exist_count} 个预约（existCount={exist_count}），跳过",
                    raw_response=check_resp,
                )
            logger.debug("座位 %s 当前可用（existCount=0）", seat_num)
        except AuthError:
            raise
        except Exception as exc:
            logger.warning("检查座位 %s 时发生异常，将仍然尝试提交：%s", seat_num, exc)

        # 2. 获取 enc 参数（需要先加载 select 页面）
        try:
            enc = self._client.fetch_select_page_enc(
                dept_id_enc=cfg.dept_id_enc,
                room_id=cfg.room_id,
                day=cfg.day,
                fid_enc=cfg.fid_enc,
            )
            logger.debug("获取到 enc：%s", enc)
        except AuthError:
            raise
        except ValueError as exc:
            return AttemptResult(
                seat_num=seat_num,
                success=False,
                message=str(exc),
            )
        except Exception as exc:
            return AttemptResult(
                seat_num=seat_num,
                success=False,
                message=f"获取 select 页面失败：{exc}",
            )

        # 3. 提交预约
        try:
            resp = self._client.submit_reservation(
                dept_id_enc=cfg.dept_id_enc,
                room_id=cfg.room_id,
                seat_num=seat_num,
                day=cfg.day,
                start_time=cfg.start_time,
                end_time=cfg.end_time,
                submit_enc=enc,
                fid_enc=cfg.fid_enc,
            )
        except AuthError:
            raise
        except Exception as exc:
            return AttemptResult(
                seat_num=seat_num,
                success=False,
                message=f"提交预约时网络异常：{exc}",
            )

        if resp.get("success"):
            seat_reserve = resp.get("data", {}).get("seatReserve", {})
            return AttemptResult(
                seat_num=seat_num,
                success=True,
                reserve_id=seat_reserve.get("id"),
                message="预约成功",
                raw_response=resp,
            )
        else:
            # 解析失败原因（超星系统通常在 msg 字段说明原因）
            msg = resp.get("msg") or resp.get("message") or str(resp)
            return AttemptResult(
                seat_num=seat_num,
                success=False,
                message=f"服务端拒绝：{msg}",
                raw_response=resp,
            )
