"""全局配置：密钥与敏感信息只从环境变量读取，不硬编码（AGENTS.md §4.1）。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # 视觉模型（WF-INPUT-PREP 不用；WF-REPORT-GEN Step 1 用，选型见 D-066）
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k3"

    # 文本生成主力（architecture.md §五）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 存储
    data_dir: str = "./state"  # 原始照片/定稿图/参数 JSON 落盘根目录


settings = Settings()
