"""Best-effort redaction of identifying data before anything leaves the machine.

This reduces exposure, it does NOT make sending logs to a third party compliant.
"""

from __future__ import annotations

import re

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HOME = re.compile(r"/(?:home|Users)/[^/\s\"']+")
_URL_CRED = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")


def _ip(m: re.Match) -> str:
    ip = m.group(0)
    return ip if ip.startswith(("127.", "0.0.0.0")) else "<ip>"


def redact(text: str) -> str:
    text = _URL_CRED.sub(r"\1<credentials>@", text)
    text = _EMAIL.sub("<email>", text)
    text = _HOME.sub(lambda m: "/" + m.group(0).split("/")[1] + "/<user>", text)
    return _IPV4.sub(_ip, text)
