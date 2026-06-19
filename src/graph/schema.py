"""Neo4j schema constraints for InterOpera compliance graph."""
from __future__ import annotations

CONSTRAINTS = [
    "CREATE CONSTRAINT position_id IF NOT EXISTS FOR (p:Position) REQUIRE p.instrument_id IS UNIQUE",
    "CREATE CONSTRAINT asset_class_name IF NOT EXISTS FOR (a:AssetClass) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT asset_class_slug IF NOT EXISTS FOR (a:AssetClass) REQUIRE a.slug IS UNIQUE",
    "CREATE CONSTRAINT issuer_name IF NOT EXISTS FOR (i:Issuer) REQUIRE i.name IS UNIQUE",
    "CREATE CONSTRAINT parent_issuer_name IF NOT EXISTS FOR (pi:ParentIssuer) REQUIRE pi.name IS UNIQUE",
    "CREATE CONSTRAINT source_chunk_id IF NOT EXISTS FOR (sc:SourceChunk) REQUIRE sc.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT limit_ref IF NOT EXISTS FOR (l:Limit) REQUIRE l.ref IS UNIQUE",
]


def apply_schema(driver) -> None:
    """Apply all Neo4j constraints."""
    with driver.session() as session:
        for constraint in CONSTRAINTS:
            session.run(constraint)
