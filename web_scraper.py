"""
Class for coordinating the web scraping services.

Attributes:
    link_collector (LinkCollector): LinkCollector instance.
"""
import logging

from link_collector import LinkCollector

# Configure logging
logging.basicConfig(level=logging.INFO)

class WebScraper:
    """
    Initialize WebScraper with a LinkCollector instance.
    """
    def __init__(self, start_url, base_url, max_pages, collection_name):
        self.link_collector = LinkCollector(start_url, base_url, max_pages, collection_name)
        # add other service initializations here

    def run(self):
        """
        Run the web scraping services.
        """
        self.link_collector.collect_links()
        # call other services here


if __name__ == "__main__":

    start = "https://www.lu.ch"
    base = "https://www.lu.ch"
    max_links = 100000
    collection = "LuGPT"

    scraper = WebScraper(start, base, max_links, collection)
    scraper.run()
