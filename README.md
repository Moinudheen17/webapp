# FastAPI + Supabase CRUD App

A full-stack item catalog: FastAPI backend, Jinja2-rendered HTML frontend,
Supabase for the database and user auth. Anyone can browse items; only
logged-in users can create or delete their own items.

## Directory layout

```
fastapi-supabase-app/
├── main.py              # Routes: auth, pages, CRUD API
├── database.py           # Supabase client setup
├── requirements.txt
├── .env.example
├── .gitignore
├── static/
│   └── style.css
└── templates/
    ├── base.html          # Layout + shared auth JS (localStorage helpers)
    ├── index.html         # Home page — item list
    ├── login.html
    ├── register.html
    ├── product_form.html  # /product/new — create item
    └── product_detail.html
```

## 1. Create the Supabase project & table

1. Create a project at https://supabase.com (or use an existing one).
2. In the SQL Editor, run:

```sql
create table if not exists items (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    price numeric not null check (price >= 0),
    description text,
    user_id uuid references auth.users(id) on delete cascade,
    created_at timestamptz default now()
);
```

## 2. Row Level Security (RLS) policies

```sql
alter table items enable row level security;

-- Anyone (including logged-out visitors) can read items.
create policy "Public read access"
on items for select
to anon, authenticated
using (true);

-- A logged-in user can only insert a row tagged with their own user_id.
create policy "Authenticated users can insert their own items"
on items for insert
to authenticated
with check (auth.uid() = user_id);

-- A logged-in user can only delete their own items.
create policy "Users can delete their own items"
on items for delete
to authenticated
using (auth.uid() = user_id);
```

These policies are why `database.py` builds a **per-request, token-scoped
Supabase client** (`get_client_for_token`) for inserts and deletes, instead
of reusing the single anon-key client used for public reads: PostgREST only
resolves `auth.uid()` when the request's `Authorization` header carries that
user's JWT. If you write or delete using the plain anon client, RLS will
correctly reject it (or worse, silently filter it), since there's no user to
match against.

By default, Supabase requires email confirmation for new sign-ups. For fast
local testing you can turn this off in **Authentication → Providers →
Email → Confirm email**, or just confirm the test user's email in
**Authentication → Users**.

## 3. Configure environment variables

```bash
cp .env.example .env
```

Fill in `SUPABASE_URL` and `SUPABASE_KEY` from **Project Settings → API**
in your Supabase dashboard. Use the **anon / public** key — never the
`service_role` key in this app, since that key bypasses RLS entirely.

## 4. Run locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit http://127.0.0.1:8000. Register an account, log in, add an item, view
its detail page, delete it.

## 5. Push to GitHub

```bash
cd fastapi-supabase-app
git init
git add .
git commit -m "Initial commit: FastAPI + Supabase CRUD app"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

`.env` is already in `.gitignore`, so your keys won't be committed. Anyone
who clones the repo runs steps 3–4 themselves with their own `.env`.

## 6. Deploying so others can use it live

GitHub itself only hosts the code — a Python server needs somewhere to
actually run. Any of these work well for a small FastAPI app and have free
tiers:

- **Render** — connect the GitHub repo, set build command
  `pip install -r requirements.txt`, start command
  `uvicorn main:app --host 0.0.0.0 --port $PORT`, and add `SUPABASE_URL` /
  `SUPABASE_KEY` as environment variables in the dashboard.
- **Railway** — similar flow: connect the repo, it detects Python
  automatically, add the two env vars.
- **Fly.io** — good if you want a `Dockerfile`; ask if you'd like one added.

In all three cases, set `SUPABASE_URL` and `SUPABASE_KEY` as the platform's
environment/secret variables (not in the repo) — that's what `.env` is
standing in for locally.

## Notes on the requirements you called out

- **`.single()` avoided** in `GET /items/{item_id}`: the code fetches as a
  list and checks length, so a missing id returns a clean `404` instead of
  an unhandled exception turning into a `500`.
- **Int or UUID primary keys**: every route treats `item_id` as a plain
  `str`, and the detail page embeds it into JS with Jinja's `|tojson`
  filter (`const ITEM_ID = {{ item.id | tojson }};`), which emits a valid
  JS string or number literal either way — no `parseInt`/type-guessing
  needed, and no XSS risk from the value.
- **XSS**: Jinja2 autoescapes HTML by default; the one place a DB value
  crosses into a `<script>` block (the item id on the detail page) uses
  `|tojson` specifically because plain autoescaping doesn't make a value
  safe inside JS.
