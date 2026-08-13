---
name: stock-metrics
description: Compute basic stock metrics (return, mean price, volatility) from a series of daily closing prices using the bundled compute.py script. Use this skill whenever the user asks to calculate simple statistics or risk metrics for a list of prices.
---

# Stock Metrics

This skill computes basic statistics for a list of daily closing prices.

## When to use

- The user supplies (or the agent has gathered) a series of numbers representing
  daily closing prices and wants return / mean / volatility.

## How to execute the bundled script

The script `compute.py` lives in this skill directory. Run it with the
`execute` tool from the project root, passing the prices as space-separated args:

```bash
python skills/stock-metrics/compute.py 100 102 99 105 103
```

It prints JSON to stdout with: `total_return`, `mean_price`, `volatility`
(standard deviation of daily returns), and `num_prices`.

Read this SKILL.md first, then run `compute.py` via the `execute` tool and
report the parsed JSON back to the user.
