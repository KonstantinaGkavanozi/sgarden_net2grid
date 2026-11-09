import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from database import products_collection, users_collection
from security.jwt_handler import get_current_user

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def global_search(
    q: Optional[str] = Query(None, description="Literal search text, 2–50 characters after trimming"),
    current_user: dict = Depends(get_current_user),
):
    """Search usernames and product names/descriptions, returning up to five of each."""
    term = q.strip() if q is not None else ""
    if not 2 <= len(term) <= 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query must contain 2–50 characters after trimming",
        )

    regex = {"$regex": re.escape(term), "$options": "i"}
    user_cursor = users_collection.find(
        {"username": regex},
        {"_id": 1, "username": 1, "role": 1},
    ).sort([("username", 1), ("_id", 1)]).limit(5)
    product_cursor = products_collection.find(
        {"$or": [{"name": regex}, {"description": regex}]},
        {"_id": 1, "name": 1, "category": 1, "price": 1},
    ).sort([("name", 1), ("_id", 1)]).limit(5)

    users = [
        {"id": str(user["_id"]), "username": user.get("username"), "role": user.get("role")}
        async for user in user_cursor
    ]
    products = [
        {
            "id": str(product["_id"]),
            "name": product.get("name"),
            "category": product.get("category"),
            "price": product.get("price"),
        }
        async for product in product_cursor
    ]
    return {"users": users, "products": products}
