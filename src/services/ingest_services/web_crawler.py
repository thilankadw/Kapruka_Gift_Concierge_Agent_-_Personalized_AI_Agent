
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from typing import List, Dict, Any, Set
import re
from loguru import logger
from urllib.parse import urljoin, urlparse
from collections import deque
import asyncio

class KaprukaWebCrawler: 
    """A web crawler specifically designed for crawling the Kapruka website.

    This class handles asynchronous web crawling, content extraction, and link discovery
    while respecting depth limits and exclusion patterns.
    """

    def __init__(self, base_url:str,max_depth: int, exclude_patterns:List[str]):
        """Initialize the KaprukaWebCrawler.

        Args:
            base_url (str): The base URL of the website to crawl.
            max_depth (int): Maximum depth to crawl from start URLs.
            exclude_patterns (List[str]): List of URL patterns to exclude from crawling.
        """
        self.base_url = base_url
        self.max_depth = max_depth
        self.exclude_patterns = exclude_patterns
        self.visited: Set[str] = set()
        self.documents: List[Dict[str, Any]] = []

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
    
    def extract_content(self, soup:BeautifulSoup, url:str) -> Dict[str, Any]:
        """Extract content from a BeautifulSoup object.

        Args:
            soup (BeautifulSoup): The parsed HTML content.
            url (str): The URL of the page.

        Returns:
            Dict[str, Any]: A dictionary containing extracted title, headings, content, and links.
        """

        for element in soup(["script", "style", "nav", "footer", "aside", "noscript", "iframe"]):
            element.decompose()

        title = soup.title.string if soup.title else url.split("/")[-1]
        title=title.strip() if title else "untitled"

        headings = [h.get_test(strip=True) for h in soup(['h1', 'h2', 'h3', 'h4'])]

        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if not href:
                continue

            if href.startswith('/'):
                href = self.base_url + href
            elif not href.startswith('http'):
                href = urljoin(url, href)

            if href.startswith(self.base_url):
                href = href.split('#')[0].split('?')[0]
                if href and href != url:
                    links.append(href)
        
        main_content = (
            soup.find('div') or 
            soup.find('main') or 
            soup.find('article') or
            soup.body
        )
        
        if main_content:
            content_md = md(str(main_content), heading_style="ATX")
        else:
            content_md = md(str(soup), heading_style="ATX")

        content_md = re.sub(r'You need to enable JavaScript.*?\.', '', content_md, flags=re.IGNORECASE)
        content_md = re.sub(r'\n{3,}', '\n\n', content_md)
        content_md = content_md.strip()
        
        return {
            "title": title,
            "headings": headings,
            "content": content_md,
            "links": list(set(links))
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
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(30000)

            while queue:
                url, depth = queue.popleft()

                if depth > self.max_depth or not self.should_crawl(url):
                    continue

                try: 
                    logger.info(f"🔍 [{depth}] {url}")
                    self.visited.add(url)

                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

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
                    doc_data['url'] = url
                    doc_data['depth_level'] = depth

                    if len(doc_data['content']) >= 100:
                        self.documents.append(doc_data)
                        logger.success(f"   ✅ Saved ({len(doc_data['content'])} chars, {len(doc_data['links'])} links found)")
                    else:
                        logger.warning(f"   ⚠️  Skipped (content too short: {len(doc_data['content'])} chars)")


                    if depth < self.max_depth:
                        links_added = 0
                        for link in doc_data['links']:
                            if link not in self.visited and link not in [item[0] for item in queue]:
                                queue.append((link, depth + 1))
                                links_added += 1
                        if links_added > 0:
                            logger.info(f"   📎 Added {links_added} new URLs to queue (depth {depth + 1})")
                    
                    logger.info(f"   📊 Progress: {len(self.documents)} docs saved, {len(self.visited)} visited, {len(queue)} in queue")
                    
                    await asyncio.sleep(request_delay)
                    
                except Exception as e:
                    error_msg = str(e)
                    if "404" in error_msg or "net::ERR_" in error_msg:
                        logger.warning(f"   ⚠️  Page not found (404) - skipping")
                    else:
                        logger.error(f"   ❌ Error: {error_msg[:100]}")
                    continue
            
            await browser.close()
        
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