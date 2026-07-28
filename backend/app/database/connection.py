from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os
from sqlalchemy.engine import URL
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# Set a default connection string for local MySQL Workbench
# Using URL.create safely handles passwords with special characters like '@'
SQLALCHEMY_DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", 3306)),
    database=os.getenv("MYSQL_DATABASE", "chatbot_db"),
)


engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    pool_pre_ping=True, 
    pool_recycle=3600
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
