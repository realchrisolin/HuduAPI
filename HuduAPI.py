import os
from typing import Optional, List, Any
from dotenv import load_dotenv
from uplink import Consumer, get, post, put, delete, returns, json, Path, Query, Body, response_handler, headers
import pydantic
from functools import partial, wraps
import backoff
import requests
from returns.result import Result, Success, Failure
from datetime import datetime
from ratelimit import limits, sleep_and_retry
import inspect

# Hudu's docs state limits are 300 API requests/minute
# The extra second is to give us a little buffer room, just in case
CALLS = 300
RATE_LIMIT = 59


class RateLimitedConsumer:
    """Wrapper class that adds rate limiting to all uplink-decorated methods"""

    def __init__(self, consumer_instance):
        self._consumer = consumer_instance
        for attr_name in dir(consumer_instance):
            if not attr_name.startswith('_'):  # skip private/special methods
                attr = getattr(consumer_instance, attr_name)
                if (inspect.ismethod(attr) and
                        any(hasattr(attr, decorator)
                            for decorator in ['get', 'post', 'put', 'delete'])):
                    setattr(self, attr_name, self._rate_limit_method(attr))
                else:
                    setattr(self, attr_name, attr)

    @sleep_and_retry
    @limits(calls=CALLS, period=RATE_LIMIT)
    def _rate_limit_method(self, method):
        @wraps(method)
        def wrapped(*args, **kwargs):
            return method(*args, **kwargs)

        return wrapped

class BaseModel(pydantic.BaseModel):
    model_config = {
        "arbitrary_types_allowed": True,
        "json_serialization": True,
        "ser_json_timedelta": "iso8601",
        "ser_json_bytes": "base64",
        "ser_json_inf_nan": "null",
        "validate_assignment": True
    }

    def pretty_print(self, indent: int = 2) -> str:
        """Returns a formatted string representation of the model with specified indentation."""
        import json
        def json_serializer(obj):
            if hasattr(obj, 'model_dump'):
                return obj.model_dump()
            return str(obj)

        return json.dumps(self.model_dump(), indent=indent, default=json_serializer)

    def __str__(self) -> str:
        """Provides a readable string representation of the model."""
        return self.pretty_print()

    def __repr__(self) -> str:
        """Provides a detailed string representation of the model."""
        class_name = self.__class__.__name__
        fields = [f"{key}={repr(value)}" for key, value in self.model_dump().items()]
        return f"{class_name}({', '.join(fields)})"

# Models
class AssetField(BaseModel):
    id: int
    label: Optional[str] = None
    position: int
    value: Optional[Any] = None

    def __init__(self, **data):
        # handle escaped JSON strings in value
        if isinstance(data.get('value'), str):
            try:
                import json
                if data['value'].startswith('{') and '\\\"' in data['value']:
                    data['value'] = data['value'].encode('utf-8').decode('unicode_escape')
                data['value'] = json.loads(data['value'])
            except json.JSONDecodeError as e:
                # if parsing fails, keep original string
                pass
        super().__init__(**data)

class IntegratorCard(BaseModel):
    """Represents an Integrator Card (based on the terminology Hudu uses) containing information about an integration with an external system."""
    id: int
    integrator_id: int
    integrator_name: str
    sync_id: int
    sync_identifier: Optional[str] = None
    sync_type: str
    primary_field: Optional[str] = None
    link: str
    data: Optional[dict[str, Any]] = None

class Company(BaseModel):
    id: int
    name: str
    phone_number: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country_name: Optional[str] = None
    company_type: Optional[str] = None
    parent_company_id: Optional[int] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None
    full_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Asset(BaseModel):
    id: int
    name: str
    company_id: int
    company_name: Optional[str] = None
    asset_layout_id: int
    fields: List[dict]
    primary_serial: Optional[str] = None
    primary_mail: Optional[str] = None
    primary_model: Optional[str] = None
    primary_manufacturer: Optional[str] = None
    archived: Optional[bool] = None
    object_type: Optional[str] = None
    asset_type: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    fields: Optional[List[AssetField]] = None
    cards: Optional[List[IntegratorCard]] = None


