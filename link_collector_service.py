"""
This module contains classes for scraping a website and storing the scraped links in Firestore.
"""
import hashlib
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, ParserRejectedMarkup
from google.cloud import firestore

logger = logging.getLogger(__name__)


class LinkCollectorService:
    """
    Class for collecting links from a website and storing them in Firestore.

    Attributes:
        start_url (str): URL to start the scraping from.
        base_url (str): Base URL used to resolve relative links.
        max_pages (int): Maximum number of pages to scrape.
        collection_name (str): Name of the Firestore collection to store the links in.
        db (firestore.Client): Firestore client.
    """
    def __init__(self, run_id,collection_name):
        """
        Initialize LinkCollector with the start URL, base URL, maximum number of pages to scrape,
        and Firestore collection name.
        """
        self.run_id = run_id
        self.collection_name = collection_name
        self.db = firestore.Client()

    def run(self, start_url, base_url, max_pages=1000000):
        """
        Collect links from the website and store them in Firestore.
        """
        logger.info(f"Starting collecting links. Run ID: {self.run_id}")
        visited = set()
        queue = [start_url]
        pages_scraped = 0

        while queue and pages_scraped < max_pages:
            url = queue.pop(0)
            logger.info(f"Visiting URL: {url}")

            if url in visited or "#" in url:
                logger.info(f"URL already visited or contains #: {url}")
                continue

            visited.add(url)

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '')

                # Check for content types
                is_not_text = 'text' not in content_type
                is_not_json = 'application/json' not in content_type
                is_not_pdf = 'application/pdf' not in content_type

                # If none of the content types are found, log a message and continue
                if is_not_text and is_not_json and is_not_pdf:
                    logger.info(f"Skipping URL due to non-text/non-PDF Content-Type: {content_type}")
                    continue

            except requests.HTTPError as err:
                logger.error(f"HTTP error occurred: {err}")
                continue
            except requests.exceptions.RequestException as err:
                logger.error(f"Request error occurred: {err}")
                continue

            try:
                soup = BeautifulSoup(response.text, 'html.parser')
            except (ParserRejectedMarkup, Exception) as e: # pylint: disable=W0718
                logger.error(f"Failed to parse HTML from URL: {url}. Error: {e}")
                continue

            for anchor_tag in soup.find_all('a', href=True):
                link = urljoin(url, anchor_tag['href'])
                if link.startswith(base_url) and "#" not in link:
                    if link not in visited and pages_scraped < max_pages:
                        queue.append(link)
                        logger.info(f"Added URL to queue: {link}")


            self._store_link(url)

            pages_scraped += 1
            logger.info(f'Scraped {url}, total pages scraped: {pages_scraped}')
            logger.info(f"Number of URLs in queue: {len(queue)}")
            logger.info(f"Number of URLs visited: {len(visited)}")

    def _hash_url(self, url):
        """
        Helper method to hash a URL and create a unique string ID.

        Parameters:
        url (str): The URL to hash.

        Returns:
        str: The hashed URL.
        """
        return hashlib.md5(url.encode()).hexdigest()

    def _store_link(self, url):
        """
        Store a URL in Firestore with a status of 'pending' and a timestamp of the current server time.
        
        The URL is hashed to create a unique string ID, which is used as the document name in Firestore.
        
        Parameters:
        url (str): The URL to store.
        """
        doc_id = self._hash_url(url)
        doc_ref = self.db.collection(self.collection_name).document(doc_id)
        doc_ref.set({
            u'url': url,
            u'status': u'pending',
            u'timestamp': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Stored URL in Firestore: {url}")
