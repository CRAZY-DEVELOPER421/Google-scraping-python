import os
import logging
import mysql.connector
from mysql.connector import Error


def get_db_connection():
    """Create and return a new MySQL database connection."""
    try:
        conn = mysql.connector.connect(
            host=os.environ.get("DB_HOST"),
            port=int(os.environ.get("DB_PORT", 3306)),
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            database=os.environ.get("DB_NAME"),
            use_pure=True,
        )
        return conn, None
    except Error as e:
        error_msg = str(e)
        logging.error(f"Database connection failed: {error_msg}")
        return None, error_msg
