# Standalone Architecture Sample

This folder is a small project reality sample for ArchitecturalKnowledgeDB. It
contains one informal document, one ADR, one Mermaid diagram, and structured
rule/definition/source-area files.

Import it into an empty local database:

```powershell
python -m architectural_knowledge_db.cli setup --project standalone-sample --name "Standalone Sample" --target Temp\akdb-sample --no-import
python -m architectural_knowledge_db.cli adr import --project standalone-sample --folder docs\examples\standalone-sample\adr
python -m architectural_knowledge_db.cli document import --project standalone-sample --folder docs\examples\standalone-sample\docs
python -m architectural_knowledge_db.cli uml import --project standalone-sample --folder docs\examples\standalone-sample\uml
python -m architectural_knowledge_db.cli rule import --project standalone-sample --file docs\examples\standalone-sample\knowledge\rules.json
python -m architectural_knowledge_db.cli definition import --project standalone-sample --file docs\examples\standalone-sample\knowledge\definitions.json
python -m architectural_knowledge_db.cli source-area import --project standalone-sample --file docs\examples\standalone-sample\knowledge\source_areas.json
```
