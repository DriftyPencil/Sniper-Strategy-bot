from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class IGConfig:
    environment: str
    api_key: str
    username: str
    password: str
    account_id: str | None

    @property
    def base_url(self) -> str:
        env = self.environment.upper()
        if env == "LIVE":
            return "https://api.ig.com/gateway/deal"
        if env == "DEMO":
            return "https://demo-api.ig.com/gateway/deal"
        raise ValueError("IG_ENV must be DEMO or LIVE")


@dataclass(frozen=True)
class StrategyConfig:
    market_epics: list[str]
    resolution: str
    price_points: int
    max_spread_points: float
    fast_ema: int
    slow_ema: int
    rsi_period: int
    atr_period: int
    adx_period: int
    macd_fast: int
    macd_slow: int
    macd_signal: int
    score_threshold: float
    min_risk_reward: float
    stop_atr_multiple: float
    target_multiples: list[float]
    broker_target_index: int
    default_size: float


@dataclass(frozen=True)
class RuntimeConfig:
    dry_run: bool
    poll_seconds: int


@dataclass(frozen=True)
class AppConfig:
    ig: IGConfig
    strategy: StrategyConfig
    runtime: RuntimeConfig


def load_config() -> AppConfig:
    load_env_file()
    return AppConfig(
        ig=IGConfig(
            environment=os.getenv("IG_ENV", "DEMO"),
            api_key=os.getenv("IG_API_KEY", ""),
            username=os.getenv("IG_USERNAME", ""),
            password=os.getenv("IG_PASSWORD", ""),
            account_id=os.getenv("IG_ACCOUNT_ID") or None,
        ),
        strategy=StrategyConfig(
            market_epics=_csv_env("MARKET_EPICS", ["CS.D.EURUSD.MINI.IP"]),
            resolution=os.getenv("RESOLUTION", "MINUTE_5"),
            price_points=int(os.getenv("PRICE_POINTS", "120")),
            max_spread_points=float(os.getenv("MAX_SPREAD_POINTS", "2.5")),
            fast_ema=int(os.getenv("FAST_EMA", "9")),
            slow_ema=int(os.getenv("SLOW_EMA", "21")),
            rsi_period=int(os.getenv("RSI_PERIOD", "14")),
            atr_period=int(os.getenv("ATR_PERIOD", "14")),
            adx_period=int(os.getenv("ADX_PERIOD", "14")),
            macd_fast=int(os.getenv("MACD_FAST", "12")),
            macd_slow=int(os.getenv("MACD_SLOW", "26")),
            macd_signal=int(os.getenv("MACD_SIGNAL", "9")),
            score_threshold=float(os.getenv("SCORE_THRESHOLD", "0")),
            min_risk_reward=float(os.getenv("MIN_RISK_REWARD", "1.0")),
            stop_atr_multiple=float(os.getenv("STOP_ATR_MULTIPLE", "1.5")),
            target_multiples=[
                float(item)
                for item in _csv_env("TARGET_MULTIPLES", ["1", "2", "3", "4", "5"])
            ],
            broker_target_index=int(os.getenv("BROKER_TARGET_INDEX", "2")),
            default_size=float(os.getenv("DEFAULT_SIZE", "0.5")),
        ),
        runtime=RuntimeConfig(
            dry_run=_bool_env("DRY_RUN", True),
            poll_seconds=int(os.getenv("POLL_SECONDS", "60")),
        ),
    )
