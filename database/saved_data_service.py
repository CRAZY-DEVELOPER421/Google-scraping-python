import logging
import os
from mysql.connector import Error
from database.db_connection import get_db_connection


def search_saved_places(keyword: str = "", location: str = "", page: int = 1, limit: int = 20):
    """
    Query the saved_data table for records matching keywords and/or city,
    with pagination support.
    
    Args:
        keyword: Search term for the keywords column
        location: Search term for the city column
        page: Page number (1-based)
        limit: Results per page (max 100)
    
    Returns:
        tuple: (success: bool, data: list or None, error: str or None, total: int)
        total is the total number of matching records without pagination.
    """
    conn, error_msg = get_db_connection()
    if not conn:
        return False, None, f"Database connection failed: {error_msg}", 0

    try:
        cursor = conn.cursor(dictionary=True)
        table_name = os.environ.get("DB_TABLE")

        # Ensure valid pagination values
        page = max(1, page)
        limit = max(1, min(100, limit))
        offset = (page - 1) * limit

        # Build WHERE conditions
        conditions = []
        params = []

        if keyword:
            conditions.append("keywords LIKE %s")
            params.append(f"%{keyword}%")

        if location:
            conditions.append("(city LIKE %s OR country LIKE %s)")
            params.append(f"%{location}%")
            params.append(f"%{location}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # First: get total count
        count_query = f"SELECT COUNT(*) as total FROM {table_name} WHERE {where_clause}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()["total"]

        # Second: get paginated data
        data_query = f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT %s OFFSET %s"
        data_params = params + [limit, offset]
        cursor.execute(data_query, data_params)
        results = cursor.fetchall()

        cursor.close()
        conn.close()

        return True, results, None, total

    except Error as e:
        logging.error(f"Query failed: {e}")
        if conn:
            conn.close()
        return False, None, str(e), 0
