"""
QuickBase SQL Translator Client
This client acts as a wrapper around the QBConn class, allowing users to
execute common SQL commands to interact with the QuickBase API.

AUTHOR: Jose Santiago Echevarria
VERSION: 2.0.0
UPDATED: 2025-08-11

NOTE: This is a translation layer, not a full SQL engine. It supports a
specific subset of SQL commands and has a simplified WHERE clause syntax.
"""
import re
import sys
from typing import Dict, Any, Optional, List

# Ensure the core client is available
try:
    from quickbase_rest_client import QBConn, QuickBaseError, FieldType
except ImportError:
    print("Error: Make sure 'quickbase_rest_client.py' is in the same directory.")
    sys.exit(1)

# Mapping of common SQL data types to QuickBase FieldTypes
SQL_TYPE_TO_QB_FIELD_TYPE = {
    "text": FieldType.TEXT,
    "varchar": FieldType.TEXT,
    "char": FieldType.TEXT,
    "int": FieldType.NUMERIC,
    "integer": FieldType.NUMERIC,
    "number": FieldType.NUMERIC,
    "numeric": FieldType.NUMERIC,
    "float": FieldType.NUMERIC,
    "date": FieldType.DATE,
    "datetime": FieldType.DATETIME,
    "timestamp": FieldType.DATETIME,
    "bool": FieldType.CHECKBOX,
    "boolean": FieldType.CHECKBOX,
}


