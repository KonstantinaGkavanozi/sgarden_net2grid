from fastapi import APIRouter, HTTPException, status, Depends
from models.product import ProductRequest, ProductResponse
from database import products_collection
from security.jwt_handler import get_current_user
from bson import ObjectId
from datetime import datetime
import re

router = APIRouter(prefix="/api/products", tags=["products"])

# CODE QUALITY ISSUE: unused variable
service_name = "ProductService"


def product_to_response(product: dict) -> dict:
    """Convert MongoDB document to API response format."""
    return {
        "id": str(product["_id"]),
        "name": product.get("name"),
        "description": product.get("description"),
        "category": product.get("category"),
        "price": product.get("price"),
        "stock": product.get("stock", 0),
        "createdAt": product.get("createdAt", "").isoformat() if product.get("createdAt") else None,
        "updatedAt": product.get("updatedAt", "").isoformat() if product.get("updatedAt") else None,
    }


def format_product(product: dict) -> dict:
    """CODE QUALITY ISSUE: duplicate of product_to_response above."""
    return {
        "id": str(product["_id"]),
        "name": product.get("name"),
        "description": product.get("description"),
        "category": product.get("category"),
        "price": product.get("price"),
        "stock": product.get("stock", 0),
        "createdAt": product.get("createdAt", "").isoformat() if product.get("createdAt") else None,
        "updatedAt": product.get("updatedAt", "").isoformat() if product.get("updatedAt") else None,
    }


@router.get("")
async def get_all_products():
    print("Fetching all products")
    products = []
    cursor = products_collection.find()
    async for product in cursor:
        products.append(product_to_response(product))
    return products


@router.get("/{product_id}")
async def get_product_by_id(product_id: str):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    product = await products_collection.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    return product_to_response(product)


@router.get("/search")
async def search_products(q: str = None, category: str = None, minPrice: float = None, maxPrice: float = None):
    """Search products by text, category, and price range.

    - `q`: case-insensitive partial match against `name` and `description`.
    - `category`: exact match.
    - `minPrice`: inclusive lower bound for `price`.
    - `maxPrice`: inclusive upper bound for `price`.
    """
    query_filter = {}

    # Text search across name and description (case-insensitive, partial)
    if q:
        safe_q = re.escape(q)
        regex = {"$regex": safe_q, "$options": "i"}
        query_filter["$or"] = [{"name": regex}, {"description": regex}]

    # Category exact match
    if category:
        query_filter["category"] = category

    # Price range
    price_query = {}
    if minPrice is not None:
        price_query["$gte"] = minPrice
    if maxPrice is not None:
        price_query["$lte"] = maxPrice
    if price_query:
        query_filter["price"] = price_query

    products = []
    cursor = products_collection.find(query_filter)
    async for product in cursor:
        products.append(product_to_response(product))

    return products

#testing something
print("This is a test print statement in products.py")
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(request: ProductRequest, current_user: dict = Depends(get_current_user)):
    product_doc = {
        "name": request.name,
        "description": request.description,
        "category": request.category,
        "price": request.price,
        "stock": request.stock if request.stock is not None else 0,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await products_collection.insert_one(product_doc)
    product_doc["_id"] = result.inserted_id
    print(f"Created product: {request.name}")
    return product_to_response(product_doc)


@router.put("/{product_id}")
async def update_product(product_id: str, request: ProductRequest, current_user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    update_fields = {}
    if request.name is not None:
        update_fields["name"] = request.name
    if request.description is not None:
        update_fields["description"] = request.description
    if request.category is not None:
        update_fields["category"] = request.category
    if request.price is not None:
        update_fields["price"] = request.price
    if request.stock is not None:
        update_fields["stock"] = request.stock

    if not update_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    update_fields["updatedAt"] = datetime.utcnow()

    result = await products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": update_fields},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    product = await products_collection.find_one({"_id": ObjectId(product_id)})
    return product_to_response(product)


@router.delete("/{product_id}")
async def delete_product(product_id: str, current_user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    result = await products_collection.delete_one({"_id": ObjectId(product_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    return {"message": "Product deleted"}
