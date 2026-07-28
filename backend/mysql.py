import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.log import Base, ChatLog
from sqlalchemy.engine import URL
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# 1. Path to your existing SQLite database
SQLITE_DB_PATH = "chatbot.db"

# 2. Your MySQL connection string
# Using URL.create safely handles passwords with special characters like '@'
MYSQL_URL = URL.create(
    drivername="mysql+pymysql",
    username=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", 3306)),
    database=os.getenv("MYSQL_DATABASE", "chatbot_db"),
)

def migrate():
    print(f"Connecting to MySQL database at {MYSQL_URL}...")
    try:
        mysql_engine = create_engine(MYSQL_URL, pool_pre_ping=True)
        # Create tables in MySQL if they don't exist
        Base.metadata.create_all(bind=mysql_engine)
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=mysql_engine)
        mysql_session = SessionLocal()
    except Exception as e:
        print(f"Failed to connect to MySQL. Ensure it is running and the credentials are correct. Error: {e}")
        return

    print(f"Connecting to SQLite database at {SQLITE_DB_PATH}...")
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"SQLite database not found at {SQLITE_DB_PATH}. Nothing to migrate.")
        return

    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM chat_logs")
        rows = cursor.fetchall()
        print(f"Found {len(rows)} records in SQLite database.")
        
        for row in rows:
            # Check if this record already exists in MySQL
            existing = mysql_session.query(ChatLog).filter_by(id=row['id']).first()
            if not existing:
                log_entry = ChatLog(
                    id=row['id'],
                    user_query=row['user_query'],
                    detected_intent=row['detected_intent'],
                    confidence_score=row['confidence_score'],
                    extracted_entities=row['extracted_entities'],
                    route=row['route'],
                    llm_response=row['llm_response'],
                    session_id=row['session_id'],
                    created_at=row['created_at']
                )
                mysql_session.add(log_entry)
        
        mysql_session.commit()
        print("Migration completed successfully!")
    except Exception as e:
        mysql_session.rollback()
        print(f"Migration failed during data transfer. Error: {e}")
    finally:
        mysql_session.close()
        conn.close()

if __name__ == "__main__":
    migrate()
