# Python Hudu API Client

A Python client for the Hudu API with automatic rate limiting, error handling, and data modeling.

> **Note**: This project is a work in progress. The current implementation covers core API endpoints but is not a complete implementation of the Hudu API specification.

## Features

- Automatic rate limiting (300 requests/minute)
- Comprehensive error handling with retries
- Type-safe data models using Pydantic
- High-level client with Result type returns
- Low-level client for direct API access

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in your project root:

```env
HUDU_BASE_URL=https://your-hudu-instance.com
HUDU_API_KEY=your-api-key
```

## Quick Start

```python
from HuduAPI import HuduClient

# Initialize using .env configuration
client = HuduClient()

# Or provide credentials directly
client = HuduClient(
    base_url="https://your-hudu-instance.com",
    api_key="your-api-key"
)

# Example usage
result = client.get_companies()
if result.is_success():
    companies = result.unwrap()
    for company in companies:
        print(f"Company: {company.name}")
```

## API Documentation

This client is an indie Available endpoints include Companies, Assets, Asset Layouts, Articles, Asset Passwords, Relations, and Uploads.

## Error Handling

The high-level client returns a `Result` type that can be either `Success` or `Failure`:

```python
result = client.get_company(123)
if result.is_success():
    company = result.unwrap()
    print(f"Found company: {company.name}")
else:
    error = result.failure()
    print(f"Error: {error}")
```

Custom exceptions:
- `HuduApiError`: Base exception
- `HuduNotFoundError`: Resource not found (404)
- `HuduAuthenticationError`: Authentication failed (401)

## Rate Limiting

The low-level API (which the high-level client inherits from) handles Hudu's rate limit of 300 requests per minute. Rate limiting is implemented using a decorator to ensure calls don't exceed this limit.

## License

MIT License

Copyright (c) 2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.