import { z } from "zod";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// --- Schemas (validated at the boundary with Zod) ---

export const SemanticConditionSchema = z.object({
  id: z.string(),
  concept: z.string(),
  card_types: z.array(z.string()),
  required: z.boolean(),
  weight: z.number(),
  directness_required: z.string().default("any"),
});

export const StructuredConditionSchema = z.object({
  field: z.string(),
  operator: z.string(),
  value: z.union([z.string(), z.number(), z.array(z.string()), z.array(z.number())]),
  tolerance_percent: z.number().nullish(),
  required: z.boolean().default(true),
});

export const ResearchConditionSchema = z.object({
  id: z.string(),
  type: z.string(),
  operator: z.string(),
  threshold: z.number().nullish(),
  lookback_days: z.number().nullish(),
  question: z.string().nullish(),
  required: z.boolean().default(true),
  weight: z.number(),
});

export const SearchPlanSchema = z.object({
  original_query: z.string(),
  universe: z.string(),
  base_semantic_conditions: z.array(SemanticConditionSchema),
  base_structured_conditions: z.array(StructuredConditionSchema),
  research_conditions: z.array(ResearchConditionSchema),
  exclusions: z.array(z.string()).default([]),
  ambiguities: z.array(z.any()).default([]),
  candidate_limit: z.number(),
  final_limit: z.number(),
});
export type SearchPlan = z.infer<typeof SearchPlanSchema>;

export const CitationSchema = z.object({
  source_type: z.string(),
  url: z.string(),
  accession: z.string().nullish(),
  description: z.string().nullish(),
  excerpt: z.string().nullish(),
  filing_date: z.string().nullish(),
});
export type Citation = z.infer<typeof CitationSchema>;

export const CompanyChatResponseSchema = z.object({
  ticker: z.string(),
  intent: z.enum([
    "company_facts",
    "ratios",
    "technical",
    "options",
    "deep_research",
    "decision_support",
    "out_of_scope",
  ]),
  answer: z.string(),
  citations: z.array(CitationSchema).default([]),
  limitations: z.array(z.string()).default([]),
  data_used: z.array(z.string()).default([]),
  confidence_label: z.enum(["high", "medium", "low"]).nullish(),
  confidence_percent: z.number().nullish(),
  short_term_view: z.enum(["positive", "mixed", "negative"]).nullish(),
  medium_term_view: z
    .enum(["positive", "mixed", "negative", "unavailable"])
    .nullish(),
  model_name: z.string(),
  generated_at: z.string(),
});
export type CompanyChatResponse = z.infer<typeof CompanyChatResponseSchema>;

export const HorizonOutlookSchema = z.object({
  horizon: z.string(),
  direction: z.enum(["positive", "mixed", "negative", "unavailable"]),
  summary: z.string(),
});

export const CompanyOutlookSchema = z.object({
  ticker: z.string(),
  short_term: HorizonOutlookSchema,
  medium_term: HorizonOutlookSchema,
  confidence_label: z.enum(["high", "medium", "low"]),
  confidence_percent: z.number(),
  citations: z.array(CitationSchema).default([]),
  limitations: z.array(z.string()).default([]),
  data_used: z.array(z.string()).default([]),
  model_name: z.string(),
  generated_at: z.string(),
  cached: z.boolean().default(false),
});
export type CompanyOutlook = z.infer<typeof CompanyOutlookSchema>;

export const ConditionResultSchema = z.object({
  condition_id: z.string(),
  condition_type: z.string().nullish(),
  status: z.string(),
  score: z.number(),
  measured_value: z.number().nullish(),
  unit: z.string().nullish(),
  current_period: z.string().nullish(),
  comparison_period: z.string().nullish(),
  explanation: z.string(),
  citations: z.array(CitationSchema).default([]),
});
export type ConditionResult = z.infer<typeof ConditionResultSchema>;

export const ResultCandidateSchema = z.object({
  company_id: z.string(),
  ticker: z.string(),
  name: z.string().nullish(),
  country: z.string().nullish(),
  exchange: z.string().nullish(),
  currency: z.string().nullish(),
  stage: z.string(),
  rank: z.number().nullish(),
  eligible: z.boolean().nullish(),
  final_score: z.number().nullish(),
  match_percent: z.number().nullish(),
  semantic_score: z.number().nullish(),
  semantic_matches: z.record(z.string(), z.any()).nullish(),
  market_cap_usd: z.number().nullish(),
  market_cap_native: z.number().nullish(),
  market_cap_retrieved_at: z.string().nullish(),
  completed: z.boolean(),
  timed_out: z.boolean(),
  overall_confidence: z.number().nullish(),
  why_matched: z.string().nullish(),
  limitations: z.array(z.string()).default([]),
  contradictions: z.array(z.string()).default([]),
  condition_results: z.array(ConditionResultSchema).default([]),
  directness_badge: z.string().nullish(),
});
export type ResultCandidate = z.infer<typeof ResultCandidateSchema>;

export const FunnelSchema = z.object({
  indexed: z.number(),
  semantic_matches: z.number().default(0),
  passed_base_filters: z.number().default(0),
  researched: z.number().default(0),
  fully_qualified: z.number().default(0),
});
export type Funnel = z.infer<typeof FunnelSchema>;

export const SessionSchema = z.object({
  id: z.string(),
  original_query: z.string(),
  status: z.string(),
  mode: z.string(),
  market: z.string(),
  search_plan: SearchPlanSchema.nullish(),
  funnel: FunnelSchema.nullish(),
  error: z.string().nullish(),
  created_at: z.string(),
  results: z.array(ResultCandidateSchema).default([]),
});
export type Session = z.infer<typeof SessionSchema>;

export const SessionSummarySchema = z.object({
  id: z.string(),
  original_query: z.string(),
  status: z.string(),
  mode: z.string(),
  market: z.string(),
  created_at: z.string(),
});
export type SessionSummary = z.infer<typeof SessionSummarySchema>;

export type ChatMessage = {
  id: string;
  role: string;
  content: string;
  intent?: string | null;
  citations: Citation[];
  limitations: string[];
  created_at: string;
};

export type ProgressEvent = { stage: string; [key: string]: unknown };

export const FinancialSeriesPointSchema = z.object({
  period: z.string(),
  end_date: z.string(),
  revenue: z.number().nullish(),
  net_income: z.number().nullish(),
  net_margin_percent: z.number().nullish(),
  revenue_yoy_percent: z.number().nullish(),
  net_income_yoy_percent: z.number().nullish(),
  accessions: z.array(z.string()).default([]),
});

export const RevenueMovementSchema = z.object({
  id: z.string(),
  period: z.string(),
  end_date: z.string(),
  revenue: z.number(),
  change_percent: z.number(),
  direction: z.enum(["increase", "decline", "stable"]),
  frequency: z.enum(["annual", "quarterly"]),
});

export const FinancialOverviewSchema = z.object({
  ticker: z.string(),
  currency: z.string(),
  annual: z.array(FinancialSeriesPointSchema),
  quarterly: z.array(FinancialSeriesPointSchema),
  headline: z.object({
    period: z.string(),
    revenue: z.number().nullish(),
    net_income: z.number().nullish(),
    net_margin_percent: z.number().nullish(),
    revenue_yoy_percent: z.number().nullish(),
  }).nullish(),
  notable_movements: z.array(RevenueMovementSchema),
  source_url: z.string(),
  limitations: z.array(z.string()).default([]),
});
export type FinancialOverview = z.infer<typeof FinancialOverviewSchema>;

export const FinancialStatementRowSchema = z.object({
  key: z.string(),
  label: z.string(),
  value_type: z.enum(["currency", "percent", "per_share", "shares"]),
  is_total: z.boolean(),
  values: z.record(z.string(), z.number().nullable()),
});

export const FinancialStatementTableSchema = z.object({
  statement_type: z.enum(["income", "balance_sheet", "cash_flow"]),
  title: z.string(),
  frequency: z.enum(["annual", "quarterly"]),
  periods: z.array(z.string()),
  rows: z.array(FinancialStatementRowSchema),
});

export const FinancialStatementsSchema = z.object({
  ticker: z.string(),
  market_data_ticker: z.string(),
  currency: z.string(),
  available: z.boolean(),
  statements: z.array(FinancialStatementTableSchema),
  source: z.string(),
  source_url: z.string(),
  retrieved_at: z.string(),
  is_delayed_or_unverified: z.boolean(),
  limitations: z.array(z.string()).default([]),
});
export type FinancialStatementRow = z.infer<typeof FinancialStatementRowSchema>;
export type FinancialStatementTable = z.infer<
  typeof FinancialStatementTableSchema
>;
export type FinancialStatements = z.infer<typeof FinancialStatementsSchema>;

export const BusinessAnalysisPointSchema = z.object({
  title: z.string(),
  explanation: z.string(),
  evidence_card_ids: z.array(z.string()).default([]),
  confidence: z.enum(["high", "medium", "low"]),
});

export const RevenueExplanationSchema = z.object({
  movement_id: z.string(),
  period: z.string(),
  change_percent: z.number(),
  driver_type: z.enum([
    "company_reported_catalyst",
    "business_context",
    "normal_variation",
    "unexplained",
  ]),
  explanation: z.string(),
  evidence_card_ids: z.array(z.string()).default([]),
  evidence_ids: z.array(z.string()).default([]),
  confidence: z.enum(["high", "medium", "low"]),
});

