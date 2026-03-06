"""
tests/test_reservation.py - 预约逻辑单元测试
"""
import pytest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lib.client import AuthError
from lib.reservation import ReservationConfig, ReservationSession, AttemptResult


def make_config(**kwargs):
    defaults = dict(
        cookie="JSESSIONID=test",
        fid_enc="4a18e12602b24c8c",
        dept_id_enc="4a18e12602b24c8c",
        room_id=13481,
        day="2026-03-07",
        start_time="08:00",
        end_time="22:30",
        seat_ids=["014", "015"],
        max_seats_to_try=5,
        interval_seconds=0.0,
        request_timeout=10,
    )
    defaults.update(kwargs)
    return ReservationConfig(**defaults)


class TestReservationSession:
    def _make_session(self, cfg=None):
        if cfg is None:
            cfg = make_config()
        return ReservationSession(cfg)

    def test_returns_none_for_empty_seat_list(self):
        cfg = make_config(seat_ids=[])
        session = self._make_session(cfg)
        with patch.object(session._client, "verify_identity") as mock_vi:
            mock_vi.return_value = {"success": True}
            result = session.run()
        assert result is None

    def test_successful_reservation(self):
        session = self._make_session()

        with (
            patch.object(session._client, "verify_identity", return_value={"success": True}),
            patch.object(
                session._client,
                "check_seat_exist",
                return_value={"success": True, "data": {"existCount": 0}},
            ),
            patch.object(
                session._client,
                "fetch_select_page_enc",
                return_value="some_enc_token_238771432",
            ),
            patch.object(
                session._client,
                "submit_reservation",
                return_value={
                    "success": True,
                    "data": {
                        "seatReserve": {
                            "id": 99999,
                            "seatNum": "014",
                            "roomId": 13481,
                        }
                    },
                },
            ),
        ):
            result = session.run()

        assert result is not None
        assert result.success is True
        assert result.seat_num == "014"
        assert result.reserve_id == 99999

    def test_skips_occupied_seat_and_tries_next(self):
        session = self._make_session()

        def check_seat_side_effect(seat_num, room_id):
            if seat_num == "014":
                return {"success": True, "data": {"existCount": 1}}
            return {"success": True, "data": {"existCount": 0}}

        with (
            patch.object(session._client, "verify_identity", return_value={"success": True}),
            patch.object(session._client, "check_seat_exist", side_effect=check_seat_side_effect),
            patch.object(
                session._client,
                "fetch_select_page_enc",
                return_value="enc_token",
            ),
            patch.object(
                session._client,
                "submit_reservation",
                return_value={
                    "success": True,
                    "data": {"seatReserve": {"id": 88888, "seatNum": "015"}},
                },
            ),
        ):
            result = session.run()

        assert result is not None
        assert result.seat_num == "015"

    def test_all_seats_fail(self):
        session = self._make_session()

        with (
            patch.object(session._client, "verify_identity", return_value={"success": True}),
            patch.object(
                session._client,
                "check_seat_exist",
                return_value={"success": True, "data": {"existCount": 0}},
            ),
            patch.object(
                session._client,
                "fetch_select_page_enc",
                return_value="enc_token",
            ),
            patch.object(
                session._client,
                "submit_reservation",
                return_value={"success": False, "msg": "座位已满"},
            ),
        ):
            result = session.run()

        assert result is None

    def test_auth_error_propagates(self):
        session = self._make_session()

        with patch.object(
            session._client,
            "verify_identity",
            side_effect=AuthError("Cookie 失效"),
        ):
            with pytest.raises(AuthError):
                session.run()

    def test_max_seats_to_try_limits_attempts(self):
        cfg = make_config(seat_ids=["001", "002", "003", "004", "005"], max_seats_to_try=2)
        session = self._make_session(cfg)

        attempt_count = 0

        def check_seat_side_effect(seat_num, room_id):
            nonlocal attempt_count
            attempt_count += 1
            return {"success": True, "data": {"existCount": 0}}

        with (
            patch.object(session._client, "verify_identity", return_value={"success": True}),
            patch.object(session._client, "check_seat_exist", side_effect=check_seat_side_effect),
            patch.object(
                session._client,
                "fetch_select_page_enc",
                return_value="enc_token",
            ),
            patch.object(
                session._client,
                "submit_reservation",
                return_value={"success": False, "msg": "失败"},
            ),
        ):
            result = session.run()

        assert result is None
        assert attempt_count == 2  # Should only try 2 seats (max_seats_to_try)
