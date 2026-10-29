"""Command line interface.

Examples
--------
    python run_backtest.py resolve --symbols 삼성전자,SK하이닉스
    python run_backtest.py fetch --symbols 005930,000660 --days 20
    python run_backtest.py backtest --symbols 005930,000660 --days 20 \
        --end 2026-10-28 --out runs/samsung

Without a subcommand the arguments are treated as ``backtest`` arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .backtest.metrics import compute_metrics
from .backtest.report import write_report
from .config import BacktestConfig, _coerce
from .data.cache import BarCache
from .data.loader import load_backtest_data
from .kiwoom.auth import KiwoomError
from .kiwoom.client import KiwoomClient
from .kiwoom.env import resolve_credentials
from .strategy.engine import BacktestEngine

COMMANDS = ("resolve", "fetch", "backtest", "all")


def _symbols(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for token in str(value).replace(";", ",").split(","):
            token = token.strip()
            if token:
                out.append(token)
    return out


def _parse_scalar(raw: str, current: Any) -> Any:
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    if isinstance(current, tuple) and isinstance(value, list):
        return tuple(value)
    return _coerce(value, current)


def _apply_override(cfg: BacktestConfig, item: str) -> None:
    if "=" not in item:
        raise ValueError(f"--set 값은 section.key=value 형식이어야 합니다: {item}")
    path, raw = item.split("=", 1)
    parts = [p for p in path.strip().split(".") if p]
    if not parts:
        raise ValueError(f"--set 경로가 비었습니다: {item}")
    target: Any = cfg
    for part in parts[:-1]:
        if not hasattr(target, part):
            raise ValueError(f"알 수 없는 설정 경로: {path}")
        target = getattr(target, part)
    leaf = parts[-1]
    if not hasattr(target, leaf):
        raise ValueError(f"알 수 없는 설정 키: {path}")
    setattr(target, leaf, _parse_scalar(raw, getattr(target, leaf)))


def build_config(args: argparse.Namespace) -> BacktestConfig:
    cfg = BacktestConfig.from_json(args.config) if args.config else BacktestConfig()
    if getattr(args, "symbols", None):
        cfg.data.symbols = _symbols(args.symbols)
    if getattr(args, "start", None):
        cfg.data.start = args.start
    if getattr(args, "end", None):
        cfg.data.end = args.end
    if getattr(args, "days", None) is not None:
        cfg.data.days = int(args.days)
    if getattr(args, "feature_mode", None):
        cfg.data.feature_mode = args.feature_mode
    if getattr(args, "selection", None):
        cfg.selection = args.selection
    if getattr(args, "out", None):
        cfg.out_dir = args.out
    if getattr(args, "cache_dir", None):
        cfg.data.cache_dir = args.cache_dir
    if getattr(args, "mock", False):
        cfg.use_mock = True
    if getattr(args, "real", False):
        cfg.use_mock = False
    if getattr(args, "verbose", False):
        cfg.verbose = True
    if getattr(args, "plot", False):
        cfg.plot = True
    if getattr(args, "no_score", False):
        cfg.score.enabled = False
        cfg.risk.enforce_grade = False
    if getattr(args, "score", False):
        cfg.score.enabled = True
        cfg.risk.enforce_grade = True
        if not getattr(args, "selection", None):
            cfg.selection = "score"
    for item in getattr(args, "set", None) or []:
        _apply_override(cfg, item)
    cfg.validate()
    return cfg


def _make_client(cfg: BacktestConfig) -> KiwoomClient:
    creds = resolve_credentials(use_mock=cfg.use_mock)
    if not creds.app_key or not creds.app_secret:
        raise KiwoomError(
            "Kiwoom 인증키가 없습니다. .env.example을 참고해 .env를 만들거나 "
            "SUPERTREND_ENV_FILE 환경변수로 지정한 파일을 확인하세요."
        )
    if cfg.verbose:
        summary = creds.public_summary()
        print(
            f"[kiwoom] server={summary['base_url']} mock={summary['use_mock']} "
            f"key={summary['app_key_present']} secret={summary['app_secret_present']}"
        )
        for source in summary["sources"]:
            print(f"[kiwoom] env: {source}")
    return KiwoomClient(creds, cache_dir=cfg.data.cache_dir, verbose=cfg.verbose)


def _resolve(client: KiwoomClient, cfg: BacktestConfig):
    return client.resolve_symbols(
        cfg.data.symbols, allow_unresolved=cfg.data.allow_unresolved
    )


# ------------------------------------------------------------------ commands
def cmd_resolve(args: argparse.Namespace) -> int:
    cfg = build_config(args)
    with _make_client(cfg) as client:
        infos = _resolve(client, cfg)
    print(f"{'code':<8} {'name':<24} {'market':<10} {'shares':>16} {'reg_day':<9} type")
    for info in infos:
        print(
            f"{info.code:<8} {info.name:<24} {info.market:<10} "
            f"{info.shares:>16,.0f} {info.reg_day:<9} {info.kind}"
        )
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = build_config(args)
    with _make_client(cfg) as client:
        infos = _resolve(client, cfg)
        cache = BarCache(cfg.data.cache_dir)
        data = load_backtest_data(
            client,
            cache,
            infos,
            cfg,
            progress=print if cfg.verbose else None,
            force_refresh=args.force_refresh,
        )
    print(
        f"fetched {len(data.series)} symbols · {data.start_date}~{data.end_date} "
        f"· {len(data.trading_dates)} trading days"
    )
    for code, series in data.series.items():
        print(f"  {series.name}({code}): {len(series.bars):,} bars ({series.feature_mode})")
    for warning in data.warnings:
        print(f"  ! {warning}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = build_config(args)
    with _make_client(cfg) as client:
        infos = _resolve(client, cfg)
        print(
            f"[backtest] {len(infos)} symbols · "
            f"{cfg.data.start or f'last {cfg.data.days} days'} ~ {cfg.data.end or 'latest'} "
            f"· feature_mode={cfg.data.feature_mode} · selection={cfg.selection}"
        )
        cache = BarCache(cfg.data.cache_dir)
        data = load_backtest_data(
            client,
            cache,
            infos,
            cfg,
            progress=print if cfg.verbose else None,
            force_refresh=args.force_refresh,
        )
    engine = BacktestEngine(cfg, data)
    result = engine.run()
    metrics = compute_metrics(result)
    paths = write_report(result, metrics, cfg.out_dir, plot=cfg.plot)

    overall = metrics["overall"]
    equity = metrics["equity"]
    win_rate = (
        f"{overall['win_rate']:.2%}" if overall["win_rate"] is not None else "-"
    )
    avg_r = "-" if overall["avg_r"] is None else f"{overall['avg_r']:.3f}"
    print(f"[done] trades={overall['trades']} win_rate={win_rate}")
    print(
        f"[done] avgR={avg_r} "
        f"net={overall['net_pnl']:,.0f} KRW "
        f"return={equity['total_return']:.2%} "
        f"mdd={equity['max_drawdown_pct']:.2%}"
    )
    for warning in result.warnings:
        print(f"[warn] {warning}")
    for name, path in paths.items():
        print(f"[report] {name}: {path}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    return cmd_backtest(args)


# -------------------------------------------------------------------- parser
def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--symbols",
        action="append",
        help="종목 코드 또는 이름. 쉼표로 여러 개 (예: 005930,삼성전자)",
    )
    parser.add_argument("--config", help="JSON 설정 파일 경로")
    parser.add_argument("--start", help="백테스트 시작일 YYYY-MM-DD")
    parser.add_argument("--end", help="백테스트 종료일 YYYY-MM-DD (기본: 최신)")
    parser.add_argument("--days", type=int, help="start가 없을 때 사용할 거래일 수")
    parser.add_argument("--cache-dir", help="캐시 디렉터리 (기본 .cache)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mock", action="store_true", help="모의투자 서버 강제")
    group.add_argument("--real", action="store_true", help="실전 서버 강제")
    parser.add_argument("--verbose", action="store_true", help="진행 로그 출력")
    parser.add_argument(
        "--set",
        action="append",
        metavar="SECTION.KEY=VALUE",
        help="설정 덮어쓰기 (예: --set delay.d_max=1.2 --set score.enabled=false)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supertrend-ema100",
        description="Supertrend-EMA100 전략 백테스트 (Kiwoom REST 데이터)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    resolve = sub.add_parser("resolve", help="종목 코드/이름 확인")
    _add_common(resolve)
    resolve.set_defaults(func=cmd_resolve)

    fetch = sub.add_parser("fetch", help="일봉/분봉을 캐시로 다운로드")
    _add_common(fetch)
    fetch.add_argument("--force-refresh", action="store_true", help="캐시 무시")
    fetch.set_defaults(func=cmd_fetch)

    backtest = sub.add_parser("backtest", help="백테스트 실행")
    _add_common(backtest)
    backtest.add_argument(
        "--feature-mode", choices=("auto", "bar", "tick"), help="피처 계산 모드"
    )
    backtest.add_argument(
        "--selection", choices=("score", "time", "random"), help="동시 신호 선택 규칙"
    )
    backtest.add_argument("--out", help="리포트 출력 디렉터리 (기본 runs/latest)")
    backtest.add_argument("--plot", action="store_true", help="equity.svg 생성")
    backtest.add_argument(
        "--no-score",
        action="store_true",
        help="1단계: 종합점수 계산/게이트 비활성화",
    )
    backtest.add_argument("--score", action="store_true", help="종합점수 활성화 (기본)")
    backtest.add_argument("--force-refresh", action="store_true", help="캐시 무시")
    backtest.set_defaults(func=cmd_backtest)

    all_cmd = sub.add_parser("all", help="fetch + backtest (backtest와 동일)")
    _add_common(all_cmd)
    all_cmd.add_argument("--feature-mode", choices=("auto", "bar", "tick"))
    all_cmd.add_argument("--selection", choices=("score", "time", "random"))
    all_cmd.add_argument("--out")
    all_cmd.add_argument("--plot", action="store_true")
    all_cmd.add_argument("--no-score", action="store_true")
    all_cmd.add_argument("--score", action="store_true")
    all_cmd.add_argument("--force-refresh", action="store_true")
    all_cmd.set_defaults(func=cmd_all)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-") and argv[0] not in COMMANDS:
        argv = ["backtest", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except (KiwoomError, RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[stopped]", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
