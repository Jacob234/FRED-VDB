"""Shared pytest configuration."""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests that require the built LanceDB index and embedding model",
    )
