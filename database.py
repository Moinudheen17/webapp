import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_KEY must be set (create a .env file — "
        "see .env.example)."
    )

# Default, unauthenticated client. Safe to share across requests — used only
# for public reads (e.g. the home page item list), which RLS allows for the
# anon role.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_client_for_token(access_token: str) -> Client:
    """
    Build a Supabase client scoped to a specific user's JWT.

    This matters for RLS: policies that check auth.uid() only see a user
    identity if the PostgREST request carries that user's access token in
    its Authorization header. The module-level `supabase` client above uses
    only the anon key and has no per-user identity, so it must never be used
    for authenticated writes (inserts/deletes tied to a user).

    A fresh client is created per call rather than mutating a shared
    instance, since a shared client is not safe to reuse across concurrent
    async requests from different users.
    """
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client.postgrest.auth(access_token)
    return client
