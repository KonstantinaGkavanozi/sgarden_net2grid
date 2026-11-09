import re

from fastapi import APIRouter, HTTPException, Query, status

from database import products_collection, users_collection
from routes.products import product_to_response

router = APIRouter(prefix="/api/search", tags=["search"])

USER_FIELDS = {
    "username": 1,
    "email": 1,
    "role": 1,
    "lastActiveAt": 1,
    "createdAt": 1,
}


@router.get("")
async def global_search(q: str = Query(..., min_length=1)):
    """Search users and products by a case-insensitive literal substring.

    Matches usernames, emails, and product names, descriptions, and categories.
    Returns separate users and products lists. User credentials are excluded.
    """
    term = q.strip()
    if not term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query must not be blank",
        )

    regex = {"$regex": re.escape(term), "$options": "i"}
    users = []
    async for user in users_collection.find(
        {"$or": [{"username": regex}, {"email": regex}]}, USER_FIELDS
    ):
        users.append({
            "id": str(user["_id"]),
            "username": user.get("username"),
            "email": user.get("email"),
            "role": user.get("role"),
            "lastActiveAt": str(user.get("lastActiveAt", "")),
            "createdAt": str(user.get("createdAt", "")),
        })

    products = []
    async for product in products_collection.find({
        "$or": [{field: regex} for field in ("name", "description", "category")]
    }):
        products.append(product_to_response(product))

    return {"users": users, "products": products}
