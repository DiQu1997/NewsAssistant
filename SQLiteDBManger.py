import sqlite3
import logging

class SQLiteDBManger:
    def __init__(self, db_file, logger):
        self.logger = logger
        self.conn = None
        self.cursor = None
        self.create_connection(db_file)

    def create_connection(self, db_file):
        try:
            self.conn = sqlite3.connect(db_file)
            self.cursor = self.conn.cursor()
            self.logger.info(f"Connected to {db_file}")
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to {db_file}: {e}")

    def query(self, query):
        try:
            self.cursor.execute(query)
            self.logger.info(f"Query executed: {query}")
        except sqlite3.Error as e:
            self.logger.error(f"Error executing query: {e}")

    def close(self):
        try:
            self.conn.close()
            self.logger.info("Connection closed")
        except sqlite3.Error as e:
            self.logger.error(f"Error closing connection: {e}")