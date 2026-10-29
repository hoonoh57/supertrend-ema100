"""Credential discovery.

Resolution order (first file wins for each key):
  1. $SUPERTREND_ENV_FILE
  2. <project>/.env

Secrets are only kept in memory and never written to reports or logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def read_env_file(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def candidate_env_files(project_root: str | Path | None = None) -> list[Path]:
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
    files: list[Path] = []
    explicit = os.environ.get("SUPERTREND_ENV_FILE")
    if explicit:
        files.append(Path(explicit))
    files.append(root / ".env")
    seen: set[str] = set()
    unique: list[Path] = []
    for p in files:
        key = str(p.resolve()).lower() if p.exists() else str(p).lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def merged_env(project_root: str | Path | None = None) -> tuple[dict[str, str], list[Path]]:
    merged: dict[str, str] = {}
    used: list[Path] = []
    for path in candidate_env_files(project_root):
        data = read_env_file(path)
        if data:
            used.append(path)
            # Earlier files take precedence.
            for k, v in data.items():
                merged.setdefault(k, v)
    return merged, used


@dataclass(frozen=True)
class Credentials:
    base_url: str
    app_key: str
    app_secret: str
    use_mock: bool
    sources: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "use_mock": self.use_mock,
            "app_key_present": bool(self.app_key),
            "app_secret_present": bool(self.app_secret),
            "sources": list(self.sources),
        }


def _pick(env: dict[str, str], *names: str) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


def resolve_credentials(
    use_mock: bool | None = None,
    project_root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Credentials:
    values, used = (env, []) if env is not None else merged_env(project_root)
    if use_mock is None:
        raw = values.get("KIWOOM_USE_MOCK", "true").strip().lower()
        use_mock = raw in ("1", "true", "yes", "y", "on")
    if use_mock:
        key = _pick(values, "KIWOOM_MOCK_APP_KEY", "KIWOOM_APP_KEY")
        secret = _pick(
            values,
            "KIWOOM_MOCK_SECRET_KEY",
            "KIWOOM_MOCK_APP_SECRET",
            "KIWOOM_SECRET_KEY",
            "KIWOOM_APP_SECRET",
        )
        base = "https://mockapi.kiwoom.com"
    else:
        key = _pick(values, "KIWOOM_REAL_APP_KEY", "KIWOOM_APP_KEY")
        secret = _pick(
            values,
            "KIWOOM_REAL_SECRET_KEY",
            "KIWOOM_REAL_APP_SECRET",
            "KIWOOM_SECRET_KEY",
            "KIWOOM_APP_SECRET",
        )
        base = "https://api.kiwoom.com"
    return Credentials(
        base_url=base,
        app_key=key,
        app_secret=secret,
        use_mock=bool(use_mock),
        sources=tuple(str(p) for p in used),
    )
