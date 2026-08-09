#!/usr/bin/env python3
"""Build a polished method-and-results PDF from the custom-signal JSON report."""

from __future__ import annotations

import html
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "apps/web/data/custom-signal.json"
OUTPUT_PATH = ROOT / "output/pdf/custom-signal-method-and-results.pdf"
TMP_DIR = ROOT / "tmp/pdfs/custom-signal-report"

INK = colors.HexColor("#132238")
MUTED = colors.HexColor("#59697D")
GREEN = colors.HexColor("#0F8B6D")
BLUE = colors.HexColor("#3267B2")
PURPLE = colors.HexColor("#7655C5")
AMBER = colors.HexColor("#C07A16")
RED = colors.HexColor("#B54A55")
PALE = colors.HexColor("#F4F7FA")
LINE = colors.HexColor("#DCE3EA")


def pct(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value * 100:.{digits}f}%"


def num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 13 * mm, 192 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.5 * mm, "EquityLens Research - Custom Signal")
    canvas.drawRightString(192 * mm, 8.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=27,
            leading=31,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=18,
            textColor=MUTED,
            spaceAfter=12,
        ),
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=GREEN,
            spaceAfter=5,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=INK,
            spaceBefore=2,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=INK,
            spaceBefore=9,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=13.5,
            textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.6,
            leading=10.5,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "formula": ParagraphStyle(
            "Formula",
            parent=base["BodyText"],
            fontName="Courier",
            fontSize=8.1,
            leading=12.5,
            leftIndent=8,
            rightIndent=8,
            borderColor=LINE,
            borderWidth=0.6,
            borderPadding=7,
            backColor=PALE,
            textColor=INK,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13.5,
            leftIndent=8,
            rightIndent=8,
            borderColor=colors.HexColor("#B9DCCE"),
            borderWidth=0.8,
            borderPadding=8,
            backColor=colors.HexColor("#EDF8F4"),
            textColor=INK,
            spaceBefore=6,
            spaceAfter=8,
        ),
        "table_head": ParagraphStyle(
            "TableHead",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.1,
            leading=8.6,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table": ParagraphStyle(
            "Table",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=8.8,
            textColor=INK,
        ),
    }


def table(data, widths, header=True, alignments=None) -> Table:
    alignment_map = {"LEFT": TA_LEFT, "CENTER": TA_CENTER, "RIGHT": TA_RIGHT}
    wrapped = []
    for row_index, row in enumerate(data):
        wrapped_row = []
        for column_index, cell in enumerate(row):
            if hasattr(cell, "wrap"):
                wrapped_row.append(cell)
                continue
            alignment = (
                alignment_map.get(alignments[column_index], TA_LEFT)
                if alignments and row_index > 0
                else TA_LEFT
            )
            wrapped_row.append(
                Paragraph(
                    html.escape(str(cell)),
                    ParagraphStyle(
                        f"Cell-{row_index}-{column_index}",
                        fontName="Helvetica",
                        fontSize=7.2,
                        leading=8.8,
                        textColor=INK,
                        alignment=alignment,
                    ),
                )
            )
        wrapped.append(wrapped_row)
    item = Table(wrapped, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, PALE]),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ]
        )
    if alignments:
        for column, alignment in enumerate(alignments):
            commands.append(("ALIGN", (column, 1 if header else 0), (column, -1), alignment))
    item.setStyle(TableStyle(commands))
    return item


def metric_grid(metrics: list[tuple[str, str, str]], styles) -> Table:
    row = []
    for label, value, note in metrics:
        row.append(
            [
                Paragraph(label.upper(), styles["small"]),
                Paragraph(f"<b>{value}</b>", styles["h2"]),
                Paragraph(note, styles["small"]),
            ]
        )
    grid = Table([row], colWidths=[174 * mm / len(row)] * len(row))
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return grid


