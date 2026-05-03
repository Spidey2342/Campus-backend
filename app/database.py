from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# Load the .env file so we can read our secrets
load_dotenv()

# Grab the database URL from .env
# We never hardcode passwords in code — always use .env
DATABASE_URL = os.getenv("DATABASE_URL")

# The engine is the actual connection to PostgreSQL
# It's like the phone line between Python and your database
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # tests connection before using it
    pool_recycle=300,        # recycles connections every 5 minutes
    connect_args={
        "connect_timeout": 10  # timeout after 10 seconds
    }
)

# SessionLocal is a factory that creates database sessions
# A session is like one conversation with the database
# You open it, do your queries, then close it
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is the parent class all our models will inherit from
# This is what makes a Python class into a database table
Base = declarative_base()

# This is a "dependency" — FastAPI will call this function
# automatically for every route that needs the database
# It opens a session, gives it to the route, then closes it
def get_db():
    db = SessionLocal()
    try:
        yield db      # "yield" gives the session to the route
    finally:
        db.close()   # always closes even if an error happens