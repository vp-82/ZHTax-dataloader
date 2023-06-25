"""
This module provides the ScraperService class, which is used to scrape text and PDF content from websites.

This service reads 'pending' links from a Firestore database, performs scraping tasks, and then updates the status
of the links to 'scraped' when finished. The service also uses multiprocessing to parallelize tasks and utilize 
multiple cores on the machine.
"""

import hashlib
import logging

import chardet
import requests
from bs4 import BeautifulSoup
from google.cloud import bigquery, firestore, storage


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

    def __init__(self, collection_name, pdf_bucket_name, gcp_bucket, dataset_id, table_id):
        """
        Initialize ScraperService with Firestore collection name and GCS bucket names.
        """
        logging.info("Initializing ScraperService...")
        self.collection_name = collection_name
        self.pdf_bucket_name = pdf_bucket_name
        self.gcp_bucket = gcp_bucket
        logging.info(f"Firestore collection name: {self.collection_name}")
        logging.info(f"PDF bucket name: {self.pdf_bucket_name}")
        logging.info(f"GCP bucket: {self.gcp_bucket}")

        self.db = firestore.Client()
        logging.info("Firestore client initialized.")

        self.bq_client = bigquery.Client()
        logging.info("BigQuery client initialized.")

        self.dataset_id = dataset_id
        self.table_id = table_id
        logging.info(f"Dataset ID: {self.dataset_id}")
        logging.info(f"Table ID: {self.table_id}")

        self._create_bigquery_table_if_not_exists()
        logging.info("ScraperService initialized.")


    def scrape_pending_links(self, limit=None):
        """
        Scrape 'pending' links from Firestore and store the scraped content in GCS.

        Parameters:
        limit (int, optional): The maximum number of links to scrape.
        """
        logging.info("Starting to scrape pending links...")
        # Retrieve 'pending' links from Firestore
        links = self._get_pending_links(limit)
        logging.info(f"Retrieved {len(links)} pending links.")

        # Loop over the list of links
        for link in links:
            # Call the _scrape_link function for each link
            self._scrape_link(link)
        logging.info("Finished scraping pending links.")

    def _get_pending_links(self, limit=None):
        """
        Retrieve 'pending' links from Firestore.

        Parameters:
        limit (int, optional): The maximum number of links to retrieve.

        Returns:
        list: A list of 'pending' links.
        """
        logging.info("Retrieving pending links...")
        docs = self.db.collection(self.collection_name).where(u'status', u'==', u'pending').stream()
        links = [doc.to_dict()['url'] for doc in docs]
        logging.info(f"Retrieved {len(links)} pending links.")
        return links[:limit]  # Limit the number of links

    def _scrape_link(self, url):
        logging.info(f"Starting to scrape URL: {url}")
        reason_skipped = None
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if 'application/pdf' in content_type:
                try:
                    self._upload_pdf(response.content, url)
                except Exception as err: # pylint: disable=W0718
                    logging.error(f"Failed to upload PDF: {err}")
                    reason_skipped = f"Failed to upload PDF: {err}"
            elif 'text' in content_type or 'application/json' in content_type:
                soup = BeautifulSoup(response.text, 'html.parser')
                text_content = ""
                char_count = 0
                is_text = True  # Assume ASCII until proven otherwise
                for paragraph in soup.find_all('p'):
                    paragraph_text = paragraph.get_text()
                    char_count += len(paragraph_text)
                    if not self._is_text(paragraph_text):
                        is_text = False
                    if self._is_text(paragraph_text) and self._has_min_chars(paragraph_text, 1):
                        text_content += paragraph_text + '\n'
                if self._has_min_chars(text_content, 1):
                    self._upload_text(text_content, url)
                else:
                    reason_skipped = "No paragraph with sufficient characters."
            else:
                logging.info(f"Skipping URL due to non-text Content-Type: {content_type}")
                reason_skipped = f"Skipping URL due to non-text Content-Type: {content_type}"
        except requests.HTTPError as err:
            logging.error(f"HTTP error occurred: {err}")
            reason_skipped = f"HTTP error occurred: {err}"
        except requests.exceptions.RequestException as err:
            logging.error(f"Request error occurred: {err}")
            reason_skipped = f"Request error occurred: {err}"

        self._update_link_status(url, 'scraped', is_text, reason_skipped, char_count)
        self._insert_into_bigquery(url, is_text, char_count, reason_skipped)


    def _update_link_status(self, url, status, non_ascii, skipped_reason, num_characters):
        """
        Update the status of a link in Firestore.

        Parameters:
        url (str): The URL of the link.
        status (str): The new status.
        non_ascii (bool): Whether the content at the URL contains non-ASCII characters.
        skipped_reason (str): The reason the URL was skipped, if applicable.
        num_characters (int): The number of characters in the content at the URL.
        """

        doc_id = self._hash_url(url)
        doc_ref = self.db.collection(self.collection_name).document(doc_id)  # Use the locally initialized client
        doc_ref.update({
            u'status': status,
            u'non_ascii': non_ascii,
            u'skipped_reason': skipped_reason,
            u'num_characters': num_characters
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

    def _is_text(self, text):
        """
        Check if text is binary or ASCII

        Parameters:
        text (str): The text to check.

        Returns:
        bool: True if text is ASCII, False if it's binary.
        """
        return chardet.detect(text.encode())['encoding'] is not None

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
        docs = self.db.collection(self.collection_name).where(u'status', u'!=', status).stream()

        for doc in docs:
            doc_ref = self.db.collection(self.collection_name).document(doc.id)
            doc_ref.update({
                u'status': status
            })
        logging.info(f"Reset status of all documents to '{status}'")

    def _create_bigquery_table_if_not_exists(self):
        """
        Create a BigQuery table to track details of each link processed.
        """
        dataset_ref = self.bq_client.dataset(self.dataset_id)
        table_ref = dataset_ref.table(self.table_id)
        try:
            self.bq_client.get_table(table_ref)
        except Exception: # pylint: disable=W0718
            schema = [
                bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("is_ascii", "BOOLEAN"),
                bigquery.SchemaField("char_count", "INTEGER"),
                bigquery.SchemaField("reason_skipped", "STRING"),
            ]
            table = bigquery.Table(table_ref, schema=schema)
            table = self.bq_client.create_table(table)

    def _insert_into_bigquery(self, url, is_ascii, char_count, reason_skipped):
        """
        Insert a new row into the BigQuery table.

        Parameters:
        url (str): The URL processed.
        is_ascii (bool): Whether the text content is ASCII.
        char_count (int): The number of characters in the text content.
        reason_skipped (str): The reason the URL was skipped, if applicable.
        """
        rows_to_insert = [
            {
                "url": url,
                "is_ascii": is_ascii,
                "char_count": char_count,
                "reason_skipped": reason_skipped,
            }
        ]

        # Make an API request.
        table_ref = f"{self.bq_client.project}.{self.dataset_id}.{self.table_id}"
        errors = self.bq_client.insert_rows_json(table_ref, rows_to_insert)

        if errors:
            print(f"Encountered errors while inserting rows: {errors}")
        else:
            print(f"Rows successfully inserted into table {self.table_id}.")