export const CompanyAnalysisSchema = z.object({
  ticker: z.string(),
  strengths: z.array(BusinessAnalysisPointSchema),
  weaknesses: z.array(BusinessAnalysisPointSchema),
  revenue_explanations: z.array(RevenueExplanationSchema),
  revenue_evidence: z.array(z.object({
    id: z.string(),
    movement_id: z.string(),
    url: z.string(),
    description: z.string(),
    excerpt: z.string(),
  })).default([]),
  limitations: z.array(z.string()).default([]),
  model_name: z.string(),
  generated_at: z.string(),
  cached: z.boolean(),
});
export type CompanyAnalysis = z.infer<typeof CompanyAnalysisSchema>;

export const TradingRatiosSchema = z.object({
  ticker: z.string(),
  market_data_ticker: z.string(),
  currency: z.string(),
  current_price: z.number().nullish(),
  previous_close: z.number().nullish(),
  market_cap: z.number().nullish(),
  trailing_pe: z.number().nullish(),
  forward_pe: z.number().nullish(),
  trailing_eps: z.number().nullish(),
  forward_eps: z.number().nullish(),
  price_to_book: z.number().nullish(),
  peg_ratio: z.number().nullish(),
  book_value: z.number().nullish(),
  profit_margin_percent: z.number().nullish(),
  operating_margin_percent: z.number().nullish(),
  gross_margin_percent: z.number().nullish(),
  return_on_equity_percent: z.number().nullish(),
  return_on_assets_percent: z.number().nullish(),
  revenue_growth_percent: z.number().nullish(),
  earnings_growth_percent: z.number().nullish(),
  debt_to_equity_percent: z.number().nullish(),
  current_ratio: z.number().nullish(),
  quick_ratio: z.number().nullish(),
  dividend_yield_percent: z.number().nullish(),
  payout_ratio_percent: z.number().nullish(),
  beta: z.number().nullish(),
  fifty_two_week_high: z.number().nullish(),
  fifty_two_week_low: z.number().nullish(),
  volume: z.number().nullish(),
  average_volume: z.number().nullish(),
  source: z.string(),
  source_url: z.string(),
  retrieved_at: z.string(),
  is_delayed_or_unverified: z.boolean(),
});
export type TradingRatios = z.infer<typeof TradingRatiosSchema>;

export const PeerMetricDefinitionSchema = z.object({
  key: z.string(),
  label: z.string(),
  category: z.string(),
  format: z.enum(["currency_compact", "multiple", "percent", "number"]),
  higher_is_better: z.boolean().nullish(),
  description: z.string(),
});

export const PeerCompanySchema = z.object({
  ticker: z.string(),
  name: z.string(),
  sector: z.string(),
  industry: z.string(),
  currency: z.string(),
  is_subject: z.boolean(),
  selection_reason: z.string(),
  similarity_percent: z.number().nullish(),
  data_completeness_percent: z.number(),
  metrics: z.record(z.string(), z.number().nullable()),
  percentiles: z.record(z.string(), z.number().nullable()),
  source: z.string(),
  source_url: z.string().nullish(),
  retrieved_at: z.string().nullish(),
});

export const PeerComparisonSchema = z.object({
  ticker: z.string(),
  peer_group_label: z.string(),
  selection_method: z.string(),
  is_manual: z.boolean(),
  metric_definitions: z.array(PeerMetricDefinitionSchema),
  companies: z.array(PeerCompanySchema),
  subject_strengths: z.array(z.string()).default([]),
  subject_watch_items: z.array(z.string()).default([]),
  source: z.string(),
  data_as_of: z.string(),
  limitations: z.array(z.string()).default([]),
});
export type PeerMetricDefinition = z.infer<typeof PeerMetricDefinitionSchema>;
export type PeerCompany = z.infer<typeof PeerCompanySchema>;
export type PeerComparison = z.infer<typeof PeerComparisonSchema>;

