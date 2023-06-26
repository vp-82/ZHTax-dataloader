"""
This module provides the WebsiteScraper class for scraping websites and storing
the content into Google Cloud Storage.

The WebsiteScraper class takes a start URL and a maximum number of pages to scrape,
and then it visits each page linked from the start page, up to the maximum number
of pages. It supports scraping of webpages and PDF files, and it skips over URLs
that have been visited or contain a '#' character.

When a page is visited, its content is stored into Google Cloud Storage. If the
content is a webpage, it is parsed and the text content is stored. If it is a PDF
file, the file is uploaded as is.

The class is intended to be used in a script or program like this:

    if __name__ == "__main__":
        scraper = WebsiteScraper(start_url='https://www.lu.ch/finanzen', 
                                 max_pages=10000, 
                                 gcp_bucket='lu-scraper-data', 
                                 pdf_bucket_name='lu-scraper-data-pdf')
        scraper.scrape_website()

This script will scrape the website at 'https://www.lu.ch/finanzen', visiting up
to 10000 pages, and store the scraped data into the specified Google Cloud Storage
buckets.

The module requires the following packages: logging, sys, requests, BeautifulSoup
from bs4, and storage from google.cloud.

Author: Your Name
Date: YYYY-MM-DD
"""

import logging
import sys
from urllib.parse import urljoin

import google.api_core.exceptions
import requests
from bs4 import BeautifulSoup, ParserRejectedMarkup
from google.cloud import storage

logging.basicConfig(stream=sys.stdout, level=logging.INFO)


class WebScraper:
    """Class for scraping a website and storing the pages as text in Google Cloud Storage."""

    def __init__(self, start_url, base_url, gcp_bucket, pdf_bucket_name, max_pages):
        """
        Initialize a WebScraper.

        :param start_url: The URL where the scraper should start.
        :param base_url: The base domain the scraper is restricted to.
        :param gcp_bucket: The name of the Google Cloud Storage bucket for storing scraped pages.
        :param pdf_bucket_name: The name of the Google Cloud Storage bucket for storing scraped PDFs.
        :param max_pages: The maximum number of pages to scrape.
        """
        self.start_url = start_url
        self.base_url = base_url
        self.gcp_bucket = gcp_bucket
        self.pdf_bucket_name = pdf_bucket_name
        self.max_pages = max_pages

    def scrape_website(self):
        """Start the scraping process."""

        visited = set()
        queue = [self.start_url]
        pages_scraped = 0

        while queue and pages_scraped < self.max_pages:  # Stop scraping if max_pages is reached
            url = queue.pop(0)
            logging.info(f"Visiting URL: {url}")

            if url in visited or "#" in url:  # Skip if URL is already visited or if it contains #
                logging.info(f"URL already visited or contains #: {url}")
                continue

            visited.add(url)

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '')
                if 'application/pdf' in content_type:
                    try:
                        self._upload_pdf(response.content, url)
                    except google.api_core.exceptions.GoogleAPIError as err:
                        logging.error(f"Failed to upload PDF due to Google API error: {err}")
                        continue
                    except Exception as err: # pylint: disable=W0718
                        logging.error(f"Failed to upload PDF due to unexpected error: {err}")
                        continue
                elif 'text' not in content_type and 'application/json' not in content_type:
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


            # Initialize a string to store the plain text content of the webpage
            text_content = ""

            for paragraph in soup.find_all('p'):
                text_content += paragraph.get_text() + '\n'

            for anchor_tag in soup.find_all('a', href=True):
                link = urljoin(url, anchor_tag['href'])
                # Only follow links within the same domain
                # Also skip if it's a PDF link or contains #
                if link.startswith(self.base_url) and not link.endswith('.pdf') and "#" not in link:
                    # Only add link to queue if max_pages is not reached
                    if link not in visited and pages_scraped < self.max_pages:
                        queue.append(link)
                        logging.info(f"Added URL to queue: {link}")

            # Store the plain text content in Google Cloud Storage
            self._upload_text(text_content, url)


            pages_scraped += 1
            logging.info(f'Scraped {url}, total pages scraped: {pages_scraped}')
            logging.info(f"Number of URLs in queue: {len(queue)}")
            logging.info(f"Number of URLs visited: {len(visited)}")

    def _upload_pdf(self, content, url):
        """
        Upload a PDF file to Google Cloud Storage.

        Args:
            content (bytes): The content of the PDF file.
            url (str): The URL of the PDF file.
        """
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.pdf_bucket_name)
        blob_name = self._clean_url(url) + ".pdf"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(content)
        logging.info(f"PDF uploaded to GCS: {blob_name}")

    def _clean_url(self, url):
        """
        Sanitize a URL to be used as a blob name.

        Args:
            url (str): The URL to be sanitized.

        Returns:
            str: The sanitized URL.
        """
        return url.replace("http://", "").replace("https://", "").replace("/", "__")



    def _upload_text(self, text_content, url):
        """Upload the scraped page content as a text file to Google Cloud Storage.

        :param text_content: The content of the page.
        :param url: The URL of the page.
        """
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.gcp_bucket)
        url_clean = url.replace("http://", "").replace("https://", "").replace("/", "__")
        blob_name = f'{url_clean}.txt'
        blob = bucket.blob(blob_name)
        blob.upload_from_string(text_content)


if __name__ == "__main__":
    web_scraper = WebScraper(
        start_url='https://www.lu.ch',
        base_url='https://www.lu.ch',
        gcp_bucket='lu-scraper-diin-data',
        pdf_bucket_name='lu-scraper-diin-data-pdf',
        max_pages=1000000
    )
    web_scraper.scrape_website()
