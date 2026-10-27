import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

supabase = create_client(url, key)

result = (
    supabase
    .table("employees")
    .select("id, name, phone_number")
    .limit(5)
    .execute()
)

print("Supabase connection successful!")
print(f"Employees retrieved: {len(result.data)}")

for employee in result.data:
    print(employee["name"])