# Third-Party Software

AKDB does not bundle external runtime services. It uses Python package dependencies declared in `pyproject.toml`.

## Runtime Dependencies

| Dependency | Purpose |
| --- | --- |
| `fastapi` | Local HTTP API. |
| `pydantic` | Request/response and data validation models. |
| `typer` | CLI command framework. |
| `uvicorn` | ASGI server for `akdb serve`. |
| `PyYAML` | YAML registry and document parsing. |

SQLite is used through Python's standard library. Git provenance scans use the local `git` executable when repository metadata is requested.

## Test Dependencies

| Dependency | Purpose |
| --- | --- |
| `pytest` | Test runner. |
| `httpx` | API test client support. |

## External Services

None are required for the default local workflow. Optional semantic recall can use an embedding endpoint via `AKDB_EMBED_URL`, but lexical search and context packs work without it.
