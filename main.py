from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr

from database import get_client_for_token, supabase

app = FastAPI(title="FastAPI + Supabase CRUD App")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

TABLE_NAME = "items"


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ItemCreate(BaseModel):
    name: str
    price: float
    description: Optional[str] = None


# --------------------------------------------------------------------------
# Auth dependency
# --------------------------------------------------------------------------
class CurrentUser:
    """Wraps the Supabase user plus the raw token, so callers can build a
    request-scoped, RLS-aware Supabase client via get_client_for_token()."""

    def __init__(self, user, token: str):
        self.user = user
        self.token = token
        self.id = user.id
        self.email = user.email


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> CurrentUser:
    """
    Verifies the 'Authorization: Bearer <token>' header against Supabase
    Auth. Raises 401 if the header is missing or the token is invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        user_response = supabase.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = getattr(user_response, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return CurrentUser(user, token)


# --------------------------------------------------------------------------
# Auth routes (JSON API, called by the login/register pages via fetch())
# --------------------------------------------------------------------------
@app.post("/auth/register")
async def register(payload: RegisterRequest):
    try:
        result = supabase.auth.sign_up(
            {"email": payload.email, "password": payload.password}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if getattr(result, "user", None) is None:
        raise HTTPException(status_code=400, detail="Registration failed")

    return {
        "message": (
            "Registration successful. If email confirmation is enabled on "
            "your Supabase project, check your inbox before logging in."
        )
    }


@app.post("/auth/login")
async def login(payload: LoginRequest):
    try:
        result = supabase.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    session = getattr(result, "session", None)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": "bearer",
        "user": {"id": result.user.id, "email": result.user.email},
    }


@app.post("/auth/logout")
async def logout(current_user: CurrentUser = Depends(get_current_user)):
    # Supabase sessions are stateless JWTs on the client side; the
    # meaningful part of "logout" is the browser dropping its token, which
    # the login.html/base.html JS does. This endpoint also asks Supabase to
    # invalidate the refresh token server-side, best-effort.
    try:
        client = get_client_for_token(current_user.token)
        client.auth.sign_out()
    except Exception:
        pass
    return {"message": "Logged out"}


# --------------------------------------------------------------------------
# HTML page routes
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    try:
        result = (
            supabase.table(TABLE_NAME)
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        items = result.data or []
    except Exception:
        items = []
    return templates.TemplateResponse(request, "index.html", {"items": items})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@app.get("/product/new", response_class=HTMLResponse)
async def new_product_page(request: Request):
    # Access control for this page is enforced client-side (redirect to
    # /login if no token) and, more importantly, server-side on the actual
    # POST /items/ call and by RLS. A logged-out visitor can see this empty
    # form, but cannot submit it.
    return templates.TemplateResponse(request, "product_form.html", {})


@app.get("/product/{item_id}", response_class=HTMLResponse)
async def product_detail_page(request: Request, item_id: str):
    try:
        result = supabase.table(TABLE_NAME).select("*").eq("id", item_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Database error")

    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Item not found")

    return templates.TemplateResponse(
        request, "product_detail.html", {"item": rows[0]}
    )


# --------------------------------------------------------------------------
# CRUD API routes (JSON), called by the page JS via fetch()
# --------------------------------------------------------------------------
@app.post("/items/", status_code=201)
async def create_item(
    payload: ItemCreate, current_user: CurrentUser = Depends(get_current_user)
):
    client = get_client_for_token(current_user.token)
    data = {
        "name": payload.name,
        "price": payload.price,
        "description": payload.description,
        "user_id": current_user.id,
    }
    try:
        result = client.table(TABLE_NAME).insert(data).execute()
    except Exception as e:
        # Most commonly an RLS policy rejection — surface it plainly rather
        # than a bare 500.
        raise HTTPException(status_code=400, detail=f"Could not create item: {e}")

    if not result.data:
        raise HTTPException(status_code=400, detail="Could not create item")

    return result.data[0]


@app.get("/items/{item_id}")
async def get_item(item_id: str):
    try:
        # Deliberately NOT using .single() here. .single() raises an
        # exception (and returns a generic 500) when the id matches zero
        # rows, which makes "not found" indistinguishable from a real
        # server error. Fetching as a list and checking length lets us
        # return a clean, intentional 404 instead.
        result = supabase.table(TABLE_NAME).select("*").eq("id", item_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Database error")

    rows = result.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Item not found")

    return rows[0]


@app.delete("/items/{item_id}")
async def delete_item(
    item_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    client = get_client_for_token(current_user.token)

    # Check existence first (via the public, anon-readable view) so a
    # missing item reliably returns 404 rather than a silent no-op delete.
    existing = supabase.table(TABLE_NAME).select("id").eq("id", item_id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        result = client.table(TABLE_NAME).delete().eq("id", item_id).execute()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not delete item: {e}")

    if not result.data:
        # RLS silently filtered the delete out — the item exists but isn't
        # owned by this user.
        raise HTTPException(
            status_code=403, detail="You don't have permission to delete this item"
        )

    return {"message": "Item deleted"}
