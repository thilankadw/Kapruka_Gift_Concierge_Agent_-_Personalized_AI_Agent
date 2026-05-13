"""Services module for the Kapruka agent.

This module contains various services including data ingestion services.
"""

from .ingest_services import KaprukaWebCrawler

__all__ = ['KaprukaWebCrawler']