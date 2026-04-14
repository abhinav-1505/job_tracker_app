from __future__ import annotations

import hashlib
import hmac
import secrets


def _pbkdf2(password: str, salt_hex: str, iterations: int = 210_000) -> str:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return dk.hex()


def make_password_salt() -> str:
    return secrets.token_hex(16)


def hash_password(password: str, salt_hex: str) -> str:
    return _pbkdf2(password=password, salt_hex=salt_hex)


def verify_password(password: str, salt_hex: str, password_hash_hex: str) -> bool:
    calc = hash_password(password=password, salt_hex=salt_hex)
    return hmac.compare_digest(calc, password_hash_hex)

