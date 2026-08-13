"""Compute basic stock metrics from a series of daily closing prices.

Usage:
    python compute.py 100 102 99 105 103

Prints a JSON object with total_return, mean_price, volatility and num_prices.
"""

import json
import math
import sys


def compute_metrics(prices: list[float]) -> dict:
    if not prices:
        raise ValueError("price list is empty")
    if len(prices) < 2:
        return {
            "total_return": 0.0,
            "mean_price": prices[0],
            "volatility": 0.0,
            "num_prices": len(prices),
        }

    total_return = (prices[-1] / prices[0]) - 1.0
    mean_price = sum(prices) / len(prices)

    daily_returns = [
        (prices[i] / prices[i - 1]) - 1.0 for i in range(1, len(prices))
    ]
    mean_ret = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
    volatility = math.sqrt(variance)

    return {
        "total_return": total_return,
        "mean_price": mean_price,
        "volatility": volatility,
        "num_prices": len(prices),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python compute.py PRICE [PRICE ...]", file=sys.stderr)
        sys.exit(2)
    prices = [float(p) for p in sys.argv[1:]]
    result = compute_metrics(prices)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
