"""
This module contains classes for scraping a website and storing the scraped links in Firestore.
"""
import hashlib
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, ParserRejectedMarkup
from google.cloud import firestore


class LinkCollector:
    """
    Class for collecting links from a website and storing them in Firestore.

    Attributes:
        start_url (str): URL to start the scraping from.
        base_url (str): Base URL used to resolve relative links.
        max_pages (int): Maximum number of pages to scrape.
        collection_name (str): Name of the Firestore collection to store the links in.
        db (firestore.Client): Firestore client.
    """
    def __init__(self, start_url, base_url, max_pages, collection_name):
        """
        Initialize LinkCollector with the start URL, base URL, maximum number of pages to scrape,
        and Firestore collection name.
        """
        self.start_url = start_url
        self.base_url = base_url
        self.max_pages = max_pages
        self.collection_name = collection_name
        self.db = firestore.Client()

    def collect_links(self):
        """
        Collect links from the website and store them in Firestore.
        """
        visited = set()
        queue = [self.start_url]
        pages_scraped = 0

        while queue and pages_scraped < self.max_pages:
            url = queue.pop(0)
            logging.info(f"Visiting URL: {url}")

            if url in visited or "#" in url:
                logging.info(f"URL already visited or contains #: {url}")
                continue

            visited.add(url)

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '')

                if 'text' not in content_type and 'application/json' not in content_type:
                    logging.info(f"Skipping URL due to non-text Content-Type: {content_type}")
                    continue
            except requests.HTTPError as err:
                logging.error(f"HTTP error occurred: {err}")
                continue
            except requests.exceptions.RequestException as err:
                logging.error(f"Request error occurred: {err}")
                continue

            try:
                soup = BeautifulSoup(response.text, 'html.parser')
            except (ParserRejectedMarkup, Exception) as e: # pylint: disable=W0718
                logging.error(f"Failed to parse HTML from URL: {url}. Error: {e}")
                continue

            for anchor_tag in soup.find_all('a', href=True):
                link = urljoin(url, anchor_tag['href'])
                if link.startswith(self.base_url) and not link.endswith('.pdf') and "#" not in link:
                    if link not in visited and pages_scraped < self.max_pages:
                        queue.append(link)
                        logging.info(f"Added URL to queue: {link}")

            self._store_link(url)

            pages_scraped += 1
            logging.info(f'Scraped {url}, total pages scraped: {pages_scraped}')
            logging.info(f"Number of URLs in queue: {len(queue)}")
            logging.info(f"Number of URLs visited: {len(visited)}")

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
        logging.info(f"Stored URL in Firestore: {url}")
