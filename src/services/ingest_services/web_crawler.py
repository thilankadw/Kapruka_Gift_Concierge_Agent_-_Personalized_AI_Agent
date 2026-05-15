
from playwright.async_api import async_playwright, Error as PlaywrightError
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from typing import List, Dict, Any, Optional, Set
import re
from loguru import logger
from urllib.parse import urljoin, urlparse
from collections import deque
import asyncio
from infrastructure.config import CRAWL_MAX_PAGES, CRAWL_MAX_SAVED_DOCS

class KaprukaWebCrawler: 
    """A web crawler specifically designed for crawling the Kapruka website.

    This class handles asynchronous web crawling, content extraction, and link discovery
    while respecting depth limits and exclusion patterns.
    """

    def __init__(
        self,
        base_url: str,
        max_depth: int,
        exclude_patterns: List[str],
        max_saved_docs: Optional[int] = None,
        max_pages: Optional[int] = None,
    ):
        """Initialize the KaprukaWebCrawler.

        Args:
            base_url (str): The base URL of the website to crawl.
            max_depth (int): Maximum depth to crawl from start URLs.
            exclude_patterns (List[str]): List of URL patterns to exclude from crawling.
            max_saved_docs (Optional[int]): Maximum number of product documents to save
                before stopping the crawl. Defaults to the configured limit.
            max_pages (Optional[int]): Maximum number of pages to visit before stopping
                the crawl. Defaults to the configured limit.
        """
        self.base_url = base_url
        self.max_depth = max_depth
        self.exclude_patterns = exclude_patterns
        self.max_saved_docs = max_saved_docs if max_saved_docs is not None else CRAWL_MAX_SAVED_DOCS
        self.max_pages = max_pages if max_pages is not None else CRAWL_MAX_PAGES
        self.visited: Set[str] = set()
        self.documents: List[Dict[str, Any]] = []

    def is_product_url(self, url: str) -> bool:
        """Return True when a URL looks like a Kapruka product detail page."""
        return "/buyonline/" in urlparse(url).path.lower()

    def prioritize_links(self, links: List[str]) -> List[str]:
        """Keep discovery order stable while prioritizing product detail links."""
        unique_links = list(dict.fromkeys(links))
        product_links = [link for link in unique_links if self.is_product_url(link)]
        other_links = [link for link in unique_links if not self.is_product_url(link)]
        return product_links + other_links

    def _extract_label_values(self, soup: BeautifulSoup, selector: str) -> List[str]:
        """Extract normalized text values from label/button-like option containers."""
        values = []
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if text:
                values.append(text)
        return list(dict.fromkeys(values))

    def should_crawl(self, url:str) -> bool:
        """Check if a URL should be crawled based on various criteria.

        Args:
            url (str): The URL to check.

        Returns:
            bool: True if the URL should be crawled, False otherwise.
        """
        if url in self.visited:
            return False
        
        if not url.startswith(self.base_url):
            return False
        
        for pattern in self.exclude_patterns:
            if pattern in url:
                return False
            
        if re.search(r'\.(jpg|jpeg|png|gif|pdf|zip|exe)$', url, re.I):
            return False
        
        return True
    
    def extract_content(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href:
                continue

            href = urljoin(url, href)
            href = href.split("#")[0].split("?")[0]

            if href.startswith(self.base_url) and href != url:
                links.append(href)

        product_name_el = soup.select_one("div.blockDelivery.imgtags h1")
        price_el = (
            soup.select_one("span#pricelbl")
            or soup.select_one("span#priceLbl")
            or soup.select_one("div.price span")
        )
        description_el = (
            soup.select_one("div#Tab1 div.detailDescription")
            or soup.select_one("div#Tab1")
        )
        tag_elements = soup.select("div.tagArea span.tags")
        partner_el = soup.select_one("span.mediumbold a")
        product_id_el = soup.select_one('input[name="id"]')
        product_type_el = soup.select_one('input[name="type"]')
        quantity_el = soup.select_one('input[name="quantity"]')
        customized_text_el = soup.select_one("input#customized_text")

        color_options = self._extract_label_values(soup, "#colorContainer label")
        size_options = self._extract_label_values(soup, "#sizeContainer label")
        option_values = self._extract_label_values(soup, "#optionsContainer label")

        product_name = product_name_el.get_text(" ", strip=True) if product_name_el else None
        price = price_el.get_text(" ", strip=True) if price_el else None
        description = description_el.get_text(" ", strip=True) if description_el else None
        partner = partner_el.get_text(" ", strip=True) if partner_el else None

        tags = [
            tag.get_text(" ", strip=True)
            for tag in tag_elements
            if tag.get_text(" ", strip=True)
        ]

        availability = None
        delivery_info = []

        for tag in tags:
            tag_lower = tag.lower()
            if "in stock" in tag_lower or "out of stock" in tag_lower:
                availability = tag
            elif "delivery" in tag_lower:
                delivery_info.append(tag)

        product_id = product_id_el.get("value") if product_id_el else None
        product_type = product_type_el.get("value") if product_type_el else None
        quantity = quantity_el.get("value") if quantity_el else None
        supports_custom_text = customized_text_el is not None
        custom_text_max_length = customized_text_el.get("maxlength") if customized_text_el else None
        custom_text_placeholder = customized_text_el.get("placeholder") if customized_text_el else None

        content_parts = [
            f"Product Name: {product_name}" if product_name else "",
            f"Partner: {partner}" if partner else "",
            f"Price: {price}" if price else "",
            f"Availability: {availability}" if availability else "",
            f"Delivery Info: {', '.join(delivery_info)}" if delivery_info else "",
            f"Colors: {', '.join(color_options)}" if color_options else "",
            f"Sizes: {', '.join(size_options)}" if size_options else "",
            f"Options: {', '.join(option_values)}" if option_values else "",
            f"Custom Text Supported: {supports_custom_text}" if supports_custom_text else "",
            f"Description: {description}" if description else "",
        ]

        content = "\n".join(part for part in content_parts if part).strip()

        return {
            "title": product_name or soup.title.get_text(strip=True) if soup.title else url,
            "product_name": product_name,
            "partner": partner,
            "price": price,
            "availability": availability,
            "delivery_info": delivery_info,
            "tags": tags,
            "description": description,
            "product_id": product_id,
            "product_type": product_type,
            "quantity": quantity,
            "color_options": color_options,
            "size_options": size_options,
            "option_values": option_values,
            "supports_custom_text": supports_custom_text,
            "custom_text_max_length": custom_text_max_length,
            "custom_text_placeholder": custom_text_placeholder,
            "url": url,
            "content": content,
            "links": list(set(links)),
        }
    
    async def crawl_async(self, start_urls: List[str], request_delay: float = 2.0) -> List[Dict[str, Any]]:
        """Asynchronously crawl the website starting from given URLs.

        Args:
            start_urls (List[str]): List of URLs to start crawling from.
            request_delay (float): Delay in seconds between requests. Defaults to 2.0.

        Returns:
            List[Dict[str, Any]]: List of crawled documents.
        """

        queue = deque([(url, 0) for url in start_urls])

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except PlaywrightError as exc:
                error_msg = str(exc)
                if "Executable doesn't exist" in error_msg or "playwright install" in error_msg:
                    raise RuntimeError(
                        "Playwright is installed, but the Chromium browser binary is missing. "
                        "Install it with `python -m playwright install chromium` and retry."
                    ) from exc
                raise
            

            while (
                queue
                and len(self.documents) < self.max_saved_docs
                and len(self.visited) < self.max_pages
            ):
                page = await browser.new_page()
                page.set_default_timeout(30000)

                url, depth = queue.popleft()

                try:
                    if depth > self.max_depth or not self.should_crawl(url):
                        continue
                    logger.info(f"🔍 [{depth}] {url}")
                    self.visited.add(url)

                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    # await page.wait_for_load_state("networkidle")

                    try:
                        await page.wait_for_selector("body", timeout=10000)
                        await page.wait_for_timeout(3000)  

                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(1000)
                    except:
                        await page.wait_for_timeout(5000)

                    html = await page.content()
                    soup = BeautifulSoup(html, 'html.parser')

                    doc_data = self.extract_content(soup, url)

                    if doc_data.get("product_name") and doc_data.get("price"):
                        doc_data["url"] = url
                        doc_data["depth_level"] = depth
                        self.documents.append(doc_data)
                        if len(self.documents) >= self.max_saved_docs:
                            logger.info(
                                f"   Reached saved document limit ({self.max_saved_docs}); stopping crawl"
                            )
                        logger.success(
                            f"✅ Product saved: {doc_data['product_name']} | {doc_data['price']}"
                        )
                    else:
                        logger.warning("⚠️ Skipped non-product page")
                    # if len(doc_data['content']) >= 10:
                    #     self.documents.append(doc_data)
                    #     logger.success(f"   ✅ Saved ({len(doc_data['content'])} chars, {len(doc_data['links'])} links found)")
                    # else:
                    #     logger.warning(f"   ⚠️  Skipped (content too short: {len(doc_data['content'])} chars)")


                    if depth < self.max_depth and len(self.documents) < self.max_saved_docs:
                        links_added = 0
                        queued_urls = {item[0] for item in queue}
                        for link in self.prioritize_links(doc_data["links"]):
                            if link not in self.visited and link not in queued_urls:
                                if self.is_product_url(link):
                                    queue.appendleft((link, depth + 1))
                                else:
                                    queue.append((link, depth + 1))
                                queued_urls.add(link)
                                links_added += 1
                        if links_added > 0:
                            logger.info(f"   📎 Added {links_added} new URLs to queue (depth {depth + 1})")
                    
                    logger.info(f"   📊 Progress: {len(self.documents)} docs saved, {len(self.visited)} visited, {len(queue)} in queue")
                    
                    if len(self.documents) >= self.max_saved_docs:
                        break

                    await asyncio.sleep(request_delay)
                    
                except Exception as e:
                    error_msg = str(e)
                    if "404" in error_msg or "net::ERR_" in error_msg:
                        logger.warning(f"   ⚠️  Page not found (404) - skipping")
                    else:
                        logger.error(f"   ❌ Error: {error_msg[:100]}")
                    continue

                finally:
                    await page.close()
            
            await browser.close()

            if len(self.visited) >= self.max_pages and len(self.documents) < self.max_saved_docs:
                logger.info(f"   Reached page visit limit ({self.max_pages}); stopping crawl")
        
        return self.documents
    
    def crawl(self, start_urls: List[str], request_delay: float = 2.0) -> List[Dict[str, Any]]:
        """Synchronous wrapper for the asynchronous crawl method.

        Args:
            start_urls (List[str]): List of seed URLs to start crawling from.
            request_delay (float): Delay in seconds between requests. Defaults to 2.0.

        Returns:
            List[Dict[str, Any]]: List of crawled documents.
        """
        return asyncio.run(self.crawl_async(start_urls, request_delay))


__all__ = ['KaprukaWebCrawler']
