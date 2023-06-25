"""
Class for coordinating the web scraping services.

Attributes:
    link_collector (LinkCollector): LinkCollector instance.
"""
import logging
import os

from dotenv import load_dotenv

from link_collector import LinkCollector
from scraping_service import ScraperService

load_dotenv()  # take environment variables from .env.

# Configure logging
logging.basicConfig(level=logging.INFO)

class WebScraper:
    """
    Initialize WebScraper with a LinkCollector instance.
    """
    def __init__(self):
        self.link_collector = LinkCollector(start_url=os.getenv('START_URL'),
                                            base_url=os.getenv('BASE_URL'),
                                            max_pages=os.getenv('MAX_PAGES'),
                                            collection_name=os.getenv('COLLECTION_NAME')
                                            )
        self.scraper_Service = ScraperService(collection_name=os.getenv('COLLECTION_NAME'),
                                               pdf_bucket_name=os.getenv('PDF_BUCKET_NAME'),
                                               gcp_bucket=os.getenv('GCP_BUCKET'),
                                               dataset_id= os.getenv('DATASET_ID'),
                                               table_id=os.getenv('TABLE_ID'),
                                               )
        # add other service initializations here

    def run(self, should_collect_links=True, should_scrape_pending_links=True, reset_collecion=True, scrape_limit=50):
        """
        Executes the web scraping services based on the given flags.

        This method allows selective execution of the link collection and link scraping services.

        Args:
            should_collect_links (bool, optional): Flag to determine if the link collection service should be run. 
                Defaults to True.
            should_scrape_pending_links (bool, optional): Flag to determine if the link scraping service should be run. 
                Defaults to True.
            scrape_limit (int, optional): Limit for the number of links to be scraped if the scraping service is run.
                Defaults to 50.

        Examples:
            # To run both services with default link limit
            scraper.run()

            # To run only the link collection service
            scraper.run(should_scrape_pending_links=False)

            # To run only the link scraping service with a limit of 100 links
            scraper.run(should_collect_links=False, scrape_limit=100)
        """
        logging.info("Running scraper...")
        if should_collect_links:
            logging.info("Collecting links...")
            self.link_collector.collect_links()
            logging.info("Link collection completed.")
        if should_scrape_pending_links:
            logging.info("Scraping links...")
            if reset_collecion:
                logging.info("Resetting collection status...")
                self.scraper_Service.reset_status()
                logging.info("Resetting completed.")
            logging.info(f"Scraping a maximum of {scrape_limit} links...")
            self.scraper_Service.scrape_pending_links(limit=scrape_limit)
            logging.info("Link scraping completed.")
        logging.info("Scraper run completed.")





if __name__ == "__main__":

    scraper = WebScraper()
    scraper.run(should_collect_links=False, reset_collecion=True, scrape_limit=500000)
