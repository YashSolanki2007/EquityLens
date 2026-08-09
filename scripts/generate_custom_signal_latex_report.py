#!/usr/bin/env python3
"""Generate the custom-signal research report with XeLaTeX."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from scripts.generate_custom_signal_pdf import save_figures


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "apps/web/data/custom-signal.json"
OUTPUT_DIR = ROOT / "output/pdf"
OUTPUT_PATH = OUTPUT_DIR / "custom-signal-method-and-results.pdf"
TEX_PATH = OUTPUT_DIR / "custom-signal-method-and-results.tex"
BUILD_DIR = ROOT / "tmp/pdfs/custom-signal-latex-build"


def pct(value: float | None, digits: int = 2) -> str:
    return "--" if value is None else f"{value * 100:.{digits}f}\\%"


def num(value: float | None, digits: int = 3) -> str:
    return "--" if value is None else f"{value:.{digits}f}"


def tex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def figure_path(path: Path) -> str:
    return rf"\detokenize{{{path.resolve()}}}"


def yearly_rows(report: dict) -> str:
    return "\n".join(
        f"{row['year']} & {pct(row['strategy'], 1)} & {pct(row['benchmark'], 1)} & "
        f"{pct(row['time_in_market'], 0)} & {row['switches']} \\\\"
        for row in report["yearly_returns"]
    )


def sensitivity_rows(report: dict) -> str:
    return "\n".join(
        f"{pct(row['threshold_quantile'], 0)} & {pct(row['threshold'])} & "
        f"{pct(row['cagr'])} & {num(row['sharpe_zero_cash'])} & "
        f"{num(row['sortino_zero_cash'])} & {pct(row['max_drawdown'])} & "
        f"{pct(row['time_in_market'])} \\\\"
        for row in report["sensitivity"]
    )


def asset_rows(report: dict) -> str:
    rows = [row for group in report["cross_market"]["groups"] for row in group["rows"]]
    return "\n".join(
        f"{tex_escape(row['name'])} & {pct(row['signal_threshold'])} & "
        f"{pct(row['cagr'])} & {pct(row['benchmark_cagr'])} & "
        f"{num(row['sharpe'])} & {num(row['benchmark_sharpe'])} & "
        f"{pct(row['max_drawdown'])} \\\\"
        for row in rows
    )


def build_tex(report: dict, figures: dict[str, Path]) -> str:
    assumptions = report["assumptions"]
    metrics = report["primary_metrics"]
    latest = report["latest_signal"]
    probability = report["probability_metrics"]
    sd = report["standard_deviation"]["summary"]
    index_group, stock_group = report["cross_market"]["groups"]

    replacements = {
        "<<START>>": tex_escape(report["evaluation_start"]),
        "<<END>>": tex_escape(report["evaluation_end"]),
        "<<START_YEAR>>": report["evaluation_start"][:4],
        "<<END_YEAR>>": report["evaluation_end"][:4],
        "<<LOOKBACK>>": str(assumptions["lookback_sessions"]),
        "<<CAGR>>": pct(metrics["cagr"]),
        "<<BENCH_CAGR>>": pct(metrics["benchmark_cagr"]),
        "<<SHARPE>>": num(metrics["sharpe_zero_cash"]),
        "<<BENCH_SHARPE>>": num(metrics["benchmark_sharpe_zero_cash"]),
        "<<SORTINO>>": num(metrics["sortino_zero_cash"]),
        "<<BENCH_SORTINO>>": num(metrics["benchmark_sortino_zero_cash"]),
        "<<MAX_DD>>": pct(metrics["max_drawdown"]),
        "<<BENCH_MAX_DD>>": pct(metrics["benchmark_max_drawdown"]),
        "<<TOTAL_RETURN>>": pct(metrics["total_return"]),
        "<<BENCH_TOTAL_RETURN>>": pct(metrics["benchmark_total_return"]),
        "<<INVESTED>>": pct(metrics["time_in_market"]),
        "<<ENTRIES>>": str(metrics["entries"]),
        "<<MARKET_BETA>>": num(metrics["market_beta"]),
        "<<THRESHOLD>>": pct(assumptions["signal_threshold"]),
        "<<CURRENT_SCORE>>": pct(latest["custom_score"]),
        "<<POSITION>>": tex_escape(latest["position"].upper()),
        "<<DAILY_BETA>>": pct(latest["daily_beta"], 3),
        "<<ANNUAL_BETA>>": pct(latest["annualized_beta"]),
        "<<RAW_Q>>": pct(latest["raw_probability"]),
        "<<ADJUSTED_Q>>": pct(latest["adjusted_probability"]),
        "<<CURRENT_SD>>": pct(sd["current_daily_sd"]),
        "<<MEDIAN_SD>>": pct(sd["median_daily_sd"]),
        "<<P90_SD>>": pct(sd["p90_daily_sd"]),
        "<<RAW_BRIER>>": num(probability["raw_brier"], 4),
        "<<ADJUSTED_BRIER>>": num(probability["adjusted_brier"], 4),
        "<<BASE_BRIER>>": num(probability["base_brier"], 4),
        "<<FORECAST_COUNT>>": f"{probability['forecast_count']:,}",
        "<<INDEX_SHARPE_WINS>>": f"{round(index_group['summary']['sharpe_win_rate'] * index_group['summary']['count'])}/{index_group['summary']['count']}",
        "<<INDEX_DD_WINS>>": f"{round(index_group['summary']['drawdown_win_rate'] * index_group['summary']['count'])}/{index_group['summary']['count']}",
        "<<STOCK_SHARPE_WINS>>": f"{round(stock_group['summary']['sharpe_win_rate'] * stock_group['summary']['count'])}/{stock_group['summary']['count']}",
        "<<STOCK_DD_WINS>>": f"{round(stock_group['summary']['drawdown_win_rate'] * stock_group['summary']['count'])}/{stock_group['summary']['count']}",
        "<<INDEX_MEDIAN_GAP>>": pct(index_group["summary"]["median_cagr_delta"]),
        "<<STOCK_MEDIAN_GAP>>": pct(stock_group["summary"]["median_cagr_delta"]),
        "<<YEARLY_ROWS>>": yearly_rows(report),
        "<<SENSITIVITY_ROWS>>": sensitivity_rows(report),
        "<<ASSET_ROWS>>": asset_rows(report),
        "<<EQUITY_FIGURE>>": figure_path(figures["equity"]),
        "<<SD_FIGURE>>": figure_path(figures["sd"]),
        "<<YEARLY_FIGURE>>": figure_path(figures["yearly"]),
        "<<CROSS_FIGURE>>": figure_path(figures["cross"]),
    }

    template = r"""
