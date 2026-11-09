import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bson import ObjectId
from fastapi.testclient import TestClient
from jose import jwt

from main import app
from security.jwt_handler import ALGORITHM, SECRET_KEY, create_token


def object_id(number):
    return ObjectId(f"{number:024x}")


class FakeCursor:
    """Implement Motor's sort/limit/async iteration without database access."""

    def __init__(self, documents, projection):
        self.documents = documents
        self.projection = projection
        self.sort_fields = None
        self.result_limit = None

    def sort(self, fields):
        self.sort_fields = fields
        for field, direction in reversed(fields):
            self.documents.sort(key=lambda doc: doc[field], reverse=direction == -1)
        return self

    def limit(self, count):
        self.result_limit = count
        return self

    def __aiter__(self):
        async def results():
            for document in self.documents[:self.result_limit]:
                yield {field: value for field, value in document.items()
                       if self.projection.get(field)}

        return results()


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.find_calls = []
        self.find_one_calls = []

    async def find_one(self, query):
        self.find_one_calls.append(query)
        return next((dict(doc) for doc in self.documents if doc["_id"] == query["_id"]), None)

    def find(self, query, projection):
        def matches(document):
            return any(
                re.search(expression["$regex"], document.get(field) or "",
                          re.I if "i" in expression.get("$options", "") else 0)
                for clause in query.get("$or", [query])
                for field, expression in clause.items()
            )

        cursor = FakeCursor([dict(doc) for doc in self.documents if matches(doc)], projection)
        self.find_calls.append((query, projection, cursor))
        return cursor


