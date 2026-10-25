import os

class Config:
    SECRET_KEY = 'your-very-secret-key'
    SQLALCHEMY_DATABASE_URI = 'postgresql://postgres:root@localhost:5432/bioattend'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEVICE_API_KEY = os.getenv("DEVICE_API_KEY")

