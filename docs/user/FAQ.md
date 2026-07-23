# FAQ

## Is AKDB tied to Unreal Engine?

No. AKDB is a standalone Python tool. It can index Unreal/Tiny Tools architecture documents, but it is not an Unreal plugin and does not require Unreal Engine.

## Does AKDB copy another repository into its database?

No. AKDB imports selected documents and stores selected Git metadata. It does not copy `.git`, and it should not keep exported external corpora committed inside this repository.

## Does the Git scanner modify source repositories?

No. Repository scanning is read-only.

## Where should Tiny Tools SAD and UML live?

AKDB's own SAD/UML is authored in the `architectural-knowledge-db` database project and exported
to this repository's `docs/architecture`. Other tools and platform-wide architecture remain owned
by their respective repositories; AKDB may index or relate them without copying their authority.

## Where do user-facing showcase scripts live?

In the repository that owns the showcased tool. Tiny Tool Observatory may discover or present it,
but neither AKDB nor the Observatory should become an accidental source-code copy.

## Can agents use AKDB?

Yes. Agents can use CLI commands, HTTP endpoints, or the `akdb-mcp` stdio server. MCP is the preferred direct integration for clients that support it.

## What should I commit?

Commit source code, tests, AKDB docs, contracts, schema, examples, and the generated projection of
AKDB-owned SAD/UML. Do not commit `.akdb/`, `Temp/`, `exports/`, live databases, backups,
embeddings, imported corpora, or exports owned by other repositories.
