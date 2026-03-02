"""Manages comment boost accounts, texts, and settings."""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR

logger = logging.getLogger(__name__)

_CONFIG_PATH = DATA_DIR / "comment_config.json"

_DEFAULT_CONFIG: dict[str, Any] = {
    "accounts": [],
    "texts": [],
    "total_comments_range": [20, 40],
    "per_acc_comments": 3,
    "enabled": True,
    "proxy": "",
}


def _extract_auth_token(raw: str) -> str | None:
    """Extract a 40-char hex auth_token from a string like 'login:pass:token' or plain token."""
    parts = raw.strip().split(":")
    token = next((p for p in parts if len(p) == 40 and re.fullmatch(r'[a-fA-F0-9]{40}', p)), None)
    if token:
        return token
    # Fallback: search anywhere in the string
    m = re.search(r'[a-fA-F0-9]{40}', raw)
    return m.group(0) if m else None


class CommentPool:
    """Manages comment boost accounts, texts, and settings.

    Backed by ``data/comment_config.json``.
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = dict(_DEFAULT_CONFIG)
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if _CONFIG_PATH.exists():
            try:
                data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
                self._config.update(data)
                logger.info(
                    "CommentPool loaded: %d accounts, %d texts",
                    len(self._config.get("accounts", [])),
                    len(self._config.get("texts", [])),
                )
            except Exception as exc:
                logger.error("Failed to load comment_config.json: %s", exc)

    def _save(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps(self._config, indent=2, default=str), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------

    def add_account(self, raw_token: str) -> bool:
        """Add a comment account. Extracts 40-char hex. Returns False if duplicate or invalid."""
        auth_token = _extract_auth_token(raw_token)
        if not auth_token:
            return False
        accounts = self._config.setdefault("accounts", [])
        for acc in accounts:
            if acc["value"] == auth_token:
                if not acc.get("valid", True):
                    acc["valid"] = True
                    self._save()
                return False
        accounts.append({
            "value": auth_token,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "valid": True,
        })
        self._save()
        return True

    def add_accounts_bulk(self, raw_lines: list[str]) -> tuple[int, int]:
        """Add multiple accounts. Returns (new_count, dup_count)."""
        new_count = 0
        dup_count = 0
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            if self.add_account(line):
                new_count += 1
            else:
                dup_count += 1
        return new_count, dup_count

    def remove_account(self, index: int) -> bool:
        accounts = self._config.get("accounts", [])
        if 0 <= index < len(accounts):
            accounts.pop(index)
            self._save()
            return True
        return False

    def clear_all_accounts(self) -> int:
        count = len(self._config.get("accounts", []))
        self._config["accounts"] = []
        self._save()
        return count

    def clear_invalid_accounts(self) -> int:
        accounts = self._config.get("accounts", [])
        before = len(accounts)
        self._config["accounts"] = [a for a in accounts if a.get("valid", True)]
        removed = before - len(self._config["accounts"])
        if removed:
            self._save()
        return removed

    def mark_invalid(self, token_value: str) -> None:
        for acc in self._config.get("accounts", []):
            if acc["value"] == token_value:
                acc["valid"] = False
                self._save()
                return

    def get_valid_accounts(self) -> list[dict[str, Any]]:
        return [a for a in self._config.get("accounts", []) if a.get("valid", True)]

    def count_valid_accounts(self) -> int:
        return sum(1 for a in self._config.get("accounts", []) if a.get("valid", True))

    def count_total_accounts(self) -> int:
        return len(self._config.get("accounts", []))

    # ------------------------------------------------------------------
    # Comment texts
    # ------------------------------------------------------------------

    @property
    def texts(self) -> list[str]:
        return list(self._config.get("texts", []))

    def add_text(self, text: str) -> None:
        texts = self._config.setdefault("texts", [])
        texts.append(text)
        self._save()

    def add_texts_bulk(self, lines: list[str]) -> int:
        count = 0
        texts = self._config.setdefault("texts", [])
        for line in lines:
            line = line.strip()
            if line:
                texts.append(line)
                count += 1
        if count:
            self._save()
        return count

    def clear_texts(self) -> int:
        count = len(self._config.get("texts", []))
        self._config["texts"] = []
        self._save()
        return count

    def get_random_text(self) -> str | None:
        texts = self._config.get("texts", [])
        return random.choice(texts) if texts else None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @property
    def total_range(self) -> list[int]:
        return self._config.get("total_comments_range", [20, 40])

    def set_total_range(self, min_val: int, max_val: int) -> None:
        self._config["total_comments_range"] = [min_val, max_val]
        self._save()

    @property
    def per_acc_comments(self) -> int:
        return self._config.get("per_acc_comments", 3)

    def set_per_acc(self, count: int) -> None:
        self._config["per_acc_comments"] = count
        self._save()

    @property
    def proxy(self) -> str:
        return self._config.get("proxy", "")

    def set_proxy(self, proxy_string: str) -> None:
        self._config["proxy"] = proxy_string.strip()
        self._save()

    def is_enabled(self) -> bool:
        return self._config.get("enabled", True)

    def toggle(self) -> bool:
        new_val = not self._config.get("enabled", True)
        self._config["enabled"] = new_val
        self._save()
        return new_val

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def summary(self) -> str:
        valid = self.count_valid_accounts()
        total = self.count_total_accounts()
        texts_count = len(self._config.get("texts", []))
        r = self.total_range
        per_acc = self.per_acc_comments
        proxy = self.proxy or "(none)"
        status = "ON" if self.is_enabled() else "OFF"
        return (
            f"Comment Boost Settings\n\n"
            f"Status: {status}\n"
            f"Accounts: {valid} valid / {total} total\n"
            f"Texts: {texts_count} loaded\n"
            f"Range: {r[0]}-{r[1]} comments\n"
            f"Per account: {per_acc} comments\n"
            f"Proxy: {proxy}"
        )

    def accounts_summary(self) -> str:
        accounts = self._config.get("accounts", [])
        valid = sum(1 for a in accounts if a.get("valid", True))
        invalid = len(accounts) - valid
        parts = [f"Comment Accounts: {valid} valid / {invalid} invalid / {len(accounts)} total"]
        previews = []
        for a in accounts[:5]:
            icon = "V" if a.get("valid", True) else "X"
            previews.append(f"{a['value'][:8]}...({icon})")
        if previews:
            parts.append("First 5: " + ", ".join(previews))
        return "\n".join(parts)
