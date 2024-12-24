import os
from typing import Optional, Iterator, List, Dict, Any, Literal
from dotenv import load_dotenv
from uplink import Consumer, get, post, put, delete, returns, json, Path, Query, Body, response_handler, headers
from pydantic import BaseModel, Field
from functools import partial
import backoff
import requests
from returns.result import Result, Success, Failure
from returns.pipeline import flow
from returns.curry import curry
from datetime import datetime
from enum import Enum


# Models
class Company(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

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
    model_config = {"arbitrary_types_allowed": True}

    id: int
    name: str
    company_id: int
    asset_layout_id: int
    primary_serial: Optional[str] = None
    primary_mail: Optional[str] = None
    primary_model: Optional[str] = None
    primary_manufacturer: Optional[str] = None
    archived: Optional[bool] = None


class AssetLayout(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

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


class Article(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    id: int
    name: str
    content: Optional[str] = None
    folder_id: Optional[int] = None
    company_id: Optional[int] = None
    enable_sharing: bool = False
    draft: bool = False


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


# Low-level API client
class HuduAPI(Consumer):
    """
    Low-level Python client for the Hudu API

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

        # Ensure HTTP only (sledgehammer fix for HTTPS cert issues on dev/test envs)
        # if self.base_url.startswith('https://'):
        #     self.base_url = self.base_url.replace('https://', 'http://')
        # elif not self.base_url.startswith('http://'):
        #     self.base_url = f'http://{self.base_url}'

        super().__init__(base_url=self.base_url)
        self.session.headers["x-api-key"] = self.api_key

    # Companies
    @raise_for_status
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

    # Assets
    @returns.json
    @get("companies/{company_id}/assets")
    def get_assets(self,
                  company_id: Path("company_id"),
                  page: Query("page") = 1,
                  page_size: Query("page_size") = 25,
                  name: Query("name") = None,
                  archived: Query("archived") = None
                  ) -> List[dict]:
        """Get assets for a company"""

    @returns.json
    @get("companies/{company_id}/assets/{asset_id}")
    def get_asset(self, company_id: Path("company_id"), asset_id: Path("asset_id")) -> dict:
        """Get a specific asset"""

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

    # Asset Layouts
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

    # Articles
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


# Higher-level client with error handling and retries
class HuduClient:
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

    # Companies
    def list_companies(self, **kwargs) -> Result[List[Company], Exception]:
        """List companies with optional filtering"""
        return self._handle_response(
            lambda: [Company(**c) for c in self.api.get_companies(**kwargs)[0]['companies']]
        )

    def get_company(self, company_id: int) -> Result[Company, Exception]:
        """Get a specific company by ID"""
        return self._handle_response(
            lambda: Company(**self.api.get_company(company_id))
        )

    def create_company(self, company: Company) -> Result[Company, Exception]:
        """Create a new company"""
        return self._handle_response(
            lambda: Company(**self.api.create_company(company.dict(exclude_unset=True)))
        )

    # Assets
    def list_assets(self, company_id: int, **kwargs) -> Result[List[Asset], Exception]:
        """List assets for a company"""
        return self._handle_response(
            lambda: [Asset(**a) for a in self.api.get_assets(company_id, **kwargs)]
        )

    def get_asset(self, company_id: int, asset_id: int) -> Result[Asset, Exception]:
        """Get a specific asset"""
        return self._handle_response(
            lambda: Asset(**self.api.get_asset(company_id, asset_id))
        )

    def create_asset(self, company_id: int, asset: Asset) -> Result[Asset, Exception]:
        """Create a new asset"""
        return self._handle_response(
            lambda: Asset(**self.api.create_asset(company_id, asset.dict(exclude_unset=True)))
        )

    # Asset Layouts
    def list_asset_layouts(self, **kwargs) -> Result[List[AssetLayout], Exception]:
        """List asset layouts"""
        return self._handle_response(
            lambda: [AssetLayout(**a) for a in self.api.get_asset_layouts(**kwargs)]
        )

    def get_asset_layout(self, layout_id: int) -> Result[AssetLayout, Exception]:
        """Get a specific asset layout"""
        return self._handle_response(
            lambda: AssetLayout(**self.api.get_asset_layout(layout_id))
        )

    # Articles
    def list_articles(self, **kwargs) -> Result[List[Article], Exception]:
        """List articles"""
        return self._handle_response(
            lambda: [Article(**a) for a in self.api.get_articles(**kwargs)]
        )

    def get_article(self, article_id: int) -> Result[Article, Exception]:
        """Get a specific article"""
        return self._handle_response(
            lambda: Article(**self.api.get_article(article_id))
        )

    def create_article(self, article: Article) -> Result[Article, Exception]:
        """Create a new article"""
        return self._handle_response(
            lambda: Article(**self.api.create_article(article.dict(exclude_unset=True)))
        )

    def update_article(self, article_id: int, article: Article) -> Result[Article, Exception]:
        """Update an existing article"""
        return self._handle_response(
            lambda: Article(**self.api.update_article(article_id, article.dict(exclude_unset=True)))
        )

    # Convenience methods
    def get_company_assets(self, company_id: int) -> Result[List[Asset], Exception]:
        """Get all assets for a company with error handling"""
        return flow(
            self.get_company(company_id),
            lambda company: self.list_assets(company.id)
        )