export const PriceCandleSchema = z.object({
  time: z.string(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number(),
});

export const PriceHistorySchema = z.object({
  ticker: z.string(),
  market_data_ticker: z.string(),
  range: z.enum(["1M", "3M", "6M", "1Y", "5Y", "MAX"]),
  interval: z.string(),
  currency: z.string(),
  candles: z.array(PriceCandleSchema),
  source: z.string(),
  source_url: z.string(),
  retrieved_at: z.string(),
  is_delayed_or_unverified: z.boolean(),
});
export type PriceHistory = z.infer<typeof PriceHistorySchema>;
export type PriceRange = PriceHistory["range"];

export const PriceForecastSchema = z.object({
  ticker: z.string(),
  market_data_ticker: z.string(),
  currency: z.string(),
  available: z.boolean(),
  model: z.string(),
  horizon_days: z.number(),
  simulations: z.number(),
  observations: z.number(),
  fit_start: z.string().nullish(),
  fit_end: z.string().nullish(),
  last_price: z.number().nullish(),
  median_terminal_price: z.number().nullish(),
  terminal_range_80_low: z.number().nullish(),
  terminal_range_80_high: z.number().nullish(),
  probability_finish_above_last: z.number().nullish(),
  annualized_arima_drift_percent: z.number().nullish(),
  current_annualized_volatility_percent: z.number().nullish(),
  long_run_annualized_volatility_percent: z.number().nullish(),
  arima_ar1: z.number().nullish(),
  arima_ma1: z.number().nullish(),
  garch_omega: z.number().nullish(),
  garch_alpha1: z.number().nullish(),
  garch_beta1: z.number().nullish(),
  student_t_degrees_of_freedom: z.number().nullish(),
  points: z.array(z.object({
    date: z.string(),
    p05: z.number(),
    p10: z.number(),
    p25: z.number(),
    median: z.number(),
    p75: z.number(),
    p90: z.number(),
    p95: z.number(),
    annualized_volatility_percent: z.number(),
  })),
  sample_paths: z.array(z.object({
    id: z.number(),
    points: z.array(z.object({
      date: z.string(),
      price: z.number(),
    })),
  })),
  regression_available: z.boolean().default(false),
  regression_model: z.string().nullish(),
  regression_terminal_price: z.number().nullish(),
  regression_terminal_return_percent: z.number().nullish(),
  regression_points: z.array(z.object({
    date: z.string(),
    predicted_price: z.number(),
    predicted_return_percent: z.number(),
  })).default([]),
  regression_observations: z.number().default(0),
  regression_validation_r_squared: z.number().nullish(),
  regression_validation_mae_percent: z.number().nullish(),
  regression_standardized_coefficients: z.record(z.string(), z.number()).default({}),
  regression_latest_features: z.record(z.string(), z.number()).default({}),
  regression_limitations: z.array(z.string()).default([]),
  source: z.string(),
  source_url: z.string(),
  generated_at: z.string(),
  is_delayed_or_unverified: z.boolean(),
  limitations: z.array(z.string()).default([]),
});
export type PriceForecast = z.infer<typeof PriceForecastSchema>;

export const OptionLegSchema = z.object({
  last_price: z.number().nullish(),
  change: z.number().nullish(),
  percent_change: z.number().nullish(),
  open_interest: z.number().nullish(),
  change_in_open_interest: z.number().nullish(),
  percent_change_in_open_interest: z.number().nullish(),
  volume: z.number().nullish(),
  implied_volatility: z.number().nullish(),
  bid_price: z.number().nullish(),
  bid_quantity: z.number().nullish(),
  ask_price: z.number().nullish(),
  ask_quantity: z.number().nullish(),
  delta: z.number().nullish(),
  gamma: z.number().nullish(),
  theta: z.number().nullish(),
  vega: z.number().nullish(),
  rho: z.number().nullish(),
});

export const OptionsChainSchema = z.object({
  ticker: z.string(),
  symbol: z.string(),
  available: z.boolean(),
  selected_expiry: z.string().nullish(),
  expiry_dates: z.array(z.string()),
  underlying_value: z.number().nullish(),
  exchange_timestamp: z.string().nullish(),
  greeks_model: z.string(),
  greeks_are_modeled: z.boolean(),
  risk_free_rate_percent: z.number(),
  dividend_yield_percent: z.number(),
  strikes: z.array(z.object({
    strike_price: z.number(),
    call: OptionLegSchema.nullish(),
    put: OptionLegSchema.nullish(),
  })),
  distribution: z.object({
    available: z.boolean(),
    method: z.string(),
    buckets: z.array(z.object({
      label: z.string(),
      lower_bound: z.number().nullish(),
      upper_bound: z.number().nullish(),
      chart_price: z.number(),
      probability: z.number(),
    })),
    curve: z.array(z.object({
      strike_price: z.number(),
      probability_above: z.number(),
    })),
    most_likely_range: z.string().nullish(),
    median_price: z.number().nullish(),
    range_50_low: z.number().nullish(),
    range_50_high: z.number().nullish(),
    range_80_low: z.number().nullish(),
    range_80_high: z.number().nullish(),
    probability_above_spot: z.number().nullish(),
    probability_below_spot: z.number().nullish(),
    quality_score: z.number(),
    quality_label: z.enum(["high", "medium", "low", "unavailable"]),
    valid_iv_coverage_percent: z.number(),
    active_contract_coverage_percent: z.number(),
    median_relative_spread_percent: z.number().nullish(),
    strikes_used: z.number(),
    total_strikes: z.number(),
    monotonic_adjustments: z.number(),
    limitation: z.string().nullish(),
  }),
  source: z.string(),
  source_url: z.string(),
  retrieved_at: z.string(),
  is_delayed_or_unverified: z.boolean(),
  limitation: z.string().nullish(),
});
export type OptionsChain = z.infer<typeof OptionsChainSchema>;

export const IVStrategySchema = z.object({
  strategy_id: z.string().nullish(),
  available: z.boolean(),
  signal: z.enum([
    "long_volatility",
    "short_volatility_defined_risk",
    "directional_defined_risk",
    "no_trade",
  ]),
  strategy_name: z.string(),
  rationale: z.string(),
  source_buckets: z.array(z.string()).default([]),
  expiry: z.string().nullish(),
  lot_size: z.number().nullish(),
  underlying_value: z.number().nullish(),
  atm_market_iv_percent: z.number().nullish(),
  atm_predicted_iv_percent: z.number().nullish(),
  market_iv_percent: z.number().nullish(),
  predicted_iv_percent: z.number().nullish(),
  iv_difference_vol_points: z.number().nullish(),
  legs: z.array(z.object({
    action: z.enum(["buy", "sell"]),
    option_type: z.enum(["call", "put"]),
    strike_price: z.number(),
    quantity_lots: z.number(),
    premium_per_unit: z.number(),
    price_source: z.string(),
  })),
  entry_premium_type: z.enum(["debit", "credit"]).nullish(),
  entry_premium_per_unit: z.number().nullish(),
  entry_cash_flow_per_lot: z.number().nullish(),
  capital_at_risk_per_lot: z.number().nullish(),
  maximum_profit_per_lot: z.number().nullish(),
  maximum_loss_per_lot: z.number().nullish(),
  lower_break_even: z.number().nullish(),
  upper_break_even: z.number().nullish(),
  payoff_points: z.array(z.object({
    underlying_price: z.number(),
    pnl_per_lot: z.number(),
    next_session_pnl_per_lot: z.number(),
    pnl_percent_of_capital_at_risk: z.number(),
  })),
  payoff_horizon: z.string().nullish(),
  limitations: z.array(z.string()),
});
export type IVStrategy = z.infer<typeof IVStrategySchema>;

export const IVSurfaceForecastSchema = z.object({
  ticker: z.string(),
  symbol: z.string(),
  available: z.boolean(),
  selected_expiry: z.string().nullish(),
  days_to_expiry: z.number().nullish(),
  forecast_for_date: z.string().nullish(),
  model: z.string(),
  model_version: z.string(),
  model_family: z.enum(["fpca_var", "path_dependent_ssvi"]).default("fpca_var"),
  observations: z.number(),
  fit_start: z.string().nullish(),
  fit_end: z.string().nullish(),
  principal_components: z.number().nullish(),
  explained_variance_percent: z.number().nullish(),
  validation_sessions: z.number(),
  validation_rmse_by_components: z.record(z.string(), z.number()),
  fourth_component_improvement_percent: z.number().nullish(),
  component_selection_note: z.string(),
  validation_model_rmse: z.number().nullish(),
  validation_baseline_rmse: z.number().nullish(),
  validation_improvement_over_baseline_percent: z.number().nullish(),
  validation_directional_accuracy_percent: z.number().nullish(),
  ssvi_parameters: z.object({
    a: z.number(),
    p: z.number(),
    rho: z.number(),
    eta: z.number(),
  }).nullish(),
  path_features: z.record(z.string(), z.record(z.string(), z.number())).nullish(),
  static_arbitrage_checks: z.object({
    calendar_monotonic: z.boolean(),
    butterfly_condition: z.boolean(),
    finite_positive_scan: z.boolean(),
    butterfly_bound: z.number(),
    butterfly_limit: z.number(),
    passed: z.boolean(),
  }).nullish(),
  tenor_grid_days: z.array(z.number()),
  comparisons: z.array(z.object({
    label: z.string(),
    side: z.enum(["call", "put", "call_put"]),
    strike_price: z.number(),
    market_iv_percent: z.number(),
    call_market_iv_percent: z.number().nullish(),
    put_market_iv_percent: z.number().nullish(),
    predicted_iv_percent: z.number(),
    difference_vol_points: z.number(),
    model_error_vol_points: z.number(),
    material_threshold_vol_points: z.number(),
    standardized_gap: z.number().nullish(),
    significant: z.boolean().nullish(),
    status: z.enum(["cheap", "expensive", "in_line"]),
    explanation: z.string(),
  })),
  strategy: IVStrategySchema,
  strategies: z.array(IVStrategySchema).default([]),
  overall_status: z.enum(["cheap", "expensive", "in_line", "unavailable"]),
  summary: z.string(),
  method_note: z.string(),
  adaptation_note: z.string(),
  source: z.string(),
  source_url: z.string(),
  paper_url: z.string(),
  generated_at: z.string(),
  is_delayed_or_unverified: z.boolean(),
  is_carried_forward: z.boolean().default(false),
  refresh_limitation: z.string().nullish(),
  limitation: z.string().nullish(),
});
export type IVSurfaceForecast = z.infer<typeof IVSurfaceForecastSchema>;

export const PaperIVTradeSchema = z.object({
  id: z.string(),
  portfolio_id: z.string(),
  ticker: z.string(),
  symbol: z.string(),
  strategy_name: z.string(),
  signal: z.string(),
  status: z.enum(["open", "closed"]),
  expiry: z.string(),
  lot_size: z.number(),
  quantity_lots: z.number(),
  entry_underlying_value: z.number().nullish(),
  entry_market_iv_percent: z.number().nullish(),
  entry_predicted_iv_percent: z.number().nullish(),
  forecast_generated_at: z.string().nullish(),
  forecast_for_date: z.string().nullish(),
  entry_premium_type: z.enum(["debit", "credit"]),
  entry_cash_flow: z.number(),
  capital_at_risk: z.number(),
  legs: z.array(z.object({
    action: z.enum(["buy", "sell"]),
    option_type: z.enum(["call", "put"]),
    strike_price: z.number(),
    quantity_lots: z.number(),
    premium_per_unit: z.number(),
    price_source: z.string(),
  })),
  created_at: z.string(),
  closed_at: z.string().nullish(),
  realized_pnl: z.number().nullish(),
  latest_mark: z.object({
    id: z.string(),
    underlying_value: z.number().nullish(),
    close_cash_flow: z.number(),
    pnl: z.number(),
    pnl_percent: z.number(),
    leg_marks: z.array(z.object({
      original_action: z.enum(["buy", "sell"]),
      close_action: z.enum(["buy", "sell"]),
      option_type: z.enum(["call", "put"]),
      strike_price: z.number(),
      quantity_lots: z.number(),
      quantity_units: z.number(),
      entry_price_per_unit: z.number(),
      close_price_per_unit: z.number(),
      close_price_source: z.string(),
      close_cash_flow: z.number(),
      current_iv_percent: z.number().nullish(),
      iv_source: z.string().nullish(),
    })),
    source_timestamp: z.string().nullish(),
    price_quality: z.enum(["executable", "estimated"]),
    current_market_iv_percent: z.number().nullish(),
    created_at: z.string(),
  }).nullish(),
  marks: z.array(z.object({
    id: z.string(),
    underlying_value: z.number().nullish(),
    close_cash_flow: z.number(),
    pnl: z.number(),
    pnl_percent: z.number(),
    leg_marks: z.array(z.object({
      original_action: z.enum(["buy", "sell"]),
      close_action: z.enum(["buy", "sell"]),
      option_type: z.enum(["call", "put"]),
      strike_price: z.number(),
      quantity_lots: z.number(),
      quantity_units: z.number(),
      entry_price_per_unit: z.number(),
      close_price_per_unit: z.number(),
      close_price_source: z.string(),
      close_cash_flow: z.number(),
      current_iv_percent: z.number().nullish(),
      iv_source: z.string().nullish(),
    })),
    source_timestamp: z.string().nullish(),
    price_quality: z.enum(["executable", "estimated"]),
    current_market_iv_percent: z.number().nullish(),
    created_at: z.string(),
  })),
  valuation_limitation: z.string().nullish(),
});
export type PaperIVTrade = z.infer<typeof PaperIVTradeSchema>;

export const IVModelEvaluationSchema = z.object({
  model_name: z.string(),
  model_version: z.string(),
  evidence_target: z.number(),
  scored_forecasts: z.number(),
  pending_forecasts: z.number(),
  covered_symbols: z.number(),
  average_explained_variance_percent: z.number().nullish(),
  average_reconstruction_rmse: z.number().nullish(),
  model_rmse: z.number().nullish(),
  baseline_rmse: z.number().nullish(),
  improvement_over_baseline_percent: z.number().nullish(),
  directional_accuracy_percent: z.number().nullish(),
  model_win_rate_percent: z.number().nullish(),
  verdict: z.string(),
  verdict_detail: z.string(),
  historical_backtest: z.object({
    available: z.boolean(),
    verdict: z.string(),
    verdict_detail: z.string(),
    observations: z.number(),
    symbols: z.number().optional(),
    target_sessions: z.number().optional(),
    first_target_date: z.string().optional(),
    last_target_date: z.string().optional(),
    excluded_for_gaps: z.number(),
    model_rmse: z.number().optional(),
    baseline_rmse: z.number().optional(),
    improvement_over_baseline_percent: z.number().optional(),
    improvement_confidence_interval_95: z.array(z.number().nullable()).length(2).optional(),
    bootstrap_probability_model_beats_baseline_percent: z.number().nullable().optional(),
    model_win_rate_percent: z.number().optional(),
    directional_accuracy_percent: z.number().nullable().optional(),
    meaningful_directional_cells: z.number().optional(),
    average_explained_variance_percent: z.number().optional(),
    average_reconstruction_rmse: z.number().optional(),
    component_counts: z.record(z.string(), z.number()).optional(),
    per_symbol: z.array(z.object({
      ticker: z.string(),
      observations: z.number(),
      model_rmse: z.number(),
      baseline_rmse: z.number(),
      improvement_over_baseline_percent: z.number(),
      model_win_rate_percent: z.number(),
      directional_accuracy_percent: z.number().nullable(),
    })).optional(),
    source: z.string(),
    methodology: z.string().optional(),
    limitation: z.string().optional(),
  }),
  path_dependent_backtest: z.object({
    available: z.boolean(),
    verdict: z.string(),
    verdict_detail: z.string(),
    statistically_significant: z.boolean().optional(),
    difference_statistically_significant: z.boolean().optional(),
    significance_result: z.string().optional(),
    bootstrap_p_value_two_sided: z.number().nullable().optional(),
    observations: z.number(),
    symbols: z.number().optional(),
    target_sessions: z.number().optional(),
    first_target_date: z.string().optional(),
    last_target_date: z.string().optional(),
    excluded_for_gaps: z.number(),
    model_rmse: z.number().optional(),
    baseline_rmse: z.number().optional(),
    fpca_rmse_same_sample: z.number().optional(),
    improvement_over_baseline_percent: z.number().optional(),
    improvement_over_fpca_percent: z.number().nullable().optional(),
    improvement_confidence_interval_95: z.array(z.number().nullable()).length(2).optional(),
    bootstrap_probability_model_beats_baseline_percent: z.number().nullable().optional(),
    model_win_rate_percent: z.number().optional(),
    directional_accuracy_percent: z.number().nullable().optional(),
    meaningful_directional_cells: z.number().optional(),
    average_calibration_rmse: z.number().optional(),
    static_arbitrage_pass_rate_percent: z.number().optional(),
    per_symbol: z.array(z.object({
      ticker: z.string(),
      observations: z.number(),
      model_rmse: z.number(),
      baseline_rmse: z.number(),
      improvement_over_baseline_percent: z.number(),
      model_win_rate_percent: z.number(),
      directional_accuracy_percent: z.number().nullable(),
    })).optional(),
    source: z.string(),
    paper_url: z.string(),
    methodology: z.string().optional(),
    limitation: z.string().optional(),
    strengths: z.array(z.string()),
    weaknesses: z.array(z.string()),
  }),
  thresholds: z.object({
    fpca_explained_variance_healthy_percent: z.number(),
    minimum_rmse_improvement_percent: z.number(),
    minimum_directional_accuracy_percent: z.number(),
    minimum_scored_forecasts: z.number(),
  }),
  records: z.array(z.object({
    id: z.string(),
    ticker: z.string(),
    status: z.string(),
    generated_at: z.string(),
    source_as_of_date: z.string(),
    target_date: z.string(),
    component_count: z.number(),
    explained_variance_percent: z.number(),
    reconstruction_rmse: z.number(),
    validation_sessions: z.number(),
    validation_model_rmse: z.number(),
    validation_baseline_rmse: z.number(),
    validation_improvement_percent: z.number(),
    validation_directional_accuracy_percent: z.number().nullish(),
    model_rmse: z.number().nullish(),
    baseline_rmse: z.number().nullish(),
    improvement_over_baseline_percent: z.number().nullish(),
    directional_accuracy_percent: z.number().nullish(),
    bias_vol_points: z.number().nullish(),
    scored_at: z.string().nullish(),
  })),
});
export type IVModelEvaluation = z.infer<typeof IVModelEvaluationSchema>;

export const MarketPulseArticleSchema = z.object({
  id: z.string(),
  title: z.string(),
  url: z.string(),
  domain: z.string(),
  published_date: z.string(),
  category: z.enum([
    "monetary_policy",
    "economy",
    "geopolitics",
    "energy_trade",
    "technology_regulation",
    "other",
  ]),
  summary_lines: z.array(z.string()),
  market_relevance: z.string(),
  impact_direction: z.enum(["positive", "negative", "mixed", "unclear"]),
  affected_areas: z.array(z.string()).default([]),
});
export type MarketPulseArticle = z.infer<typeof MarketPulseArticleSchema>;

export const MarketPulseSchema = z.object({
  market: z.literal("IN"),
  as_of: z.string(),
  lookback_days: z.number(),
  oldest_allowed_date: z.string(),
  overview: z.string(),
  key_themes: z.array(z.string()).default([]),
  articles: z.array(MarketPulseArticleSchema).default([]),
  limitations: z.array(z.string()).default([]),
  model_name: z.string(),
  cached: z.boolean(),
});
export type MarketPulse = z.infer<typeof MarketPulseSchema>;

export const BlockDealSchema = z.object({
  trade_date: z.string(),
  symbol: z.string(),
  company_name: z.string(),
  client_name: z.string(),
  side: z.enum(["BUY", "SELL"]),
  quantity: z.number(),
  weighted_average_price: z.number(),
  trade_value_inr: z.number(),
});

export const BlockDealsSchema = z.object({
  market: z.literal("IN"),
  exchange: z.literal("NSE"),
  from_date: z.string(),
  to_date: z.string(),
  retrieved_at: z.string(),
  source: z.string(),
  source_url: z.string(),
  used_latest_snapshot: z.boolean(),
  limitation: z.string(),
  deals: z.array(BlockDealSchema),
});
export type BlockDeal = z.infer<typeof BlockDealSchema>;
export type BlockDeals = z.infer<typeof BlockDealsSchema>;

export const TechnicalConditionSchema = z.object({
  indicator: z.string(),
  operator: z.string(),
  value: z.union([z.number(), z.array(z.number())]),
  required: z.boolean(),
});

export const TechnicalScanPlanSchema = z.object({
  original_query: z.string(),
  semantic_concept: z.string().nullish(),
  conditions: z.array(TechnicalConditionSchema),
  sort_by: z.string().nullish(),
  sort_direction: z.enum(["asc", "desc"]),
  result_limit: z.number(),
});

export const TechnicalScanResultSchema = z.object({
  ticker: z.string(),
  name: z.string(),
  sector: z.string(),
  industry: z.string(),
  price: z.number().nullish(),
  candle_time: z.string(),
  candle_interval: z.enum(["1m", "5m", "15m", "30m", "1h", "1d"]),
  candles_used: z.number(),
  rsi_14: z.number().nullish(),
  macd_histogram: z.number().nullish(),
  price_vs_vwap_percent: z.number().nullish(),
  ema_9_vs_ema_21_percent: z.number().nullish(),
  return_5c_percent: z.number().nullish(),
  return_15c_percent: z.number().nullish(),
  return_60c_percent: z.number().nullish(),
  relative_volume: z.number().nullish(),
  atr_percent: z.number().nullish(),
  bollinger_position_percent: z.number().nullish(),
  source: z.string(),
  source_url: z.string(),
  is_delayed_or_unverified: z.boolean(),
  options_available: z.boolean(),
  option_expiry: z.string().nullish(),
  call_open_interest: z.number().nullish(),
  put_open_interest: z.number().nullish(),
  call_oi_change_percent: z.number().nullish(),
  put_oi_change_percent: z.number().nullish(),
  put_call_oi_ratio: z.number().nullish(),
  call_delta: z.number().nullish(),
  call_delta_strike: z.number().nullish(),
  put_delta: z.number().nullish(),
  put_delta_strike: z.number().nullish(),
  option_source_url: z.string().nullish(),
  technical_score: z.number(),
  semantic_score: z.number().nullish(),
  combined_score: z.number(),
  matched_conditions: z.array(z.string()),
  semantic_evidence: z.string().nullish(),
});

export const TechnicalScanResponseSchema = z.object({
  query: z.string(),
  plan: TechnicalScanPlanSchema,
  universe: z.string(),
  universe_size: z.number(),
  semantic_candidates: z.number(),
  scanned: z.number(),
  failed: z.number(),
  candle_scan_skipped: z.boolean(),
  option_candidates: z.number(),
  options_scanned: z.number(),
  options_available: z.number(),
  options_failed: z.number(),
  returned: z.number(),
  candle_interval: z.enum(["1m", "5m", "15m", "30m", "1h", "1d"]),
  candle_limit: z.number(),
  generated_at: z.string(),
  data_source: z.string(),
  results: z.array(TechnicalScanResultSchema),
  limitations: z.array(z.string()),
});
export type TechnicalScanResponse = z.infer<typeof TechnicalScanResponseSchema>;
export type TechnicalScanResult = z.infer<typeof TechnicalScanResultSchema>;

export const PairChartPointSchema = z.object({
  date: z.string(),
  stock_a_indexed: z.number(),
  stock_b_indexed: z.number(),
  spread_zscore: z.number().nullish(),
});

export const PairSuggestionSchema = z.object({
  pair_id: z.string(),
  stock_a: z.string(),
  stock_a_name: z.string(),
  stock_a_type: z.enum(["stock", "index"]),
  stock_b: z.string(),
  stock_b_name: z.string(),
  stock_b_type: z.enum(["stock", "index"]),
  sector: z.string(),
  signal: z.enum(["long_a_short_b", "short_a_long_b", "watch"]),
  long_ticker: z.string(),
  short_ticker: z.string(),
  example_long_quantity: z.number(),
  example_short_quantity: z.number(),
  example_long_price: z.number(),
  example_short_price: z.number(),
  example_long_value_inr: z.number(),
  example_short_value_inr: z.number(),
  example_target_long_price: z.number(),
  example_target_short_price: z.number(),
  example_gross_return_percent: z.number(),
  futures_plan_available: z.boolean(),
  futures_plan_note: z.string().nullish(),
  futures_price_date: z.string().nullish(),
  estimated_reversion_date: z.string().nullish(),
  futures_expiry: z.string().nullish(),
  futures_requires_rollover: z.boolean(),
  long_futures_contract_name: z.string().nullish(),
  short_futures_contract_name: z.string().nullish(),
  long_futures_price: z.number().nullish(),
  short_futures_price: z.number().nullish(),
  long_futures_target_price: z.number().nullish(),
  short_futures_target_price: z.number().nullish(),
  long_futures_lot_size: z.number().nullish(),
  short_futures_lot_size: z.number().nullish(),
  long_futures_contracts: z.number().nullish(),
  short_futures_contracts: z.number().nullish(),
  long_futures_units: z.number().nullish(),
  short_futures_units: z.number().nullish(),
  long_futures_notional_inr: z.number().nullish(),
  short_futures_notional_inr: z.number().nullish(),
  futures_hedge_fit_percent: z.number().nullish(),
  explanation: z.string(),
  hedge_ratio: z.number(),
  current_zscore: z.number(),
  cointegration_p_value: z.number(),
  fdr_q_value: z.number(),
  half_life_days: z.number(),
  return_correlation: z.number(),
  observations: z.number(),
  stock_a_market_cap_crore: z.number().nullish(),
  stock_b_market_cap_crore: z.number().nullish(),
  stock_a_median_daily_value_crore: z.number().nullish(),
  stock_b_median_daily_value_crore: z.number().nullish(),
  chart: z.array(PairChartPointSchema),
});

export const PairSuggestionsResponseSchema = z.object({
  universe: z.string(),
  minimum_market_cap_crore: z.number(),
  official_underlyings: z.number(),
  stock_underlyings: z.number(),
  index_underlyings: z.number(),
  universe_size: z.number(),
  price_eligible_universe: z.number(),
  pairs_tested: z.number(),
  p_value_threshold: z.number(),
  p_significant_pairs: z.number(),
  threshold_counts: z.array(
    z.object({
      threshold: z.number(),
      p_significant_pairs: z.number(),
    })
  ),
  returned: z.number(),
  generated_at: z.string(),
  data_source: z.string(),
  cached: z.boolean(),
  results: z.array(PairSuggestionSchema),
  limitations: z.array(z.string()),
});
export type PairSuggestion = z.infer<typeof PairSuggestionSchema>;
export type PairSuggestionsResponse = z.infer<typeof PairSuggestionsResponseSchema>;

export const PairMethodLabChartPointSchema = z.object({
  date: z.string(),
  stock_a_indexed: z.number(),
  stock_b_indexed: z.number(),
  paper_zscore: z.number().nullish(),
});

export const PairMethodLabCandidateSchema = z.object({
  pair_id: z.string(),
  stock_a: z.string(),
  stock_a_name: z.string(),
  stock_a_type: z.enum(["stock", "index"]),
  stock_b: z.string(),
  stock_b_name: z.string(),
  stock_b_type: z.enum(["stock", "index"]),
  sector: z.string(),
  hedge_ratio: z.number(),
  return_correlation: z.number(),
  observations: z.number(),
  engle_granger_p_value: z.number(),
  fdr_q_value: z.number(),
  engle_granger_pass: z.boolean(),
  kss_statistic: z.number(),
  kss_critical_value: z.number(),
  kss_pass: z.boolean(),
  half_life_days: z.number(),
  adaptive_lookback_days: z.number(),
  current_zscore: z.number(),
  latest_price_a: z.number(),
  latest_price_b: z.number(),
  spread_gap_to_mean: z.number(),
  potential_convergence_return_percent: z.number(),
  futures_capital_available: z.boolean(),
  futures_price_date: z.string().nullish(),
  futures_expiry: z.string().nullish(),
  capital_plan_is_active: z.boolean(),
  capital_long_ticker: z.string().nullish(),
  capital_short_ticker: z.string().nullish(),
  long_futures_contracts: z.number().nullish(),
  short_futures_contracts: z.number().nullish(),
  long_futures_units: z.number().nullish(),
  short_futures_units: z.number().nullish(),
  long_futures_price: z.number().nullish(),
  short_futures_price: z.number().nullish(),
  long_futures_notional_inr: z.number().nullish(),
  short_futures_notional_inr: z.number().nullish(),
  combined_futures_notional_inr: z.number().nullish(),
  futures_hedge_fit_percent: z.number().nullish(),
  futures_capital_note: z.string().nullish(),
  paper_signal: z.enum([
    "long_a_short_b",
    "short_a_long_b",
    "inside_entry_band",
  ]),
  long_ticker: z.string().nullish(),
  short_ticker: z.string().nullish(),
  tracker_entry_type: z
    .enum(["direct", "confirmed_convergence"])
    .nullish(),
  tracker_recent_peak_abs_zscore: z.number().nullish(),
  tracker_remaining_return_percent: z.number().nullish(),
  rolling_windows: z.number(),
  stability_passed_windows: z.number(),
  stability_score_percent: z.number(),
  stability_band: z.enum([
    "strong",
    "moderate",
    "unstable",
    "insufficient_history",
  ]),
  engle_granger_stability_percent: z.number(),
  kss_stability_percent: z.number(),
  entry_events: z.number(),
  reversion_success_rate_percent: z.number().nullish(),
  median_five_day_z_change: z.number().nullish(),
  current_method_p_value: z.number().nullish(),
  current_method_half_life_days: z.number().nullish(),
  current_method_zscore: z.number().nullish(),
  current_method_pass: z.boolean(),
  current_method_signal: z.enum([
    "long_a_short_b",
    "short_a_long_b",
    "watch",
    "not_eligible",
  ]),
  comparison: z.enum([
    "both_methods",
    "paper_only",
    "current_only",
    "neither",
  ]),
  chart: z.array(PairMethodLabChartPointSchema),
});

export const PairMethodLabResponseSchema = z.object({
  development_only: z.literal(true),
  paper_title: z.string(),
  paper_url: z.string(),
  universe: z.string(),
  minimum_market_cap_crore: z.number(),
  official_underlyings: z.number(),
  universe_size: z.number(),
  price_eligible_universe: z.number(),
  pairs_tested: z.number(),
  formation_days: z.number(),
  current_comparison_days: z.number(),
  trading_days: z.number(),
  rolling_validation_windows: z.number(),
  engle_granger_cutoff: z.number(),
  kss_critical_value: z.number(),
  engle_granger_candidates: z.number(),
  kss_candidates: z.number(),
  either_test_candidates: z.number(),
  returned: z.number(),
  generated_at: z.string(),
  data_source: z.string(),
  cached: z.boolean(),
  results: z.array(PairMethodLabCandidateSchema),
  limitations: z.array(z.string()),
});
export type PairMethodLabCandidate = z.infer<typeof PairMethodLabCandidateSchema>;
export type PairMethodLabResponse = z.infer<typeof PairMethodLabResponseSchema>;

export const CopulaSignalPointSchema = z.object({
  date: z.string(),
  h_a_given_b: z.number(),
  h_b_given_a: z.number(),
  phase: z.enum(["formation", "trading"]),
});

export const CopulaPairSignalSchema = z.object({
  pair_id: z.string(),
  stock_a: z.string(),
  stock_a_name: z.string(),
  stock_b: z.string(),
  stock_b_name: z.string(),
  sector: z.string(),
  engle_granger_p_value: z.number(),
  fdr_q_value: z.number(),
  kss_statistic: z.number(),
  reference_ticker: z.string(),
  reference_beta_a: z.number(),
  reference_beta_b: z.number(),
  reference_kss_a: z.number().nullish(),
  reference_kss_b: z.number().nullish(),
  marginal_a: z.enum(["Gaussian", "Student-t", "Cauchy"]),
  marginal_b: z.enum(["Gaussian", "Student-t", "Cauchy"]),
  marginal_a_aic: z.number(),
  marginal_b_aic: z.number(),
  copula_family: z.enum(["Gaussian", "Student-t", "Clayton", "Frank", "Gumbel"]),
  copula_parameter: z.number(),
  copula_degrees_of_freedom: z.number().nullish(),
  copula_aic: z.number(),
  kendall_tau: z.number(),
  h_a_given_b: z.number(),
  h_b_given_a: z.number(),
  signal: z.enum([
    "enter_long_a_short_b",
    "enter_short_a_long_b",
    "exit",
    "watch",
  ]),
  long_ticker: z.string().nullish(),
  short_ticker: z.string().nullish(),
  long_weight: z.number().nullish(),
  short_weight: z.number().nullish(),
  signal_explanation: z.string(),
  history: z.array(CopulaSignalPointSchema),
});

export const CopulaPairSignalsResponseSchema = z.object({
  development_only: z.literal(true),
  paper_title: z.string(),
  paper_url: z.string(),
  reference_ticker: z.string(),
  universe: z.string(),
  formation_days: z.number(),
  trading_days: z.number(),
  entry_threshold: z.number(),
  exit_threshold: z.number(),
  fdr_q_cutoff: z.number(),
  dual_test_candidates: z.number(),
  entry_signals: z.number(),
  exit_signals: z.number(),
  returned: z.number(),
  generated_at: z.string(),
  data_source: z.string(),
  cached: z.boolean(),
  results: z.array(CopulaPairSignalSchema),
  limitations: z.array(z.string()),
});
export type CopulaPairSignal = z.infer<typeof CopulaPairSignalSchema>;
export type CopulaPairSignalsResponse = z.infer<typeof CopulaPairSignalsResponseSchema>;

export const IntradayCopulaHistoryPointSchema = z.object({
  timestamp: z.string(),
  h_a_given_b: z.number(),
  h_b_given_a: z.number(),
  stock_a_price: z.number(),
  stock_b_price: z.number(),
});

export const IntradayCopulaCandidateSchema = z.object({
  pair_id: z.string(),
  stock_a: z.string(),
  stock_a_name: z.string(),
  stock_b: z.string(),
  stock_b_name: z.string(),
  sector: z.string(),
  engle_granger_p_value: z.number(),
  fdr_q_value: z.number(),
  kss_statistic: z.number(),
  regression_days: z.number(),
  intraday_sessions: z.number(),
  formation_bars: z.number(),
  reference_beta_a: z.number(),
  reference_beta_b: z.number(),
  marginal_a: z.enum(["Gaussian", "Student-t", "Cauchy"]),
  marginal_b: z.enum(["Gaussian", "Student-t", "Cauchy"]),
  copula_family: z.enum(["Gaussian", "Student-t", "Clayton", "Frank", "Gumbel"]),
  copula_parameter: z.number(),
  copula_degrees_of_freedom: z.number().nullish(),
  copula_aic: z.number(),
  h_a_given_b: z.number(),
  h_b_given_a: z.number(),
  signal: z.enum([
    "enter_long_a_short_b",
    "enter_short_a_long_b",
    "exit",
    "watch",
  ]),
  long_ticker: z.string().nullish(),
  short_ticker: z.string().nullish(),
  long_weight: z.number().nullish(),
  short_weight: z.number().nullish(),
  stock_a_price: z.number(),
  stock_b_price: z.number(),
  session_open_a: z.number(),
  session_open_b: z.number(),
  session_open_timestamp: z.string(),
  latest_bar_end: z.string(),
  can_enter: z.boolean(),
  entry_block_reason: z.string().nullish(),
  history: z.array(IntradayCopulaHistoryPointSchema),
});

export const IntradayCopulaTradeMarkSchema = z.object({
  id: z.string().nullish(),
  long_price: z.number(),
  short_price: z.number(),
  long_pnl: z.number(),
  short_pnl: z.number(),
  total_pnl: z.number(),
  return_percent: z.number(),
  current_gross_notional: z.number(),
  h_a_given_b: z.number(),
  h_b_given_a: z.number(),
  quote_timestamp: z.string(),
  price_source: z.string(),
  created_at: z.string(),
});

export const IntradayCopulaTradeSchema = z.object({
  id: z.string(),
  portfolio_id: z.string(),
  pair_id: z.string(),
  session_date: z.string(),
  status: z.enum(["open", "closed"]),
  stock_a: z.string(),
  stock_b: z.string(),
  long_ticker: z.string(),
  short_ticker: z.string(),
  long_units: z.number(),
  short_units: z.number(),
  entry_long_price: z.number(),
  entry_short_price: z.number(),
  entry_long_notional: z.number(),
  entry_short_notional: z.number(),
  entry_combined_notional: z.number(),
  entry_h_a_given_b: z.number(),
  entry_h_b_given_a: z.number(),
  entry_q_value: z.number(),
  entry_kss_statistic: z.number(),
  copula_family: z.string(),
  profit_target_percent: z.number(),
  stop_loss_percent: z.number(),
  entry_price_timestamp: z.string(),
  entry_price_source: z.string(),
  created_at: z.string(),
  closed_at: z.string().nullish(),
  realized_pnl: z.number().nullish(),
  exit_reason: z.string().nullish(),
  exit_h_a_given_b: z.number().nullish(),
  exit_h_b_given_a: z.number().nullish(),
  latest_mark: IntradayCopulaTradeMarkSchema.nullish(),
  marks: z.array(IntradayCopulaTradeMarkSchema),
});

export const IntradayCopulaPendingEntrySchema = z.object({
  id: z.string(),
  pair_id: z.string(),
  signal_session_date: z.string(),
  status: z.enum(["queued", "entered", "cancelled"]),
  stock_a: z.string(),
  stock_b: z.string(),
  long_ticker: z.string(),
  short_ticker: z.string(),
  observed_h_a_given_b: z.number(),
  observed_h_b_given_a: z.number(),
  entry_q_value: z.number(),
  copula_family: z.string(),
  signal_observed_at: z.string(),
  entered_trade_id: z.string().nullish(),
  created_at: z.string(),
});

export const IntradayCopulaTrackerResponseSchema = z.object({
  development_only: z.literal(true),
  bar_minutes: z.number(),
  daily_regression_days: z.number(),
  intraday_history_period: z.string(),
  entry_threshold: z.number(),
  exit_band_low: z.number(),
  exit_band_high: z.number(),
  profit_target_percent: z.number(),
  entry_start_ist: z.string(),
  last_entry_ist: z.string(),
  forced_exit_ist: z.string(),
  eligible_pairs: z.number(),
  returned_candidates: z.number(),
  entry_signals: z.number(),
  created_trades: z.number(),
  queued_entries_created: z.number(),
  generated_at: z.string(),
  snapshot_bar_end: z.string().nullish(),
  cached: z.boolean().default(false),
  refreshing: z.boolean().default(false),
  data_source: z.string(),
  candidates: z.array(IntradayCopulaCandidateSchema),
  pending_entries: z.array(IntradayCopulaPendingEntrySchema),
  trades: z.array(IntradayCopulaTradeSchema),
  limitations: z.array(z.string()),
});

export type IntradayCopulaCandidate = z.infer<typeof IntradayCopulaCandidateSchema>;
export type IntradayCopulaPendingEntry = z.infer<typeof IntradayCopulaPendingEntrySchema>;
export type IntradayCopulaTrade = z.infer<typeof IntradayCopulaTradeSchema>;
export type IntradayCopulaTradeMark = z.infer<typeof IntradayCopulaTradeMarkSchema>;
export type IntradayCopulaTrackerResponse = z.infer<typeof IntradayCopulaTrackerResponseSchema>;

export const PaperLabSpotTradeMarkSchema = z.object({
  id: z.string().nullish(),
  long_price: z.number(),
  short_price: z.number(),
  long_pnl: z.number(),
  short_pnl: z.number(),
  total_pnl: z.number(),
  return_percent: z.number(),
  current_long_notional: z.number(),
  current_short_notional: z.number(),
  current_gross_notional: z.number(),
  estimated_zscore: z.number().nullish(),
  estimated_p_value: z.number().nullish(),
  quote_timestamp: z.string(),
  price_source: z.string(),
  is_live: z.boolean(),
  created_at: z.string(),
});

export const PaperLabSpotTradeSchema = z.object({
  id: z.string(),
  portfolio_id: z.string(),
  pair_id: z.string(),
  status: z.enum(["open", "closed"]),
  long_ticker: z.string(),
  short_ticker: z.string(),
  long_units: z.number(),
  short_units: z.number(),
  entry_long_price: z.number(),
  entry_short_price: z.number(),
  entry_long_notional: z.number(),
  entry_short_notional: z.number(),
  entry_combined_notional: z.number(),
  hedge_ratio: z.number(),
  entry_zscore: z.number(),
  entry_p_value: z.number(),
  entry_kss_statistic: z.number(),
  entry_q_value: z.number(),
  entry_expected_return_percent: z.number().nullish(),
  formal_entry_signal: z.boolean(),
  entry_signal_type: z.enum(["direct", "confirmed_convergence", "legacy"]),
  entry_recent_peak_abs_zscore: z.number().nullish(),
  entry_remaining_return_percent: z.number().nullish(),
  entry_price_timestamp: z.string(),
  entry_price_source: z.string(),
  created_at: z.string(),
  closed_at: z.string().nullish(),
  realized_pnl: z.number().nullish(),
  exit_reason: z.string().nullish(),
  exit_zscore: z.number().nullish(),
  exit_p_value: z.number().nullish(),
  latest_mark: PaperLabSpotTradeMarkSchema.nullish(),
  live_mark: PaperLabSpotTradeMarkSchema.nullish(),
  marks: z.array(PaperLabSpotTradeMarkSchema),
  valuation_limitation: z.string().nullish(),
});

export const PaperLabSpotTradeSyncSchema = z.object({
  eligible_pairs: z.number(),
  created_trades: z.number(),
  trades: z.array(PaperLabSpotTradeSchema),
});

export type PaperLabSpotTrade = z.infer<typeof PaperLabSpotTradeSchema>;
export type PaperLabSpotTradeMark = z.infer<typeof PaperLabSpotTradeMarkSchema>;

const PaperPairTradeMarkSchema = z.object({
  id: z.string().nullish(),
  price_date: z.string(),
  long_price: z.number(),
  short_price: z.number(),
  long_pnl: z.number(),
  short_pnl: z.number(),
  current_long_notional: z.number(),
  current_short_notional: z.number(),
  quote_timestamp: z.string(),
  price_source: z.string(),
  is_live: z.boolean(),
  total_pnl: z.number(),
  return_percent: z.number(),
  current_gross_notional: z.number(),
  created_at: z.string(),
});

export const PaperPairTradeSchema = z.object({
  id: z.string(),
  portfolio_id: z.string(),
  pair_id: z.string(),
  status: z.enum(["open", "closed"]),
  entry_signal: z.enum(["active", "watch"]),
  long_ticker: z.string(),
  short_ticker: z.string(),
  expiry: z.string(),
  estimated_reversion_date: z.string().nullish(),
  requires_rollover: z.boolean(),
  long_contract_name: z.string(),
  short_contract_name: z.string(),
  long_contracts: z.number(),
  short_contracts: z.number(),
  long_lot_size: z.number(),
  short_lot_size: z.number(),
  long_units: z.number(),
  short_units: z.number(),
  entry_long_price: z.number(),
  entry_short_price: z.number(),
  entry_long_notional: z.number(),
  entry_short_notional: z.number(),
  entry_combined_notional: z.number(),
  hedge_ratio: z.number(),
  hedge_fit_percent: z.number(),
  entry_zscore: z.number(),
  entry_q_value: z.number(),
  entry_price_date: z.string(),
  entry_price_source: z.string(),
  entry_price_timestamp: z.string().nullish(),
  created_at: z.string(),
  closed_at: z.string().nullish(),
  realized_pnl: z.number().nullish(),
  latest_mark: PaperPairTradeMarkSchema.nullish(),
  live_mark: PaperPairTradeMarkSchema.nullish(),
  marks: z.array(PaperPairTradeMarkSchema),
  valuation_limitation: z.string().nullish(),
});
export type PaperPairTrade = z.infer<typeof PaperPairTradeSchema>;

const PaperPairPortfolioPositionSchema = z.object({
  pair_id: z.string(),
  long_ticker: z.string(),
  short_ticker: z.string(),
  long_units: z.number(),
  short_units: z.number(),
  entry_long_price: z.number(),
  entry_short_price: z.number(),
  entry_price_date: z.string(),
  entry_long_notional: z.number(),
  entry_short_notional: z.number(),
  allocated_gross_inr: z.number(),
  hedge_ratio: z.number(),
  entry_zscore: z.number(),
  entry_q_value: z.number(),
  pair_quality_rank: z.number(),
  mean_abs_correlation_to_portfolio: z.number(),
});

const PaperPairPortfolioMarkSchema = z.object({
  date: z.string(),
  portfolio_value_inr: z.number(),
  total_pnl_inr: z.number(),
  return_percent: z.number(),
  current_gross_notional_inr: z.number(),
});

export const PaperPairPortfolioSchema = z.object({
  id: z.string(),
  owner_portfolio_id: z.string(),
  status: z.enum(["current", "superseded"]),
  initial_capital_inr: z.number(),
  allocated_gross_inr: z.number(),
  unallocated_cash_inr: z.number(),
  p_value_threshold: z.number(),
  entry_price_date: z.string(),
  entry_price_source: z.string(),
  positions: z.array(PaperPairPortfolioPositionSchema),
  marks: z.array(PaperPairPortfolioMarkSchema),
  selection_summary: z.object({
    fully_ticker_disjoint: z.boolean(),
    used_same_side_overlap_fallback: z.boolean(),
    mean_absolute_pair_correlation: z.number().nullish(),
    maximum_absolute_pair_correlation: z.number().nullish(),
    target_pairs: z.number(),
    selected_pairs: z.number(),
    unique_companies: z.number(),
    selection_method: z.string(),
    per_pair_mean_absolute_correlation: z.record(z.string(), z.number()),
  }),
  limitations: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string(),
});
export type PaperPairPortfolio = z.infer<typeof PaperPairPortfolioSchema>;

export const MaterializationStatusSchema = z.object({
  state: z.enum(["unknown", "running", "idle", "completed"]),
  stage: z.enum(["metadata", "cards"]).nullish(),
  run_completed: z.number(),
  run_total: z.number(),
  run_percent: z.number(),
  rate_per_hour: z.number().nullish(),
  eta_seconds: z.number().nullish(),
  eta_at: z.string().nullish(),
  last_ticker: z.string().nullish(),
  last_outcome: z.string().nullish(),
  updated_at: z.string().nullish(),
  universe_size: z.number(),
  companies_with_reports: z.number(),
  report_coverage_percent: z.number(),
  companies_with_cards: z.number(),
  card_coverage_percent: z.number(),
  total_cards: z.number(),
  embedded_cards: z.number(),
});
export type MaterializationStatus = z.infer<typeof MaterializationStatusSchema>;

// --- Fetch helpers ---

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body.slice(0, 300)}`);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string }>(`/api/health`),
  planSearch: (query: string, mode: string, market: "US" | "IN" = "US") =>
    request(`/api/search/plan`, {
      method: "POST",
      body: JSON.stringify({ query, mode, market }),
    }).then((d) => SearchPlanSchema.parse(d)),
  runSearch: (body: {
    query?: string;
    plan?: SearchPlan;
    mode: string;
    market: "US" | "IN";
  }) =>
    request<{ search_id: string; status: string }>(`/api/search/run`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getSearch: (id: string) =>
    request(`/api/search/${id}`).then((d) => SessionSchema.parse(d)),
  listSessions: () =>
    request<unknown[]>(`/api/search/sessions`).then((d) =>
      z.array(SessionSummarySchema).parse(d)
    ),
  getMessages: (id: string) => request<ChatMessage[]>(`/api/search/${id}/messages`),
  followUp: (id: string, message: string) =>
    request<{
      message_id: string;
      intent: string;
      answer: string;
      citations: Citation[];
      limitations: string[];
    }>(`/api/search/${id}/follow-up`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  patchPlan: (id: string, body: { instruction?: string; plan?: SearchPlan; rerun?: boolean }) =>
    request(`/api/search/${id}/plan`, { method: "PATCH", body: JSON.stringify(body) }),
  listCompanies: () => request<unknown[]>(`/api/companies`),
  getCompany: (ticker: string) => request<Record<string, unknown>>(`/api/companies/${ticker}`),
  getCompanyCards: (ticker: string) => request<Record<string, unknown>[]>(`/api/companies/${ticker}/cards`),
  getCompanyFilings: (ticker: string) => request<Record<string, unknown>[]>(`/api/companies/${ticker}/filings`),
  getCompanyFinancialOverview: (ticker: string) =>
    request(`/api/companies/${ticker}/financial-overview`).then((d) =>
      FinancialOverviewSchema.parse(d)
    ),
  getCompanyFinancialStatements: (ticker: string) =>
    request(`/api/companies/${ticker}/financial-statements`).then((d) =>
      FinancialStatementsSchema.parse(d)
    ),
  getCompanyAnalysis: (ticker: string) =>
    request(`/api/companies/${ticker}/analysis`, { method: "POST" }).then((d) =>
      CompanyAnalysisSchema.parse(d)
    ),
  chatAboutCompany: (
    ticker: string,
    message: string,
    history: { role: "user" | "assistant"; content: string }[]
  ) =>
    request(`/api/companies/${ticker}/chat`, {
      method: "POST",
      body: JSON.stringify({ message, history: history.slice(-8) }),
    }).then((d) => CompanyChatResponseSchema.parse(d)),
  getCompanyOutlook: (ticker: string) =>
    request(`/api/companies/${ticker}/outlook`).then((d) =>
      CompanyOutlookSchema.parse(d)
    ),
  getCompanyTradingRatios: (ticker: string) =>
    request(`/api/companies/${ticker}/trading-ratios`).then((d) =>
      TradingRatiosSchema.parse(d)
    ),
  getCompanyPeerComparison: (ticker: string, symbols?: string[]) => {
    const query =
      symbols === undefined
        ? ""
        : `?symbols=${encodeURIComponent(symbols.join(","))}`;
    return request(`/api/companies/${ticker}/peer-comparison${query}`).then((d) =>
      PeerComparisonSchema.parse(d)
    );
  },
  getCompanyPriceHistory: (ticker: string, range: PriceRange) =>
    request(`/api/companies/${ticker}/price-history?range=${range}`).then((d) =>
      PriceHistorySchema.parse(d)
    ),
  getCompanyPriceForecast: (
    ticker: string,
    horizonDays: number,
    simulations: number
  ) =>
    request(
      `/api/companies/${ticker}/price-forecast?horizon_days=${horizonDays}&simulations=${simulations}`
    ).then((d) => PriceForecastSchema.parse(d)),
  getCompanyOptionsChain: (ticker: string, expiry?: string) => {
    const query = expiry ? `?expiry=${encodeURIComponent(expiry)}` : "";
    return request(`/api/companies/${ticker}/options-chain${query}`).then((d) =>
      OptionsChainSchema.parse(d)
    );
  },
  getCompanyIVSurfaceForecast: (ticker: string, expiry?: string) => {
    const query = expiry ? `?expiry=${encodeURIComponent(expiry)}` : "";
    return request(`/api/companies/${ticker}/iv-surface-forecast${query}`).then((d) =>
      IVSurfaceForecastSchema.parse(d)
    );
  },
  getCompanyPathDependentIVSurfaceForecast: (ticker: string, expiry?: string) => {
    const query = expiry ? `?expiry=${encodeURIComponent(expiry)}` : "";
    return request(
      `/api/companies/${ticker}/path-dependent-iv-surface-forecast${query}`
    ).then((d) => IVSurfaceForecastSchema.parse(d));
  },
  listCompanyPaperIVTrades: (ticker: string, portfolioId: string) =>
    request(
      `/api/companies/${ticker}/paper-iv-trades?portfolio_id=${encodeURIComponent(portfolioId)}`
    ).then((d) => z.array(PaperIVTradeSchema).parse(d)),
  listOptionPaperTrades: (portfolioId: string, includeClosed = true) =>
    request(
      `/api/trade-tracker/options?portfolio_id=${encodeURIComponent(portfolioId)}&include_closed=${includeClosed}`
    ).then((d) => z.array(PaperIVTradeSchema).parse(d)),
  getIVModelEvaluation: () =>
    request(`/api/iv-model-evaluation`).then((d) =>
      IVModelEvaluationSchema.parse(d)
    ),
  runIVModelEvaluation: (limit = 30) =>
    request<{
      scoring: { pending_checked: number; scored: number };
      collection: {
        attempted: number;
        created: number;
        skipped: number;
        errors: { ticker: string; reason: string }[];
        generated_at: string;
      };
    }>(`/api/iv-model-evaluation/run?limit=${limit}`, { method: "POST" }),
  createCompanyPaperIVTrade: (
    ticker: string,
    portfolioId: string,
    expiry: string,
    strategyId?: string,
    quantityLots = 1,
    modelFamily: "fpca_var" | "path_dependent_ssvi" = "fpca_var"
  ) =>
    request(`/api/companies/${ticker}/paper-iv-trades`, {
      method: "POST",
      body: JSON.stringify({
        portfolio_id: portfolioId,
        expiry,
        strategy_id: strategyId,
        quantity_lots: quantityLots,
        model_family: modelFamily,
      }),
    }).then((d) => PaperIVTradeSchema.parse(d)),
  closeCompanyPaperIVTrade: (
    ticker: string,
    portfolioId: string,
    tradeId: string
  ) =>
    request(`/api/companies/${ticker}/paper-iv-trades/${tradeId}/close`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId }),
    }).then((d) => PaperIVTradeSchema.parse(d)),
  getMarketPulse: () =>
    request(`/api/market/pulse`).then((d) =>
      MarketPulseSchema.parse(d)
    ),
  getBlockDeals: (days = 30) =>
    request(`/api/market/block-deals?days=${days}`).then((d) =>
      BlockDealsSchema.parse(d)
    ),
  getTechnicalStatus: () =>
    request<{
      market: string;
      universe: string;
      preferred_source: string;
      active_source: string;
      upstox_configured: boolean;
      yahoo_stream: {
        enabled: boolean;
        connected: boolean;
        connected_shards: number;
        total_shards: number;
        subscribed_symbols: number;
        base_symbols: number;
        dynamic_symbols: number;
        max_symbols: number;
        base_label: string;
        quotes_received: number;
        started_at: string | null;
        last_message_at: string | null;
        last_error: string | null;
      };
      default_interval: string;
      supported_intervals: string[];
      minimum_candles: number;
      maximum_candles: number;
      concurrency: number;
    }>(`/api/technical/status`),
  runTechnicalScan: (
    query: string,
    resultLimit = 20,
    candleInterval: "1m" | "5m" | "15m" | "30m" | "1h" | "1d" = "1m",
    candleCount = 70,
  ) =>
    request(`/api/technical/scan`, {
      method: "POST",
      body: JSON.stringify({
        query,
        result_limit: resultLimit,
        candle_interval: candleInterval,
        candle_count: candleCount,
      }),
    }).then((d) => TechnicalScanResponseSchema.parse(d)),
  getTradeSuggestions: (
    limit = 12,
    refresh = false,
    pValueThreshold = 0.001
  ) =>
    request(
      `/api/trade-suggestions?limit=${limit}&refresh=${refresh ? "true" : "false"}&p_value_threshold=${pValueThreshold}`
    ).then((d) => PairSuggestionsResponseSchema.parse(d)),
  getPairMethodLab: (limit = 24, refresh = false) =>
    request(
      `/api/trade-suggestions/method-lab?limit=${limit}&refresh=${refresh ? "true" : "false"}`
    ).then((d) => PairMethodLabResponseSchema.parse(d)),
  getCopulaPairSignals: (limit = 24, refresh = false) =>
    request(
      `/api/trade-suggestions/method-lab/copula-signals?limit=${limit}&refresh=${refresh ? "true" : "false"}`
    ).then((d) => CopulaPairSignalsResponseSchema.parse(d)),
  syncIntradayCopulaTracker: (portfolioId: string, candidateLimit = 12) =>
    request(`/api/trade-suggestions/method-lab/intraday-copula/sync`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId, candidate_limit: candidateLimit }),
    }).then((d) => IntradayCopulaTrackerResponseSchema.parse(d)),
  closeIntradayCopulaTrade: (portfolioId: string, tradeId: string) =>
    request(`/api/trade-suggestions/method-lab/intraday-copula/trades/${tradeId}/close`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId }),
    }).then((d) => IntradayCopulaTradeSchema.parse(d)),
  listPairMethodLabSpotTrades: (portfolioId: string) =>
    request(
      `/api/trade-suggestions/method-lab/paper-trades?portfolio_id=${encodeURIComponent(portfolioId)}`
    ).then((d) => z.array(PaperLabSpotTradeSchema).parse(d)),
  syncPairMethodLabSpotTrades: (portfolioId: string) =>
    request(`/api/trade-suggestions/method-lab/paper-trades/sync`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId }),
    }).then((d) => PaperLabSpotTradeSyncSchema.parse(d)),
  markPairMethodLabSpotTrades: (portfolioId: string) =>
    request(`/api/trade-suggestions/method-lab/paper-trades/mark`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId }),
    }).then((d) => z.array(PaperLabSpotTradeSchema).parse(d)),
  closePairMethodLabSpotTrade: (portfolioId: string, tradeId: string) =>
    request(`/api/trade-suggestions/method-lab/paper-trades/${tradeId}/close`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId }),
    }).then((d) => PaperLabSpotTradeSchema.parse(d)),
  listPaperPairTrades: (portfolioId: string) =>
    request(
      `/api/trade-suggestions/paper-trades?portfolio_id=${encodeURIComponent(portfolioId)}`
    ).then((d) => z.array(PaperPairTradeSchema).parse(d)),
  createPaperPairTrade: (
    portfolioId: string,
    pairId: string,
    pValueThreshold: number
  ) =>
    request(`/api/trade-suggestions/paper-trades`, {
      method: "POST",
      body: JSON.stringify({
        portfolio_id: portfolioId,
        pair_id: pairId,
        p_value_threshold: pValueThreshold,
      }),
    }).then((d) => PaperPairTradeSchema.parse(d)),
  closePaperPairTrade: (portfolioId: string, tradeId: string) =>
    request(`/api/trade-suggestions/paper-trades/${tradeId}/close`, {
      method: "POST",
      body: JSON.stringify({ portfolio_id: portfolioId }),
    }).then((d) => PaperPairTradeSchema.parse(d)),
  getCurrentPairPortfolio: (ownerPortfolioId: string, refresh = true) =>
    request(
      `/api/trade-suggestions/pair-portfolios/current?owner_portfolio_id=${encodeURIComponent(ownerPortfolioId)}&refresh=${refresh ? "true" : "false"}`
    ).then((d) => (d == null ? null : PaperPairPortfolioSchema.parse(d))),
  createPairPortfolio: (
    ownerPortfolioId: string,
    investmentAmountInr: number,
    pValueThreshold: number
  ) =>
    request(`/api/trade-suggestions/pair-portfolios`, {
      method: "POST",
      body: JSON.stringify({
        owner_portfolio_id: ownerPortfolioId,
        investment_amount_inr: investmentAmountInr,
        p_value_threshold: pValueThreshold,
      }),
    }).then((d) => PaperPairPortfolioSchema.parse(d)),
  refreshPairPortfolio: (ownerPortfolioId: string) =>
    request(`/api/trade-suggestions/pair-portfolios/current/refresh`, {
      method: "POST",
      body: JSON.stringify({ owner_portfolio_id: ownerPortfolioId }),
    }).then((d) => PaperPairPortfolioSchema.parse(d)),
  adminStatus: () => request<Record<string, unknown>>(`/api/admin/status`),
  materializationStatus: () =>
    request(`/api/admin/materialization-status`).then((d) =>
      MaterializationStatusSchema.parse(d)
    ),
  adminIngest: (ticker: string) =>
    request<{ job_id: string }>(`/api/admin/ingest/${ticker}`, { method: "POST" }),
  adminBootstrap: () =>
    request<{ job_id: string }>(`/api/admin/bootstrap`, { method: "POST" }),
};

export function technicalQuoteStreamUrl(tickers: string[]): string {
  const base = API_BASE.replace(/^http:/, "ws:").replace(/^https:/, "wss:").replace(/\/$/, "");
  const params = new URLSearchParams({ tickers: tickers.join(",") });
  return `${base}/api/technical/stream?${params.toString()}`;
}

export function streamSearch(
  id: string,
  onEvent: (event: ProgressEvent) => void,
  onDone: () => void
): () => void {
  const source = new EventSource(`${API_BASE}/api/search/${id}/stream`);
  source.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data) as ProgressEvent;
      onEvent(event);
      if (event.stage === "completed" || event.stage === "failed") {
        source.close();
        onDone();
      }
    } catch {
      // ignore malformed events
    }
  };
  source.onerror = () => {
    source.close();
    onDone();
  };
  return () => source.close();
}

export function formatMarketCap(
  v?: number | null,
  currency?: string | null,
  nativeValue?: number | null
): string {
  if (currency === "INR" && nativeValue != null) {
    const crore = nativeValue / 10_000_000;
    if (crore >= 100_000) return `₹${(crore / 100_000).toFixed(2)}L Cr`;
    return `₹${crore.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
  }
  if (v == null) return "n/a";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}
