from graphql.execution.executors.asyncio import AsyncioExecutor
from starlette.applications import Starlette
from starlette.graphql import GraphQLApp
from starlette.testclient import TestClient
import graphene


class Query(graphene.ObjectType):
    hello = graphene.String(name=graphene.String(default_value="stranger"))

    def resolve_hello(self, info, name):
        return "Hello " + name


schema = graphene.Schema(query=Query)
app = GraphQLApp(schema=schema)
client = TestClient(app)


def test_graphql_get():
    response = client.get("/?query={ hello }")
    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello stranger"}, "errors": None}


def test_graphql_post():
    response = client.post("/?query={ hello }")
    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello stranger"}, "errors": None}


def test_graphql_post_json():
    response = client.post("/", json={"query": "{ hello }"})
    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello stranger"}, "errors": None}


def test_graphql_post_graphql():
    response = client.post(
        "/", data="{ hello }", headers={"content-type": "application/graphql"}
    )
    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello stranger"}, "errors": None}


def test_graphql_post_invalid_media_type():
    response = client.post("/", data="{ hello }", headers={"content-type": "dummy"})
    assert response.status_code == 415
    assert response.text == "Unsupported Media Type"


def test_graphql_put():
    response = client.put("/", json={"query": "{ hello }"})
    assert response.status_code == 405
    assert response.text == "Method Not Allowed"


def test_graphql_no_query():
    response = client.get("/")
    assert response.status_code == 400
    assert response.text == "No GraphQL query found in the request"


def test_graphql_invalid_field():
    response = client.post("/", json={"query": "{ dummy }"})
    assert response.status_code == 400
    assert response.json() == {
        "data": None,
        "errors": [
            {
                "locations": [{"column": 3, "line": 1}],
                "message": 'Cannot query field "dummy" on type "Query".',
            }
        ],
    }


def test_graphiql_get():
    response = client.get("/", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text


def test_add_graphql_route():
    app = Starlette()
    app.add_graphql_route("/", schema)
    client = TestClient(app)
    response = client.get("/?query={ hello }")
    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello stranger"}, "errors": None}


class ASyncQuery(graphene.ObjectType):
    hello = graphene.String(name=graphene.String(default_value="stranger"))

    async def resolve_hello(self, info, name):
        return "Hello " + name


async_schema = graphene.Schema(query=ASyncQuery)
async_app = GraphQLApp(schema=async_schema, executor=AsyncioExecutor())


def test_graphql_async():
    client = TestClient(async_app)
    response = client.get("/?query={ hello }")
    assert response.status_code == 200
    assert response.json() == {"data": {"hello": "Hello stranger"}, "errors": None}
