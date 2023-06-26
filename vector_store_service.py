import logging
import os

from dotenv import load_dotenv
from google.cloud import storage
from langchain.document_loaders import GCSFileLoader
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import Milvus
from pymilvus import Collection, MilvusClient

load_dotenv()  # take environment variables from .env.
logging.basicConfig(level=logging.INFO)

class VectorStoreService:
    """
    A service that retrieves text data from Google Cloud Storage and feeds it into a Milvus database.
    """
    def __init__(self, project_name, bucket_name, collection_name):
        """
        Initializes the service with the given project name and bucket name.

        :param project_name: The name of the GCP project.
        :param bucket_name: The name of the GCS bucket containing the text data.
        """
        self.project_name = project_name
        self.bucket_name = bucket_name
        self.collection_name = collection_name
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.milvus_api_key = os.getenv('MILVUS_API_KEY')

        self.storage_client = storage.Client()

        self.connection_args = {
            "uri": "https://in03-5052868020ac71b.api.gcp-us-west1.zillizcloud.com",
            "user": "vaclav@pechtor.ch",
            "token": self.milvus_api_key,
            "secure": True
        }

        self.client = MilvusClient(
            uri="https://in03-5052868020ac71b.api.gcp-us-west1.zillizcloud.com",
            token=self.milvus_api_key
        )
        logging.info(f'Milvus connection: {self.client}')

        self.embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
        logging.info(f'OpenAI embedings: {self.embeddings}')

        logging.info('Init completed')


    def run(self, num_docs=None, collection_name="LuGPT"):
        """
        Runs the service, processing each document in the bucket individually.

        :param num_docs: The number of documents to process. If None, all documents will be processed.
        :param collection_name: The name of the collection to store the vector data in. Defaults to 'default'.
        """
        logging.info('Starting VectorStoreService.')

        blobs = self.storage_client.list_blobs(self.bucket_name)

        if num_docs is not None:
            blobs = list(blobs)[:num_docs]

        batch_size = 100
        batch_docs = []
        text_splitter = CharacterTextSplitter(chunk_size=1024, chunk_overlap=0)

        for i, blob in enumerate(blobs):
            logging.info(f'Processing document {i}.')
            try:
                loader = GCSFileLoader(project_name=self.project_name, bucket=self.bucket_name, blob=blob.name)
                doc = loader.load()
                logging.info(f'Loaded document {i}.')

                docs = text_splitter.split_documents(doc)

                batch_docs.extend(docs)

                if (i + 1) % batch_size == 0:
                    logging.info('Writing batch to Milvus.')
                    vector_store = Milvus.from_documents(
                        batch_docs,  # process a batch of documents
                        embedding=self.embeddings,
                        connection_args=self.connection_args,
                        collection_name=collection_name  # Use the given collection name
                    )
                    self.client.flush(collection_name=self.collection_name)
                    num_entities = self.client.num_entities(collection_name=self.collection_name)
                    logging.info(f'Number of vectors in the database: {num_entities}')
                    batch_docs = []
            except Exception as e: # pylint: disable=W0718
                logging.error(f'Exception occurred while processing document {i}: {e}', exc_info=True)

        # If there are any documents left in the batch, process them
        logging.info(f'Writing {len(batch_docs)} remaining batch_docs to Milvus.')
        if batch_docs:
            vector_store = Milvus.from_documents(
                batch_docs,  # process the remaining documents
                embedding=self.embeddings,
                connection_args=self.connection_args,
                collection_name=collection_name  # Use the given collection name
            )
            self.client.flush(collection_name=self.collection_name)
        num_entities = self.client.num_entities(collection_name=self.collection_name)
        logging.info(f'Number of vectors in the database: {num_entities}')
        logging.info('VectorStoreService has finished processing.')




    def clear_database(self):
        """
        Clears the specified Milvus collection.
        """
        try:
            self.client.drop_collection(self.collection_name)
            logging.info(f"Collection '{self.collection_name}' dropped successfully.")
        except Exception as e: # pylint: disable=W0718
            logging.error(f"Exception occurred while dropping collection '{self.collection_name}': {e}", exc_info=True)
