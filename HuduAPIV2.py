import os
from typing import Optional, Iterator, List, Dict, Any
from dotenv import load_dotenv
from uplink import Consumer, get, post, put, delete, returns, json, Path, Query, Body, headers
from pydantic import BaseModel, Field
from functools import partial
import backoff
from returns.result import Result, Success, Failure
from returns.pipeline import flow
from returns.curry import curry
from datetime import datetime
from enum import Enum


# Models
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


class Asset(BaseModel):
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


# API Client
class HuduClient(Consumer):
    """
    Python client for the Hudu API

    Args:
        base_url: The base URL for your Hudu instance (defaults to HUDU_BASE_URL env var)
        api_key: Your Hudu API key (defaults to HUDU_API_KEY env var)
    """

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

        # Ensure HTTP only
        if self.base_url.startswith('https://'):
            self.base_url = self.base_url.replace('https://', 'http://')
        elif not self.base_url.startswith('http://'):
            self.base_url = f'http://{self.base_url}'

        super().__init__(base_url=self.base_url)
        self.session.headers["x-api-key"] = self.api_key

    # Companies
    @returns.json
    @get("companies")
    def list_companies(self,
                       page: Optional[int] = Query("page", default=1),
                       page_size: Optional[int] = Query("page_size", default=25),
                       name: Optional[str] = Query("name"),
                       phone_number: Optional[str] = Query("phone_number"),
                       website: Optional[str] = Query("website")
                       ) -> List[Dict]:
        """List companies with optional filtering"""

    @returns.json
    @get("companies/{company_id}")
    def get_company(self, company_id: Path("company_id")) -> Dict:
        """Get a specific company by ID"""

    @returns.json
    @post("companies")
    def create_company(self, company: Body) -> Dict:
        """Create a new company"""

    @returns.json
    @put("companies/{company_id}")
    def update_company(self, company_id: Path("company_id"), company: Body) -> Dict:
        """Update an existing company"""

    @delete("companies/{company_id}")
    def delete_company(self, company_id: Path("company_id")):
        """Delete a company"""

    # Assets
    @returns.json
    @get("companies/{company_id}/assets")
    def list_assets(self,
                    company_id: Path("company_id"),
                    page: Optional[int] = Query("page", default=1),
                    page_size: Optional[int] = Query("page_size", default=25),
                    name: Optional[str] = Query("name"),
                    archived: Optional[bool] = Query("archived")
                    ) -> List[Dict]:
        """List assets for a company"""

    @returns.json
    @get("companies/{company_id}/assets/{asset_id}")
    def get_asset(self, company_id: Path("company_id"), asset_id: Path("id")) -> Dict:
        """Get a specific asset"""

    @returns.json
    @post("companies/{company_id}/assets")
    def create_asset(self, company_id: Path("company_id"), asset: Body) -> Dict:
        """Create a new asset"""

    @returns.json
    @put("companies/{company_id}/assets/{asset_id}")
    def update_asset(self, company_id: Path("company_id"), asset_id: Path("id"), asset: Body) -> Dict:
        """Update an existing asset"""

    @delete("companies/{company_id}/assets/{asset_id}")
    def delete_asset(self, company_id: Path("company_id"), asset_id: Path("id")):
        """Delete an asset"""

    # Asset Layouts
    @returns.json
    @get("asset_layouts")
    def list_asset_layouts(self,
                           page: Optional[int] = Query("page", default=1),
                           name: Optional[str] = Query("name")
                           ) -> List[Dict]:
        """List asset layouts"""

    @returns.json
    @get("asset_layouts/{layout_id}")
    def get_asset_layout(self, layout_id: Path("id")) -> Dict:
        """Get a specific asset layout"""

    # Articles
    @returns.json
    @get("articles")
    def list_articles(self,
                      page: Optional[int] = Query("page", default=1),
                      page_size: Optional[int] = Query("page_size", default=25),
                      company_id: Optional[int] = Query("company_id"),
                      name: Optional[str] = Query("name"),
                      draft: Optional[bool] = Query("draft")
                      ) -> List[Dict]:
        """List articles"""

    @returns.json
    @get("articles/{article_id}")
    def get_article(self, article_id: Path("id")) -> Dict:
        """Get a specific article"""

    @returns.json
    @post("articles")
    def create_article(self, article: Body) -> Dict:
        """Create a new article"""

    @returns.json
    @put("articles/{article_id}")
    def update_article(self, article_id: Path("id"), article: Body) -> Dict:
        """Update an existing article"""

    @delete("articles/{article_id}")
    def delete_article(self, article_id: Path("id")):
        """Delete an article"""


# Higher-level wrapper with error handling and retries
class HuduAPI:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.client = HuduClient(base_url, api_key)

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
    def get_companies(self, **kwargs) -> Result[List[Company], Exception]:
        """Get list of companies with optional filtering"""
        return self._handle_response(
            lambda: [Company(**c) for c in self.client.list_companies(**kwargs)]
        )

    def get_company(self, company_id: int) -> Result[Company, Exception]:
        """Get a specific company by ID"""
        return self._handle_response(
            lambda: Company(**self.client.get_company(company_id))
        )

    def create_company(self, company: Company) -> Result[Company, Exception]:
        """Create a new company"""
        return self._handle_response(
            lambda: Company(**self.client.create_company(company.dict(exclude_unset=True)))
        )

    # Assets
    def get_assets(self, company_id: int, **kwargs) -> Result[List[Asset], Exception]:
        """Get list of assets for a company"""
        return self._handle_response(
            lambda: [Asset(**a) for a in self.client.list_assets(company_id, **kwargs)]
        )

    def get_asset(self, company_id: int, asset_id: int) -> Result[Asset, Exception]:
        """Get a specific asset"""
        return self._handle_response(
            lambda: Asset(**self.client.get_asset(company_id, asset_id))
        )

    def create_asset(self, company_id: int, asset: Asset) -> Result[Asset, Exception]:
        """Create a new asset"""
        return self._handle_response(
            lambda: Asset(**self.client.create_asset(company_id, asset.dict(exclude_unset=True)))
        )

    # Example usage
    def get_company_assets(self, company_id: int) -> Result[List[Asset], Exception]:
        """Get all assets for a company with error handling"""
        return flow(
            self.get_company(company_id),
            lambda company: self.get_assets(company.id)
        )