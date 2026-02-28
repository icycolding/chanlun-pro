import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add the project src directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.db import db, TableByCompanyFinancials

def check_all_financial_data():
    """
    Directly queries and prints all data from the company_financials table.
    """
    print("Attempting to query all data from the company_financials table...")
    
    # The db object from chanlun.db manages the session for us
    session = db.Session()
    
    try:
        # Query all records from the table
        all_data = session.query(TableByCompanyFinancials).all()
        
        if not all_data:
            print("The 'company_financials' table is empty.")
            return

        # Convert to a list of dictionaries for pandas DataFrame
        data_list = []
        for record in all_data:
            data_list.append({
                'code': record.code,
                'name': record.name,
                'report_date': record.report_date,
                'statement_type': record.statement_type,
                'item_name': record.item_name,
                'item_value': record.item_value
            })
        
        # Create and print DataFrame
        df = pd.DataFrame(data_list)
        print("Data found in 'company_financials' table:")
        print(df.to_string())

    except Exception as e:
        print(f"An error occurred while querying the database: {e}")
    finally:
        session.close()
        print("Database session closed.")

if __name__ == "__main__":
    check_all_financial_data()