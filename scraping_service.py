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
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)


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

    def __init__(self, run_id, collection_name, pdf_bucket_name, gcp_bucket, dataset_id, table_id):
        """
        Initialize ScraperService with Firestore collection name and GCS bucket names.
        """
        logger.info("Initializing ScraperService...")
        self.collection_name = collection_name
        self.pdf_bucket_name = pdf_bucket_name
        self.gcp_bucket = gcp_bucket
        self.run_id = run_id
        logger.info(f"Bigquery run_id: {self.run_id}")
        logger.info(f"Firestore collection name: {self.collection_name}")
        logger.info(f"PDF bucket name: {self.pdf_bucket_name}")
        logger.info(f"GCP bucket: {self.gcp_bucket}")

        self.db = firestore.Client()
        logger.info("Firestore client initialized.")

        self.bq_client = bigquery.Client()
        logger.info("BigQuery client initialized.")

        self.dataset_id = dataset_id
        self.table_id = table_id
        logger.info(f"Dataset ID: {self.dataset_id}")
        logger.info(f"Table ID: {self.table_id}")

        self._create_bigquery_table_if_not_exists()
        logger.info("ScraperService initialized.")


    def run(self, limit=None):
        """
        Scrape 'pending' links from Firestore and store the scraped content in GCS.

        Parameters:
        limit (int, optional): The maximum number of links to scrape.
        """
        logger.info(f"Starting to scrape pending links. Run ID: {self.run_id}")
        # Retrieve 'pending' links from Firestore
        links = self._get_pending_links(limit)
        logger.info(f"Retrieved {len(links)} pending links.")

        # Loop over the list of links
        for link in links:
            # Call the _scrape_link function for each link
            self._scrape_link(link)
        logger.info("Finished scraping pending links.")

    def _get_pending_links(self, limit=None):
        """
        Retrieve 'pending' links from Firestore.

        Parameters:
        limit (int, optional): The maximum number of links to retrieve.

        Returns:
        list: A list of 'pending' links.
        """
        logger.info("Retrieving pending links...")

        # Define the FieldFilter
        status_filter = FieldFilter(u'status', u'==', 'pending')

        # Query for documents where status is 'pending'
        query = self.db.collection(self.collection_name).where(filter=status_filter)

        # Execute the query and get the documents
        docs = query.stream()

        links = [doc.to_dict()['url'] for doc in docs]
        logger.info(f"Retrieved {len(links)} pending links.")
        return links[:limit]  # Limit the number of links

    def _scrape_link(self, url):
        logger.info(f"Starting to scrape URL: {url}")
        reason_skipped = None
        file_name = "None"
        content_type = "Unknown"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' in content_type:
                try:
                    file_name = self._upload_pdf(response.content, url)
                    is_text = False
                    char_count = 0
                except Exception as err: # pylint: disable=W0718
                    logger.error(f"Failed to upload PDF: {err}")
                    reason_skipped = f"Failed to upload PDF: {err}"
            elif 'text' in content_type or 'application/json' in content_type:
                soup = BeautifulSoup(response.text, 'html.parser')
                text_content = ""
                char_count = 0
                content_type = "text"
                is_text = True  # Assume ASCII until proven otherwise
                for paragraph in soup.find_all('p'):
                    paragraph_text = paragraph.get_text()
                    char_count += len(paragraph_text)
                    if not self._is_text(paragraph_text):
                        continue
                    if self._is_text(paragraph_text) and self._has_min_chars(paragraph_text, 1):
                        text_content += paragraph_text + '\n'
                if self._has_min_chars(text_content, 1):
                    file_name = self._upload_text(text_content, url)
                else:
                    reason_skipped = "No paragraph with sufficient characters."
            else:
                logger.info(f"Skipping URL due to non-text Content-Type: {content_type}")
                reason_skipped = f"Skipping URL due to non-text Content-Type: {content_type}"
        except requests.HTTPError as err:
            logger.error(f"HTTP error occurred: {err}")
            reason_skipped = f"HTTP error occurred: {err}"
        except requests.exceptions.RequestException as err:
            logger.error(f"Request error occurred: {err}")
            reason_skipped = f"Request error occurred: {err}"

        self._update_link_status(url, 'scraped', is_text, reason_skipped, char_count, file_name, content_type)
        self._insert_into_bigquery(url, is_text, char_count, reason_skipped, file_name, content_type)


    def _update_link_status(self, url, status, is_text, skipped_reason, num_characters, file_name, content_type):
        """
        Update the status of a link in Firestore.

        Parameters:
        url (str): The URL of the link.
        status (str): The new status.
        non_ascii (bool): Whether the content at the URL contains non-ASCII characters.
        skipped_reason (str): The reason the URL was skipped, if applicable.
        num_characters (int): The number of characters in the content at the URL.
        file_name (str): The name of the file stored in GCS.
        content_type (str): The content type of the URL's content.
        """

        doc_id = self._hash_url(url)
        doc_ref = self.db.collection(self.collection_name).document(doc_id)  # Use the locally initialized client
        doc_ref.update({
            u'status': status,
            u'is_text': is_text,
            u'skipped_reason': skipped_reason,
            u'num_characters': num_characters,
            u'file_name': file_name,
            u'content_type': content_type  # Add content_type to the document
        })

        logger.info(f"Updated URL status in Firestore: {url} => {status}")


    def _upload_pdf(self, content, url):
        """
        Upload a PDF file to Google Cloud Storage.

        Args:
            content (bytes): The content of the PDF file.
            url (str): The URL of the PDF file.

        Returns:
            str: The name of the uploaded blob.
        """
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.pdf_bucket_name)
        blob_name = self._clean_url(url) + ".pdf"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(content)
        logger.info(f"PDF uploaded to GCS: {blob_name}")
        return blob_name  # Return the blob name

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

        Returns:
            str: The name of the uploaded blob.
        """
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(self.gcp_bucket)
        url_clean = url.replace("http://", "").replace("https://", "").replace("/", "__")
        blob_name = f'{url_clean}.txt'
        blob = bucket.blob(blob_name)
        blob.upload_from_string(text_content)
        return blob_name  # Return the blob name

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
                bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("is_ascii", "BOOLEAN"),
                bigquery.SchemaField("char_count", "INTEGER"),
                bigquery.SchemaField("reason_skipped", "STRING"),
                bigquery.SchemaField("file_name", "STRING"),  # <-- added line
                bigquery.SchemaField("content_type", "STRING"),  # <-- added line
            ]
            table = bigquery.Table(table_ref, schema=schema)
            table = self.bq_client.create_table(table)

    def _insert_into_bigquery(self, url, is_ascii, char_count, reason_skipped, file_name, content_type):
        """
        Insert a new row or update existing one into the BigQuery table.
        """
        errors = None
        table_ref = f"{self.bq_client.project}.{self.dataset_id}.{self.table_id}"
        table = self.bq_client.get_table(table_ref)  # Get table reference

        rows_to_insert = [
            {   
                "run_id": str(self.run_id),
                "url": url,
                "is_ascii": is_ascii,
                "char_count": char_count,
                "reason_skipped": reason_skipped,
                "file_name": file_name,
                "content_type": content_type,
            }
        ]
        errors = self.bq_client.insert_rows_json(table, rows_to_insert)

        if errors:
            logger.error(f"Encountered errors while inserting/updating rows: {errors}")
        else:
            logger.info(f"Rows successfully inserted/updated into table {self.table_id}.")