class QBSQLClient:
    """
    A client that translates a subset of SQL commands into QuickBase API calls.

    This class provides a high-level interface for developers familiar with SQL
    to perform data (CRUD) and schema (DDL) operations without needing to
    construct the raw API payloads manually.

    Supported SQL Commands:
    - SELECT [TOP n] col1, col2 FROM table WHERE ... ORDER BY ... LIMIT n OFFSET n
    - INSERT INTO table (col1, col2) VALUES (val1, val2)
    - UPDATE table SET col1 = val1 WHERE ...
    - DELETE FROM table WHERE ...
    - CREATE TABLE table (col1 TYPE, col2 TYPE)
    - ALTER TABLE table ADD COLUMN col TYPE
    - ALTER TABLE table DROP COLUMN col
    - ALTER TABLE table RENAME COLUMN old TO new
    - ALTER TABLE table RENAME TO new_name
    - DROP TABLE table

    Limitations:
    - WHERE Clause Syntax: You must use Quickbase's query syntax, but you can
      use field names in quotes instead of field IDs. The client translates the names.
      Example: `WHERE 'Status' EX 'In Progress' AND 'Value' > 100`
    - JOINs: Explicit `JOIN` keywords are NOT supported. To query data from related
      (parent) tables, simply include the lookup field name from the child table
      in your SELECT statement. The client will resolve it to the correct lookup field ID.
    - Aggregations: Functions like COUNT(), SUM(), AVG() are not supported in queries.
      These must be configured in a Quickbase Report and executed via the run_report() method.
    """

    def __init__(self, qb_conn: QBConn):
        """
        Initializes the SQL client with an authenticated QBConn instance.

        Args:
            qb_conn: An initialized and authenticated instance of the QBConn client.
        """
        if not isinstance(qb_conn, QBConn):
            raise TypeError("qb_conn must be an instance of the QBConn class.")
        self.qb = qb_conn
        self._schema_cache: Dict[str, Any] = {}
        print("QBSQLClient initialized. Caching schema for default app...")
        self._warm_up_cache()

    def _warm_up_cache(self):
        """Pre-fetches table and field info for the default app_id if available."""
        if self.qb.app_id:
            try:
                tables = self.qb.get_tables()
                if tables:
                    for table in tables:
                        table_id = table.get('id')
                        if table_id:
                            self._load_schema_for_table(table_id)
                print("Schema cache is ready.")
            except QuickBaseError as e:
                print(f"Warning: Could not warm up schema cache for app '{self.qb.app_id}': {e}")
        else:
            print("No default app_id set in QBConn; schema will be cached on demand.")


    def _load_schema_for_table(self, table_id: str):
        """Loads and caches the fields for a given table ID."""
        if table_id not in self._schema_cache:
            fields = self.qb.get_fields(table_id)
            if fields:
                self._schema_cache[table_id] = {
                    "name_to_id": {f["label"].lower(): f["id"] for f in fields},
                    "id_to_name": {f["id"]: f["label"] for f in fields},
                }

    def _get_table_id(self, table_name: str) -> str:
        """Translates a table name to its ID."""
        # Sanitize quoted table names
        table_name = table_name.strip("'\"`")
        table_id = self.qb.get_table_id_by_name(table_name)
        if not table_id:
            raise QuickBaseError(f"Table '{table_name}' not found in app '{self.qb.app_id}'.")
        return table_id

    def _get_field_id(self, table_id: str, field_name: str) -> int:
        """Translates a field name to its ID for a given table."""
        self._load_schema_for_table(table_id)
        # Sanitize quoted field names
        field_name = field_name.strip("'\"`")
        field_name_lower = field_name.lower()

        if table_id in self._schema_cache and field_name_lower in self._schema_cache[table_id]["name_to_id"]:
            return self._schema_cache[table_id]["name_to_id"][field_name_lower]
        
        # Fallback to a fresh API call if not in cache (and update cache)
        self.qb.clear_cache() # Force refresh
        self._load_schema_for_table(table_id)
        if table_id in self._schema_cache and field_name_lower in self._schema_cache[table_id]["name_to_id"]:
             return self._schema_cache[table_id]["name_to_id"][field_name_lower]

        raise QuickBaseError(f"Field '{field_name}' not found in table '{table_id}'.")

    def _translate_where_clause(self, where_sql: str, table_id: str) -> str:
        """Translates a Quickbase-like WHERE clause with field names into a valid Quickbase query."""
        if not where_sql:
            return ""

        # Find all field names enclosed in single quotes
        field_names = re.findall(r"['\"]([^'\"]+)['\"]", where_sql)
        
        qb_query = where_sql
        for name in set(field_names):
            field_id = self._get_field_id(table_id, name)
            # Replace the quoted name with the field ID for QB query syntax
            qb_query = qb_query.replace(f"'{name}'", str(field_id)).replace(f'"{name}"', str(field_id))

        # This simple replacement relies on the user providing valid QB operators (e.g., EX, CT, GT)
        # It's a translation of names to IDs, not a full SQL syntax conversion.
        return qb_query

    def execute(self, sql: str) -> Any:
        """
        Parses and executes a SQL command.

        Args:
            sql: The SQL command string to execute.

        Returns:
            The result of the operation, which varies by command type.
        """
        sql = sql.strip()
        sql_upper = sql.upper()

        if sql_upper.startswith("SELECT"):
            return self._execute_select(sql)
        elif sql_upper.startswith("INSERT"):
            return self._execute_insert(sql)
        elif sql_upper.startswith("UPDATE"):
            return self._execute_update(sql)
        elif sql_upper.startswith("DELETE"):
            return self._execute_delete(sql)
        elif sql_upper.startswith("CREATE TABLE"):
            return self._execute_create_table(sql)
        elif sql_upper.startswith("ALTER TABLE"):
            return self._execute_alter_table(sql)
        elif sql_upper.startswith("DROP TABLE"):
            return self._execute_drop_table(sql)
        else:
            raise NotImplementedError("This SQL command is not supported.")

    def _execute_select(self, sql: str):
        """Handler for SELECT queries."""
        pattern = re.compile(
            r"SELECT\s+(?:TOP\s+(?P<top>\d+)\s+)?(?P<columns>.+?)\s+FROM\s+(['\"]?[\w\s]+['\"]?)"
            r"(?:\s+WHERE\s+(?P<where>.+?))?"
            r"(?:\s+ORDER BY\s+(?P<orderby>.+?))?"
            r"(?:(?:\s+LIMIT\s+(?P<limit>\d+))?(?:\s+OFFSET\s+(?P<offset>\d+))?)?;?",
            re.IGNORECASE | re.DOTALL
        )
        match = pattern.match(sql)
        if not match:
            raise ValueError("Invalid SELECT statement format.")

        parts = match.groupdict()
        table_name = match.groups()[1]
        table_id = self._get_table_id(table_name)
        self._load_schema_for_table(table_id)

        # Translate column names
        select_fids = []
        if parts["columns"].strip() == "*":
            select_fids = list(self._schema_cache[table_id]["id_to_name"].keys())
        else:
            columns = [c.strip() for c in parts["columns"].split(",")]
            select_fids = [self._get_field_id(table_id, col) for col in columns]

        where_clause = self._translate_where_clause(parts.get("where") or "", table_id)

        # Translate ORDER BY
        sort_by = []
        if parts.get("orderby"):
            clauses = [c.strip() for c in parts["orderby"].split(",")]
            for clause in clauses:
                col_name, *order = clause.split()
                sort_by.append({
                    "fieldId": self._get_field_id(table_id, col_name.strip()),
                    "order": "DESC" if order and order[0].upper() == "DESC" else "ASC"
                })
        
        # Handle TOP, LIMIT, and OFFSET
        options = {}
        top_val = parts.get("top") or parts.get("limit")
        if top_val:
            options["top"] = int(top_val)
        if parts.get("offset"):
            options["skip"] = int(parts["offset"])

        return self.qb.query_records(
            table_id=table_id,
            select=select_fids,
            where=where_clause if where_clause else None,
            sort_by=sort_by if sort_by else None,
            options=options if options else None
        )

    def _execute_insert(self, sql: str):
        """Handler for INSERT statements."""
        pattern = re.compile(r"INSERT INTO\s+(['\"]?[\w\s]+['\"]?)\s*\((.+?)\)\s*VALUES\s*\((.+?)\);?", re.IGNORECASE | re.DOTALL)
        match = pattern.match(sql)
        if not match:
            raise ValueError("Invalid INSERT. Use `INSERT INTO table (col1, col2) VALUES ('val1', 'val2')`")

        table_name, columns_str, values_str = match.groups()
        table_id = self._get_table_id(table_name)
        
        columns = [c.strip() for c in columns_str.split(",")]
        # Simple CSV-like split for values to handle commas inside quotes
        values = [v.strip().strip("'\"") for v in re.split(r",(?=(?:[^']*'[^']*')*[^']*$)", values_str)]

        if len(columns) != len(values):
            raise ValueError("Column and value counts do not match.")

        record = {self._get_field_id(table_id, col): val for col, val in zip(columns, values)}
        
        # For pure INSERTs, merge field is irrelevant but required. Record ID #3 is ignored for new records.
        return self.qb.upsert_records(table_id, [record], merge_field_id=3)

    def _execute_update(self, sql: str):
        """Handler for UPDATE statements."""
        pattern = re.compile(r"UPDATE\s+(['\"]?[\w\s]+['\"]?)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?;?", re.IGNORECASE | re.DOTALL)
        match = pattern.match(sql)
        if not match:
            raise ValueError("Invalid UPDATE statement format.")
        
        table_name, set_str, where_str = match.groups()
        if not where_str:
            raise ValueError("UPDATE statements without a WHERE clause are not supported for safety.")

        table_id = self._get_table_id(table_name)
        qb_where = self._translate_where_clause(where_str, table_id)
        
        records_to_update = self.qb.query_records(table_id, where=qb_where, select=[3])
        if not records_to_update or not records_to_update.get("data"):
            return {"message": "No records found matching the WHERE clause. Nothing to update."}
        
        record_ids = [r['3']['value'] for r in records_to_update['data']]
        
        set_clauses = [s.strip() for s in re.split(r",(?=(?:[^']*'[^']*')*[^']*$)", set_str)]
        update_data = {}
        for clause in set_clauses:
            col_name, value = [p.strip().strip("'\"") for p in clause.split("=")]
            update_data[self._get_field_id(table_id, col_name)] = value
            
        records_payload = [{3: rid, **update_data} for rid in record_ids]
            
        return self.qb.upsert_records(table_id, records_payload, merge_field_id=3)

    def _execute_delete(self, sql: str):
        """Handler for DELETE statements."""
        pattern = re.compile(r"DELETE FROM\s+(['\"]?[\w\s]+['\"]?)(?:\s+WHERE\s+(.+))?;?", re.IGNORECASE | re.DOTALL)
        match = pattern.match(sql)
        if not match:
            raise ValueError("Invalid DELETE statement format.")
        
        table_name, where_str = match.groups()
        if not where_str:
            raise ValueError("DELETE statements without a WHERE clause are not supported for safety.")
        
        table_id = self._get_table_id(table_name)
        qb_where = self._translate_where_clause(where_str, table_id)

        return self.qb.delete_records(table_id, where=qb_where)
        
    def _execute_create_table(self, sql: str):
        """Handler for CREATE TABLE statements."""
        pattern = re.compile(r"CREATE TABLE\s+(['\"]?[\w\s]+['\"]?)\s*\((.+)\);?", re.IGNORECASE | re.DOTALL)
        match = pattern.match(sql)
        if not match:
            raise ValueError("Invalid CREATE TABLE format.")
        
        table_name, columns_str = match.groups()
        if not self.qb.app_id:
            raise QuickBaseError("An app_id must be set in the QBConn client to create a table.")

        table = self.qb.create_table(self.qb.app_id, table_name.strip("'\""))
        if not table or not table.get("id"):
            raise QuickBaseError(f"Failed to create table '{table_name}'.")
        table_id = table['id']
        
        columns = [c.strip() for c in columns_str.split(",")]
        for col in columns:
            col_name, col_type = col.split(None, 1) # Split only on the first space
            qb_type = SQL_TYPE_TO_QB_FIELD_TYPE.get(col_type.lower().split('(')[0], FieldType.TEXT)
            self.qb.create_field(table_id, col_name, qb_type)
        
        return {"message": f"Table '{table_name}' and fields created successfully.", "tableId": table_id}

    def _execute_alter_table(self, sql: str):
        """Handler for ALTER TABLE statements."""
        sql = sql.strip().rstrip(';')
        
        # RENAME TO
        rename_match = re.match(r"ALTER TABLE\s+(['\"]?[\w\s]+['\"]?)\s+RENAME TO\s+(['\"]?[\w\s]+['\"]?)", sql, re.IGNORECASE)
        if rename_match:
            old_name, new_name = [n.strip("'\"") for n in rename_match.groups()]
            table_id = self._get_table_id(old_name)
            return self.qb.update_table(table_id, self.qb.app_id, {"name": new_name})

        # ADD COLUMN
        add_match = re.match(r"ALTER TABLE\s+(['\"]?[\w\s]+['\"]?)\s+ADD COLUMN\s+(['\"]?[\w\s]+['\"]?)\s+([\w\(\)]+)", sql, re.IGNORECASE)
        if add_match:
            table_name, col_name, col_type = [c.strip("'\"") for c in add_match.groups()]
            table_id = self._get_table_id(table_name)
            qb_type = SQL_TYPE_TO_QB_FIELD_TYPE.get(col_type.lower().split('(')[0], FieldType.TEXT)
            return self.qb.create_field(table_id, col_name, qb_type)

        # DROP COLUMN
        drop_match = re.match(r"ALTER TABLE\s+(['\"]?[\w\s]+['\"]?)\s+DROP COLUMN\s+(['\"]?[\w\s]+['\"]?)", sql, re.IGNORECASE)
        if drop_match:
            table_name, col_name = [c.strip("'\"") for c in drop_match.groups()]
            table_id = self._get_table_id(table_name)
            field_id = self._get_field_id(table_id, col_name)
            return self.qb.delete_fields(table_id, [field_id])
            
        # RENAME COLUMN
        rename_col_match = re.match(r"ALTER TABLE\s+(['\"]?[\w\s]+['\"]?)\s+RENAME COLUMN\s+(['\"]?[\w\s]+['\"]?)\s+TO\s+(['\"]?[\w\s]+['\"]?)", sql, re.IGNORECASE)
        if rename_col_match:
            table_name, old_col_name, new_col_name = [c.strip("'\"") for c in rename_col_match.groups()]
            table_id = self._get_table_id(table_name)
            field_id = self._get_field_id(table_id, old_col_name)
            return self.qb.update_field(table_id, field_id, {"label": new_col_name})
            
        raise ValueError("Unsupported ALTER TABLE statement.")
        
    def _execute_drop_table(self, sql: str):
        """Handler for DROP TABLE statements."""
        match = re.search(r"DROP TABLE\s+(['\"]?[\w\s]+['\"]?);?", sql, re.IGNORECASE)
        if not match:
            raise ValueError("Invalid DROP TABLE format.")
        table_name = match.groups()[0]
        table_id = self._get_table_id(table_name)
        if not self.qb.app_id:
             raise QuickBaseError("An app_id must be set in the QBConn client to drop a table.")
        return self.qb.delete_table(table_id, self.qb.app_id)


