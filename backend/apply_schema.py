"""Applies schema.sql to ClickHouse Cloud through mcp-clickhouse (write access).

Run once: python -m backend.apply_schema
"""

import asyncio
import json
import pathlib

from backend.mcp_client import clickhouse_session, _first_text

SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


async def main():
    statements = [
        s.strip() for s in SCHEMA_PATH.read_text().split(";") if s.strip()
    ]
    async with clickhouse_session(allow_write=True) as session:
        for statement in statements:
            table_name = statement.split("IF NOT EXISTS", 1)[1].split("(", 1)[0].strip()
            result = await session.call_tool("run_query", {"query": statement})
            if result.is_error:
                raise RuntimeError(f"failed on {table_name}: {_first_text(result)}")
            print(f"applied: {table_name} -> {json.loads(_first_text(result))}")


if __name__ == "__main__":
    asyncio.run(main())
