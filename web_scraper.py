"""
Class for coordinating the web scraping services.

Attributes:
    link_collector (LinkCollector): LinkCollector instance.
"""
import argparse
import logging
import os
import sys
import uuid

from dotenv import load_dotenv

from link_collector_service import LinkCollectorService
from scraping_service import ScraperService
from vector_store_service import VectorStoreService

load_dotenv()  # take environment variables from .env.

# Create a custom logger at the root
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create handlers
console_handler = logging.StreamHandler(sys.stdout)
file_handler = logging.FileHandler('app.log')

# Set the level for each handler
console_handler.setLevel(logging.INFO)
file_handler.setLevel(logging.INFO)

# Create formatters and add it to handlers
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(log_format)
file_handler.setFormatter(log_format)

# Add the handlers to the logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

class WebScraper:
    """
    Initialize WebScraper with a LinkCollector instance.
    """
    def __init__(self):
        self.run_id = uuid.uuid4()
        self.link_collector = LinkCollectorService(
                                            run_id=self.run_id,
                                            collection_name=os.getenv('COLLECTION_NAME')
                                            )
        self.scraper_Service = ScraperService(
                                            run_id=self.run_id,
                                            collection_name=os.getenv('COLLECTION_NAME'),
                                            pdf_bucket_name=os.getenv('PDF_BUCKET_NAME'),
                                            gcp_bucket=os.getenv('GCS_BUCKET_NAME'),
                                            dataset_id= os.getenv('DATASET_ID'),
                                            table_id=os.getenv('TABLE_ID'),
                                            )
        self.vector_store_service = VectorStoreService(
                                            run_id=self.run_id,
                                            project_name=os.getenv('GCP_PROJECT_NAME'),
                                            bucket_name=os.getenv('GCS_BUCKET_NAME'),
                                            collection_name=os.getenv('MILVUS_COLLECTION_NAME')
        )

    def run_service(self, service, kwargs):
        """
        Runs a service with the given arguments.
        """
        logger.info(f"Running {service.__class__.__name__}...")
        service.run(**kwargs)
        logger.info(f"{service.__class__.__name__} completed.")

    def run(self, services_to_run):
        """
        Runs the services in the order they are provided.

        :param services_to_run: List of tuples,
            where each tuple contains a service instance and a dictionary of arguments for its run method.
        """
        for service, kwargs in services_to_run:
            self.run_service(service, kwargs)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Web Scraper')

    parser.add_argument('-u', '--urls', nargs='*', help='URLs to scrape')
    parser.add_argument('-b', '--base_url', type=str, help='Base URL for relative links')
    parser.add_argument('-lc', '--link_collector', action='store_true', help='Run LinkCollectorService')
    parser.add_argument('-ss', '--scraper_service', action='store_true', help='Run ScraperService')
    parser.add_argument('-vs', '--vector_store', action='store_true', help='Run VectorStoreService')

    args = parser.parse_args()

    logger.info("-" * 60)  # This will create a line of 60 hyphens
    logger.info("Starting new run...")

    # Ensure that URLs are provided if the LinkCollectorService is selected
    if args.link_collector and not args.urls:
        raise ValueError("Error: The LinkCollectorService requires at least one URL.")

    if args.link_collector:
        for url in args.urls:
            scraper = WebScraper()

            services_to_run = []

            base_url = args.base_url if args.base_url else url
            services_to_run.append((scraper.link_collector, {"start_url": url, "base_url": base_url}))

            if args.scraper_service:
                services_to_run.append((scraper.scraper_Service, {}))

            if args.vector_store:
                services_to_run.append((scraper.vector_store_service, {}))

            scraper.run(services_to_run)

    else:
        scraper = WebScraper()

        services_to_run = []

        if args.scraper_service:
            services_to_run.append((scraper.scraper_Service, {}))

        if args.vector_store:
            services_to_run.append((scraper.vector_store_service, {}))

        scraper.run(services_to_run)

    logger.info(f"Finished run with ID {scraper.run_id}")
