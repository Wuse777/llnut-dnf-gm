"""Interoperate with the deployed pipe-delimited AES-GCM protocol.

Do not log decrypted responses: successful login responses contain game tokens.
"""
import base64
import hashlib
import os
import urllib.request
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class Gateway:
    def __init__(self, url: str, aes_hex: str):
        if not url.startswith("https://"):
            raise ValueError("Production gateway requires verified HTTPS")
        self.url = url.rstrip("/")
        self.cipher = AESGCM(bytes.fromhex(aes_hex))
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, command: str, username: str, password: str) -> dict:
        if command not in ("login", "regedit"):
            raise ValueError("Unsupported M0 request")
        if not username.isascii() or not username.replace("_", "").isalnum():
            raise ValueError("Invalid account name")
        digest = hashlib.md5(password.encode()).hexdigest()  # Existing game protocol, not GM password storage.
        last = "00-00-00-00-00-00" if command == "login" else ""
        nonce = os.urandom(12)
        plain = f"{command}|{username}|{digest}|{last}".encode()
        payload = base64.b64encode(nonce + self.cipher.encrypt(nonce, plain, None))
        request = urllib.request.Request(self.url + "/api/v1/auth", data=payload,
                                        headers={"Content-Type": "application/octet-stream"})
        with self.opener.open(request, timeout=15) as response:
            encrypted = base64.b64decode(response.read(8193), validate=True)
            text = self.cipher.decrypt(encrypted[:12], encrypted[12:], None).decode()
        # Deliberately return neither the token nor raw response text.
        accepted = text.startswith("0|") if command == "login" else text == "success"
        return {"accepted": accepted, "http_status": response.status}
