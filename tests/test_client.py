"""
tests/test_client.py - 客户端模块单元测试
"""
import pytest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lib.client import ReservationClient, AuthError


class TestParseCookies:
    def test_simple_cookie(self):
        cookies = ReservationClient._parse_cookies("a=1; b=2; c=3")
        assert cookies == {"a": "1", "b": "2", "c": "3"}

    def test_cookie_with_spaces(self):
        cookies = ReservationClient._parse_cookies("  JSESSIONID=abc123 ; route=xyz ")
        assert "JSESSIONID" in cookies
        assert cookies["JSESSIONID"] == "abc123"

    def test_cookie_with_equals_in_value(self):
        cookies = ReservationClient._parse_cookies("token=abc=def=ghi")
        assert cookies["token"] == "abc=def=ghi"

    def test_empty_cookie(self):
        cookies = ReservationClient._parse_cookies("")
        assert cookies == {}


class TestCheckAuth:
    def test_no_auth_error_on_json_response(self):
        resp = MagicMock()
        resp.headers = {"Content-Type": "application/json"}
        resp.url = "https://office.chaoxing.com/data/apps/seat/submit"
        # Should not raise
        ReservationClient._check_auth(resp)

    def test_auth_error_on_login_redirect(self):
        resp = MagicMock()
        resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        resp.url = "https://passport2.chaoxing.com/login?refer=..."
        with pytest.raises(AuthError):
            ReservationClient._check_auth(resp)

    def test_no_auth_error_on_html_non_login(self):
        resp = MagicMock()
        resp.headers = {"Content-Type": "text/html"}
        resp.url = "https://office.chaoxing.com/front/third/apps/seat/select"
        # Should not raise (not a login page)
        ReservationClient._check_auth(resp)


class TestFetchSelectPageEnc:
    def test_parse_submit_enc_standard_order(self):
        """fetch_select_page_enc should extract the submit_enc value from the page HTML."""
        client = ReservationClient(cookie_str="JSESSIONID=test")

        html = (
            '<html><body>'
            '<input type="hidden" id="submit_enc" value="abc123token_238771432"/>'
            '</body></html>'
        )

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.url = "https://office.chaoxing.com/front/third/apps/seat/select"

        with patch.object(client, "_get", return_value=mock_resp):
            enc = client.fetch_select_page_enc(
                dept_id_enc="4a18e12602b24c8c",
                room_id=13481,
                day="2026-03-07",
                fid_enc="4a18e12602b24c8c",
            )
        assert enc == "abc123token_238771432"

    def test_parse_submit_enc_alternate_order(self):
        """Handle alternate HTML attribute order."""
        client = ReservationClient(cookie_str="JSESSIONID=test")

        html = (
            '<html><body>'
            '<input value="xyz789_111" id="submit_enc" type="hidden"/>'
            '</body></html>'
        )

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.url = "https://office.chaoxing.com/front/third/apps/seat/select"

        with patch.object(client, "_get", return_value=mock_resp):
            enc = client.fetch_select_page_enc(
                dept_id_enc="4a18e12602b24c8c",
                room_id=13481,
                day="2026-03-07",
                fid_enc="4a18e12602b24c8c",
            )
        assert enc == "xyz789_111"

    def test_raises_value_error_if_not_found(self):
        """Should raise ValueError if submit_enc is absent from page."""
        client = ReservationClient(cookie_str="JSESSIONID=test")

        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Some page without submit_enc</body></html>"
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.url = "https://office.chaoxing.com/front/third/apps/seat/select"

        with patch.object(client, "_get", return_value=mock_resp):
            with pytest.raises(ValueError, match="submit_enc"):
                client.fetch_select_page_enc(
                    dept_id_enc="4a18e12602b24c8c",
                    room_id=13481,
                    day="2026-03-07",
                    fid_enc="4a18e12602b24c8c",
                )


class TestComputeEnc:
    """Tests for the enc computation used when submitting a reservation."""

    def test_matches_real_har_data(self):
        """Verify enc computation against captured real-world data from session.har."""
        form_data = {
            "deptIdEnc": "4a18e12602b24c8c",
            "roomId": "13481",
            "startTime": "12:00",
            "endTime": "22:30",
            "day": "2026-03-06",
            "seatNum": "014",
            "captcha": "",
            "wyToken": "",
        }
        submit_enc = "baea60c55f554ce7ab3c43f952228d7e_238771432"
        expected_enc = "bd8b8ff5d7c60d7add50fcbcf4017274"

        result = ReservationClient._compute_enc(form_data, submit_enc)
        assert result == expected_enc

    def test_sorted_order_is_key(self):
        """Enc computation should be based on alphabetically sorted keys."""
        # Same params in different insertion order should yield the same enc
        form_data_a = {
            "roomId": "100",
            "day": "2026-01-01",
            "captcha": "",
            "wyToken": "",
        }
        form_data_b = {
            "captcha": "",
            "wyToken": "",
            "roomId": "100",
            "day": "2026-01-01",
        }
        submit_enc = "sometoken_123"
        assert ReservationClient._compute_enc(form_data_a, submit_enc) == \
               ReservationClient._compute_enc(form_data_b, submit_enc)

    def test_different_submit_enc_gives_different_enc(self):
        """Different submit_enc values must produce different enc outputs."""
        form_data = {"roomId": "100", "day": "2026-01-01"}
        enc1 = ReservationClient._compute_enc(form_data, "token_a_123")
        enc2 = ReservationClient._compute_enc(form_data, "token_b_456")
        assert enc1 != enc2

    def test_enc_is_32_char_hex(self):
        """Output should be a 32-character lowercase hex string (MD5)."""
        result = ReservationClient._compute_enc({"roomId": "1"}, "tok_1")
        assert len(result) == 32
        assert result == result.lower()
        assert all(c in "0123456789abcdef" for c in result)