def save_figures(report: dict) -> dict[str, Path]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.edgecolor": "#DCE3EA",
            "axes.labelcolor": "#59697D",
            "xtick.color": "#59697D",
            "ytick.color": "#59697D",
            "grid.color": "#E7ECF1",
        }
    )
    paths = {}

    chart = pd.DataFrame(report["chart"])
    chart["date"] = pd.to_datetime(chart["date"])
    figure, axes = plt.subplots(2, 1, figsize=(9.2, 5.2), sharex=True, gridspec_kw={"height_ratios": [1.6, 1]})
    axes[0].plot(chart["date"], chart["strategy_equity"], color="#0F8B6D", lw=2, label="Custom signal")
    axes[0].plot(chart["date"], chart["benchmark_equity"], color="#3267B2", lw=1.5, label="NIFTY 50")
    axes[0].set_ylabel("Growth of 1 unit")
    axes[0].legend(frameon=False, ncol=2, loc="upper left")
    axes[1].fill_between(chart["date"], chart["benchmark_drawdown"] * 100, 0, color="#3267B2", alpha=0.12, label="NIFTY 50")
    axes[1].plot(chart["date"], chart["strategy_drawdown"] * 100, color="#0F8B6D", lw=1.4, label="Custom signal")
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    for axis in axes:
        axis.grid(axis="y", lw=0.6)
        axis.spines[["top", "right"]].set_visible(False)
    figure.tight_layout()
    paths["equity"] = TMP_DIR / "equity-drawdown.png"
    figure.savefig(paths["equity"], dpi=190, bbox_inches="tight")
    plt.close(figure)

    sd = pd.DataFrame(report["standard_deviation"]["history"])
    sd["date"] = pd.to_datetime(sd["date"])
    threshold = chart[["date", "signal_threshold"]].dropna()
    figure, axes = plt.subplots(2, 1, figsize=(9.2, 5.1), sharex=True)
    axes[0].plot(sd["date"], sd["daily_sd"] * 100, color="#7655C5", lw=1.5)
    axes[0].axhline(1.0, color="#B54A55", lw=1, ls="--", label="1.00% reference")
    axes[0].set_ylabel("Daily SD (%)")
    axes[0].legend(frameon=False, loc="upper left")
    axes[1].plot(chart["date"], chart["custom_score"] * 100, color="#0F8B6D", lw=1.2, label="Custom score")
    axes[1].plot(threshold["date"], threshold["signal_threshold"] * 100, color="#C07A16", lw=1.4, ls="--", label="Expanding median daily-SD cutoff")
    axes[1].set_ylabel("Score / threshold (%)")
    axes[1].legend(frameon=False, ncol=2, loc="upper left")
    axes[1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    for axis in axes:
        axis.grid(axis="y", lw=0.6)
        axis.spines[["top", "right"]].set_visible(False)
    figure.tight_layout()
    paths["sd"] = TMP_DIR / "sd-threshold.png"
    figure.savefig(paths["sd"], dpi=190, bbox_inches="tight")
    plt.close(figure)

    years = pd.DataFrame(report["yearly_returns"])
    figure, axis = plt.subplots(figsize=(9.2, 3.6))
    positions = range(len(years))
    axis.bar([p - 0.2 for p in positions], years["strategy"] * 100, width=0.4, color="#0F8B6D", label="Custom signal")
    axis.bar([p + 0.2 for p in positions], years["benchmark"] * 100, width=0.4, color="#3267B2", label="NIFTY 50")
    axis.axhline(0, color="#59697D", lw=0.7)
    axis.set_xticks(list(positions), years["year"].astype(str), rotation=45)
    axis.set_ylabel("Calendar return (%)")
    axis.legend(frameon=False, ncol=2, loc="upper left")
    axis.grid(axis="y", lw=0.6)
    axis.spines[["top", "right"]].set_visible(False)
    figure.tight_layout()
    paths["yearly"] = TMP_DIR / "yearly-returns.png"
    figure.savefig(paths["yearly"], dpi=190, bbox_inches="tight")
    plt.close(figure)

    rows = [row for group in report["cross_market"]["groups"] for row in group["rows"]]
    rows = sorted(rows, key=lambda row: row["cagr_delta"])
    figure, axes = plt.subplots(1, 2, figsize=(9.2, 5.4), gridspec_kw={"width_ratios": [1.1, 1]})
    labels = [row["name"] for row in rows]
    gaps = [row["cagr_delta"] * 100 for row in rows]
    colors_gap = ["#0F8B6D" if value > 0 else "#B54A55" for value in gaps]
    axes[0].barh(labels, gaps, color=colors_gap, alpha=0.85)
    axes[0].axvline(0, color="#59697D", lw=0.7)
    axes[0].set_xlabel("CAGR gap vs buy-and-hold (pp)")
    drawdown = [row["drawdown_improvement"] * 100 for row in rows]
    colors_dd = ["#0F8B6D" if value > 0 else "#B54A55" for value in drawdown]
    axes[1].barh(labels, drawdown, color=colors_dd, alpha=0.85)
    axes[1].axvline(0, color="#59697D", lw=0.7)
    axes[1].set_xlabel("Drawdown improvement (pp)")
    axes[1].set_yticks([])
    for axis in axes:
        axis.grid(axis="x", lw=0.6)
        axis.spines[["top", "right", "left"]].set_visible(False)
    figure.tight_layout()
    paths["cross"] = TMP_DIR / "cross-market.png"
    figure.savefig(paths["cross"], dpi=190, bbox_inches="tight")
    plt.close(figure)

    return paths


def build_pdf(report: dict, figures: dict[str, Path]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title="EquityLens Custom Signal: Method, Results and Research Roadmap",
        author="EquityLens Research",
        subject="Walk-forward momentum probability signal for Indian equities",
    )
    story = []
    assumptions = report["assumptions"]
    primary = report["primary_metrics"]
    active_lookback = assumptions["lookback_sessions"]
    probability = report["probability_metrics"]
    latest = report["latest_signal"]
    sd_summary = report["standard_deviation"]["summary"]

    story.extend(
        [
            Spacer(1, 18 * mm),
            Paragraph("EQUITYLENS RESEARCH NOTE", styles["eyebrow"]),
            Paragraph("Custom Momentum Probability Signal", styles["title"]),
            Paragraph(
                "Method, point-in-time asset-adaptive thresholds, current Indian-market results, limitations and a practical research roadmap.",
                styles["subtitle"],
            ),
            HRFlowable(width="100%", thickness=1.2, color=GREEN, spaceBefore=5, spaceAfter=14),
            metric_grid(
                [
                    ("Test window", f"{report['evaluation_start'][:4]}-{report['evaluation_end'][:4]}", "NIFTY 50 price index"),
                    ("Current score cutoff", pct(assumptions["signal_threshold"]), "Expanding 70th percentile"),
                    ("Current position", latest["position"].upper(), f"Score {pct(latest['custom_score'])}"),
                ],
                styles,
            ),
            Spacer(1, 10 * mm),
            Paragraph("Executive conclusion", styles["h1"]),
            Paragraph(
                f"The active signal uses a {active_lookback}-session log-price regression to estimate a smoother daily trend while still forecasting only the next session. The longer estimation window reduces slope instability; the holding decision remains daily and can change after every close.",
                styles["body"],
            ),
            Paragraph(
                f"NIFTY 50: CAGR {pct(primary['cagr'])} versus {pct(primary['benchmark_cagr'])}; Sharpe {num(primary['sharpe_zero_cash'])} versus {num(primary['benchmark_sharpe_zero_cash'])}; Sortino {num(primary['sortino_zero_cash'])} versus {num(primary['benchmark_sortino_zero_cash'])}; maximum drawdown {pct(primary['max_drawdown'])} versus {pct(primary['benchmark_max_drawdown'])}.",
                styles["callout"],
            ),
            Spacer(1, 32 * mm),
            Paragraph(
                f"Generated from the EquityLens walk-forward dataset through {report['evaluation_end']}. Research use only; not investment advice.",
                styles["small"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART I - METHOD", styles["eyebrow"]),
            Paragraph("1. Research objective and model pipeline", styles["h1"]),
            Paragraph(
                "The objective is to combine trend strength with an estimate of how plausible the forecasted next-day move is under the asset's recent return distribution. The score is then converted into a long-or-cash exposure rule. Every forecast and threshold is constructed with information available at the close of date t.",
                styles["body"],
            ),
            table(
                [
                    [Paragraph("Stage", styles["table_head"]), Paragraph("Operation", styles["table_head"]), Paragraph("Purpose", styles["table_head"])],
                    ["1. Trend", f"{assumptions['lookback_sessions']}-session OLS on log prices", "Estimate direction and magnitude"],
                    ["2. Forecast", "Convert daily slope into simple return", "Define tomorrow's return hurdle"],
                    ["3. Volatility", "21-session EWMA daily SD", "Standardize unequal volatility regimes"],
                    ["4. Distribution", "756-session Yeo-Johnson transformed PDF", "Estimate a continuous signed-tail probability"],
                    ["5. Calibration", "Expected-window beta-binomial update", "Use recent completed hit behavior"],
                    ["6. Score", "Daily forecast / daily SD times adjusted probability", "Combine trend, scale and plausibility"],
                    ["7. Threshold", "Asset's expanding 70th score percentile", "Adapt the cutoff without future data"],
                    ["8. Execution", "Long or cash with delayed execution", "Avoid same-close look-ahead"],
                ],
                [24 * mm, 68 * mm, 82 * mm],
            ),
            Paragraph("Key design change", styles["h2"]),
            Paragraph(
                f"The score no longer annualizes beta. It divides the predicted next-day return by the current daily EWMA SD and then applies the adjusted probability. For every asset and date, the entry cutoff is the expanding 70th percentile of completed historical scores. The first cutoff requires {assumptions['signal_threshold_minimum_rows']} prior scores.",
                styles["callout"],
            ),
            Paragraph("Information timing", styles["h2"]),
            Paragraph(
                "A signal formed after close t is acted on at close t+1. The first return attributed to the position is the close-to-close return from t+1 to t+2. A 10 basis-point one-way cost is charged whenever the target position changes. Cash earns zero and the primary benchmark is a price index, so dividends and cash yield are excluded.",
                styles["body"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART I - METHOD", styles["eyebrow"]),
            Paragraph("2. Trend estimate and return forecast", styles["h1"]),
            Paragraph(f"For lookback L = {assumptions['lookback_sessions']}, define y_i = log(P_i) and x_i = 0, 1, ..., L-1. The ordinary least-squares daily slope is:", styles["body"]),
            Paragraph("beta_d,t = Sum[(x_i - x_bar)(y_i - y_bar)] / Sum[(x_i - x_bar)^2]", styles["formula"]),
            Paragraph("The one-day simple-return forecast is:", styles["body"]),
            Paragraph("m_t = exp(beta_d,t) - 1", styles["formula"]),
            Paragraph(
                "The regression slope is descriptive, not a guaranteed conditional expectation. It extrapolates the recent log-price trend by one day. R-squared and annualized beta are retained for diagnosis only; neither enters the active score.",
                styles["body"],
            ),
            Paragraph("3. Conditional volatility and standardized shocks", styles["h1"]),
            Paragraph(
                "Let r_t = log(P_t / P_{t-1}). A 21-session exponentially weighted standard deviation produces sigma_t. Operationally, the newest squared deviations receive weight alpha = 2/(21+1), with older observations decaying geometrically. Historical shocks are standardized by the volatility forecast known before the return occurred:",
                styles["body"],
            ),
            Paragraph("z_t = r_t / sigma_(t-1)", styles["formula"]),
            Paragraph(
                "This lag is important. Dividing a return by a same-day volatility estimate would let an extreme observation widen its own denominator and contaminate calibration. Today's sigma_t is used as the volatility estimate for tomorrow's forecast hurdle.",
                styles["body"],
            ),
            Paragraph("4. Yeo-Johnson transformation", styles["h1"]),
            Paragraph(
                "A 756-session rolling sample of standardized shocks is transformed to improve symmetry and Gaussian fit while allowing zero and negative values. The transformation parameter lambda is refitted every 21 sessions using only the available rolling window.",
                styles["body"],
            ),
            Paragraph(
                "T_lambda(z) = ((z+1)^lambda - 1)/lambda, z >= 0 and lambda != 0<br/>"
                "T_lambda(z) = log(z+1), z >= 0 and lambda = 0<br/>"
                "T_lambda(z) = -((1-z)^(2-lambda) - 1)/(2-lambda), z < 0 and lambda != 2<br/>"
                "T_lambda(z) = -log(1-z), z < 0 and lambda = 2",
                styles["formula"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART I - METHOD", styles["eyebrow"]),
            Paragraph("5. Signed-tail probability", styles["h1"]),
            Paragraph(
                "Let a_t = T_lambda(m_t / sigma_t), and let mu_T and s_T be the fitted transformed mean and SD. With Phi denoting the standard normal CDF, the raw probability is the probability that tomorrow's return meets the signed forecast:",
                styles["body"],
            ),
            Paragraph(
                "q_raw,t = 1 - Phi((a_t - mu_T)/s_T), if m_t >= 0<br/>q_raw,t = Phi((a_t - mu_T)/s_T), if m_t < 0",
                styles["formula"],
            ),
            Paragraph(
                "The event is not a fixed plus-or-minus 1% move. For a positive trend, a hit means R_(t+1) >= m_t. For a negative trend, a hit means R_(t+1) <= m_t. This probability can remain near one-half when the predicted move is near the center of the fitted distribution.",
                styles["body"],
            ),
            Paragraph("6. Expected-window beta-binomial adjustment", styles["h1"]),
            Paragraph(
                "The raw probability implies an expected waiting window. The implementation caps it between 2 and 63 sessions, then counts completed forecast hits inside that window:",
                styles["body"],
            ),
            Paragraph(
                "N_t = clip(ceil(1/q_raw,t), 2, 63)<br/>q_adj,t = (kappa * q_raw,t + H_t) / (kappa + n_t), where kappa = 20",
                styles["formula"],
            ),
            Paragraph(
                "H_t is the number of hits and n_t the number of completed observations in the expected window. This provides local shrinkage toward the PDF probability. It acknowledges clustering in a limited way, but it is not a complete time-series model of dependence.",
                styles["body"],
            ),
            Paragraph("7. Daily standardized score and adaptive threshold", styles["h1"]),
            Paragraph(
                "The final score and asset-specific entry cutoff are:",
                styles["body"],
            ),
            Paragraph(
                "u_t = m_t / sigma_t<br/>S_t = u_t * q_adj,t<br/>theta_t(asset) = 70th percentile{S_s(asset): s < t}<br/>target_t = 1 if S_t > theta_t(asset), otherwise 0",
                styles["formula"],
            ),
            Paragraph(
                "The score is now horizon-consistent: both m_t and sigma_t are daily quantities, and no annualization enters S_t. The threshold is drawn from the score's own historical distribution. The 70th percentile is still a research choice rather than an economically derived optimum, so it must be validated out of sample.",
                styles["callout"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART I - METHOD", styles["eyebrow"]),
            Paragraph("8. Walk-forward protocol and evaluation metrics", styles["h1"]),
            Paragraph(
                f"The backtest is strictly chronological. The PDF fit, volatility estimate, beta-binomial hit history, expanding threshold and position decision at date t contain no returns after t. The score cutoff uses at least {assumptions['signal_threshold_minimum_rows']} completed historical scores. The Yeo-Johnson PDF uses at most 756 standardized observations and is refitted every 21 sessions.",
                styles["body"],
            ),
            table(
                [
                    [Paragraph("Metric", styles["table_head"]), Paragraph("Definition used", styles["table_head"]), Paragraph("Interpretation", styles["table_head"])],
                    ["CAGR", "Geometric annualized growth", "Long-run capital growth"],
                    ["Sharpe", "Annualized mean / annualized SD; 0% cash rate", "Reward per unit of total volatility"],
                    ["Sortino", "Annualized mean / downside deviation; 0% MAR", "Reward per unit of downside volatility"],
                    ["Maximum drawdown", "Largest peak-to-trough equity loss", "Worst historical capital decline"],
                    ["Market beta", "Cov(strategy, market) / Var(market)", "Residual exposure to market moves"],
                    ["Time invested", "Mean active long position", "Fraction of days exposed"],
                ],
                [31 * mm, 72 * mm, 71 * mm],
            ),
            Paragraph("What the backtest does not include", styles["h2"]),
            Paragraph(
                "The primary series is the NIFTY 50 price index, not a directly tradable total-return instrument. Dividends, taxes, financing, bid-ask variation and market-impact scaling are excluded. A constant 10 basis-point one-way cost is included. The current large-cap sample uses present-day constituents and therefore carries survivorship bias.",
                styles["body"],
            ),
            Paragraph("Probability diagnostics", styles["h2"]),
            Paragraph(
                f"The report evaluates raw and adjusted probabilities with Brier score and log loss over {probability['forecast_count']:,} completed forecasts. Current adjusted Brier is {num(probability['adjusted_brier'], 4)} versus {num(probability['raw_brier'], 4)} raw and {num(probability['base_brier'], 4)} for the rolling base rate. These tests assess event calibration, not trading profitability.",
                styles["body"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART II - CURRENT RESULTS", styles["eyebrow"]),
            Paragraph("9. NIFTY 50 performance", styles["h1"]),
            metric_grid(
                [
                    ("Strategy CAGR", pct(primary["cagr"]), f"Index {pct(primary['benchmark_cagr'])}"),
                    ("Sharpe", num(primary["sharpe_zero_cash"]), f"Index {num(primary['benchmark_sharpe_zero_cash'])}"),
                    ("Sortino", num(primary["sortino_zero_cash"]), f"Index {num(primary['benchmark_sortino_zero_cash'])}"),
                    ("Max drawdown", pct(primary["max_drawdown"]), f"Index {pct(primary['benchmark_max_drawdown'])}"),
                ],
                styles,
            ),
            Spacer(1, 4 * mm),
            Image(str(figures["equity"]), width=174 * mm, height=98 * mm),
            Paragraph(
                f"The strategy compounded one unit to {1 + primary['total_return']:.2f}, versus {1 + primary['benchmark_total_return']:.2f} for the index. It was invested {pct(primary['time_in_market'])} of the time with market beta {num(primary['market_beta'])}. The adaptive cutoff materially reduced drawdown but did not preserve enough upside to match buy-and-hold CAGR.",
                styles["body"],
            ),
            Paragraph(
                f"Result: the {active_lookback}-session NIFTY 50 signal has Sharpe {num(primary['sharpe_zero_cash'])} versus {num(primary['benchmark_sharpe_zero_cash'])} for buy-and-hold, and Sortino {num(primary['sortino_zero_cash'])} versus {num(primary['benchmark_sortino_zero_cash'])}. Its lower volatility is overwhelmed by lost return and switching costs.",
                styles["callout"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART II - CURRENT RESULTS", styles["eyebrow"]),
            Paragraph("10. Volatility normalization and score cutoff", styles["h1"]),
            Paragraph(
                f"The current NIFTY 50 score cutoff is {pct(assumptions['signal_threshold'])}. Current conditional daily SD is {pct(sd_summary['current_daily_sd'])}; it is used in the denominator of the score, not as the entry threshold. The cutoff is the 70th percentile of completed historical standardized scores.",
                styles["body"],
            ),
            Image(str(figures["sd"]), width=174 * mm, height=96 * mm),
            Paragraph(
                "The lower panel compares the dimensionless daily score with its own point-in-time percentile cutoff. For a new asset, the rule waits for the same minimum score history instead of borrowing NIFTY's numerical threshold.",
                styles["body"],
            ),
            metric_grid(
                [
                    ("Mean daily SD", pct(sd_summary["mean_daily_sd"]), "Forecast sample"),
                    ("Median daily SD", pct(sd_summary["median_daily_sd"]), "Forecast sample"),
                    ("90th percentile", pct(sd_summary["p90_daily_sd"]), "High-volatility regime"),
                ],
                styles,
            ),
            PageBreak(),
        ]
    )

    story.extend(
        [
            Paragraph("PART II - CURRENT RESULTS", styles["eyebrow"]),
            Paragraph("11. Calendar-year behavior", styles["h1"]),
            Image(str(figures["yearly"]), width=174 * mm, height=68 * mm),
            Paragraph(
                "A long-or-cash momentum overlay tends to lag in rapid reversals. It may remain exposed during the first leg of a sell-off, then move to cash after the trend breaks and miss part of the rebound. The result is path-dependent: reducing average exposure is valuable in persistent declines, but costly during fast recoveries and sustained bull markets.",
                styles["body"],
            ),
            table(
                [[Paragraph("Year", styles["table_head"]), Paragraph("Signal", styles["table_head"]), Paragraph("Index", styles["table_head"]), Paragraph("Invested", styles["table_head"]), Paragraph("Switches", styles["table_head"])]]
                + [
                    [str(row["year"]), pct(row["strategy"], 1), pct(row["benchmark"], 1), pct(row["time_in_market"], 0), str(row["switches"])]
                    for row in report["yearly_returns"]
                ],
                [28 * mm, 36 * mm, 36 * mm, 38 * mm, 36 * mm],
                alignments=["CENTER"] * 5,
            ),
            PageBreak(),
        ]
    )

    groups = report["cross_market"]["groups"]
    index_group, stock_group = groups
    story.extend(
        [
            Paragraph("PART II - CURRENT RESULTS", styles["eyebrow"]),
            Paragraph("12. Cross-market generalization", styles["h1"]),
            Paragraph(
                "All instruments use the same model architecture and costs, but each has its own point-in-time expanding 70th score percentile. Therefore, this is a rule-level generalization test rather than a shared numerical-cutoff test.",
                styles["body"],
            ),
            metric_grid(
                [
                    ("Index Sharpe wins", f"{round(index_group['summary']['sharpe_win_rate'] * index_group['summary']['count'])}/{index_group['summary']['count']}", "Versus same-asset buy-and-hold"),
                    ("Index DD wins", f"{round(index_group['summary']['drawdown_win_rate'] * index_group['summary']['count'])}/{index_group['summary']['count']}", "Smaller maximum drawdown"),
                    ("Stock Sharpe wins", f"{round(stock_group['summary']['sharpe_win_rate'] * stock_group['summary']['count'])}/{stock_group['summary']['count']}", "Current large-cap sample"),
                    ("Stock DD wins", f"{round(stock_group['summary']['drawdown_win_rate'] * stock_group['summary']['count'])}/{stock_group['summary']['count']}", "Smaller maximum drawdown"),
                ],
                styles,
            ),
            Spacer(1, 4 * mm),
            Image(str(figures["cross"]), width=174 * mm, height=102 * mm),
            Paragraph(
                f"Median CAGR gap is {pct(index_group['summary']['median_cagr_delta'])} for the six additional indices and {pct(stock_group['summary']['median_cagr_delta'])} for the ten large caps. Drawdown improves in {round(index_group['summary']['drawdown_win_rate'] * index_group['summary']['count'])}/{index_group['summary']['count']} indices and {round(stock_group['summary']['drawdown_win_rate'] * stock_group['summary']['count'])}/{stock_group['summary']['count']} stocks. The live model does not generalize as an alpha model, and its defensive benefit is inconsistent among individual stocks.",
                styles["callout"],
            ),
            PageBreak(),
        ]
    )

    all_rows = [row for group in groups for row in group["rows"]]
    table_rows = [
        [
            Paragraph("Asset", styles["table_head"]),
            Paragraph("Threshold", styles["table_head"]),
            Paragraph("CAGR", styles["table_head"]),
            Paragraph("Benchmark CAGR", styles["table_head"]),
            Paragraph("Sharpe", styles["table_head"]),
            Paragraph("Benchmark Sharpe", styles["table_head"]),
            Paragraph("Max DD", styles["table_head"]),
            Paragraph("Benchmark DD", styles["table_head"]),
        ]
    ]
    for row in all_rows:
        table_rows.append(
            [
                Paragraph(row["name"].replace("&", "&amp;"), styles["table"]),
                pct(row["signal_threshold"]),
                pct(row["cagr"]),
                pct(row["benchmark_cagr"]),
                num(row["sharpe"]),
                num(row["benchmark_sharpe"]),
                pct(row["max_drawdown"]),
                pct(row["benchmark_max_drawdown"]),
            ]
        )
    story.extend(
        [
            Paragraph("PART II - CURRENT RESULTS", styles["eyebrow"]),
            Paragraph("13. Asset-level scorecard", styles["h1"]),
            table(
                table_rows,
                [39 * mm, 18 * mm, 20 * mm, 20 * mm, 18 * mm, 18 * mm, 20 * mm, 20 * mm],
                alignments=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"],
            ),
            Spacer(1, 4 * mm),
            Paragraph(
                "Cutoffs are the latest expanding 70th percentile of completed standardized daily scores for each instrument. They are not selected to maximize that instrument's backtest. Different starting histories mean each row's evaluation window can differ.",
                styles["small"],
            ),
            PageBreak(),
        ]
    )

    limitations = [
        ("Percentile selection", "The daily score is now horizon-consistent, but the 70th percentile is a research choice. Its apparent performance may not survive other periods or instruments."),
        ("Weak one-day predictability", f"A {assumptions['lookback_sessions']}-day price trend contains little information relative to next-day return noise. Probability rescaling cannot manufacture signal absent in beta."),
        ("Distribution risk", "Yeo-Johnson can improve symmetry, but a transformed Gaussian can still misstate heavy tails, skew, volatility clustering and abrupt regime shifts."),
        ("Partial non-IID treatment", "The beta-binomial window reacts to local hit counts but does not model autocorrelation, latent regimes or conditional tail dependence directly."),
        ("Selection and overfitting", "Lookbacks, refit cadence, prior strength, costs and the threshold rule were examined on the same broad historical record. Multiple testing can inflate apparent performance."),
        ("Benchmark and implementation", "The NIFTY price index excludes dividends; cash earns zero; taxes, variable spreads and capacity are absent. Close-based execution may be difficult at the assumed price."),
        ("Cross-sectional bias", "The large-cap screen uses current constituents, creating survivorship bias. It is not a historical-constituent portfolio simulation."),
        ("Binary exposure", "All-or-nothing positioning discards information about signal strength and can create whipsaw around the threshold."),
    ]
    limitation_h2 = ParagraphStyle(
        "LimitationH2",
        parent=styles["h2"],
        spaceBefore=6,
        spaceAfter=3,
    )
    limitation_body = ParagraphStyle(
        "LimitationBody",
        parent=styles["body"],
        fontSize=8.8,
        leading=12,
        spaceAfter=4,
    )
    story.extend(
        [
            Paragraph("PART III - LIMITATIONS AND ROADMAP", styles["eyebrow"]),
            Paragraph("14. Limitations", styles["h1"]),
        ]
    )
    for title, detail in limitations:
        story.extend(
            [Paragraph(title, limitation_h2), Paragraph(detail, limitation_body)]
        )
    story.append(PageBreak())

    improvements = [
        ("Nested walk-forward validation", "Choose every hyperparameter and threshold rule only inside past training windows, then score untouched forward periods. Report confidence intervals and stability by regime."),
        ("Test cutoff and hysteresis jointly", "Select entry and exit percentiles only inside past training windows. Separate bands may retain genuine short-term momentum while reducing threshold whipsaw."),
        ("Direct probability calibration", "Use walk-forward isotonic or logistic calibration and compare Brier/log-loss improvement out of sample. Retain the beta-binomial layer only if it adds incremental value."),
        ("Richer conditional distributions", "Compare skew-t, filtered historical simulation, GARCH-family volatility and extreme-value tails. Score them with proper probability metrics, not only trading returns."),
        ("Explicit regime models", "Allow parameters or exposure to depend on volatility, liquidity and trend regimes through a transparent state model or hidden Markov framework."),
        ("Continuous sizing and hysteresis", "Map score strength to 0-100% exposure, use separate entry and exit bands, and target portfolio volatility to reduce threshold whipsaw."),
        ("Realistic investable test", "Use total-return indices or futures/ETF proxies, historical constituents, risk-free cash yield, variable trading costs and liquidity constraints."),
        ("Statistical evidence", "Add block bootstrap intervals, turnover-adjusted comparisons, deflated Sharpe and probability-of-backtest-overfitting diagnostics before making an alpha claim."),
    ]
    story.extend(
        [
            Paragraph("PART III - LIMITATIONS AND ROADMAP", styles["eyebrow"]),
            Paragraph("15. Recommended research roadmap", styles["h1"]),
        ]
    )
    for index, (title, detail) in enumerate(improvements, 1):
        story.extend(
            [
                Paragraph(f"{index}. {title}", styles["h2"]),
                Paragraph(detail, styles["body"]),
            ]
        )
    story.extend(
        [
            Paragraph("Bottom line", styles["h1"]),
            Paragraph(
                f"Removing annualization fixes the score's horizon mismatch, but even the smoother {active_lookback}-session beta remains weak in a binary long-or-cash design. Before treating it as a short-term trading signal, the next milestone should test confirmation, hysteresis and continuous sizing through nested walk-forward validation on investable total-return data.",
                styles["callout"],
            ),
            Paragraph("References and data notes", styles["h2"]),
            Paragraph(
                "Yeo, I. K. and Johnson, R. A. (2000), power-transformation method referenced by the user: https://www.tandfonline.com/doi/epdf/10.1080/713665670. Data: Yahoo Finance delayed and auto-adjusted histories as identified in the generated EquityLens dataset. Calculations: EquityLens walk-forward research code and generated JSON snapshot.",
                styles["small"],
            ),
        ]
    )

    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)


def main() -> None:
    from scripts.generate_custom_signal_latex_report import main as latex_main

    latex_main()


if __name__ == "__main__":
    main()
