import databases
import pytest
import sqlalchemy

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

DATABASE_URL = "sqlite:///test.db"

metadata = sqlalchemy.MetaData()

notes = sqlalchemy.Table(
    "notes",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("text", sqlalchemy.String(length=100)),
    sqlalchemy.Column("completed", sqlalchemy.Boolean),
)


pytestmark = pytest.mark.usefixtures("no_trio_support")


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


database = databases.Database(DATABASE_URL, force_rollback=True)


async def startup():
    await database.connect()


async def shutdown():
    await database.disconnect()


async def list_notes(request: Request):
    query = notes.select()
    results = await database.fetch_all(query)
    content = [
        {"text": result["text"], "completed": result["completed"]} for result in results
    ]
    return JSONResponse(content)


@database.transaction()
async def add_note(request: Request):
    data = await request.json()
    query = notes.insert().values(text=data["text"], completed=data["completed"])
    await database.execute(query)
    if "raise_exc" in request.query_params:
        raise RuntimeError()
    return JSONResponse({"text": data["text"], "completed": data["completed"]})


async def bulk_create_notes(request: Request):
    data = await request.json()
    query = notes.insert()
    await database.execute_many(query, data)
    return JSONResponse({"notes": data})


async def read_note(request: Request):
    note_id = request.path_params["note_id"]
    query = notes.select().where(notes.c.id == note_id)
    result = await database.fetch_one(query)
    assert result is not None
    content = {"text": result["text"], "completed": result["completed"]}
    return JSONResponse(content)


async def read_note_text(request: Request):
    note_id = request.path_params["note_id"]
    query = sqlalchemy.select([notes.c.text]).where(notes.c.id == note_id)
    result = await database.fetch_one(query)
    assert result is not None
    return JSONResponse(result[0])


app = Starlette(
    routes=[
        Route("/notes", endpoint=list_notes, methods=["GET"]),
        Route("/notes", endpoint=add_note, methods=["POST"]),
        Route("/notes/bulk_create", endpoint=bulk_create_notes, methods=["POST"]),
        Route("/notes/{note_id:int}", endpoint=read_note, methods=["GET"]),
        Route("/notes/{note_id:int}/text", endpoint=read_note_text, methods=["GET"]),
    ],
    on_startup=[startup],
    on_shutdown=[shutdown],
)


def test_database(test_client_factory):
    with test_client_factory(app) as client:
        response = client.post(
            "/notes", json={"text": "buy the milk", "completed": True}
        )
        assert response.status_code == 200

        with pytest.raises(RuntimeError):
            response = client.post(
                "/notes",
                json={"text": "you wont see me", "completed": False},
                params={"raise_exc": "true"},
            )

        response = client.post(
            "/notes", json={"text": "walk the dog", "completed": False}
        )
        assert response.status_code == 200

        response = client.get("/notes")
        assert response.status_code == 200
        assert response.json() == [
            {"text": "buy the milk", "completed": True},
            {"text": "walk the dog", "completed": False},
        ]

        response = client.get("/notes/1")
        assert response.status_code == 200
        assert response.json() == {"text": "buy the milk", "completed": True}

        response = client.get("/notes/1/text")
        assert response.status_code == 200
        assert response.json() == "buy the milk"


def test_database_execute_many(test_client_factory):
    with test_client_factory(app) as client:
        data = [
            {"text": "buy the milk", "completed": True},
            {"text": "walk the dog", "completed": False},
        ]
        response = client.post("/notes/bulk_create", json=data)
        assert response.status_code == 200

        response = client.get("/notes")
        assert response.status_code == 200
        assert response.json() == [
            {"text": "buy the milk", "completed": True},
            {"text": "walk the dog", "completed": False},
        ]


def test_database_isolated_during_test_cases(test_client_factory):
    """
    Using `TestClient` as a context manager
    """
    with test_client_factory(app) as client:
        response = client.post(
            "/notes", json={"text": "just one note", "completed": True}
        )
        assert response.status_code == 200

        response = client.get("/notes")
        assert response.status_code == 200
        assert response.json() == [{"text": "just one note", "completed": True}]

    with test_client_factory(app) as client:
        response = client.post(
            "/notes", json={"text": "just one note", "completed": True}
        )
        assert response.status_code == 200

        response = client.get("/notes")
        assert response.status_code == 200
        assert response.json() == [{"text": "just one note", "completed": True}]
