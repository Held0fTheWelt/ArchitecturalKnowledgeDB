# FAQ

## Is AKDB tied to Unreal Engine?

No. AKDB is a standalone Python tool. It can index Unreal/Tiny Tools architecture documents, but it is not an Unreal plugin and does not require Unreal Engine.

## Does AKDB copy another repository into its database?

No. AKDB imports selected documents and stores selected Git metadata. It does not copy `.git`, and it should not keep exported external corpora committed inside this repository.

## Does the Git scanner modify source repositories?

No. Repository scanning is read-only.

## Where should Tiny Tools SAD and UML live?

In the Tiny Tool workspace, cross-project SAD/UML authority lives in `D:\TinyToolDevelopment\Git\docs` and `D:\TinyToolDevelopment\Git\UML`. AKDB can index it, but AKDB is not the authority folder for those files.

## Where do user-facing showcase scripts live?

In the Tiny Tool workspace, public showcase/user scripts live under `D:\TinyToolDevelopment\Git\Tools`, with user scripts under `D:\TinyToolDevelopment\Git\Tools\User`.

## Can agents use AKDB?

Yes. Agents can use CLI commands, HTTP endpoints, or the `akdb-mcp` stdio server. MCP is the preferred direct integration for clients that support it.

## What should I commit?

Commit source code, tests, AKDB docs, contracts, schema, examples, and AKDB-owned specs. Do not commit `.akdb/`, `Temp/`, `exports/`, live SQLite files, or generated imports from other repositories.
