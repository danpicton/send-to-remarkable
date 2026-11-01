"""Single-account, fixed-lifetime sessions; no passwords are stored in cookies."""

import hashlib
import hmac
import time
from collections import deque

from fastapi import Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from app.errors import AppError


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class SessionAuth:
    cookie = "__Host-rm-send-session"

    def __init__(self, settings):
        self.username = settings.rmfakecloud_username
        self.password = settings.rmfakecloud_password.get_secret_value()
        self.max_age = settings.auth_session_days * 86400
        # Changing either credential invalidates all existing sessions.
        credential_version = hashlib.sha256(
            (self.username + "\0" + self.password).encode()
        ).hexdigest()
        self.signer = URLSafeTimedSerializer(
            settings.auth_session_secret.get_secret_value(),
            salt="rm-send-session-v1:" + credential_version,
            signer_kwargs={"digest_method": hashlib.sha256},
        )
        # Account-wide bound, independent of spoofable forwarded client addresses.
        # Single worker per pod, as with the application's conversion limits.
        self.attempts = deque()

    def valid(self, request: Request) -> bool:
        token = request.cookies.get(self.cookie, "")
        if not token or len(token) > 2048:
            return False
        try:
            return self.signer.loads(token, max_age=self.max_age) == {
                "origin": request.state.public_origin
            }
        except BadSignature:
            return False

    def login(self, payload: Login, request: Request):
        now = time.monotonic()
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= 5:
            raise AppError(
                "login_throttled", "Too many sign-in attempts. Try again in a minute.", 429
            )
        self.attempts.append(now)
        user_ok = hmac.compare_digest(payload.username.encode(), self.username.encode())
        password_ok = hmac.compare_digest(payload.password.encode(), self.password.encode())
        if not (user_ok and password_ok):
            raise AppError("invalid_login", "Incorrect username or password.", 401)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            self.cookie,
            self.signer.dumps({"origin": request.state.public_origin}),
            max_age=self.max_age,
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return response
