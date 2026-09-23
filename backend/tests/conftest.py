import os

# Test runs never call external models or use the project database.
os.environ["AI_MODE"] = "mock"
os.environ["DATABASE_URL"] = "sqlite://"
