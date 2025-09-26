"""
QuickBase REST API v1 Connection Class
This class provides comprehensive methods to interact with QuickBase using the REST API v1.
It supports all documented operations for applications, tables, fields, records, relationships,
reports, file attachments, user tokens, audit logs, platform analytics, solutions, and more.

Designed for Python 3.7+ with type hints.

AUTHOR: Jose Santiago Echevarria 
VERSION: 5.1.0
UPDATED: 2025-08-11

IMPORTANT NOTES ON API ENDPOINTS:
1. Records API: The upsert functionality uses the same /records endpoint with the mergeFieldId parameter.
2. File Downloads: Returns raw byte content that may need to be saved to a file.
3. Solutions API: Handles YAML content for create/update operations.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import base64
import logging
import os
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Tuple, TypedDict, Iterator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Constants and Enums
# -------------------------------------------------------------------------

class QuickBaseConstants:
    """QuickBase system field IDs and other constants."""
    RECORD_ID_FIELD = "3"
    DATE_CREATED_FIELD = "1"
    DATE_MODIFIED_FIELD = "2"
    RECORD_OWNER_FIELD = "4"
    LAST_MODIFIED_BY_FIELD = "5"

    # API Limits
    MAX_RECORDS_PER_REQUEST = 1000
    MAX_PAYLOAD_SIZE_MB = 40
    MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 30

    # Rate Limits
    RATE_LIMIT_REQUESTS_PER_SECOND = 10
    RATE_LIMIT_REQUESTS_PER_MINUTE = 100

class HTTPMethod(Enum):
    """HTTP methods enum."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"

class FieldType(Enum):
    """QuickBase field types."""
    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"
    DURATION = "duration"
    CHECKBOX = "checkbox"
    USER = "user"
    EMAIL = "email"
    URL = "url"
    PHONE = "phone"
    RICH_TEXT = "rich-text"
    FILE = "file"
    LOOKUP = "lookup"
    SUMMARY = "summary"
    FORMULA = "formula"
    MULTI_SELECT = "text-multiple-choice"
    MULTI_USER = "multiuser"
    ADDRESS = "address"

class QueryOperator(Enum):
    """QuickBase query operators."""
    EX = "EX"  # Exact match
    NEX = "NEX"  # Not exact match
    CT = "CT"  # Contains
    NCT = "NCT"  # Does not contain
    BF = "BF"  # Before
    AF = "AF"  # After
    OBF = "OBF"  # On or before
    OAF = "OAF"  # On or after
    GT = "GT"  # Greater than
    GTE = "GTE"  # Greater than or equal
    LT = "LT"  # Less than
    LTE = "LTE"  # Less than or equal
    SW = "SW"  # Starts with
    NSW = "NSW"  # Does not start with
    EW = "EW"  # Ends with
    NEW = "NEW"  # Does not end with
    TRUE = "TRUE"  # Is true (checkbox)
    FALSE = "FALSE"  # Is false (checkbox)
    IR = "IR"  # Is during (date range)
    XIR = "XIR"  # Is not during (date range)

# -------------------------------------------------------------------------
# Type Definitions
# -------------------------------------------------------------------------

class QueryOptions(TypedDict, total=False):
    """Type definition for query options."""
    skip: int
    top: int
    compareWithAppLocalTime: bool

# -------------------------------------------------------------------------
# Exceptions
# -------------------------------------------------------------------------

class QuickBaseError(Exception):
    """Base exception for QuickBase API errors."""
    pass

class QuickBaseAuthError(QuickBaseError):
    """Authentication error."""
    pass

class QuickBaseRateLimitError(QuickBaseError):
    """Rate limit exceeded error."""
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after

class QuickBaseValidationError(QuickBaseError):
    """Validation error."""
    pass

class QuickBaseNotFoundError(QuickBaseError):
    """Resource not found error."""
    pass

# -------------------------------------------------------------------------
# Rate Limiter & Cache
# -------------------------------------------------------------------------

