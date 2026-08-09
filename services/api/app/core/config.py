from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/equity_research"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embed_model: str = "qwen3-embedding:0.6b"
    embed_dim: int = 1024

    # Chat provider: "ollama" (default, fully local) or "nvidia" (free
    # OpenAI-compatible hosted endpoint; embeddings always stay on Ollama).
    llm_provider: str = "ollama"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-3.3-70b-instruct"

    # Current-news retrieval for follow-up deep research. The semantic stock-search
    # pipeline does not use this service.
    tavily_base_url: str = "https://api.tavily.com"
    tavily_api_key: str = ""
    deep_research_lookback_days: int = 90
    deep_research_max_news_queries: int = 3
    deep_research_max_news_results: int = 5
    deep_research_max_companies: int = 3
    deep_research_deadline_seconds: int = 120
    market_pulse_lookback_days: int = 7
    market_pulse_max_articles: int = 8
    market_pulse_cache_ttl_seconds: int = 60 * 60

    sec_user_agent: str = "EquityResearchPrototype developer@example.com"
    sec_max_rps: float = 8.0
    nse_max_rps: float = 2.0

    # Read-only intraday market data for the NSE technical scanner. Yahoo's
    # WebSocket is the credential-free development default; Upstox remains an
    # optional licensed/broker-backed replacement when a token is present.
    upstox_base_url: str = "https://api.upstox.com/v3"
    upstox_access_token: str = ""
    technical_scan_concurrency: int = 10
    technical_scan_max_rps: float = 40.0
    technical_scan_candles: int = 70
    technical_scan_cache_ttl_seconds: int = 60
    technical_scan_deadline_seconds: int = 45
    technical_option_scan_limit: int = 60
    technical_option_deadline_seconds: int = 90
    yahoo_live_stream_enabled: bool = True
    yahoo_live_max_symbols: int = 500

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cache_dir: str = "data/cache"
    filings_dir: str = "data/filings"
    log_level: str = "INFO"
    app_environment: str = "development"

    # Hard limits for bounded research workers (spec §8)
    worker_deadline_seconds: int = 25
    worker_max_filing_downloads: int = 4
    worker_max_model_calls: int = 3
    worker_max_chunks_per_call: int = 12

    prompt_version: str = "v1"

    @property
    def cache_path(self) -> Path:
        p = REPO_ROOT / self.cache_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def filings_path(self) -> Path:
        p = REPO_ROOT / self.filings_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
