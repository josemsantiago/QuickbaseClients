# QuickBase Python Client

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![API Coverage](https://img.shields.io/badge/API%20Coverage-100%25-brightgreen.svg)](https://developer.quickbase.com/)

A comprehensive Python and JavaScript client library for the QuickBase REST API v1, providing complete coverage of all QuickBase operations with enterprise-grade features.

## Overview

This library provides two complete implementations for QuickBase REST API v1:
- **Python Client**: Full-featured client with 70+ methods, type hints, and advanced error handling
- **JavaScript Client**: Node.js client with identical functionality and async/await support

Based on the official QuickBase API specification (52,449 lines), both clients support every documented endpoint and operation.

## Features

### 🚀 **Complete API Coverage**
- **Applications**: Create, read, update, delete, copy apps
- **Tables**: Full table lifecycle management
- **Fields**: Field creation, updates, usage analytics
- **Records**: Query, upsert, delete with advanced filtering
- **Reports**: Generate and run custom reports
- **Files**: Upload, download, manage attachments
- **Users & Groups**: User management and permissions
- **Authentication**: Token management and SSO
- **Audit Logs**: Access audit trails and analytics
- **Solutions**: Import/export app configurations
- **Document Generation**: Generate documents from templates

### 🛡️ **Enterprise Features**
- **Rate Limiting**: Automatic rate limit handling with exponential backoff
- **Caching**: Intelligent response caching for GET requests
- **Retry Logic**: Configurable retry mechanisms for failed requests
- **Error Handling**: Comprehensive exception types with detailed error information
- **Type Safety**: Full type hints in Python client
- **Async Support**: Native async/await in JavaScript client

### 🔧 **Developer Experience**
- **Intuitive API**: Consistent method naming and parameter patterns
- **Comprehensive Documentation**: Full JSDoc and docstring coverage
- **Helper Methods**: Utility functions for common operations
- **Debugging Support**: Detailed logging and error reporting

## Quick Start

### Python Installation

```bash
pip install requests  # Only dependency
```

### JavaScript Installation

```bash
npm install axios  # Only dependency
```

## Usage Examples

### Python Client

```python
from quickbase_rest_client import QBConn

# Initialize client
client = QBConn(
    token="your_user_token",
    realm="your_company.quickbase.com",
    app_id="your_app_id"  # Optional default
)

# Create an application
app = client.create_app(
    name="My New App",
    description="A sample application",
    assign_token=True
)

# Query records
records = client.query_records({
    "from": "table_id",
    "select": [3, 6, 7],  # Field IDs
    "where": "{3.GT.'100'}",
    "sortBy": [{"fieldId": 3, "order": "ASC"}]
})

# Upsert records
result = client.upsert_records(
    table_id="bq123456",
    records=[
        {"6": "John Doe", "7": "john@example.com"},
        {"6": "Jane Smith", "7": "jane@example.com"}
    ],
    merge_field_id=7  # Email field for deduplication
)

# Upload file
file_result = client.upload_file(
    table_id="bq123456",
    record_id=1,
    field_id=8,
    file_path="./document.pdf"
)
```

### JavaScript Client

```javascript
const { QuickBaseClient } = require('./quickbase_rest_client');

// Initialize client
const client = new QuickBaseClient({
    token: "your_user_token",
    realm: "your_company.quickbase.com",
    appId: "your_app_id"  // Optional default
});

// Create an application
const app = await client.createApp(
    "My New App",
    "A sample application",
    true  // assign token
);

// Query records with pagination
for await (const record of client.getRecordsPaginated({
    tableId: "bq123456",
    where: "{3.GT.'100'}",
    select: [3, 6, 7],
    pageSize: 500
})) {
    console.log(record);
}

// Upsert records
const result = await client.upsertRecords(
    "bq123456",
    [
        {"6": "John Doe", "7": "john@example.com"},
        {"6": "Jane Smith", "7": "jane@example.com"}
    ],
    7  // Email field for deduplication
);

// Upload file
const fileResult = await client.uploadFile(
    "bq123456",
    1,
    8,
    "./document.pdf"
);
```

## API Reference

### Core Methods

#### Application Management
- `getApp(appId)` - Get application details
- `createApp(name, description, ...)` - Create new application
- `updateApp(appId, updates)` - Update application properties
- `copyApp(appId, name, ...)` - Copy existing application
- `deleteApp(appId, name)` - Delete application
- `getAppEvents(appId)` - Get application events

#### Table Management
- `getTables(appId)` - List all tables in app
- `getTable(tableId, appId)` - Get table details
- `createTable(appId, name, ...)` - Create new table
- `updateTable(tableId, appId, updates)` - Update table properties
- `deleteTable(tableId, appId)` - Delete table

#### Field Management
- `getFields(tableId)` - List all fields in table
- `getField(fieldId, tableId)` - Get field details
- `createField(tableId, label, fieldType, ...)` - Create new field
- `updateField(tableId, fieldId, updates)` - Update field properties
- `deleteFields(tableId, fieldIds)` - Delete multiple fields
- `getFieldUsage(tableId, fieldId)` - Get field usage analytics

#### Record Operations
- `queryRecords(payload)` - Query records with filters
- `getRecordsPaginated(options)` - Paginated record iteration
- `upsertRecords(tableId, records, mergeFieldId)` - Insert/update records
- `deleteRecords(tableId, where)` - Delete records by query
- `getRecordsModifiedSince(tableId, timestamp)` - Get recently modified records

#### File Management
- `uploadFile(tableId, recordId, fieldId, filePath)` - Upload file from path
- `uploadFileBytes(tableId, recordId, fieldId, fileName, data)` - Upload file from bytes
- `downloadFile(tableId, recordId, fieldId, version)` - Download file content
- `deleteFile(tableId, recordId, fieldId, version)` - Delete file attachment

### Advanced Features

#### Authentication & Tokens
- `getTempToken(dbid)` - Get temporary token
- `exchangeSSOToken(subjectToken)` - Exchange SSO token
- `cloneUserToken(name, description)` - Clone user token
- `deactivateUserToken()` - Deactivate current token
- `transferUserToken(tokenId, fromUser, toUser)` - Transfer token ownership

#### User & Group Management
- `getUsers(filters)` - List users with filters
- `denyUsers(userIds)` - Deny user access
- `undenyUsers(userIds)` - Restore user access
- `addMembersToGroup(groupId, userIds)` - Add users to group
- `removeMembersFromGroup(groupId, userIds)` - Remove users from group

#### Audit & Analytics
- `getAuditLogs(date, filters)` - Get audit log entries
- `getReadSummaries(day)` - Get read analytics
- `getEventSummaries(start, end, groupBy)` - Get event analytics

#### Solutions (Import/Export)
- `exportSolution(solutionId)` - Export app configuration
- `createSolution(qblData)` - Create app from configuration
- `updateSolution(solutionId, qblData)` - Update app configuration
- `getSolutionInfo(solutionId)` - Get solution metadata

## Configuration

### Python Client Options

```python
client = QBConn(
    token="your_token",           # Required: QB user token
    realm="company.quickbase.com", # Required: QB realm
    app_id="app123",              # Optional: default app ID
    user_agent="MyApp/1.0",       # Optional: custom user agent
    enable_rate_limiting=True,    # Optional: rate limiting
    enable_caching=True,          # Optional: response caching
    cache_ttl=300,               # Optional: cache TTL in seconds
    timeout=30,                  # Optional: request timeout
    max_retries=3,               # Optional: max retry attempts
    retry_delay=1                # Optional: retry delay in seconds
)
```

### JavaScript Client Options

```javascript
const client = new QuickBaseClient({
    token: "your_token",           // Required: QB user token
    realm: "company.quickbase.com", // Required: QB realm
    appId: "app123",              // Optional: default app ID
    userAgent: "MyApp/1.0",       // Optional: custom user agent
    enableRateLimiting: true,     // Optional: rate limiting
    enableCaching: true,          // Optional: response caching
    cacheTtl: 300,               // Optional: cache TTL in seconds
    timeout: 30000,              // Optional: request timeout (ms)
    maxRetries: 3,               // Optional: max retry attempts
    retryDelay: 1                // Optional: retry delay in seconds
});
```

## Error Handling

Both clients provide comprehensive error handling with specific exception types:

### Python Exceptions

```python
from quickbase_rest_client import (
    QBConn,                   # Main client class
    QuickBaseError,           # Base exception
    QuickBaseAuthError,       # Authentication errors
    QuickBaseRateLimitError,  # Rate limit exceeded
    QuickBaseNotFoundError,   # Resource not found
    QuickBaseValidationError  # Input validation errors
)

try:
    records = client.query_records(payload)
except QuickBaseRateLimitError as e:
    print(f"Rate limited. Retry after: {e.retry_after} seconds")
except QuickBaseAuthError:
    print("Authentication failed. Check your token.")
except QuickBaseNotFoundError:
    print("Table or field not found.")
except QuickBaseError as e:
    print(f"API error: {e}")
```

### JavaScript Exceptions

```javascript
const {
    QuickBaseError,
    QuickBaseAuthError,
    QuickBaseRateLimitError,
    QuickBaseNotFoundError,
    QuickBaseValidationError
} = require('./quickbase_rest_client');

try {
    const records = await client.queryRecords(payload);
} catch (error) {
    if (error instanceof QuickBaseRateLimitError) {
        console.log(`Rate limited. Retry after: ${error.retryAfter} seconds`);
    } else if (error instanceof QuickBaseAuthError) {
        console.log("Authentication failed. Check your token.");
    } else if (error instanceof QuickBaseNotFoundError) {
        console.log("Table or field not found.");
    } else if (error instanceof QuickBaseError) {
        console.log(`API error: ${error.message}`);
    }
}
```

## File Structure

```
QuickBase Python Client/
├── quickbase_rest_client.py          # Python client (70+ methods)
├── quickbase_rest_client.js          # JavaScript client (70+ methods)
├── QuickBase_RESTful_API_*.json      # Official API specification (52,449 lines)
├── package.json                      # Node.js dependencies
├── LICENSE                           # MIT License
├── .gitignore                        # Git ignore rules
└── README.md                         # This documentation
```

## API Specification

This client is based on the official QuickBase REST API v1 specification:
- **Specification Version**: 2025-09-26
- **Total Lines**: 52,449
- **Endpoints Covered**: 42+
- **Methods Implemented**: 70+

## Requirements

### Python
- Python 3.7+
- No external dependencies (uses built-in `urllib`)

### JavaScript
- Node.js 14+
- `axios` for HTTP requests

## Development

### Running Tests

```bash
# Python (manual testing)
python quickbase_rest_client.py

# JavaScript (manual testing)
node -e "const {QuickBaseClient} = require('./quickbase_rest_client'); console.log('Loaded successfully');"
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## Changelog

### Version 2.0.0 (2025-09-26)
- **MAJOR**: Complete JavaScript client rewrite with full API coverage
- **FEATURE**: Added 60+ missing methods to JavaScript client
- **FEATURE**: All endpoints now supported in both clients
- **ENHANCEMENT**: Improved error handling and documentation

### Version 1.0.0 (2025-08-11)
- Initial release with Python client
- Basic JavaScript client with limited functionality

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues and questions:
1. Check the [QuickBase API Documentation](https://developer.quickbase.com/)
2. Review the examples in this README
3. Open an issue with detailed error information

## Related Projects

- [QuickBase Official API Documentation](https://developer.quickbase.com/)
- [QuickBase JavaScript SDK](https://github.com/QuickBase/quickbase-cli) (Official)
- [QuickBase Python SDK](https://pypi.org/search/?q=quickbase) (Community)

---

*Built with ❤️ for the QuickBase developer community*