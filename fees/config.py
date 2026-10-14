"""Settings, read only from environment variables (never from code).

Locally: local.settings.json (git-ignored). In Azure: Function App settings
(or Key Vault references).
"""

import os
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError

AUTH_MODE_ENTRA = "entra"
AUTH_MODE_LOCAL_DEV = "local-dev"


@dataclass(frozen=True)
class Settings:
    sql_connection_string: str
    auth_mode: str
    tenant_id: str
    audiences: tuple[str, ...]
    fee_timezone: str

    def today(self) -> date:
        """'Today' in the institution's timezone, used for overdue checks."""
        return datetime.now(ZoneInfo(self.fee_timezone)).date()


def running_in_azure() -> bool:
    return bool(os.environ.get("WEBSITE_SITE_NAME"))


def load_settings() -> Settings:
    conn = os.environ.get("SqlConnectionString", "").strip()
    if not conn:
        raise ConfigurationError("App setting 'SqlConnectionString' is not configured.")

    mode = os.environ.get("AUTH_MODE", AUTH_MODE_ENTRA).strip().lower()
    if mode not in (AUTH_MODE_ENTRA, AUTH_MODE_LOCAL_DEV):
        raise ConfigurationError("AUTH_MODE must be 'entra' or 'local-dev'.")
    if mode == AUTH_MODE_LOCAL_DEV and running_in_azure():
        # Safety net: the header-based dev mode must never run in the cloud.
        raise ConfigurationError("AUTH_MODE=local-dev is not allowed when running in Azure.")

    tenant = os.environ.get("AUTH_TENANT_ID", "").strip()
    audiences = tuple(a.strip() for a in os.environ.get("AUTH_AUDIENCES", "").split(",") if a.strip())
    if mode == AUTH_MODE_ENTRA and (not tenant or not audiences):
        raise ConfigurationError("AUTH_TENANT_ID and AUTH_AUDIENCES are required when AUTH_MODE=entra.")

    tz = os.environ.get("FEE_TIMEZONE", "Asia/Kolkata").strip()
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"FEE_TIMEZONE '{tz}' is not a valid IANA timezone.") from exc

    return Settings(conn, mode, tenant, audiences, tz)
