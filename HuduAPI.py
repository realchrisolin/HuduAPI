import time
import logging
from typing import Optional, Dict, Any, List, Union, Iterator, TypeVar, Generic
import requests
from dataclasses import dataclass
from datetime import datetime
import queue
import threading

T = TypeVar('T')


class RateLimiter:
    """Rate limiter using token bucket algorithm"""

    def __init__(self, rate: int = 300, per: int = 60):
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.last_update = time.time()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Acquire a token, blocking if none are available"""
        with self._lock:
            now = time.time()
            # Add new tokens based on time passed
            elapsed = now - self.last_update
            new_tokens = elapsed * (self.rate / self.per)
            self.tokens = min(self.rate, self.tokens + new_tokens)
            self.last_update = now

            if self.tokens < 1:
                # Calculate sleep time needed
                sleep_time = (1 - self.tokens) * (self.per / self.rate)
                time.sleep(sleep_time)
                self.tokens = 1

            self.tokens -= 1


@dataclass
class HuduEvent:
    """Event object for the pub/sub system"""
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class HuduEventBus:
    """Event bus for handling Hudu API events"""

    def __init__(self):
        self.subscribers: Dict[str, List[callable]] = {}
        self.queue = queue.Queue()
        self._running = False
        self._thread = None

    def subscribe(self, event_type: str, callback: callable) -> None:
        """Subscribe to an event type"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event: HuduEvent) -> None:
        """Publish an event to the bus"""
        self.queue.put(event)

    def _process_events(self) -> None:
        """Process events from the queue"""
        while self._running:
            try:
                event = self.queue.get(timeout=1)
                if event.event_type in self.subscribers:
                    for callback in self.subscribers[event.event_type]:
                        try:
                            callback(event)
                        except Exception as e:
                            logging.error(f"Error in event handler: {e}")
            except queue.Empty:
                continue

    def start(self) -> None:
        """Start the event processing thread"""
        self._running = True
        self._thread = threading.Thread(target=self._process_events)
        self._thread.daemon = True
        self._thread.start()

    def stop(self) -> None:
        """Stop the event processing thread"""
        self._running = False
        if self._thread:
            self._thread.join()


class PaginatedResponse(Generic[T]):
    """Iterator for handling paginated API responses"""

    def __init__(self, client: 'HuduClient', endpoint: str, response_key: str = None, **params):
        self.client = client
        self.endpoint = endpoint
        self.response_key = response_key
        self.params = params
        self.current_page = 1
        self.has_more = True
        self._current_batch: List[T] = []

    def __iter__(self) -> Iterator[T]:
        return self

    def __next__(self) -> T:
        if not self._current_batch and self.has_more:
            self._fetch_next_batch()

        if not self._current_batch and not self.has_more:
            raise StopIteration

        return self._current_batch.pop(0)

    def _fetch_next_batch(self) -> None:
        """Fetch the next batch of results"""
        self.params['page'] = self.current_page
        response = self.client._make_request('GET', self.endpoint, params=self.params)
        data = response.json()

        # Handle different response structures
        if self.response_key:
            items = data.get(self.response_key, [])
        elif isinstance(data, list):
            items = data
        else:
            items = [data] if data else []

        if not items:
            self.has_more = False
            return

        self._current_batch.extend(items)
        self.current_page += 1

    def all(self) -> List[T]:
        """Retrieve all results as a list"""
        return list(self)


class HuduClient:
    """Main client for interacting with the Hudu API"""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.rate_limiter = RateLimiter()
        self.event_bus = HuduEventBus()
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        })
        self.event_bus.start()

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make a rate-limited request to the API"""
        self.rate_limiter.acquire()
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()

            # Publish event for successful request
            self.event_bus.publish(HuduEvent(
                event_type=f"{method.lower()}_{endpoint.split('/')[0]}",
                data={'response': response.json() if response.text else None}
            ))

            return response
        except requests.exceptions.RequestException as e:
            # Publish event for failed request
            self.event_bus.publish(HuduEvent(
                event_type='request_error',
                data={'error': str(e), 'endpoint': endpoint}
            ))
            raise

    # Companies
    def get_companies(self, page_size: int = 25, **params) -> PaginatedResponse[Dict[str, Any]]:
        """Get a paginated list of companies with optional filtering"""
        params['page_size'] = page_size
        return PaginatedResponse(self, 'companies', None, **params)

    def create_company(self, company_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new company"""
        return self._make_request('POST', 'companies', json={'company': company_data}).json()

    def get_company(self, company_id: int) -> Dict[str, Any]:
        """Get a specific company by ID"""
        return self._make_request('GET', f'companies/{company_id}').json()

    # Assets
    def get_assets(self, page_size: int = 25, **params) -> PaginatedResponse[Dict[str, Any]]:
        """Get a paginated list of assets with optional filtering"""
        params['page_size'] = page_size
        return PaginatedResponse(self, 'assets', 'assets', **params)

    def create_asset(self, company_id: int, asset_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new asset for a company"""
        return self._make_request('POST', f'companies/{company_id}/assets',
                                  json={'asset': asset_data}).json()

    # Articles
    def get_articles(self, page_size: int = 25, **params) -> PaginatedResponse[Dict[str, Any]]:
        """Get a paginated list of articles with optional filtering"""
        params['page_size'] = page_size
        return PaginatedResponse(self, 'articles', None, **params)

    def create_article(self, article_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new article"""
        return self._make_request('POST', 'articles', json={'article': article_data}).json()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.event_bus.stop()
        self.session.close()


# Example usage
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)


    # Example event handler
    def log_company_events(event: HuduEvent):
        logging.info(f"Company event received: {event.event_type} at {event.timestamp}")


    # Create client
    client = HuduClient(
        api_key="your-api-key",
        base_url="https://your-hudu-domain.com"
    )

    # Subscribe to events
    client.event_bus.subscribe('get_companies', log_company_events)
    client.event_bus.subscribe('post_companies', log_company_events)
    client.event_bus.subscribe('request_error', lambda e: logging.error(f"API Error: {e.data}"))

    try:
        # Example of iterating through all companies
        for company in client.get_companies():
            logging.info(f"Processing company: {company['name']}")

        # Example of getting all companies as a list
        all_companies = client.get_companies().all()
        logging.info(f"Found {len(all_companies)} companies")

        # Example with filtering and custom page size
        recent_articles = client.get_articles(
            page_size=25,
            updated_at="2024-01-01T00:00:00Z,"
        )
        for article in recent_articles:
            logging.info(f"Recent article: {article['name']}")

    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        client.event_bus.stop()