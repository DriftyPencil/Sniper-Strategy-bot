from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from sniper_bot.config import load_config
from sniper_bot.csv_loader import load_candles_csv
from sniper_bot.market import Candle
from sniper_bot.strategy import Direction, Signal, SniperStrategy


@dataclass(frozen=True)
class Trade:
    direction: Direction
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    exit_reason: str
    pnl_points: float
    pnl_cash: float
    bull_score: float
    bear_score: float
    bias: str


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    net_points: float
    net_cash: float
    win_rate: float
    profit_factor: float
    max_drawdown_cash: float


def run_backtest(candles: list[Candle], strategy: SniperStrategy, size: float) -> BacktestResult:
    trades: list[Trade] = []
    open_signal: Signal | None = None
    open_time = ""

    for index in range(1, len(candles)):
        history = candles[: index + 1]
        current = candles[index]

        if open_signal is not None:
            exit_price, exit_reason = _exit_for_candle(current, open_signal)
            if exit_price is not None:
                pnl_points = _pnl_points(open_signal.direction, open_signal.entry_price, exit_price)
                trades.append(
                    Trade(
                        direction=open_signal.direction,
                        entry_time=open_time,
                        exit_time=current.timestamp.isoformat(),
                        entry_price=open_signal.entry_price,
                        exit_price=exit_price,
                        stop_price=open_signal.stop_price,
                        target_price=_target_price(open_signal),
                        exit_reason=exit_reason,
                        pnl_points=pnl_points,
                        pnl_cash=pnl_points * size,
                        bull_score=open_signal.bull_score,
                        bear_score=open_signal.bear_score,
                        bias=open_signal.bias,
                    )
                )
                open_signal = None
            continue

        signal = strategy.evaluate(history)
        if signal.direction in {Direction.BUY, Direction.SELL}:
            open_signal = signal
            open_time = current.timestamp.isoformat()

    if open_signal is not None:
        final = candles[-1]
        pnl_points = _pnl_points(open_signal.direction, open_signal.entry_price, final.close_mid)
        trades.append(
            Trade(
                direction=open_signal.direction,
                entry_time=open_time,
                exit_time=final.timestamp.isoformat(),
                entry_price=open_signal.entry_price,
                exit_price=final.close_mid,
                stop_price=open_signal.stop_price,
                target_price=_target_price(open_signal),
                exit_reason="END_OF_DATA",
                pnl_points=pnl_points,
                pnl_cash=pnl_points * size,
                bull_score=open_signal.bull_score,
                bear_score=open_signal.bear_score,
                bias=open_signal.bias,
            )
        )

    return _summarize(trades)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the KhanSaab sniper indicator rules on OHLC CSV data.")
    parser.add_argument("csv_path", help="CSV with timestamp/open/high/low/close columns and optional volume/spread.")
    parser.add_argument("--spread", type=float, default=0.0, help="Default spread if the CSV has no spread column.")
    parser.add_argument("--size", type=float, default=None, help="Cash value per point. Defaults to DEFAULT_SIZE.")
    parser.add_argument("--trades-out", default=None, help="Optional path to write the trade log CSV.")
    args = parser.parse_args()

    config = load_config()
    candles = load_candles_csv(args.csv_path, default_spread=args.spread)
    result = run_backtest(candles, SniperStrategy(config.strategy), args.size or config.strategy.default_size)
    print_summary(result)
    if args.trades_out:
        write_trades_csv(result.trades, args.trades_out)


def print_summary(result: BacktestResult) -> None:
    print(f"Trades: {len(result.trades)}")
    print(f"Net points: {result.net_points:.5f}")
    print(f"Net cash: {result.net_cash:.2f}")
    print(f"Win rate: {result.win_rate:.1f}%")
    print(f"Profit factor: {result.profit_factor:.2f}")
    print(f"Max drawdown cash: {result.max_drawdown_cash:.2f}")


def write_trades_csv(trades: list[Trade], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(Trade.__dataclass_fields__.keys()))
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.__dict__)


def _exit_for_candle(candle: Candle, signal: Signal) -> tuple[float | None, str]:
    target_price = _target_price(signal)
    if signal.direction == Direction.BUY:
        stop_hit = candle.low_mid <= signal.stop_price
        target_hit = candle.high_mid >= target_price
    else:
        stop_hit = candle.high_mid >= signal.stop_price
        target_hit = candle.low_mid <= target_price

    if stop_hit:
        return signal.stop_price, "SL"
    if target_hit:
        return target_price, "TP"
    return None, ""


def _target_price(signal: Signal) -> float:
    if signal.direction == Direction.BUY:
        return signal.entry_price + signal.limit_distance
    if signal.direction == Direction.SELL:
        return signal.entry_price - signal.limit_distance
    return signal.entry_price


def _pnl_points(direction: Direction, entry: float, exit_price: float) -> float:
    if direction == Direction.BUY:
        return exit_price - entry
    return entry - exit_price


def _summarize(trades: list[Trade]) -> BacktestResult:
    net_points = sum(trade.pnl_points for trade in trades)
    net_cash = sum(trade.pnl_cash for trade in trades)
    winners = [trade.pnl_cash for trade in trades if trade.pnl_cash > 0]
    losers = [trade.pnl_cash for trade in trades if trade.pnl_cash < 0]
    win_rate = (len(winners) / len(trades) * 100) if trades else 0.0
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    return BacktestResult(
        trades=trades,
        net_points=net_points,
        net_cash=net_cash,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_cash=_max_drawdown_cash(trades),
    )


def _max_drawdown_cash(trades: list[Trade]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_cash
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return abs(max_drawdown)


if __name__ == "__main__":
    main()
