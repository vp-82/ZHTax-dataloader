import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from google.cloud import storage
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def scrape_website(start_url, max_pages):
    visited = set()
    queue = [start_url]
    pages_scraped = 0
    pdf_bucket_name = 'lu-scraper-data-pdf'  # replace with your bucket name for PDFs

    while queue and pages_scraped < max_pages:  # Stop scraping if max_pages is reached
        url = queue.pop(0)
        logging.info(f"Visiting URL: {url}")

        if url in visited or "#" in url:  # Skip if URL is already visited or if it contains #
            logging.info(f"URL already visited or contains #: {url}")
            continue

        visited.add(url)

        try:
            response = requests.get(url)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            if 'application/pdf' in content_type:
                storage_client = storage.Client()
                bucket = storage_client.get_bucket(pdf_bucket_name)
                blob_name = f'{url.replace("http://", "").replace("https://", "").replace("/", "__")}.pdf'
                blob = bucket.blob(blob_name)
                blob.upload_from_file(response.content)
                logging.info(f"PDF uploaded to GCS: {blob_name}")
                continue
            elif 'text' not in content_type and 'application/json' not in content_type:
                logging.info(f"Skipping URL due to non-text Content-Type: {content_type}")
                continue
        except requests.HTTPError as err:
            logging.error(f"HTTP error occurred: {err}")
            continue
        except Exception as err:
            logging.error(f"An error occurred: {err}")
            continue

        # ... the rest of your code ...

        soup = BeautifulSoup(response.text, 'html.parser')

        # Initialize a string to store the plain text content of the webpage
        text_content = ""

        for p in soup.find_all('p'):
            text_content += p.get_text() + '\n'

        for a in soup.find_all('a', href=True):
            link = urljoin(url, a['href'])
            # Only follow links within the same domain
            if link.startswith(start_url) and not link.endswith('.pdf') and "#" not in link:  # Also skip if it's a PDF link or contains #
                if link not in visited and pages_scraped < max_pages:  # Only add link to queue if max_pages is not reached
                    queue.append(link)
                    logging.info(f"Added URL to queue: {link}")

        # Store the plain text content in Google Cloud Storage
        storage_client = storage.Client()
        bucket = storage_client.get_bucket('lu-scraper-data')
        url_clean = url.replace("http://", "").replace("https://", "").replace("/", "__")
        blob_name = f'{url_clean}.txt'
        blob = bucket.blob(blob_name)
        blob.upload_from_string(text_content)

        pages_scraped += 1
        logging.info(f'Scraped {url}, total pages scraped: {pages_scraped}')
        logging.info(f"Number of URLs in queue: {len(queue)}")
        logging.info(f"Number of URLs visited: {len(visited)}")


if __name__ == "__main__":
    scrape_website('https://informatik.lu.ch', max_pages=100)
