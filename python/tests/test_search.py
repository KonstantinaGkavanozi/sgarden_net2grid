import re
import unittest
from datetime import datetime
from unittest.mock import patch

from bson import ObjectId
from fastapi.testclient import TestClient

from main import app


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    def find(self, query, projection=None):
        self.calls.append((query, projection))

        async def results():
            for document in self.documents:
                if any(
                    re.search(expression["$regex"], document.get(field, ""), re.I)
                    for clause in query["$or"]
                    for field, expression in clause.items()
                ):
                    if projection:
                        yield {key: value for key, value in document.items()
                               if key == "_id" or projection.get(key)}
                    else:
                        yield document

        return results()


class GlobalSearchTests(unittest.TestCase):
    def setUp(self):
        self.user_id = ObjectId()
        self.product_id = ObjectId()
        self.users = FakeCollection([{
            "_id": self.user_id,
            "username": "Gardener",
            "email": "owner@example.com",
            "password": "private-hash",
            "role": "user",
        }])
        self.products = FakeCollection([{
            "_id": self.product_id,
            "name": "Garden fork",
            "description": "Stainless tool",
            "category": "Equipment",
            "price": 12.5,
            "createdAt": datetime(2026, 1, 1),
        }])
        for name, collection in (("users_collection", self.users),
                                 ("products_collection", self.products)):
            patcher = patch(f"routes.search.{name}", collection)
            patcher.start()
            self.addCleanup(patcher.stop)
        # No lifespan context: these route tests must not seed or connect to MongoDB.
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_searches_both_collections_and_serializes_results(self):
        response = self.client.get("/api/search", params={"q": "  GARDEN  "})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["users"][0]["id"], str(self.user_id))
        self.assertEqual(data["products"][0]["id"], str(self.product_id))
        self.assertEqual(data["products"][0]["createdAt"], "2026-01-01T00:00:00")
        self.assertNotIn("private-hash", response.text)
        self.assertNotIn("password", response.text)
        self.assertNotIn("password", self.users.calls[0][1])

    def test_searches_email_and_each_product_text_field(self):
        for term, users, products in (
            ("EXAMPLE.COM", 1, 0), ("fork", 0, 1),
            ("stainless", 0, 1), ("equipment", 0, 1),
        ):
            with self.subTest(term=term):
                data = self.client.get("/api/search", params={"q": term}).json()
                self.assertEqual(len(data["users"]), users)
                self.assertEqual(len(data["products"]), products)

    def test_regex_metacharacters_are_literal(self):
        self.users.documents[0]["username"] = "literal.*name"
        data = self.client.get("/api/search", params={"q": ".*"}).json()
        self.assertEqual(len(data["users"]), 1)
        self.assertEqual(data["products"], [])

    def test_no_matches_returns_empty_groups(self):
        response = self.client.get("/api/search", params={"q": "missing"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"users": [], "products": []})

    def test_missing_empty_or_blank_query_is_rejected_before_database_access(self):
        for params in ({}, {"q": ""}, {"q": "   "}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/api/search", params=params).status_code, 422)
        self.assertEqual(self.users.calls, [])
        self.assertEqual(self.products.calls, [])


if __name__ == "__main__":
    unittest.main()
