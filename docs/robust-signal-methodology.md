# Risk-budgeted trend signal

Status: **research only / paper-trade candidate**. The historical result is a
defensive exposure rule, not evidence of a reliable return forecast or guaranteed
drawdown limit.

## Decision rule

After each completed `W-FRI` trading week, calculate from NIFTY 50 adjusted price-index
closes:

\[
g_t = I\left(EMA_{15,t} > EMA_{45,t}\right)
\]

\[
\hat\sigma_t = \max\left(
\sqrt{252}\,EWMAStd_{21}(\Delta\log P_t),
\sqrt{252}\,RollingStd_{63}(\Delta\log P_t)
\right)
\]

\[
w_t^* = g_t \min\left(1, \frac{0.08}{\hat\sigma_t}\right)
\]

- If `EMA15 <= EMA45`, target cash.
- If `EMA15 > EMA45`, target a long position between 0% and 100% according to the
  8% annual volatility budget.
- A signal observed after close `t` trades at close `t+1`; the new position first earns
  the `t+1 -> t+2` return.
- Charge 10 bps times the absolute fractional position change. No leverage or shorts.
- A partial current week cannot create a new decision.

The maximum of short EWMA and medium rolling volatility is deliberately conservative:
position size cannot rise merely because one estimator forgets an older volatility
shock more quickly.

## Why this family

The repository's flexible predictors failed. The five-session ML ensemble has negative
out-of-sample R-squared and approximately chance direction accuracy, while the custom
probability model does not establish a transferable Sharpe edge. A low-parameter trend
regime plus causal risk scaling is easier to audit and is motivated by published work on
[time-series momentum](https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf)
and [volatility-managed portfolios](https://www.nber.org/papers/w22208). Important
counterevidence finds that volatility management does not systematically outperform in
real-time implementations; see
[Cederburg et al.](https://doi.org/10.1016/j.jfineco.2020.04.015).

## Frozen historical result

The primary window begins 1 January 2008 so it includes the global financial crisis and
does not inherit the more flattering April 2012 start used by the earlier report.

| Metric | Candidate | NIFTY buy-and-hold |
|---|---:|---:|
| CAGR | 3.93% | 7.74% |
| Annual volatility | 6.40% | 20.35% |
| Sharpe, zero cash | 0.651 | 0.478 |
| Sortino, zero cash | 0.946 | 0.679 |
| Maximum drawdown | -16.36% | -59.86% |
| Total return | 104.84% | 299.89% |

On the April 2012 comparison window, the candidate reports 5.52% CAGR, 0.871 Sharpe,
1.260 Sortino, and -12.47% maximum drawdown. That window is shown only for comparison;
it is not the primary evidence.

The trade-off is substantial: the rule achieved its lower drawdown with only 37.4%
average exposure and gave up roughly half the benchmark CAGR.

## Controls and uncertainty

The report includes:

- buy-and-hold;
- an ex-post constant exposure with the same realized volatility;
- volatility-only sizing with no trend gate;
- trend-only sizing with no risk budget;
- the existing 21/63 EMA rule on the same long window;
- 0/10/20/30 bps one-way cost stress;
- stationary-block-bootstrap intervals with paired sampling and expected block lengths
  of 10, 20, and 40 sessions;
- Newey-West/Bartlett HAC tests;
- a monthly Deflated Sharpe Ratio using a lower bound of 75 inspected trials;
- frozen transfer tests across six Indian indices.

The [stationary bootstrap](https://doi.org/10.1080/01621459.1994.10476870) preserves
short-range dependence better than IID resampling. The
[Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
penalizes selection and non-normality. HAC inference follows
[Newey and West](https://www.nber.org/papers/t0055).

The candidate does **not** pass promotion:

- Deflated-Sharpe probability is about 1.4%, versus a required 95%.
- The paired 95% bootstrap interval for its Sharpe difference versus the volatility-only
  control is approximately -0.236 to +0.336.
- It beats benchmark Sharpe in only two of six frozen Indian-index transfers, although
  it reduces historical drawdown in all six.
- There are zero genuinely unseen forward sessions.

## Current frozen state

Using completed daily bars through the 7 August 2026 close:

- regime: long;
- last completed decision: 7 August 2026;
- current exposure after the last completed close: 65.49%;
- pending resize target: 64.85% at the next available session close (earliest
  10 August 2026);
- next scheduled decision: 14 August 2026;
- decision-time risk forecast: 12.34% annualized.

The same-calendar-day Yahoo row is always excluded because it can be an incomplete,
still-revisable market-session bar.

The configuration hash in the generated report freezes the rule from 11 August 2026.
Changing any parameter restarts the prospective test.

## Data gate before a diversified version

A diversified equity/gold/bond version is statistically more plausible than forcing a
single-index signal, but it was rejected because the current free Yahoo histories are
not fit for performance claims:

- `NIFTYBEES.NS` contains phantom split-scale moves around December 2019;
- `GOLDBEES.NS` contains an even larger unrecorded denomination discontinuity;
- `LIQUIDBEES.NS` price history omits returns distributed through reinvested units;
- available bond ETF histories are too short.

Do not hand-delete these observations. A future diversified study needs immutable raw
downloads and corporate-action checks using official
[NIFTY total-return and fixed-income history](https://www.niftyindices.com/reports/historical-data),
the [NIFTY 5-year G-Sec TR index](https://www.niftyindices.com/indices/fixed-income/gsec-indices/nifty-5-yr-benchmark-gsec),
the [NIFTY 1D Rate](https://www.niftyindices.com/indices/fixed-income/money-market-indices/nifty-1d-rate),
and [AMFI NAV history](https://www.amfiindia.com/sif/latest-nav/nav-history).

## Reproduce

From the repository root:

```bash
services/api/.venv/bin/python -m scripts.generate_robust_signal --end 2026-08-10
services/api/.venv/bin/python -m unittest scripts.test_robust_signal
```

The generator emits `apps/web/data/robust-signal.json`. Yahoo data are delayed and may
be revised; the checked-in report is the frozen research snapshot.
