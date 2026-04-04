"""Federal Reserve statement watcher for APEX Trading System."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import aiohttp


class CBWatcher:
    """Watches central bank (Fed) RSS feeds and detects policy surprises."""

    _FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"

    def __init__(self) -> None:
        """Initialise the CBWatcher."""

    async def fetch_fed_rss(self) -> list[dict[str, Any]]:
        """Fetch and parse the Federal Reserve press release RSS feed.

        Returns:
            List of dicts with keys "title", "link", and "published".
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self._FED_RSS_URL, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                text = await resp.text()

        root = ET.fromstring(text)  # noqa: S314  # Fed RSS feed is trusted source
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items: list[dict[str, Any]] = []

        # Try RSS 2.0 format first
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                items.append(
                    {
                        "title": title_el.text if title_el is not None else "",
                        "link": link_el.text if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                    }
                )
        else:
            # Atom format
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                pub_el = entry.find("atom:published", ns)
                items.append(
                    {
                        "title": title_el.text if title_el is not None else "",
                        "link": link_el.get("href", "") if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                    }
                )

        return items

    async def detect_surprise(self, statement: str) -> str | None:
        """Detect policy surprises from Fed statement text using keyword analysis.

        Args:
            statement: Full text of the Fed statement.

        Returns:
            "hawkish_surprise" if hawkish keywords found, "dovish_surprise" if
            dovish keywords found, or None if no surprise detected.
        """
        lower = statement.lower()
        is_surprise = any(kw in lower for kw in ("unexpected", "emergency", "surprise"))
        if not is_surprise:
            return None

        hawkish_keywords = ("raise", "hike", "tighten", "inflation concern")
        dovish_keywords = ("cut", "ease", "lower", "stimulus", "support")

        hawkish_score = sum(1 for kw in hawkish_keywords if kw in lower)
        dovish_score = sum(1 for kw in dovish_keywords if kw in lower)

        if hawkish_score > dovish_score:
            return "hawkish_surprise"
        if dovish_score > hawkish_score:
            return "dovish_surprise"
        return None

    async def get_latest_statement(self) -> str | None:
        """Return the latest Fed statement text.

        Returns:
            Statement text string, or None (Phase 2 will scrape actual content).
        """
        # TODO Phase 2: Scrape actual statement content from Fed website
        return None
