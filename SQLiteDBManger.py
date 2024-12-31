import sqlite3
import logging

class SQLiteDBManger:
    def __init__(self,  , logger):
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

    def create_table(self, table_name, column_definitions):
        """
        Create a table with the specified columns
        
        Args:
            table_name (str): Name of the table
            column_definitions (list): List of tuples (name, type, constraints)
        """
        try:
            columns = ", ".join([f"{col[0]} {col[1]} {col[2]}" for col in column_definitions])
            self.cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({columns})")
            self.logger.info(f"Table {table_name} created with columns: {columns}")
        except sqlite3.Error as e:
            self.logger.error(f"Error creating table {table_name}: {e}")

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