"""Kiwoom REST authentication and throttled HTTP transport."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .env import Credentials


class KiwoomError(RuntimeError):
    pass


class KiwoomAuthError(KiwoomError):
    pass


class KiwoomRateLimitError(KiwoomError):
    pass


@dataclass
class Response:
    json: dict[str, Any]
    status: int
    headers: dict[str, str]


def _parse_expiry(value: str) -> float | None:
    value = (value or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).timestamp()
        except ValueError:
            continue
    return None


class KiwoomHttp:
    """One session = one token + per-api-id rate limiting."""

    # The REST gateway allows one call per second per API ID.  A small margin
    # avoids 429s when a page boundary is crossed.
    DEFAULT_MIN_INTERVAL = 1.08

    def __init__(
        self,
        credentials: Credentials,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: float = 30.0,
        verbose: bool = False,
    ) -> None:
        self.creds = credentials
        self.min_interval = max(0.0, min_interval)
        self.timeout = timeout
        self.verbose = verbose
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expiry: float | None = None
        self._last_call: dict[str, float] = {}
        self.call_count = 0

    # ------------------------------------------------------------------ auth
    @property
    def token(self) -> str | None:
        return self._token

    def _token_valid(self) -> bool:
        if not self._token:
            return False
        if self._token_expiry is None:
            return True
        return time.time() < self._token_expiry - 300

    def issue_token(self, force: bool = False) -> str:
        if not force and self._token_valid():
            assert self._token is not None
            return self._token
        if not self.creds.app_key or not self.creds.app_secret:
            raise KiwoomAuthError(
                "키움 AppKey/SecretKey를 찾지 못했습니다. 프로젝트 .env 또는 "
                "SUPERTREND_ENV_FILE로 지정한 파일의 KIWOOM_* 값을 확인하세요."
            )
        url = f"{self.creds.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.creds.app_key.strip(),
            "secretkey": self.creds.app_secret.strip(),
        }
        if self.verbose:
            print(f"[kiwoom] token request -> {url} (mock={self.creds.use_mock})")
        try:
            res = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KiwoomAuthError(f"토큰 요청 네트워크 오류: {exc}") from exc
        self.call_count += 1
        try:
            data = res.json()
        except ValueError as exc:
            raise KiwoomAuthError(
                f"토큰 응답 파싱 실패 (HTTP {res.status_code}): {res.text[:200]}"
            ) from exc
        token = data.get("token") or data.get("access_token")
        if not token:
            msg = data.get("return_msg") or data.get("error_description") or res.text[:200]
            raise KiwoomAuthError(f"토큰 발급 실패 (HTTP {res.status_code}): {msg}")
        self._token = str(token)
        self._token_expiry = _parse_expiry(str(data.get("expires_dt", "")))
        if self.verbose:
            expiry = (
                datetime.fromtimestamp(self._token_expiry).isoformat()
                if self._token_expiry
                else "unknown"
            )
            print(f"[kiwoom] token issued (expires {expiry})")
        return self._token

    # --------------------------------------------------------------- request
    def _throttle(self, api_id: str) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        last = self._last_call.get(api_id, 0.0)
        wait = self.min_interval - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._last_call[api_id] = time.monotonic()

    def request(
        self,
        api_id: str,
        path: str,
        body: dict[str, Any],
        cont_yn: str = "N",
        next_key: str = "",
        retries: int = 3,
    ) -> Response:
        token = self.issue_token()
        url = f"{self.creds.base_url}{path}"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": api_id,
            "cont-yn": cont_yn,
            "next-key": next_key or "",
        }
        last_error: Exception | None = None
        for attempt in range(retries):
            self._throttle(api_id)
            try:
                res = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                continue
            self.call_count += 1
            try:
                data = res.json()
            except ValueError:
                last_error = KiwoomError(
                    f"{api_id} 응답 JSON 파싱 실패 (HTTP {res.status_code}): {res.text[:200]}"
                )
                time.sleep(1.0 * (attempt + 1))
                continue

            rc = str(data.get("return_code", "0"))
            msg = str(data.get("return_msg") or data.get("msg") or "")
            if res.status_code == 429 or (rc == "5" and "요청" in msg):
                # Rate limit - wait and retry.
                last_error = KiwoomRateLimitError(f"{api_id}: {msg or '요청 한도 초과'}")
                time.sleep(max(2.0, self.min_interval * (attempt + 2)))
                continue
            if self._is_auth_error(res.status_code, rc, msg):
                if attempt == 0:
                    token = self.issue_token(force=True)
                    headers["authorization"] = f"Bearer {token}"
                    continue
                raise KiwoomAuthError(f"{api_id} 인증 오류 (HTTP {res.status_code}): {msg}")
            if res.status_code >= 400:
                raise KiwoomError(f"{api_id} HTTP {res.status_code}: {msg or res.text[:200]}")
            if rc != "0":
                raise KiwoomError(f"{api_id} 키움 오류 {rc}: {msg}")
            hdr = {k.lower(): v for k, v in res.headers.items()}
            return Response(json=data, status=res.status_code, headers=hdr)
        raise KiwoomError(f"{api_id} 요청 실패: {last_error}")

    @staticmethod
    def _is_auth_error(status: int, rc: str, msg: str) -> bool:
        if status in (401, 403):
            return True
        if rc.startswith("80"):
            return True
        return any(word in msg for word in ("토큰", "인증", "권한"))
