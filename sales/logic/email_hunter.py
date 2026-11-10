import aiohttp
import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import random
import logging

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
]

class AsyncEmailHunter:
    def __init__(self, concurrency=10):
        self.concurrency = concurrency
        self.email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    async def fetch_url(self, session, url):
        if not url.startswith('http'):
            url = 'https://' + url
        
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        try:
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status == 200:
                    text = await response.text()
                    return text, url
        except Exception as e:
            # logger.error(f"Failed to fetch {url}: {e}")
            pass
        return None, url

    def extract_emails_from_html(self, html):
        emails = set()
        if not html: return list(emails)
        
        # Regex search
        found = re.findall(self.email_pattern, html)
        for email in found:
            # Basic filter (images)
            if not any(email.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                emails.add(email.lower())
        
        # Mailto links
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.select('a[href^="mailto:"]'):
                href = a.get('href')
                if href:
                    cleaned = href.replace('mailto:', '').split('?')[0]
                    if re.match(self.email_pattern, cleaned):
                        emails.add(cleaned.lower())
        except: pass
        
        return list(emails)

    async def process_batch(self, urls):
        """
        Process a list of URLs and return a dictionary {url: [emails]}
        """
        results = {}
        timeout = aiohttp.ClientTimeout(total=20)
        connector = aiohttp.TCPConnector(limit=self.concurrency)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = [self.fetch_url(session, u) for u in urls]
            responses = await asyncio.gather(*tasks)
            
            for html, url in responses:
                if html:
                    emails = self.extract_emails_from_html(html)
                    results[url] = emails
                else:
                    results[url] = []
        
        return results