class RateLimiter:
    """Rate limiter for API requests."""
    def __init__(self, requests_per_second: int, requests_per_minute: int):
        self.requests_per_second = requests_per_second
        self.requests_per_minute = requests_per_minute
        self.request_times: List[float] = []

    def wait_if_needed(self):
        """Waits if the request rate exceeds the defined limits."""
        now = time.time()
        # Filter times to keep the last minute
        self.request_times = [t for t in self.request_times if now - t < 60]

        if len(self.request_times) >= self.requests_per_minute:
            sleep_time = 60 - (now - self.request_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        # Check requests in the last second
        recent_requests = [t for t in self.request_times if now - t < 1]
        if len(recent_requests) >= self.requests_per_second:
            time.sleep(1 - (now - recent_requests[0]))

        self.request_times.append(time.time())

class ResponseCache:
    """Simple response cache with TTL."""
    def __init__(self, default_ttl: int = 300):
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """Gets a value from the cache if it exists and has not expired."""
        if key in self.cache:
            value, expiry = self.cache[key]
            if time.time() < expiry:
                return value
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Sets a value in the cache with a specified TTL."""
        ttl = ttl if ttl is not None else self.default_ttl
        self.cache[key] = (value, time.time() + ttl)

    def clear(self):
        """Clears the entire cache."""
        self.cache.clear()

# -------------------------------------------------------------------------
# Main QuickBase Connection Class
# -------------------------------------------------------------------------

class QBConn:
    """
    A comprehensive connection class for the QuickBase REST API v1.
    """

    def __init__(self,
                 token: str,
                 realm: str,
                 app_id: Optional[str] = None,
                 user_agent: Optional[str] = "QBConn Python Client/5.1.0",
                 log_level: str = "INFO",
                 enable_rate_limiting: bool = True,
                 enable_caching: bool = True,
                 cache_ttl: int = 300,
                 timeout: int = QuickBaseConstants.DEFAULT_TIMEOUT,
                 max_retries: int = QuickBaseConstants.MAX_RETRIES,
                 retry_delay: int = 1):
        """
        Initializes the QuickBase connection using the REST API (v1).
        """
        # API Configuration
        self.base_url = "https://api.quickbase.com/v1/"
        self.token = token
        self.realm = realm
        self.app_id = app_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Set up headers
        self.headers = {
            "Authorization": f"QB-USER-TOKEN {self.token}",
            "QB-Realm-Hostname": self.realm,
            "User-Agent": user_agent
        }

        # Error tracking
        self.error = 0
        self.last_error_message = ""

        # Rate limiting and Caching
        self.rate_limiter = RateLimiter(QuickBaseConstants.RATE_LIMIT_REQUESTS_PER_SECOND, 
                                        QuickBaseConstants.RATE_LIMIT_REQUESTS_PER_MINUTE) if enable_rate_limiting else None
        self.cache = ResponseCache(cache_ttl) if enable_caching else None

        # Logging
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # Metadata cache
        self.tables: Dict[str, str] = {}
        self._field_cache: Dict[str, List[Dict]] = {}

        if self.app_id:
            try:
                self.tables = self._get_tables_metadata()
            except Exception as e:
                self.logger.warning(f"Failed to load initial table metadata for app {self.app_id}: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cache:
            self.cache.clear()
        return False

    def _request(self,
                 method: Union[str, HTTPMethod],
                 endpoint: str,
                 data: Optional[Union[Dict, str, list]] = None,
                 params: Optional[Dict] = None,
                 additional_headers: Optional[Dict] = None,
                 use_cache: bool = False,
                 cache_ttl: Optional[int] = None,
                 is_file_download: bool = False) -> Optional[Union[Dict, bytes, list]]:
        """Internal helper to send an HTTP request to QuickBase."""
        if isinstance(method, HTTPMethod):
            method = method.value

        url = self.base_url + endpoint
        cache_key = f"{url}:{json.dumps(params or {})}"

        if use_cache and self.cache and method == "GET":
            cached = self.cache.get(cache_key)
            if cached is not None:
                self.logger.debug(f"Cache hit for {cache_key}")
                return cached

        if self.rate_limiter:
            self.rate_limiter.wait_if_needed()

        request_headers = self.headers.copy()
        if additional_headers:
            request_headers.update(additional_headers)

        if 'Content-Type' not in request_headers:
            request_headers['Content-Type'] = 'application/json'

        for attempt in range(self.max_retries):
            try:
                self.logger.debug(f"Request: {method} {url} (Attempt {attempt + 1}/{self.max_retries})")
                full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
                data_bytes = None
                if data is not None:
                    if isinstance(data, (dict, list)):
                        data_bytes = json.dumps(data).encode('utf-8')
                    elif isinstance(data, str):
                        data_bytes = data.encode('utf-8')

                req = urllib.request.Request(full_url, data=data_bytes, headers=request_headers, method=method)

                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    if is_file_download:
                        return response.read()

                    response_data = response.read().decode('utf-8')
                    result = json.loads(response_data) if response_data else {}

                    if use_cache and self.cache and method == "GET":
                        self.cache.set(cache_key, result, cache_ttl)
                    
                    self.error = 0
                    self.last_error_message = ""
                    return result

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if e.fp else f"HTTP Error {e.code}"
                if e.code == 429: # Rate limit
                    retry_after = int(e.headers.get('Retry-After', self.retry_delay * (2 ** attempt)))
                    self.logger.warning(f"Rate limit hit. Retrying in {retry_after} seconds...")
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise QuickBaseRateLimitError(f"Rate limit exceeded: {error_body}", retry_after)
                elif e.code == 401:
                    raise QuickBaseAuthError(f"Authentication failed: {error_body}")
                elif e.code == 404:
                    raise QuickBaseNotFoundError(f"Resource not found: {error_body}")
                else:
                    self.error = e.code
                    self.last_error_message = error_body
                    self.logger.error(f"HTTP Error {e.code}: {error_body}")
                    raise QuickBaseError(f"HTTP Error {e.code}: {error_body}")
            except Exception as e:
                self.logger.error(f"An unexpected error occurred on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    continue
                self.error = -1
                self.last_error_message = str(e)
                raise QuickBaseError(f"An unexpected error occurred: {e}")
        return None

    # -------------------------------------------------------------------------
    # Authentication and Token Management
    # -------------------------------------------------------------------------

    def get_temp_token(self, dbid: str) -> Optional[Dict]:
        """Gets a temporary authorization token, scoped to either an app or a table."""
        return self._request("GET", f"auth/temporary/{dbid}")
    
    def exchange_sso_token(self, subject_token: str) -> Optional[Dict]:
        """Exchanges a SAML assertion for a Quickbase token."""
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requested_token_type": "urn:quickbase:params:oauth:token-type:temp_token",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:saml2"
        }
        return self._request("POST", "auth/oauth/token", data=payload)

    def clone_user_token(self, name: str, description: Optional[str] = None) -> Optional[Dict]:
        """Clones the authenticated user token."""
        payload = {"name": name}
        if description:
            payload["description"] = description
        return self._request("POST", "usertoken/clone", data=payload)

    def deactivate_user_token(self) -> Optional[Dict]:
        """Deactivates the authenticated user token."""
        return self._request("POST", "usertoken/deactivate")

    def delete_user_token(self) -> Optional[Dict]:
        """Deletes the authenticated user token."""
        return self._request("DELETE", "usertoken")

    def transfer_user_token(self, token_id: int, from_user_id: str, to_user_id: str) -> Optional[Dict]:
        """Transfers the specified user token."""
        payload = {"id": token_id, "from": from_user_id, "to": to_user_id}
        return self._request("POST", "usertoken/transfer", data=payload)

    # -------------------------------------------------------------------------
    # Application Management
    # -------------------------------------------------------------------------

    def get_app(self, app_id: str) -> Optional[Dict]:
        """Returns the main properties of an application, including application variables."""
        return self._request("GET", f"apps/{app_id}", use_cache=True)

    def create_app(self, name: str, description: Optional[str] = None,
                   assign_token: bool = False, variables: Optional[List[Dict]] = None,
                   security_properties: Optional[Dict] = None) -> Optional[Dict]:
        """Creates an application in an account."""
        payload: Dict[str, Any] = {"name": name, "assignToken": assign_token}
        if description:
            payload["description"] = description
        if variables:
            payload["variables"] = variables
        if security_properties:
            payload["securityProperties"] = security_properties
        return self._request("POST", "apps", data=payload)

    def update_app(self, app_id: str, updates: Dict) -> Optional[Dict]:
        """Updates the main properties and/or application variables for a specific application."""
        return self._request("POST", f"apps/{app_id}", data=updates)

    def copy_app(self, app_id: str, name: str, description: Optional[str] = None,
                 properties: Optional[Dict] = None) -> Optional[Dict]:
        """Copies the specified application."""
        payload: Dict[str, Any] = {"name": name}
        if description:
            payload["description"] = description
        if properties:
            payload["properties"] = properties
        return self._request("POST", f"apps/{app_id}/copy", data=payload)

    def delete_app(self, app_id: str, name: str) -> Optional[Dict]:
        """Deletes an entire application, including all of its tables and data."""
        return self._request("DELETE", f"apps/{app_id}", data={"name": name})

    def get_app_events(self, app_id: str) -> Optional[List[Dict]]:
        """Gets a list of events that can be triggered in an application."""
        return self._request("GET", f"apps/{app_id}/events")

    # -------------------------------------------------------------------------
    # Table Management
    # -------------------------------------------------------------------------

    def get_tables(self, app_id: Optional[str] = None) -> Optional[List[Dict]]:
        """Gets a list of all tables in a specific application."""
        app_id_to_use = app_id or self.app_id
        if not app_id_to_use:
            raise QuickBaseValidationError("app_id must be provided either during initialization or in the method call.")
        return self._request("GET", "tables", params={"appId": app_id_to_use}, use_cache=True)

    def get_table(self, table_id: str, app_id: Optional[str] = None) -> Optional[Dict]:
        """Gets the properties of an individual table."""
        app_id_to_use = app_id or self.app_id
        if not app_id_to_use:
            raise QuickBaseValidationError("app_id must be provided either during initialization or in the method call.")
        return self._request("GET", f"tables/{table_id}", params={"appId": app_id_to_use}, use_cache=True)

    def create_table(self, app_id: str, name: str, description: Optional[str] = None,
                     single_record_name: Optional[str] = None,
                     plural_record_name: Optional[str] = None) -> Optional[Dict]:
        """Creates a table in an application."""
        payload: Dict[str, Any] = {"name": name}
        if description:
            payload["description"] = description
        if single_record_name:
            payload["singleRecordName"] = single_record_name
        if plural_record_name:
            payload["pluralRecordName"] = plural_record_name
        return self._request("POST", "tables", params={"appId": app_id}, data=payload)

    def update_table(self, table_id: str, app_id: str, updates: Dict) -> Optional[Dict]:
        """Updates the main properties of a specific table."""
        return self._request("POST", f"tables/{table_id}", params={"appId": app_id}, data=updates)

    def delete_table(self, table_id: str, app_id: str) -> Optional[Dict]:
        """Deletes a specific table in an application."""
        return self._request("DELETE", f"tables/{table_id}", params={"appId": app_id})

    # -------------------------------------------------------------------------
    # Field Management
    # -------------------------------------------------------------------------

    def get_fields(self, table_id: str, include_field_perms: bool = False) -> Optional[List[Dict]]:
        """Gets the properties for all fields in a specific table."""
        params = {"tableId": table_id, "includeFieldPerms": include_field_perms}
        result = self._request("GET", "fields", params=params, use_cache=True)
        if result and isinstance(result, list):
            self._field_cache[table_id] = result
        return result

    def get_field(self, field_id: Union[str, int], table_id: str, include_field_perms: bool = False) -> Optional[Dict]:
        """Gets the properties of an individual field."""
        params = {"tableId": table_id, "includeFieldPerms": include_field_perms}
        return self._request("GET", f"fields/{field_id}", params=params, use_cache=True)

    def create_field(self, table_id: str, label: str, field_type: Union[str, FieldType], **kwargs) -> Optional[Dict]:
        """Creates a field within a table."""
        if table_id in self._field_cache:
            del self._field_cache[table_id]
        if isinstance(field_type, FieldType):
            field_type = field_type.value
        payload = {"label": label, "fieldType": field_type, **kwargs}
        return self._request("POST", "fields", params={"tableId": table_id}, data=payload)

    def update_field(self, table_id: str, field_id: Union[str, int], updates: Dict) -> Optional[Dict]:
        """Updates the properties and custom permissions of a field."""
        if table_id in self._field_cache:
            del self._field_cache[table_id]
        return self._request("POST", f"fields/{field_id}", params={"tableId": table_id}, data=updates)

    def delete_fields(self, table_id: str, field_ids: List[int]) -> Optional[Dict]:
        """Deletes one or many fields in a table."""
        if table_id in self._field_cache:
            del self._field_cache[table_id]
        payload = {"fieldIds": field_ids}
        return self._request("DELETE", "fields", params={"tableId": table_id}, data=payload)

    def get_field_usage(self, table_id: str, field_id: int) -> Optional[Dict]:
        """Gets a single field's usage statistics."""
        return self._request("GET", f"fields/usage/{field_id}", params={"tableId": table_id})

    def get_fields_usage(self, table_id: str, skip: Optional[int] = None, top: Optional[int] = None) -> Optional[List[Dict]]:
        """Gets all field usage statistics for a table."""
        params: Dict[str, Any] = {"tableId": table_id}
        if skip is not None:
            params['skip'] = skip
        if top is not None:
            params['top'] = top
        return self._request("GET", "fields/usage", params=params)

    # -------------------------------------------------------------------------
    # Record Management
    # -------------------------------------------------------------------------

    def query_records(self,
                      table_id: str,
                      select: Optional[List[int]] = None,
                      where: Optional[str] = None,
                      sort_by: Optional[List[Dict]] = None,
                      group_by: Optional[List[Dict]] = None,
                      options: Optional[QueryOptions] = None) -> Optional[Dict]:
        """Queries for records with full options."""
        payload: Dict[str, Any] = {"from": table_id}
        if select:
            payload["select"] = select
        if where:
            payload["where"] = where
        if sort_by:
            payload["sortBy"] = sort_by
        if group_by:
            payload["groupBy"] = group_by
        if options:
            payload["options"] = options
        return self._request("POST", "records/query", data=payload)

    def get_records_paginated(self,
                              table_id: str,
                              where: Optional[str] = None,
                              select: Optional[List[int]] = None,
                              sort_by: Optional[List[Dict]] = None,
                              page_size: int = 1000,
                              max_records: Optional[int] = None) -> Iterator[Dict]:
        """Iterates through records with automatic pagination."""
        skip = 0
        total_returned = 0
        while True:
            options: QueryOptions = {"skip": skip, "top": page_size}
            response = self.query_records(table_id, select, where, sort_by, options=options)
            if not response or "data" not in response or not response["data"]:
                break
            
            for record in response["data"]:
                yield record
                total_returned += 1
                if max_records and total_returned >= max_records:
                    return
            
            if len(response["data"]) < page_size:
                break
            skip += page_size

    def upsert_records(self,
                       table_id: str,
                       records: List[Dict],
                       merge_field_id: int,
                       fields_to_return: Optional[List[int]] = None) -> Optional[Dict]:
        """Inserts and/or updates records in a table."""
        data_to_send = []
        for r in records:
            record_data = {str(k): {"value": v} for k, v in r.items()}
            data_to_send.append(record_data)

        payload: Dict[str, Any] = {"to": table_id, "data": data_to_send, "mergeFieldId": merge_field_id}
        if fields_to_return:
            payload["fieldsToReturn"] = fields_to_return
        return self._request("POST", "records", data=payload)

    def delete_records(self, table_id: str, where: str) -> Optional[Dict]:
        """Deletes records in a table based on a query."""
        payload = {"from": table_id, "where": where}
        return self._request("DELETE", "records", data=payload)
    
    # -------------------------------------------------------------------------
    # Formula Execution
    # -------------------------------------------------------------------------

    def run_formula(self, table_id: str, formula: str,
                    record_id: Optional[int] = None) -> Optional[Dict]:
        """Allows running a formula via an API call."""
        payload: Dict[str, Any] = {"from": table_id, "formula": formula}
        if record_id:
            payload["rid"] = record_id
        return self._request("POST", "formula/run", data=payload)

    # -------------------------------------------------------------------------
    # Relationship Management
    # -------------------------------------------------------------------------

    def get_relationships(self, table_id: str, skip: Optional[int] = None) -> Optional[List[Dict]]:
        """Gets a list of all relationships for a specific table."""
        params = {"skip": skip} if skip is not None else {}
        return self._request("GET", f"tables/{table_id}/relationships", params=params, use_cache=True)

    def create_relationship(self, child_table_id: str, parent_table_id: str, **kwargs) -> Optional[Dict]:
        """Creates a relationship in a table."""
        payload = {"parentTableId": parent_table_id, **kwargs}
        return self._request("POST", f"tables/{child_table_id}/relationship", data=payload)

    def update_relationship(self, child_table_id: str, relationship_id: int, **kwargs) -> Optional[Dict]:
        """Adds lookup and summary fields to an existing relationship."""
        return self._request("POST", f"tables/{child_table_id}/relationship/{relationship_id}", data=kwargs)

    def delete_relationship(self, child_table_id: str, relationship_id: int) -> Optional[Dict]:
        """Deletes an entire relationship."""
        return self._request("DELETE", f"tables/{child_table_id}/relationship/{relationship_id}")

    # -------------------------------------------------------------------------
    # Report Management
    # -------------------------------------------------------------------------

    def get_reports(self, table_id: str) -> Optional[List[Dict]]:
        """Gets the schema of all reports for a table."""
        return self._request("GET", "reports", params={"tableId": table_id}, use_cache=True)

    def get_report(self, table_id: str, report_id: int) -> Optional[Dict]:
        """Gets the schema of an individual report."""
        return self._request("GET", f"reports/{report_id}", params={"tableId": table_id}, use_cache=True)

    def run_report(self, table_id: str, report_id: int, skip: Optional[int] = None, top: Optional[int] = None) -> Optional[Dict]:
        """Runs a report and returns the underlying data."""
        params: Dict[str, Any] = {"tableId": table_id}
        if skip is not None:
            params['skip'] = skip
        if top is not None:
            params['top'] = top
        return self._request("POST", f"reports/{report_id}/run", params=params, data={})

    # -------------------------------------------------------------------------
    # File Attachment Management
    # -------------------------------------------------------------------------

    def upload_file(self, table_id: str, record_id: int,
                    field_id: int, file_path: str) -> Optional[Dict]:
        """Uploads a file attachment from a local path."""
        if not os.path.isfile(file_path):
            raise QuickBaseValidationError(f"File not found: {file_path}")
        with open(file_path, 'rb') as f:
            file_data = f.read()
        file_name = os.path.basename(file_path)
        return self.upload_file_bytes(table_id, record_id, field_id, file_name, file_data)

    def upload_file_bytes(self, table_id: str, record_id: int,
                          field_id: int, file_name: str,
                          file_data: bytes) -> Optional[Dict]:
        """Uploads file content from bytes using the records API."""
        if len(file_data) > QuickBaseConstants.MAX_PAYLOAD_SIZE_MB * 1024 * 1024:
            raise QuickBaseValidationError(f"File size exceeds the {QuickBaseConstants.MAX_PAYLOAD_SIZE_MB}MB limit.")

        encoded_data = base64.b64encode(file_data).decode('utf-8')
        record_update = {
            str(QuickBaseConstants.RECORD_ID_FIELD): {"value": record_id},
            str(field_id): {"value": {"fileName": file_name, "data": encoded_data}}
        }
        payload = {"to": table_id, "data": [record_update]}
        return self._request("POST", "records", data=payload)

    def download_file(self, table_id: str, record_id: int,
                      field_id: int, version_number: int) -> Optional[bytes]:
        """Downloads the raw byte content of a file attachment."""
        endpoint = f"files/{table_id}/{record_id}/{field_id}/{version_number}"
        return self._request("GET", endpoint, is_file_download=True)

    def delete_file(self, table_id: str, record_id: int,
                    field_id: int, version_number: int) -> Optional[Dict]:
        """Deletes one file attachment version."""
        endpoint = f"files/{table_id}/{record_id}/{field_id}/{version_number}"
        return self._request("DELETE", endpoint)

    # -------------------------------------------------------------------------
    # User and Group Management
    # -------------------------------------------------------------------------

    def get_users(self, account_id: Optional[int] = None, emails: Optional[List[str]] = None,
                  app_ids: Optional[List[str]] = None, next_page_token: Optional[str] = None) -> Optional[Dict]:
        """Gets all users in an account or a narrowed down list of users."""
        params = {"accountId": account_id} if account_id else {}
        payload: Dict[str, Any] = {}
        if emails:
            payload["emails"] = emails
        if app_ids:
            payload["appIds"] = app_ids
        if next_page_token:
            payload["nextPageToken"] = next_page_token
        return self._request("POST", "users", data=payload, params=params)

    def deny_users(self, user_ids: List[str], account_id: Optional[int] = None,
                   should_delete_from_groups: Optional[bool] = None) -> Optional[Dict]:
        """Denies users access to the realm and optionally removes them from groups."""
        params = {"accountId": account_id} if account_id else {}
        endpoint = "users/deny"
        if should_delete_from_groups is not None:
            endpoint += f"/{str(should_delete_from_groups).lower()}"
        return self._request("PUT", endpoint, data=user_ids, params=params)

    def undeny_users(self, user_ids: List[str], account_id: Optional[int] = None) -> Optional[Dict]:
        """Grants users that have previously been denied access to the realm."""
        params = {"accountId": account_id} if account_id else {}
        return self._request("PUT", "users/undeny", data=user_ids, params=params)

    def add_members_to_group(self, group_id: int, user_ids: List[str]) -> Optional[Dict]:
        """Adds a list of users to a given group as members."""
        return self._request("POST", f"groups/{group_id}/members", data=user_ids)

    def remove_members_from_group(self, group_id: int, user_ids: List[str]) -> Optional[Dict]:
        """Removes a list of members from a given group."""
        return self._request("DELETE", f"groups/{group_id}/members", data=user_ids)

    def add_managers_to_group(self, group_id: int, user_ids: List[str]) -> Optional[Dict]:
        """Adds a list of users to a given group as managers."""
        return self._request("POST", f"groups/{group_id}/managers", data=user_ids)

    def remove_managers_from_group(self, group_id: int, user_ids: List[str]) -> Optional[Dict]:
        """Removes a list of managers from a given group."""
        return self._request("DELETE", f"groups/{group_id}/managers", data=user_ids)

    def add_subgroups_to_group(self, group_id: int, subgroup_ids: List[str]) -> Optional[Dict]:
        """Adds a list of groups to a given group."""
        return self._request("POST", f"groups/{group_id}/subgroups", data=subgroup_ids)

    def remove_subgroups_from_group(self, group_id: int, subgroup_ids: List[str]) -> Optional[Dict]:
        """Removes a list of groups from a given group."""
        return self._request("DELETE", f"groups/{group_id}/subgroups", data=subgroup_ids)

    # -------------------------------------------------------------------------
    # Audit Logs
    # -------------------------------------------------------------------------

    def get_audit_logs(self, date: str, topics: Optional[List[str]] = None,
                       num_rows: Optional[int] = None, next_token: Optional[str] = None,
                       query_id: Optional[str] = None) -> Optional[Dict]:
        """Gathers the audit logs for a single day from a realm."""
        payload: Dict[str, Any] = {"date": date}
        if topics:
            payload["topics"] = topics
        if num_rows:
            payload["numRows"] = num_rows
        if next_token:
            payload["nextToken"] = next_token
        if query_id:
            payload["queryId"] = query_id
        return self._request("POST", "audit", data=payload)

    # -------------------------------------------------------------------------
    # Platform Analytics
    # -------------------------------------------------------------------------

    def get_read_summaries(self, day: str) -> Optional[Dict]:
        """Gets user read and integration read summaries for any day in the past."""
        return self._request("GET", "analytics/reads", params={"day": day})

    def get_event_summaries(self, start: str, end: str, group_by: str,
                            account_id: Optional[int] = None, next_token: Optional[str] = None,
                            where: Optional[List[Dict]] = None) -> Optional[Dict]:
        """Gets event summaries for a specified time span."""
        params = {"accountId": account_id} if account_id else {}
        payload: Dict[str, Any] = {"start": start, "end": end, "groupBy": group_by}
        if next_token:
            payload["nextToken"] = next_token
        if where:
            payload["where"] = where
        return self._request("POST", "analytics/events/summaries", data=payload, params=params)

    # -------------------------------------------------------------------------
    # Solutions
    # -------------------------------------------------------------------------

    def export_solution(self, solution_id: str, qbl_version: Optional[str] = None) -> Optional[str]:
        """Returns the QBL for the specified solution."""
        headers = {"QBL-Version": qbl_version} if qbl_version else {}
        response = self._request("GET", f"solutions/{solution_id}", additional_headers=headers, is_file_download=True)
        return response.decode('utf-8') if isinstance(response, bytes) else None

    def update_solution(self, solution_id: str, qbl_data: str) -> Optional[Dict]:
        """Updates the solution using the provided QBL."""
        headers = {"Content-Type": "application/x-yaml"}
        return self._request("PUT", f"solutions/{solution_id}", data=qbl_data, additional_headers=headers)

    def create_solution(self, qbl_data: str) -> Optional[Dict]:
        """Creates a solution using the provided QBL."""
        headers = {"Content-Type": "application/x-yaml"}
        return self._request("POST", "solutions", data=qbl_data, additional_headers=headers)

    def export_solution_to_record(self, solution_id: str, table_id: str, field_id: int,
                                  qbl_version: Optional[str] = None) -> Optional[Dict]:
        """Exports the solution and outputs the QBL to a new record."""
        params = {"tableId": table_id, "fieldId": field_id}
        headers = {"QBL-Version": qbl_version} if qbl_version else {}
        return self._request("GET", f"solutions/{solution_id}/torecord", params=params, additional_headers=headers)

    def create_solution_from_record(self, table_id: str, record_id: int, field_id: int) -> Optional[Dict]:
        """Creates a solution using the QBL from the specified record."""
        params = {"tableId": table_id, "recordId": record_id, "fieldId": field_id}
        return self._request("GET", "solutions/fromrecord", params=params)

    def update_solution_from_record(self, solution_id: str, table_id: str, record_id: int, field_id: int) -> Optional[Dict]:
        """Updates a solution using the QBL from the specified record."""
        params = {"tableId": table_id, "recordId": record_id, "fieldId": field_id}
        return self._request("GET", f"solutions/{solution_id}/fromrecord", params=params)

    def list_solution_changes(self, solution_id: str, qbl_data: str) -> Optional[Dict]:
        """Returns a list of changes that would occur if the provided QBL were applied."""
        headers = {"Content-Type": "application/x-yaml"}
        return self._request("PUT", f"solutions/{solution_id}/changeset", data=qbl_data, additional_headers=headers)

    def list_solution_changes_from_record(self, solution_id: str, table_id: str, record_id: int, field_id: int) -> Optional[Dict]:
        """Returns a list of changes from a QBL file stored in a record."""
        params = {"tableId": table_id, "recordId": record_id, "fieldId": field_id}
        return self._request("GET", f"solutions/{solution_id}/changeset/fromrecord", params=params)

    def get_solution_info(self, solution_id: str) -> Optional[Dict]:
        """Returns the metadata and resource information for a solution."""
        return self._request("GET", f"solutions/{solution_id}/resources")

    # -------------------------------------------------------------------------
    # Document Templates
    # -------------------------------------------------------------------------

    def generate_document(self, template_id: int, table_id: str, filename: str,
                          record_id: Optional[int] = None, file_format: str = "pdf",
                          accept: str = "application/json", **kwargs) -> Optional[Union[Dict, bytes]]:
        """
        Generates a document from a template.
        
        Args:
            accept: 'application/json' to get base64 data, or 'application/octet-stream' to get raw file bytes.
            **kwargs: Can include margin, unit, pageSize, orientation.
        """
        params = {"tableId": table_id, "filename": filename, "format": file_format}
        if record_id:
            params["recordId"] = record_id
        params.update(kwargs)
        
        is_direct_download = (accept == "application/octet-stream")
        
        return self._request("GET", f"docTemplates/{template_id}/generate", params=params,
                             additional_headers={"Accept": accept}, is_file_download=is_direct_download)

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_tables_metadata(self) -> Dict[str, str]:
        """Gets table name to ID mapping."""
        tables = {}
        response = self.get_tables()
        if response and isinstance(response, list):
            for table in response:
                if table.get("name") and table.get("id"):
                    tables[table["name"]] = table["id"]
        return tables

    def get_table_id_by_name(self, table_name: str, app_id: Optional[str] = None) -> Optional[str]:
        """Gets table ID by its name."""
        app_id_to_use = app_id or self.app_id
        if not app_id_to_use:
            raise QuickBaseValidationError("app_id must be provided to find a table by name.")

        # Check local cache first
        if table_name in self.tables:
            return self.tables[table_name]
        
        # Fetch fresh list if not found
        tables_list = self.get_tables(app_id_to_use)
        if tables_list:
            for table in tables_list:
                if table.get("name", "").lower() == table_name.lower():
                    table_id = table.get("id")
                    if table_id:
                        self.tables[table_name] = table_id
                        return table_id
        return None

    def get_field_id_by_name(self, table_id: str, field_name: str) -> Optional[int]:
        """Gets field ID by its name/label."""
        fields = self._field_cache.get(table_id) or self.get_fields(table_id)
        if fields:
            for field in fields:
                if field.get("label", "").lower() == field_name.lower():
                    return field.get("id")
        return None

    def clear_cache(self):
        """Clears all local caches (responses, fields, tables)."""
        if self.cache:
            self.cache.clear()
        self._field_cache.clear()
        self.tables.clear()
        self.logger.info("All local caches have been cleared.")

if __name__ == "__main__":
    print("QuickBase REST API Client v5.1.0")
    print("This module provides comprehensive access to the QuickBase REST API v1.")
    print("\nExample usage:")
    print("  from quickbase_rest_client import QBConn")
    print("  qb = QBConn(token='YOUR_TOKEN', realm='yourrealm.quickbase.com', app_id='YOUR_APP_ID')")
    print("  # Example: Get tables for the application")
    print("  # tables = qb.get_tables()")
    print("\nFor full documentation, see the docstrings for each method.")