class AssetLayout(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    color: Optional[str] = None
    icon_color: Optional[str] = None
    include_passwords: bool
    include_photos: bool
    include_comments: bool
    include_files: bool
    active: bool


class AssetPassword(BaseModel):
    id: int
    passwordable_id: Optional[int]
    passwordable_type: Optional[str] = None
    company_id: int
    name: str
    username: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    password: str
    otp_secret: Optional[str] = None
    password_type: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    password_folder_id: Optional[int] = None
    password_folder_name: Optional[str] = None
    login_url: Optional[str] = None


class Article(BaseModel):
    id: int
    name: str
    content: Optional[str] = None
    folder_id: Optional[int] = None
    company_id: Optional[int] = None
    enable_sharing: bool = False
    draft: bool = False

class Relations(BaseModel):
    id: int
    description: Optional[str] = None
    is_inverse: Optional[bool] = None
    name: Optional[str] = None
    fromable_id: Optional[int] = None
    fromable_type: Optional[str] = None
    toable_id: Optional[int] = None
    toable_type: Optional[str] = None
    toable_url: Optional[str] = None

class Uploads(BaseModel):
    id: int
    url: Optional[str] = None
    name: Optional[str] = None
    ext: Optional[str] = None
    mime: Optional[str] = None
    size: Optional[str] = None
    created_date: Optional[str] = None
    archived_at: Optional[str] = None
    uploadable_id: Optional[int] = None
    uploadable_type: Optional[str] = None

# Custom exceptions
class HuduApiError(Exception):
    """Base exception for Hudu API errors"""
    pass


class HuduNotFoundError(HuduApiError):
    """Raised when a resource is not found"""
    pass


class HuduAuthenticationError(HuduApiError):
    """Raised when authentication fails"""
    pass


# API Client
class HuduAPI(Consumer):
    """
    Low-level Python client for the Hudu API with automatic rate limiting

    Args:
        base_url: The base URL for your Hudu instance (defaults to HUDU_BASE_URL env var)
        api_key: Your Hudu API key (defaults to HUDU_API_KEY env var)
    """

    @response_handler
    def raise_for_status(self):
        try:
            self.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Status Code: {self.status_code}")
            print(f"Response Headers: {self.headers}")
            print(f"Response Content: {self.content}")
            raise
        return self

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        # Load environment variables
        load_dotenv()

        # Get credentials from env vars if not provided
        self.base_url = base_url or os.getenv('HUDU_BASE_URL')
        self.api_key = api_key or os.getenv('HUDU_API_KEY')

        if not self.base_url:
            raise ValueError("base_url must be provided either directly or via HUDU_BASE_URL environment variable")
        if not self.api_key:
            raise ValueError("api_key must be provided either directly or via HUDU_API_KEY environment variable")

        # Ensure HTTP only to quickly work around cert issues on dev environments
        # if self.base_url.startswith('https://'):
        #     self.base_url = self.base_url.replace('https://', 'http://')
        # elif not self.base_url.startswith('http://'):
        #     self.base_url = f'http://{self.base_url}'

        # Initialize the consumer
        super().__init__(base_url=self.base_url)
        self.session.headers["x-api-key"] = self.api_key

        # Wrap with rate limiting
        self._api = RateLimitedConsumer(self)

        # Forward all API calls through the rate-limited wrapper
        for attr_name in dir(self._api):
            if not attr_name.startswith('_'):
                attr = getattr(self._api, attr_name)
                if inspect.ismethod(attr):
                    setattr(self, attr_name, attr)

    # Companies endpoints
    @returns.json
    @get("companies")
    def get_companies(self,
                      page: Query("page") = 1,
                      page_size: Query("page_size") = 25,
                      name: Query("name") = None,
                      phone_number: Query("phone_number") = None,
                      website: Query("website") = None
                      ) -> List[dict]:
        """Get companies with optional filtering"""

    @returns.json
    @get("companies/{company_id}")
    def get_company(self, company_id: Path("company_id")) -> dict:
        """Get a specific company by ID"""

    @returns.json
    @post("companies")
    def create_company(self, company: Body) -> dict:
        """Create a new company"""

    @returns.json
    @put("companies/{company_id}")
    def update_company(self, company_id: Path("company_id"), company: Body) -> dict:
        """Update an existing company"""

    @delete("companies/{company_id}")
    def delete_company(self, company_id: Path("company_id")):
        """Delete a company"""

    # Assets endpoints
    @returns.json
    @get("companies/{company_id}/assets")
    def get_company_assets(self,
                   company_id: Path("company_id"),
                   page: Query("page") = 1,
                   page_size: Query("page_size") = 25,
                   name: Query("name") = None,
                   archived: Query("archived") = None
                   ) -> List[dict]:
        """Get assets for a company"""

    @returns.json
    @get("companies/{company_id}/assets/{asset_id}")
    def get_company_asset(self, company_id: Path("company_id"), asset_id: Path("asset_id")) -> dict:
        """Get a specific asset"""

    @returns.json
    @get("assets")
    def get_assets(self,
                   page: Query("page") = 1,
                   page_size: Query("page_size") = 25,
                   id: Query("id") = None,
                   name: Query("name") = None,
                   primary_serial: Query("primary_serial") = None,
                   asset_layout_id: Query("asset_layout_id") = None,
                   archived: Query("archived") = bool,
                   slug: Query("slug") = None,
                   search: Query("search") = None,
                   updated_at: Query("updated_at") = None
                   ) -> List[dict]:
        """Get all assets"""

    @returns.json
    @post("companies/{company_id}/assets")
    def create_asset(self, company_id: Path("company_id"), asset: Body) -> dict:
        """Create a new asset"""

    @returns.json
    @put("companies/{company_id}/assets/{asset_id}")
    def update_asset(self, company_id: Path("company_id"), asset_id: Path("asset_id"), asset: Body) -> dict:
        """Update an existing asset"""

    @delete("companies/{company_id}/assets/{asset_id}")
    def delete_asset(self, company_id: Path("company_id"), asset_id: Path("asset_id")):
        """Delete an asset"""

    # Asset Layouts endpoints
    @returns.json
    @get("asset_layouts")
    def get_asset_layouts(self,
                          page: Query("page", 1),
                          name: Query("name", None)
                          ) -> List[dict]:
        """Get asset layouts"""

    @returns.json
    @get("asset_layouts/{layout_id}")
    def get_asset_layout(self, layout_id: Path("layout_id")) -> dict:
        """Get a specific asset layout"""

    # Articles endpoints
    @returns.json
    @get("articles")
    def get_articles(self,
                     page: Query("page") = 1,
                     page_size: Query("page_size") = 25,
                     company_id: Query("company_id") = None,
                     name: Query("name") = None,
                     draft: Query("draft") = None
                     ) -> List[dict]:
        """Get articles"""

    @returns.json
    @get("articles/{article_id}")
    def get_article(self, article_id: Path("article_id")) -> dict:
        """Get a specific article"""

    @returns.json
    @post("articles")
    def create_article(self, article: Body) -> dict:
        """Create a new article"""

    @returns.json
    @put("articles/{article_id}")
    def update_article(self, article_id: Path("article_id"), article: Body) -> dict:
        """Update an existing article"""

    @delete("articles/{article_id}")
    def delete_article(self, article_id: Path("article_id")):
        """Delete an article"""

    # Asset Passwords
    @returns.json
    @get("asset_passwords")
    def get_asset_passwords(self,
                      page: Query("page") = 1,
                      page_size: Query("page_size") = 25,
                      name: Query("name") = None,
                      company_id: Query("company_id") = None,
                      slug: Query("slug") = None,
                      search: Query("search") = None,
                      updated_at: Query("updated_at") = None
                      ) -> List[dict]:
        """Get asset passwords with optional filtering"""

    # Relations
    @returns.json
    @get("relations")
    def get_relations(self,
                      page: Query("page") = 1,
                      page_size: Query("page_size") = 25
                      ) -> List[dict]:
        """Get relations"""

    # Uploads
    @returns.json
    @get("uploads")
    def get_uploads(self,
                    page: Query("page") = 1,
                    page_size: Query("page_size") = 25
                    ) -> List[dict]:
        """Get uploads"""

# High-level client
class HuduClient:
    """High-level client for the Hudu API with proper error handling and data modeling"""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.api = HuduAPI(base_url, api_key)

    @backoff.on_exception(
        backoff.expo,
        (HuduApiError, ConnectionError),
        max_tries=3
    )
    def _handle_response(self, operation):
        """Handle API response with retries and error handling"""
        try:
            response = operation()
            return Success(response)
        except Exception as e:
            if hasattr(e, 'status_code'):
                if e.status_code == 404:
                    return Failure(HuduNotFoundError(str(e)))
                elif e.status_code == 401:
                    return Failure(HuduAuthenticationError(str(e)))
            return Failure(HuduApiError(str(e)))

    # Company methods
    def get_companies(self, **kwargs) -> Result[List[Company], HuduApiError]:
        """Get companies with optional filtering"""
        return self._handle_response(
            lambda: [Company(**c) for c in self.api.get_companies(**kwargs)[0]['companies']]
        )

    def get_company(self, company_id: int) -> Result[Company, HuduApiError]:
        """Get a specific company by ID"""
        return self._handle_response(
            lambda: Company(**self.api.get_company(company_id=company_id)[0]['company'])
        )

    def create_company(self, company: Company) -> Result[Company, HuduApiError]:
        """Create a new company"""
        company_dict = {"company": company.dict(exclude_unset=True)}
        return self._handle_response(
            lambda: Company(**self.api.create_company(company=company_dict)[0]['company'])
        )

    def update_company(self, company_id: int, company: Company) -> Result[Company, HuduApiError]:
        """Update an existing company"""
        company_dict = {"company": company.dict(exclude_unset=True)}
        return self._handle_response(
            lambda: Company(**self.api.update_company(company_id=company_id, company=company_dict)[0]['company'])
        )

    def delete_company(self, company_id: int) -> Result[None, HuduApiError]:
        """Delete a company"""
        return self._handle_response(
            lambda: self.api.delete_company(company_id=company_id)
        )

    def get_company_assets(self, company_id: int, **kwargs) -> Result[List[Asset], HuduApiError]:
        """Get assets for a company"""
        return self._handle_response(
            lambda: [Asset(**a) for a in self.api.get_assets(company_id=company_id, **kwargs)[0]['assets']]
        )

    def get_company_asset(self, company_id: int, asset_id: int) -> Result[Asset, HuduApiError]:
        """Get a specific company asset"""
        return self._handle_response(
            lambda: Asset(**self.api.get_asset(company_id=company_id, asset_id=asset_id)[0]['asset'])
        )

    def get_assets(self, **kwargs) -> Result[List[Asset], HuduApiError]:
        """Get assets"""
        return self._handle_response(
            lambda: [Asset(**a) for a in self.api.get_assets(**kwargs)[0]['assets']]
        )

    def create_asset(self, company_id: int, asset: Asset) -> Result[Asset, HuduApiError]:
        """Create a new asset"""
        asset_dict = {"asset": asset.dict(exclude_unset=True)}
        return self._handle_response(
            lambda: Asset(**self.api.create_asset(company_id=company_id, asset=asset_dict)[0]['asset'])
        )

    def update_asset(self, company_id: int, asset_id: int, asset: Asset) -> Result[Asset, HuduApiError]:
        """Update an existing asset"""
        asset_dict = {"asset": asset.dict(exclude_unset=True)}
        return self._handle_response(
            lambda: Asset(
                **self.api.update_asset(company_id=company_id, asset_id=asset_id, asset=asset_dict)[0]['asset'])
        )

    def delete_asset(self, company_id: int, asset_id: int) -> Result[None, HuduApiError]:
        """Delete an asset"""
        return self._handle_response(
            lambda: self.api.delete_asset(company_id=company_id, asset_id=asset_id)
        )

    def get_asset_layouts(self, **kwargs) -> Result[List[AssetLayout], HuduApiError]:
        """Get asset layouts"""
        return self._handle_response(
            lambda: [AssetLayout(**l) for l in self.api.get_asset_layouts(**kwargs)[0]['asset_layouts']]
        )

    def get_asset_layout(self, layout_id: int) -> Result[AssetLayout, HuduApiError]:
        """Get a specific asset layout"""
        return self._handle_response(
            lambda: AssetLayout(**self.api.get_asset_layout(layout_id=layout_id)[0]['asset_layout'])
        )

    def get_asset_passwords(self, **kwargs) -> Result[List[AssetPassword], HuduApiError]:
        """Get asset passwords"""
        return self._handle_response(
            lambda: [AssetPassword(**a) for a in self.api.get_asset_passwords(**kwargs)[0]['asset_passwords']]
        )

    def get_articles(self, **kwargs) -> Result[List[Article], HuduApiError]:
        """Get articles"""
        return self._handle_response(
            lambda: [Article(**a) for a in self.api.get_articles(**kwargs)[0]['articles']]
        )

    def get_article(self, article_id: int) -> Result[Article, HuduApiError]:
        """Get a specific article"""
        return self._handle_response(
            lambda: Article(**self.api.get_article(article_id=article_id)[0]['article'])
        )

    def create_article(self, article: Article) -> Result[Article, HuduApiError]:
        """Create a new article"""
        article_dict = {"article": article.dict(exclude_unset=True)}
        return self._handle_response(
            lambda: Article(**self.api.create_article(article=article_dict)[0]['article'])
        )

    def update_article(self, article_id: int, article: Article) -> Result[Article, HuduApiError]:
        """Update an existing article"""
        article_dict = {"article": article.dict(exclude_unset=True)}
        return self._handle_response(
            lambda: Article(**self.api.update_article(article_id=article_id, article=article_dict)[0]['article'])
        )

    # Relations
    def get_relations(self, **kwargs) -> Result[List[Relations], HuduApiError]:
        """Get relations"""
        return self._handle_response(
            lambda: [Relations(**r) for r in self.api.get_relations(**kwargs)[0]['relations']]
        )

    # Uploads
    def get_uploads(self, **kwargs) -> Result[[Uploads], HuduApiError]:
        """Get uploads"""
        return self._handle_response(
            lambda: [Uploads(**u) for u in self.api.get_uploads(**kwargs)]
        )