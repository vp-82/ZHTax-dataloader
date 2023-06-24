"""
This module provides the ScraperService class, which is used to scrape text and PDF content from websites.

This service reads 'pending' links from a Firestore database, performs scraping tasks, and then updates the status
of the links to 'scraped' when finished. The service also uses multiprocessing to parallelize tasks and utilize 
multiple cores on the machine.
"""

import hashlib
import logging
import multiprocessing

import google.api_core.exceptions
import requests
from bs4 import BeautifulSoup, ParserRejectedMarkup
from google.cloud import firestore, storage


class ScraperService:
    """
    The ScraperService class is used to scrape text and PDF content from websites.

    This service reads 'pending' links from a Firestore database, performs scraping tasks, and then updates the status
    of the links to 'scraped' when finished. The service also uses multiprocessing to parallelize tasks and utilize 
    multiple cores on the machine.

    Attributes:
        collection_name (str): Name of the Firestore collection to read the links from.
        pdf_bucket_name (str): Name of the GCS bucket to store PDF files.
        gcp_bucket (str): Name of the GCS bucket to store text files.
        db (firestore.Client): Firestore client.
    """

    def __init__(self, collection_name, pdf_bucket_name, gcp_bucket):
        """
        Initialize ScraperService with Firestore collection name and GCS bucket names.
        """
        self.collection_name = collection_name
        self.pdf_bucket_name = pdf_bucket_name
        self.gcp_bucket = gcp_bucket
        self.db = firestore.Client()

    def scrape_pending_links(self, limit=None):
        """
        Scrape 'pending' links from Firestore and store the scraped content in GCS.

        Parameters:
        limit (int, optional): The maximum number of links to scrape.
        """
        # Retrieve 'pending' links from Firestore
        links = self._get_pending_links(limit)

        # Create a pool of processes
        with multiprocessing.Pool() as pool:
            # Map the scrape_link function to the list of links
            pool.map(self._scrape_link, links)

    def _get_pending_links(self, limit=None):
        """
        Retrieve 'pending' links from Firestore.

        Parameters:
        limit (int, optional): The maximum number of links to retrieve.

        Returns:
        list: A list of 'pending' links.
        """
        docs = self.db.collection(self.collection_name).where(u'status', u'==', u'pending').stream()
        links = [doc.to_dict()['url'] for doc in docs]
        return links[:limit]  # Limit the number of links

    def _scrape_link(self, url):
        """
        Scrape a link and store the scraped content in GCS.

        Parameters:
        url (str): The link to scrape.
        """
        logging.info(f"Visiting URL: {url}")

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if 'application/pdf' in content_type:
                try:
                    self._upload_pdf(response.content, url)  # Update this call if your _upload_pdf method has changed
                except google.api_core.exceptions.GoogleAPIError as err:
                    logging.error(f"Failed to upload PDF due to Google API error: {err}")
                except Exception as err: # pylint: disable=W0718
                    logging.error(f"Failed to upload PDF due to unexpected error: {err}")
            elif 'text' not in content_type and 'application/json' not in content_type:
                logging.info(f"Skipping URL due to non-text Content-Type: {content_type}")
            else:
                try:
                    soup = BeautifulSoup(response.text, 'html.parser')
                except (ParserRejectedMarkup, Exception) as e:  # pylint: disable=W0718
                    logging.error(f"Failed to parse HTML from URL: {url}. Error: {e}")
                else:
                    text_content = ""
                    for paragraph in soup.find_all('p'):
                        paragraph_text = paragraph.get_text()
                        if self._is_text_ascii(paragraph_text) and self._has_min_chars(paragraph_text, 1):
                            text_content += paragraph_text + '\n'

                    if self._has_min_chars(text_content, 1): # Check if overall text content has at least 50 characters
                        self._upload_text(text_content, url)

        except requests.HTTPError as err:
            logging.error(f"HTTP error occurred: {err}")
        except requests.exceptions.RequestException as err:
            logging.error(f"Request error occurred: {err}")

        # After successfully scraping a link, update its status to 'scraped'
        self._update_link_status(url, 'scraped')


    def _update_link_status(self, url, status):
        """
        Update the status of a link in Firestore.

        Parameters:
        url (str): The URL of the link.
        status (str): The new status.
        """
        doc_id = self._hash_url(url)
        doc_ref = self.db.collection(self.collection_name).document(doc_id)
        doc_ref.update({
            u'status': status
        })
        logging.info(f"Updated URL status in Firestore: {url} => {status}")

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

    def _hash_url(self, url):
        """
       Generate a unique ID for a URL by hashing it.

        Parameters:
        url (str): The URL to hash.

        Returns:
        str: The hashed URL.
        """
        return hashlib.md5(url.encode()).hexdigest()

    def _is_text_ascii(self, text):
        """
        Check if text is ASCII

        Parameters:
        text (str): The text to check.

        Returns:
        bool: True if text is ASCII, False otherwise.
        """
        return all(ord(character) < 128 for character in text)

    def _has_min_chars(self, text, min_chars):
        """
        Check if text has a minimum number of characters

        Parameters:
        text (str): The text to check.
        min_chars (int): The minimum number of characters.

        Returns:
        bool: True if text has the minimum number of characters, False otherwise.
        """
        return len(text) >= min_chars
    
    def reset_status(self, status='pending'):
        """
        Reset the status of all documents in Firestore back to a specified status.

        Parameters:
        status (str, optional): The status to reset to. Defaults to 'pending'.
        """
        docs = self.db.collection(self.collection_name).stream()

        for doc in docs:
            doc_ref = self.db.collection(self.collection_name).document(doc.id)
            doc_ref.update({
                u'status': status
            })
        logging.info(f"Reset status of all documents to '{status}'")
