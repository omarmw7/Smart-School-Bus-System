"""Create an admin account. Run from the terminal: python create_admin.py"""
import os
import sys
from getpass import getpass

from dotenv import load_dotenv
from supabase import create_client
from werkzeug.security import generate_password_hash

load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

email = input("Admin email: ").strip().lower()
name = input("Display name: ").strip()
password = getpass("Password (min 10 characters): ")

if "@" not in email:
    sys.exit("Invalid email.")
if len(password) < 10:
    sys.exit("Password is too short.")
if getpass("Repeat password: ") != password:
    sys.exit("Passwords do not match.")

supabase.table("admins").insert({
    "email": email,
    "name": name or None,
    "password_hash": generate_password_hash(password),
}).execute()
print(f"Admin {email} created.")
