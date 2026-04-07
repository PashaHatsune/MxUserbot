from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=f'{Path(__file__).parents[2]}/.env',
        env_file_encoding='utf-8',
        extra='ignore'
    )


class MatrixConfig(BaseConfig):
    model_config = SettingsConfigDict(
        env_prefix='mtx_'
    )

    owner: str
    password: SecretStr
    base_url: str
    device_id: str = Field('org.vranki.hemppa')


class Config(BaseConfig):
    matrix_config: MatrixConfig = Field(
        default_factory=MatrixConfig
    )

    @classmethod
    def load(cls):
        return cls()


config = Config.load()