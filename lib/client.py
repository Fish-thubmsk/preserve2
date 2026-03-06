"""
lib/client.py - HTTP 请求客户端封装
"""
import logging
import time
from hashlib import md5
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("reserve")

BASE_URL = "https://office.chaoxing.com"

# 模拟真实浏览器的请求头（来自抓包数据）
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


class AuthError(Exception):
    """登录态失效或权限不足时抛出。"""


class ReservationClient:
    """
    封装与超星座位预约系统的 HTTP 交互。

    使用方式::

        client = ReservationClient(cookie_str="JSESSIONID=xxx; ...")
        room_info = client.get_room_info(room_id=13481, day="2026-03-07")
        result = client.submit_reservation(...)
    """

    def __init__(self, cookie_str: str, timeout: int = 15) -> None:
        """
        :param cookie_str: 完整的 Cookie 字符串（从浏览器复制）
        :param timeout: HTTP 请求超时秒数
        """
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._session.cookies.update(self._parse_cookies(cookie_str))

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cookies(cookie_str: str) -> Dict[str, str]:
        """将 Cookie 字符串解析为字典。"""
        cookies: Dict[str, str] = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                cookies[key.strip()] = value.strip()
        return cookies

    def _get(self, path: str, params: Optional[Dict] = None, **kwargs) -> requests.Response:
        url = BASE_URL + path
        logger.debug("GET %s params=%s", url, params)
        resp = self._session.get(url, params=params, timeout=self._timeout, **kwargs)
        resp.raise_for_status()
        self._check_auth(resp)
        return resp

    def _post(self, path: str, data: Optional[Dict] = None, **kwargs) -> requests.Response:
        url = BASE_URL + path
        logger.debug("POST %s data=%s", url, data)
        resp = self._session.post(url, data=data, timeout=self._timeout, **kwargs)
        resp.raise_for_status()
        self._check_auth(resp)
        return resp

    @staticmethod
    def _compute_enc(form_data: Dict[str, str], submit_enc: str) -> str:
        """
        计算预约提交所需的 enc 参数。

        算法：将表单字段按键名排序后格式化为 ``[key=value]``，
        最后追加 ``[submit_enc_value]``，对整个字符串做 MD5。

        :param form_data: 不含 enc 字段的表单数据（值均为字符串）
        :param submit_enc: 从 HTML 页面提取的 submit_enc 原始值
        :returns: 32 位小写十六进制 MD5 字符串
        """
        parts = ["[" + k + "=" + v + "]" for k, v in sorted(form_data.items())]
        parts.append("[" + submit_enc + "]")
        return md5("".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _check_auth(resp: requests.Response) -> None:
        """检测响应是否为登录页面重定向（Cookie 失效信号）。"""
        ct = resp.headers.get("Content-Type", "")
        if "text/html" in ct and "login" in resp.url:
            raise AuthError(
                "检测到登录页面重定向，Cookie 可能已失效。"
                "请重新在浏览器登录图书馆座位系统后更新 .env 中的 CX_COOKIE。"
            )

    # ------------------------------------------------------------------
    # 公开 API 方法
    # ------------------------------------------------------------------

    def verify_identity(self, fid_enc: str) -> Dict[str, Any]:
        """验证用户身份（/data/apps/seat/identity/verify）。"""
        resp = self._get(
            "/data/apps/seat/identity/verify",
            params={"mappId": "0", "fidEnc": fid_enc},
        )
        result: Dict[str, Any] = resp.json()
        if not result.get("success"):
            raise AuthError(f"身份验证失败：{result}")
        return result

    def get_room_list(
        self,
        dept_id_enc: str,
        day: str,
        first_level_name: str = "",
        second_level_name: str = "",
        third_level_name: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """获取房间列表（/data/apps/seat/room/list）。"""
        resp = self._get(
            "/data/apps/seat/room/list",
            params={
                "time": "",
                "cpage": str(page),
                "pageSize": str(page_size),
                "firstLevelName": first_level_name,
                "secondLevelName": second_level_name,
                "thirdLevelName": third_level_name,
                "day": day,
                "deptIdEnc": dept_id_enc,
            },
        )
        return resp.json()

    def get_room_info(
        self, room_id: int, day: str, fid_enc: str
    ) -> Dict[str, Any]:
        """获取房间详情（/data/apps/seat/room/info）。"""
        resp = self._post(
            "/data/apps/seat/room/info",
            data={
                "id": str(room_id),
                "toDay": day,
                "fidEnc": fid_enc,
                "queryReserve": "true",
            },
        )
        return resp.json()

    def get_seat_grid(self, room_id: int, fid_enc: str) -> Dict[str, Any]:
        """获取座位网格（/data/apps/seat/seatgrid/roomid）。"""
        resp = self._get(
            "/data/apps/seat/seatgrid/roomid",
            params={"roomId": str(room_id), "fidEnc": fid_enc},
        )
        return resp.json()

    def get_used_seat_nums(
        self,
        room_id: int,
        day: str,
        start_time: str,
        end_time: str,
        fid_enc: str,
    ) -> Dict[str, Any]:
        """获取已预约座位统计（/data/apps/seat/getusedseatnums）。"""
        resp = self._post(
            "/data/apps/seat/getusedseatnums",
            data={
                "roomId": str(room_id),
                "startTime": start_time,
                "endTime": end_time,
                "day": day,
                "fidEnc": fid_enc,
            },
        )
        return resp.json()

    def check_seat_exist(self, seat_num: str, room_id: int) -> Dict[str, Any]:
        """
        检查座位是否存在且可预约（/data/apps/seat/check/exist）。

        返回示例：``{"data": {"existCount": 0, "signDuration": 30}, "success": true}``

        existCount == 0 表示该座位当前时段无预约，可以尝试预约。
        """
        resp = self._get(
            "/data/apps/seat/check/exist",
            params={"seatNum": seat_num, "roomId": str(room_id)},
        )
        return resp.json()

    def fetch_select_page_enc(
        self,
        dept_id_enc: str,
        room_id: int,
        day: str,
        fid_enc: str,
    ) -> str:
        """
        获取座位选择页面，并解析出预约所需的 enc 参数。

        超星系统在 HTML 页面中内嵌了一个隐藏字段::

            <input type="hidden" id="submit_enc" value="{token}_{uid}"/>

        此 token 需要随 POST /data/apps/seat/submit 一起提交。

        :returns: 完整的 submit_enc 值（含 ``_{uid}`` 后缀）
        :raises ValueError: 若页面中未找到 submit_enc 字段
        """
        import re

        self._session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": BASE_URL + "/front/third/apps/seat/list?deptIdEnc=" + dept_id_enc,
            }
        )
        resp = self._get(
            "/front/third/apps/seat/select",
            params={
                "deptIdEnc": dept_id_enc,
                "id": str(room_id),
                "day": day,
                "backLevel": "2",
                "fidEnc": fid_enc,
            },
        )
        # Restore XHR accept header for subsequent API calls
        self._session.headers.update({"Accept": "*/*"})

        # Match <input> tag that has id="submit_enc" regardless of attribute order
        match = re.search(
            r'<input\b[^>]*\bid="submit_enc"[^>]*\bvalue="([^"]+)"'
            r'|'
            r'<input\b[^>]*\bvalue="([^"]+)"[^>]*\bid="submit_enc"',
            resp.text,
        )
        enc_value = (match.group(1) or match.group(2)) if match else None
        if not enc_value:
            raise ValueError(
                "在座位选择页面中未找到 submit_enc 字段，"
                "请检查 Cookie 是否有效或房间/日期参数是否正确。"
            )
        return enc_value

    def submit_reservation(
        self,
        dept_id_enc: str,
        room_id: int,
        seat_num: str,
        day: str,
        start_time: str,
        end_time: str,
        submit_enc: str,
        fid_enc: str,
    ) -> Dict[str, Any]:
        """
        提交座位预约（POST /data/apps/seat/submit）。

        :param submit_enc: 从 fetch_select_page_enc() 获取的 submit_enc 原始值（含 ``_{uid}`` 后缀）
        :returns: API 响应的 JSON dict
        :raises AuthError: 登录态失效
        :raises requests.HTTPError: HTTP 层面的错误
        """
        referer = (
            f"{BASE_URL}/front/third/apps/seat/select"
            f"?deptIdEnc={dept_id_enc}&id={room_id}&day={day}"
            f"&backLevel=2&fidEnc={fid_enc}"
        )
        self._session.headers.update(
            {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": BASE_URL,
                "Referer": referer,
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
            }
        )
        form_data = {
            "deptIdEnc": dept_id_enc,
            "roomId": str(room_id),
            "startTime": start_time,
            "endTime": end_time,
            "day": day,
            "seatNum": seat_num,
            "captcha": "",
            "wyToken": "",
        }
        form_data["enc"] = self._compute_enc(form_data, submit_enc)
        resp = self._post(
            "/data/apps/seat/submit",
            data=form_data,
        )
        return resp.json()

    def cancel_reservation(self, reserve_id: int) -> Dict[str, Any]:
        """
        签退/取消预约（GET /data/apps/seat/signback）。

        :param reserve_id: 预约 ID（由 submit_reservation 响应中的 id 字段获取）
        """
        resp = self._get(
            "/data/apps/seat/signback",
            params={"id": str(reserve_id)},
        )
        return resp.json()
