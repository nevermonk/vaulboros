import asyncio
import requests
import json
import datetime

from collections import defaultdict
from typing import Union

try:
    import aiohttp
    AIOHTTP_INSTALLED = True
except:
    AIOHTTP_INSTALLED = False

class ApiRequest:

    def __init__(self, url: str, method: str, headers: dict={}, data: str=""):
        self.url = url
        self.method = method
        self.headers = headers
        self.data = data

class ApiResponse:

    def __init__(self, url: str, method: str, headers: dict, status_code: int, content: str):
        self.url = url
        self.method = method
        self.headers = headers
        self.status_code = status_code
        self.content = content

        self.request: ApiRequest = None

    def __repr__(self) -> str:
        return f"{self.status_code} - {self.url}: {self.content}"

    @classmethod
    def from_requests_response(cls, response: requests.Response):
        
        try:
            content = json.loads(response.content.decode())
        except:
            content = response.content

        return cls(
            url = response.url,
            method = response.request.method.lower(),
            headers = response.headers,
            status_code = response.status_code,
            content = content
        )
    
    @classmethod
    async def from_aiohttp_response(cls, response):
        response: aiohttp.ClientResponse = response

        headers = response.headers
        status_code = response.status
        content = await response.json()
        url = str(response.url)
        method = response.method.lower()

        return cls(
            url, method, headers, status_code, content
        )

# очень простой кеш, который будет хранить мапу METHOD[URL] <--> ApiResponse и возвращать с него ответы
class Cache:

    def __init__(self):
        self.__cache = defaultdict(dict)
        self.stats = dict(
            number_of_queries = 0
        )

    def add(self, response: ApiResponse):
        self.__cache[response.method][response.url] = response

    def get(self, request: ApiRequest) -> ApiResponse:
        if request.url in self.__cache[request.method].keys():
            self.stats['number_of_queries'] += 1
            return self.__cache[request.method][request.url]
        
    def full(self):
        return self.__cache

    def __contains__(self, item: ApiRequest):
        return item.url in self.__cache[item.method].keys()

class BaseApiClient: # класс с общими методами для sync, async

    logger = None

    def __init__(self, common_headers: dict={}, cache_response: bool=True, cache=None) -> None:
        self.common_headers = common_headers
        self.cache_response = cache_response

        self.cache = Cache() if cache is None else cache

    @staticmethod
    def log_response(response: ApiResponse) -> None:
        if BaseApiClient.logger is not None:
            print(f"[ {datetime.datetime.now()} ] [{response.method}] <-- {response.url} - {response.status_code}")
    
    @staticmethod
    def log_request(request: ApiRequest) -> None:
        if BaseApiClient.logger is not None:
            print(f"[ {datetime.datetime.now()} ] [{request.method}] --> {request.url} - H: {request.headers} D: {request.data}")

class AsyncApiClient(BaseApiClient):

    available = AIOHTTP_INSTALLED

    def __init__(self, common_headers={}, cache_response: bool=True, cache: Cache=None):

        if not AsyncApiClient.available:
            raise Exception("You are trying to use async api client but aiohttp is not installed! It's not gonna work!")

        super().__init__(common_headers, cache_response, cache)

    async def _request(self, request: ApiRequest) -> ApiResponse:
        response: ApiResponse = None

        self.log_request(request)

        if self.cache_response:
            if request in self.cache:
                response = self.cache.get(request)

        if response is None:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                        method=request.method, 
                        url=request.url, 
                        data=request.data,
                        headers=request.headers) as raw_response:
                    
                    response = await ApiResponse.from_aiohttp_response(raw_response)

            response.request = request

            if self.cache_response:
                self.cache.add(response)

        self.log_response(response)

        return response

    async def get(self, url, headers={}) -> ApiResponse:
        response = await self._request(ApiRequest(url, 'get', {**headers, **self.common_headers}))
        return response
    
    async def post(self, url, headers={}, data="") -> ApiResponse:
        response = await self._request(ApiRequest(url, 'post', {**headers, **self.common_headers}, data))
        return response
    
    async def list(self, url, headers={}) -> ApiResponse:
        response = await self._request(ApiRequest(url, 'list', {**headers, **self.common_headers}))
        return response

class SyncApiClient(BaseApiClient):

    def __init__(self, common_headers={}, cache_response: bool=True, cache: Cache=None):
        super().__init__(common_headers, cache_response, cache)

    def _request(self, request: ApiRequest) -> ApiResponse:
        response: ApiResponse = None

        self.log_request(request)

        if self.cache_response:
            if request in self.cache:
                response = self.cache.get(request)

        if response is None:

            raw_response = requests.request(
                method=request.method,
                url=request.url,
                data=request.data,
                headers=request.headers
            )

            response = ApiResponse.from_requests_response(raw_response)

            response.request = request

            if self.cache_response:
                self.cache.add(response)

        self.log_response(response)

        return response
    
    def get(self, url, headers={}) -> ApiResponse:
        response = self._request(ApiRequest(url, 'get', {**headers, **self.common_headers}))

        return response

    def post(self, url, headers={}, data="") -> ApiResponse:
        response = self._request(ApiRequest(url, 'post', {**headers, **self.common_headers}, data))

        return response

    def list(self, url, headers={}) -> ApiResponse:
        response = self._request(ApiRequest(url, 'list', {**headers, **self.common_headers}))

        return response
    
def sync_async_clients_fabric() -> tuple[SyncApiClient, AsyncApiClient]:

    cache_obj = Cache()
    sync_client = SyncApiClient(cache=cache_obj)
    async_client = AsyncApiClient(cache=cache_obj)

    return sync_client, async_client