class GlobalSearchTests(unittest.TestCase):
    def setUp(self):
        self.auth_user = {"_id": object_id(100), "username": "viewer", "role": "user"}
        self.auth_users = FakeCollection([self.auth_user])
        self.users = FakeCollection([{
            "_id": object_id(1), "username": "Gardener", "role": "user",
            "email": "private@example.com", "password": "secret",
            "passwordHash": "secret-hash", "createdAt": datetime(2026, 1, 1),
            "lastActiveAt": datetime(2026, 1, 2),
        }])
        self.products = FakeCollection([{
            "_id": object_id(2), "name": "Garden fork", "category": "Equipment",
            "description": "Stainless tool", "price": 12.5, "stock": 10,
            "createdAt": datetime(2026, 1, 1), "updatedAt": datetime(2026, 1, 2),
        }])
        for target, collection in (
            ("security.jwt_handler.users_collection", self.auth_users),
            ("routes.search.users_collection", self.users),
            ("routes.search.products_collection", self.products),
        ):
            patcher = patch(target, collection)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Deliberately avoid the lifespan context so startup never seeds MongoDB.
        # Keep the real authentication dependency and JWT verification enabled.
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + create_token(
            str(self.auth_user["_id"]), "viewer", "user"
        )}

    def search(self, term):
        return self.client.get("/api/search", params={"q": term}, headers=self.headers)

    def assert_no_search(self):
        self.assertEqual(self.users.find_calls, [])
        self.assertEqual(self.products.find_calls, [])

    def test_missing_token_returns_401_even_without_query(self):
        for params in ({}, {"q": "garden"}):
            self.assertEqual(self.client.get("/api/search", params=params).status_code, 401)
        self.assert_no_search()

    def test_invalid_tokens_return_401(self):
        wrong_signature = jwt.encode(
            {"sub": str(self.auth_user["_id"])}, SECRET_KEY + "-wrong", algorithm=ALGORITHM
        )
        for authorization in ("Bearer garbage", "Bearer " + wrong_signature, "Basic abc"):
            with self.subTest(authorization=authorization.split()[0]):
                response = self.client.get("/api/search", params={"q": "garden"},
                                           headers={"Authorization": authorization})
                self.assertEqual(response.status_code, 401)
        self.assert_no_search()

    def test_expired_token_returns_401(self):
        token = jwt.encode({
            "sub": str(self.auth_user["_id"]),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }, SECRET_KEY, algorithm=ALGORITHM)
        response = self.client.get("/api/search", params={"q": "garden"},
                                   headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 401)
        self.assert_no_search()

    def test_missing_or_malformed_subject_returns_401(self):
        for payload in ({}, {"sub": "invalid-id"}, {"sub": 123}):
            with self.subTest(payload=payload):
                token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
                response = self.client.get("/api/search", params={"q": "garden"},
                                           headers={"Authorization": "Bearer " + token})
                self.assertEqual(response.status_code, 401)
        self.assert_no_search()

    def test_token_for_missing_user_returns_401(self):
        self.auth_users.documents = []
        self.assertEqual(self.search("garden").status_code, 401)
        self.assert_no_search()

    def test_valid_authentication_and_exact_response_fields(self):
        response = self.search("garden")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "users": [{"id": str(object_id(1)), "username": "Gardener", "role": "user"}],
            "products": [{"id": str(object_id(2)), "name": "Garden fork",
                          "category": "Equipment", "price": 12.5}],
        })
        self.assertEqual(len(self.auth_users.find_one_calls), 1)
        self.assertEqual(set(self.users.find_calls[0][1]), {"_id", "username", "role"})
        self.assertEqual(set(self.products.find_calls[0][1]), {"_id", "name", "category", "price"})

    def test_invalid_queries_return_400_before_search(self):
        for params in ({}, {"q": ""}, {"q": " \t\n "}, {"q": "a"},
                       {"q": " a "}, {"q": "x" * 51}):
            with self.subTest(params=params):
                response = self.client.get("/api/search", params=params, headers=self.headers)
                self.assertEqual(response.status_code, 400)
        self.assert_no_search()

    def test_query_length_boundaries_are_valid_after_trimming(self):
        for term in (" ab ", " " + "x" * 50 + " "):
            with self.subTest(term=term):
                self.assertEqual(self.search(term).status_code, 200)

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(self.search(" \t garden \n").json(), self.search("garden").json())
        self.assertEqual(self.users.find_calls[0][0]["username"]["$regex"], "garden")

    def test_matching_is_case_insensitive(self):
        self.assertEqual(self.search("GARDEN").json(), self.search("garden").json())
        self.assertEqual(len(self.search("GARDEN").json()["users"]), 1)
        self.assertEqual(len(self.search("GARDEN").json()["products"]), 1)

    def test_description_is_searchable(self):
        data = self.search("STAINLESS").json()
        self.assertEqual(data["users"], [])
        self.assertEqual(len(data["products"]), 1)

    def test_email_role_and_category_are_not_searchable(self):
        for term in ("private@example.com", "user", "Equipment"):
            with self.subTest(term=term):
                self.assertEqual(self.search(term).json(), {"users": [], "products": []})

    def test_regex_characters_match_literally(self):
        for term in (".*", "(a"):
            with self.subTest(term=term):
                self.users.documents.append({
                    "_id": object_id(3), "username": "literal" + term, "role": "user",
                })
                self.products.documents.append({
                    "_id": object_id(4), "name": "Literal tool", "description": term,
                    "category": "Tools", "price": 0,
                })
                response = self.search(term)
                self.assertEqual(response.status_code, 200)
                self.assertEqual([u["id"] for u in response.json()["users"]], [str(object_id(3))])
                self.assertEqual([p["id"] for p in response.json()["products"]], [str(object_id(4))])
                self.users.documents.pop()
                self.products.documents.pop()

    def test_limits_and_stable_order_include_id_tiebreaker(self):
        # Reverse insertion order with duplicate names ensures sorting precedes limiting.
        names = ["Match A", "Match A", "Match A", "Match B", "Match B", "Match C", "Match D"]
        self.users.documents = [
            {"_id": object_id(i), "username": name, "role": "user"}
            for i, name in reversed(list(enumerate(names, 1)))
        ]
        self.products.documents = [
            {"_id": object_id(i), "name": name, "category": None, "price": 0}
            for i, name in reversed(list(enumerate(names, 1)))
        ]
        data = self.search("match").json()
        for group in ("users", "products"):
            self.assertEqual(len(data[group]), 5)
            self.assertEqual([item["id"] for item in data[group]],
                             [str(object_id(i)) for i in range(1, 6)])
        self.users.documents.reverse()
        self.products.documents.reverse()
        self.assertEqual(self.search("match").json(), data)
        for collection, field in ((self.users, "username"), (self.products, "name")):
            cursor = collection.find_calls[0][2]
            self.assertEqual(cursor.sort_fields, [(field, 1), ("_id", 1)])
            self.assertEqual(cursor.result_limit, 5)

    def test_no_matches_returns_two_empty_lists(self):
        response = self.search("absent")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"users": [], "products": []})


if __name__ == "__main__":
    unittest.main()
