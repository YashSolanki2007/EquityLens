"""Response models for the development-only copula pair-signal lab."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CopulaSignalPoint(BaseModel):
    date: str
    h_a_given_b: float
    h_b_given_a: float
    phase: Literal["formation", "trading"]


class CopulaPairSignal(BaseModel):
    pair_id: str
    stock_a: str
    stock_a_name: str
    stock_b: str
    stock_b_name: str
    sector: str
    engle_granger_p_value: float
    fdr_q_value: float
    kss_statistic: float
    reference_ticker: str
    reference_beta_a: float
    reference_beta_b: float
    reference_kss_a: float | None = None
    reference_kss_b: float | None = None
    marginal_a: Literal["Gaussian", "Student-t", "Cauchy"]
    marginal_b: Literal["Gaussian", "Student-t", "Cauchy"]
    marginal_a_aic: float
    marginal_b_aic: float
    copula_family: Literal["Gaussian", "Student-t", "Clayton", "Frank", "Gumbel"]
    copula_parameter: float
    copula_degrees_of_freedom: float | None = None
    copula_aic: float
    kendall_tau: float
    h_a_given_b: float
    h_b_given_a: float
    signal: Literal[
        "enter_long_a_short_b",
        "enter_short_a_long_b",
        "exit",
        "watch",
    ]
    long_ticker: str | None = None
    short_ticker: str | None = None
    long_weight: float | None = None
    short_weight: float | None = None
    signal_explanation: str
    history: list[CopulaSignalPoint] = Field(default_factory=list)


class CopulaPairSignalsResponse(BaseModel):
    development_only: bool = True
    paper_title: str
    paper_url: str
    reference_ticker: str
    universe: str = "NSE_FNO"
    formation_days: int
    trading_days: int
    entry_threshold: float
    exit_threshold: float
    fdr_q_cutoff: float
    dual_test_candidates: int
    entry_signals: int
    exit_signals: int
    returned: int
    generated_at: datetime
    data_source: str
    cached: bool = False
    results: list[CopulaPairSignal] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
