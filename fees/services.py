"""Builds dependencies lazily, once per worker process."""

from functools import cached_property

from .config import Settings, load_settings
from .db import SqlServerDatabase
from .repository import FeeRepository


class Services:
    @cached_property
    def settings(self) -> Settings:
        return load_settings()

    @cached_property
    def _repository(self) -> FeeRepository:
        return FeeRepository(SqlServerDatabase(self.settings.sql_connection_string))

    def repository(self) -> FeeRepository:
        return self._repository


services = Services()
