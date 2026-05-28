# IDChanger

A web tool to remap column values across PostgreSQL and SQL Server databases.

## Features

- Connect to multiple PostgreSQL and SQL Server databases
- Browse schemas, tables, and columns
- Define value conversion mappings in the UI (old value → new value)
- Preview affected rows before committing
- Apply changes with a single click

## Setup

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000

## SQL Server note

You need the Microsoft ODBC Driver installed on the host machine.  
On Ubuntu: `apt-get install msodbcsql17`  
On macOS: `brew install msodbcsql17`