\documentclass[11pt,a4paper]{article}
\usepackage[a4paper,margin=19mm,headsep=8mm,footskip=12mm]{geometry}
\usepackage{fontspec}
\usepackage{unicode-math}
\setmainfont{Georgia}[
  BoldFont={Georgia Bold},
  ItalicFont={Georgia Italic},
  BoldItalicFont={Georgia Bold Italic}
]
\setsansfont{Arial}
\setmonofont{Menlo}
\setmathfont{STIX Two Math}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{longtable}
\usepackage{array}
\usepackage{amsmath}
\usepackage{hyperref}
\hypersetup{colorlinks=true,linkcolor=DeepBlue,urlcolor=SignalGreen,pdftitle={EquityLens Custom Momentum Probability Signal}}
\definecolor{Ink}{HTML}{132238}
\definecolor{Muted}{HTML}{59697D}
\definecolor{SignalGreen}{HTML}{0F8B6D}
\definecolor{DeepBlue}{HTML}{3267B2}
\definecolor{Soft}{HTML}{F1F6F8}
\definecolor{Rule}{HTML}{D7E1E7}
\color{Ink}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.55em}
\setlength{\emergencystretch}{2em}
\setlength{\tabcolsep}{4.5pt}
\renewcommand{\arraystretch}{1.18}
\newcolumntype{Y}{>{\raggedright\arraybackslash}X}
\newcommand{\sectionrule}{\vspace{-0.5em}\par\noindent\color{SignalGreen}\rule{\linewidth}{0.7pt}\color{Ink}\par\vspace{0.3em}}
\newcommand{\metricbox}[3]{\fcolorbox{Rule}{Soft}{\parbox[c][18mm][c]{0.27\textwidth}{\sffamily\scriptsize\color{Muted}#1\\[2pt]\normalfont\Large\color{Ink}#2\\[-1pt]\scriptsize\color{Muted}#3}}}
\newcommand{\note}[1]{\begin{center}\fcolorbox{SignalGreen}{Soft}{\parbox{0.91\linewidth}{#1}}\end{center}}
\newcommand{\code}[1]{\texttt{#1}}
\pagestyle{plain}
\begin{document}

\begin{titlepage}
\vspace*{18mm}
{\sffamily\small\color{SignalGreen}\bfseries EQUITYLENS RESEARCH NOTE}\par
\vspace{7mm}
{\sffamily\fontsize{30}{35}\selectfont\bfseries Custom Momentum\\Probability Signal}\par
\vspace{5mm}
{\Large A walk-forward annualized-beta and transformed-return model for India's stock market}\par
\vspace{10mm}
\sectionrule
\vspace{7mm}
\metricbox{TEST WINDOW}{<<START_YEAR>>--<<END_YEAR>>}{NIFTY 50 price index}\hfill
\metricbox{STRATEGY CAGR}{<<CAGR>>}{NIFTY 50: <<BENCH_CAGR>>}\hfill
\metricbox{CURRENT POSITION}{<<POSITION>>}{Score <<CURRENT_SCORE>>; cutoff <<THRESHOLD>>}
\par\vspace{10mm}
\begin{minipage}{0.92\linewidth}
\textbf{Research conclusion.} The restored 63-session specification compounds the daily log-price slope over 252 sessions, multiplies it by the locally adjusted tail probability, and compares that score with the expanding median daily EWMA volatility. It produces a <<CAGR>> CAGR, <<SHARPE>> Sharpe ratio, and <<MAX_DD>> maximum drawdown over the completed sample. The benchmark compounds faster at <<BENCH_CAGR>>, so the result is defensive rather than evidence of market-beating alpha.
\end{minipage}
\vfill
{\small Generated from the point-in-time EquityLens dataset through <<END>>. Research use only; not investment advice.}
\end{titlepage}

\tableofcontents
\clearpage

\section{Objective and complete signal definition}
\sectionrule
The model asks whether a recent log-price trend, combined with a continuous estimate of return plausibility, can support a daily long-or-cash decision. The estimation window is <<LOOKBACK>> sessions, while the forecast horizon remains one session.

For adjusted close $P_t$, define log price $y_i=\log P_i$ and time index $x_i=i$ over the latest $L=<<LOOKBACK>>$ observations. The ordinary least-squares slope is
\begin{equation}
\widehat{\beta}_{d,t}
=
\frac{\sum_{i=1}^{L}(x_i-\bar{x})(y_i-\bar{y})}
     {\sum_{i=1}^{L}(x_i-\bar{x})^2}.
\label{eq:daily-beta}
\end{equation}
This is a daily continuously compounded trend estimate. The one-session simple-return hurdle inserted into the probability distribution is
\begin{equation}
m_t=\exp\!\left(\widehat{\beta}_{d,t}\right)-1.
\label{eq:daily-forecast}
\end{equation}
The restored score uses the annualized slope
\begin{equation}
\widehat{\beta}_{a,t}
=\exp\!\left(252\widehat{\beta}_{d,t}\right)-1.
\label{eq:annual-beta}
\end{equation}

\note{The annualization in Equation~\ref{eq:annual-beta} changes the magnitude of the score; it does not change the one-day forecast horizon in Equation~\ref{eq:daily-forecast}.}

\section{Conditional return distribution}
\sectionrule
Let the one-day log return be $r_t=\log(P_t/P_{t-1})$. A 21-session exponentially weighted standard deviation estimates conditional daily volatility:
\begin{align}
\alpha &= \frac{2}{21+1},\\
\widehat{\sigma}^{2}_t
&=(1-\alpha)\widehat{\sigma}^{2}_{t-1}
  +\alpha\left(r_t-\widehat{\mu}_t\right)^2.
\end{align}
Each historical shock is standardized by the volatility forecast known before it occurred,
\begin{equation}
z_t=\frac{r_t}{\widehat{\sigma}_{t-1}}.
\end{equation}
Using at most 756 completed observations, the model applies the Yeo--Johnson transform
\begin{equation}
T_{\lambda}(z)=
\begin{cases}
\dfrac{(z+1)^{\lambda}-1}{\lambda}, & z\ge 0,\ \lambda\ne0,\\[6pt]
\log(z+1), & z\ge0,\ \lambda=0,\\[6pt]
-\dfrac{(1-z)^{2-\lambda}-1}{2-\lambda}, & z<0,\ \lambda\ne2,\\[6pt]
-\log(1-z), & z<0,\ \lambda=2.
\end{cases}
\label{eq:yeojohnson}
\end{equation}
The transformation parameter is refitted every 21 sessions. If $\mu_T$ and $s_T$ denote the transformed rolling mean and standard deviation, define
\begin{equation}
a_t=T_{\lambda}\!\left(\frac{m_t}{\widehat{\sigma}_t}\right),
\qquad
u_t=\frac{a_t-\mu_T}{s_T}.
\end{equation}
The signed-tail probability is
\begin{equation}
q^{\mathrm{raw}}_t=
\begin{cases}
1-\Phi(u_t), & m_t\ge0,\\
\Phi(u_t), & m_t<0,
\end{cases}
\label{eq:tail}
\end{equation}
where $\Phi$ is the standard normal cumulative distribution function.

\section{Non-IID adjustment and trading score}
\sectionrule
The raw probability defines an expected waiting window
\begin{equation}
N_t=\operatorname{clip}\!\left(\left\lceil\frac{1}{q^{\mathrm{raw}}_t}\right\rceil,2,63\right).
\end{equation}
Let $h_t$ be the number of completed forecast hits within that window and $n_t$ the number of completed observations. With prior strength $\kappa=20$,
\begin{equation}
q^{\mathrm{adj}}_t
=\frac{\kappa q^{\mathrm{raw}}_t+h_t}{\kappa+n_t}.
\label{eq:beta-binomial}
\end{equation}
The restored score is
\begin{equation}
S_t=\widehat{\beta}_{a,t}\,q^{\mathrm{adj}}_t.
\label{eq:score}
\end{equation}
For asset $j$, the point-in-time cutoff is the expanding median of completed daily volatility estimates:
\begin{equation}
\theta_{j,t}=\operatorname{median}\left\{\widehat{\sigma}_{j,s}:s<t\right\}.
\label{eq:threshold}
\end{equation}
After at least 126 completed volatility observations, the target exposure is
\begin{equation}
w_t^{\star}=\mathbf{1}\!\left\{S_t>\theta_{j,t}\right\}.
\end{equation}
The signal formed after close $t$ is acted on at close $t+1$; the first attributed return is from $t+1$ to $t+2$. A 10-basis-point one-way cost is charged whenever target exposure changes.

\note{Equations~\ref{eq:score} and~\ref{eq:threshold} compare an annualized-return score with a daily-volatility cutoff. This recreates the original profitable-looking specification exactly, but it is a dimensional inconsistency and must be treated as a research limitation rather than an economic identity.}

\section{Walk-forward evaluation protocol}
\sectionrule
At every date, the regression, volatility estimate, transformed PDF, beta-binomial hit history, and cutoff contain only information available at that close. The PDF requires 504 training rows and is refitted every 21 sessions. The primary benchmark is the NIFTY 50 price index, cash earns zero, and dividends are excluded.

\begin{table}[h]
\centering
\caption{Primary NIFTY 50 results, <<START>> to <<END>>.}
\begin{tabular}{lrr}
\toprule
Metric & Custom signal & NIFTY 50 \\
\midrule
CAGR & <<CAGR>> & <<BENCH_CAGR>> \\
Sharpe ratio, 0\% cash rate & <<SHARPE>> & <<BENCH_SHARPE>> \\
Sortino ratio, 0\% MAR & <<SORTINO>> & <<BENCH_SORTINO>> \\
Maximum drawdown & <<MAX_DD>> & <<BENCH_MAX_DD>> \\
Total return & <<TOTAL_RETURN>> & <<BENCH_TOTAL_RETURN>> \\
\bottomrule
\end{tabular}
\end{table}

The strategy is invested <<INVESTED>> of the time, makes <<ENTRIES>> entries, and has market beta <<MARKET_BETA>>. Its Sharpe ratio is close to but below the benchmark, its Sortino ratio is slightly higher, and its drawdown is materially smaller. Its CAGR remains below buy-and-hold because substantial positive market returns occur while the strategy is in cash.

\begin{figure}[p]
\centering
\includegraphics[width=\textwidth]{<<EQUITY_FIGURE>>}
\caption{Growth of one unit and drawdown for the restored annualized specification.}
\end{figure}

\clearpage
\section{Volatility, score, and current state}
\sectionrule
Current daily beta is <<DAILY_BETA>>, corresponding to an annualized beta of <<ANNUAL_BETA>>. The raw and adjusted probabilities are <<RAW_Q>> and <<ADJUSTED_Q>>, producing a score of <<CURRENT_SCORE>> against a cutoff of <<THRESHOLD>>. The resulting position is \textbf{<<POSITION>>}.

Current daily EWMA volatility is <<CURRENT_SD>>, the expanding-sample median is <<MEDIAN_SD>>, and the 90th percentile is <<P90_SD>>.

\begin{figure}[h]
\centering
\includegraphics[width=\textwidth]{<<SD_FIGURE>>}
\caption{Daily conditional volatility and the restored annualized-beta probability score. The dashed amber line is the expanding median daily-SD cutoff.}
\end{figure}

\begin{table}[h]
\centering
\caption{Sensitivity to the daily-volatility percentile used as the cutoff.}
\begin{tabular}{rrrrrrr}
\toprule
SD percentile & Cutoff & CAGR & Sharpe & Sortino & Max DD & Invested \\
\midrule
<<SENSITIVITY_ROWS>>
\bottomrule
\end{tabular}
\end{table}

The 50th percentile is the live rule. Nearby cutoffs produce similar outcomes, which is more reassuring than a single isolated optimum, but the comparison is still in-sample and does not constitute hyperparameter validation.

\clearpage
\section{Calendar-year behaviour}
\sectionrule
\begin{figure}[h]
\centering
\includegraphics[width=\textwidth]{<<YEARLY_FIGURE>>}
\caption{Calendar-year returns for the restored signal and NIFTY 50.}
\end{figure}

\begin{center}
\small
\begin{longtable}{rrrrr}
\toprule
Year & Signal & Index & Invested & Switches \\
\midrule
\endhead
<<YEARLY_ROWS>>
\bottomrule
\end{longtable}
\end{center}

The long-or-cash construction tends to reduce losses in persistent declines but can remain long during the first leg of a reversal and then miss the recovery after moving to cash. The result is path-dependent and particularly sensitive to abrupt trend changes.

\clearpage
\section{Probability diagnostics}
\sectionrule
The report evaluates <<FORECAST_COUNT>> completed one-day forecasts. Brier scores are <<RAW_BRIER>> for the transformed-PDF probability, <<ADJUSTED_BRIER>> after the beta-binomial update, and <<BASE_BRIER>> for the rolling base probability.

These diagnostics measure event calibration, not trading profitability. A probability model can be well calibrated while the event itself has little economic value, and multiplying a weak trend by a calibrated probability does not manufacture predictive alpha.

The event is defined relative to the signed contemporaneous forecast:
\begin{equation}
H_{t+1}=\begin{cases}
1, & R_{t+1}\ge m_t,\quad m_t\ge0,\\
1, & R_{t+1}\le m_t,\quad m_t<0,\\
0, & \text{otherwise.}
\end{cases}
\end{equation}
This is not a fixed $\pm1\%$ event. When $m_t$ lies near the centre of the fitted distribution, the raw tail probability can naturally remain close to one half.

\section{Cross-market evidence}
\sectionrule
The same architecture is applied without asset-specific performance tuning. Each instrument receives its own point-in-time median daily-SD cutoff.

\begin{table}[h]
\centering
\begin{tabularx}{\textwidth}{Yrrrr}
\toprule
Sample & Sharpe wins & Drawdown wins & Count & Median CAGR gap \\
\midrule
Indian indices & <<INDEX_SHARPE_WINS>> & <<INDEX_DD_WINS>> & 6 & <<INDEX_MEDIAN_GAP>> \\
Indian large caps & <<STOCK_SHARPE_WINS>> & <<STOCK_DD_WINS>> & 10 & <<STOCK_MEDIAN_GAP>> \\
\bottomrule
\end{tabularx}
\end{table}

\begin{figure}[h]
\centering
\includegraphics[width=\textwidth]{<<CROSS_FIGURE>>}
\caption{CAGR gap and maximum-drawdown improvement versus same-asset buy-and-hold.}
\end{figure}

The model wins on Sharpe in only <<INDEX_SHARPE_WINS>> indices and <<STOCK_SHARPE_WINS>> large-cap stocks, while drawdown improves in <<INDEX_DD_WINS>> and <<STOCK_DD_WINS>>, respectively. The cross-sectional evidence therefore supports a possible defensive overlay more than a general alpha claim.

\clearpage
\section{Asset-level scorecard}
\sectionrule
\scriptsize
\begin{longtable}{p{33mm}rrrrrr}
\toprule
Asset & Cutoff & CAGR & B\&H CAGR & Sharpe & B\&H Sharpe & Max DD \\
\midrule
\endhead
<<ASSET_ROWS>>
\bottomrule
\end{longtable}
\normalsize

The large-cap universe uses current constituents and therefore contains survivorship bias. Different histories also create different evaluation windows. The table should not be interpreted as a historical-constituent portfolio simulation.

\section{Limitations}
\sectionrule
\begin{enumerate}
\item \textbf{Dimensional mismatch.} The annualized score in Equation~\ref{eq:score} is compared with a daily-volatility cutoff in Equation~\ref{eq:threshold}. The restored rule is empirically defined rather than dimensionally derived.
\item \textbf{Annualization amplifies estimation error.} Small changes in $\widehat{\beta}_{d,t}$ are magnified by the nonlinear map
\[
g(\widehat{\beta}_{d,t})=\exp(252\widehat{\beta}_{d,t})-1.
\]
\item \textbf{Weak one-day predictability.} A fitted price trend is descriptive and is not automatically the conditional expectation of tomorrow's return.
\item \textbf{Distribution risk.} Yeo--Johnson can improve symmetry, but a transformed Gaussian can still understate tails, skew, volatility clustering, and regime changes.
\item \textbf{Partial non-IID treatment.} The beta-binomial window reacts to recent hit counts but does not model return autocorrelation, latent regimes, or tail dependence directly.
\item \textbf{Selection risk.} The lookback, refit cadence, prior strength, volatility cutoff, and trading cost were examined on the same broad historical record.
\item \textbf{Implementation omissions.} The primary series excludes dividends; cash earns zero; taxes, variable spreads, market impact, and capacity limits are absent.
\item \textbf{Binary exposure.} An all-or-nothing target discards information about signal strength and can create threshold whipsaw.
\end{enumerate}

\section{Recommended research programme}
\sectionrule
\begin{enumerate}
\item Select every parameter inside nested walk-forward training windows and score untouched forward periods.
\item Test entry and exit hysteresis jointly, rather than using the same threshold for both decisions.
\item Compare the annualized formulation with dimensionally consistent alternatives on exactly the same dates.
\item Calibrate probabilities out of sample with isotonic or logistic methods and retain the beta-binomial layer only if it improves proper scoring rules.
\item Compare skew-$t$, filtered historical simulation, GARCH-family volatility, and extreme-value tails.
\item Test continuous position sizing and portfolio-volatility targeting.
\item Use total-return indices or investable futures/ETF proxies, historical constituents, variable costs, and non-zero cash yield.
\item Add block-bootstrap confidence intervals, turnover-adjusted tests, deflated Sharpe, and probability-of-backtest-overfitting diagnostics.
\end{enumerate}

\section{Conclusion}
\sectionrule
The restored annualized specification reproduces the earlier result: <<CAGR>> CAGR, <<SHARPE>> Sharpe, <<SORTINO>> Sortino, and <<MAX_DD>> maximum drawdown. It substantially outperforms the later 15-session variants and reduces drawdown relative to buy-and-hold. It still trails the NIFTY 50 CAGR of <<BENCH_CAGR>> and does not generalize as an alpha model across the frozen Indian-market sample. Its strongest current interpretation is a defensive trend overlay whose annualization and threshold construction require stricter out-of-sample validation.

\begin{thebibliography}{9}
\bibitem{yeojohnson}
I. K. Yeo and R. A. Johnson, ``A New Family of Power Transformations to Improve Normality or Symmetry,'' \emph{Biometrika}, vol. 87, no. 4, 2000. \url{https://doi.org/10.1080/713665670}
\bibitem{data}
Yahoo Finance delayed and auto-adjusted histories as identified in the generated EquityLens dataset. Primary series: NIFTY 50 price index (\code{\^{}NSEI}).
\end{thebibliography}

\end{document}
"""
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    unresolved = [part for part in template.split() if part.startswith("<<")]
    if unresolved:
        raise RuntimeError(f"Unresolved LaTeX placeholders: {unresolved}")
    return template


def compile_report(tex: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    TEX_PATH.write_text(tex)
    command = [
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={BUILD_DIR}",
        str(TEX_PATH),
    ]
    for _ in range(2):
        subprocess.run(command, cwd=ROOT, check=True)
    built_pdf = BUILD_DIR / TEX_PATH.with_suffix(".pdf").name
    shutil.copy2(built_pdf, OUTPUT_PATH)


def main() -> None:
    report = json.loads(DATA_PATH.read_text())
    figures = save_figures(report)
    compile_report(build_tex(report, figures))
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)} with XeLaTeX")


if __name__ == "__main__":
    main()
