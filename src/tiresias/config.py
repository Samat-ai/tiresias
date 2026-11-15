from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_base_url: str = "http://localhost:8000"
    service_consent_version: str = "2026-11-14.v1"
    database_url: str = ""
    test_database_url: str = ""
    mongodb_uri: str = ""
    mongodb_database: str = "tiresias"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    agent_name: str = "tiresias-agent"
    gemini_api_key: str = ""
    gemini_model: str = ""
    elevenlabs_api_key: str = ""
    eleven_api_key: str = ""
    elevenlabs_stt_model: str = "scribe_v2_realtime"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    chert_project_id: str = ""
    chert_line_id: str = ""
    chert_api_key: str = ""
    chert_integration_mode: str = "cli"
    private_snapshot_dir: str = "./data/snapshots"
    phone_data_encryption_key: str = ""
    solana_rpc_url: str = "https://api.devnet.solana.com"
    solana_treasury_key_file: str = ""
    solana_reward_lamports: int = 50_000_000
    solana_helper_wallet: str = ""
    allow_registration: bool = False
    enable_browser_demo: bool = True
    enable_support_bot: bool = False
    enable_imessage: bool = False
    enable_billing: bool = False
    enable_rewards: bool = True
    frame_max_local_age_ms: int = 2000
    vision_timeout_seconds: int = 12
    visual_evidence_max_age_ms: int = 12000
    evidence_ttl_seconds: int = 1800
    grok_bot_webhook_url: str = ""
    grok_bot_webhook_bearer: str = ""
    session_secret: str = ""
    use_mock_providers: bool = False
    argon2_memory_kib: int = 65536
    argon2_time_cost: int = 3
    argon2_parallelism: int = 1
    max_vision_requests_per_call: int = 30
    reward_cap_per_call: int = 3

    def elevenlabs_key(self) -> str:
        return self.elevenlabs_api_key or self.eleven_api_key

    def assert_runtime_safe(self) -> None:
        if self.app_env == "production" and self.use_mock_providers:
            raise RuntimeError("production cannot silently use a mock provider")
        if self.solana_rpc_url and "devnet" not in self.solana_rpc_url and self.app_env != "production":
            raise RuntimeError("R0 rewards are hard-limited to Solana devnet")
        if "mainnet" in self.solana_rpc_url:
            raise RuntimeError("mainnet rewards are outside R0")
