import inspect
from vaulboros.api_client import SyncApiClient, AsyncApiClient, ApiResponse, sync_async_clients_fabric

class VaultResponse:

    def __init__(self, api_reponse: ApiResponse, response_entity: any=None):
        self.result = response_entity
        self.api_response = api_reponse

class VaultToken:
    
    def __init__(self, vault_token):
        self.token = vault_token

    def __repr__(self) -> str:
        return str(self.token)

    @classmethod
    def from_api_response(cls, response: ApiResponse):
        token = cls(vault_token = response.content['auth']['client_token'])
        return token 

class Headers:

    def __init__(self, sync_client: SyncApiClient, async_client: AsyncApiClient):
        self.sync_client_headers = sync_client.common_headers
        
        self.async_client_headers = False if not async_client else async_client.common_headers

    def __setitem__(self, key, value):
        header_value = str(value)
        self.sync_client_headers[key] = header_value

        if self.async_client_headers is not False:
            self.async_client_headers[key] = header_value

    def __getitem__(self, key):
        if key in self.sync_client_headers.keys():
            return_header = self.sync_client_headers[key]
        else:
            return_header = None
        return return_header
    
    def __repr__(self) -> str:
        return str(self.sync_client_headers)

class BaseApi: # базовый класс для API
        

    def __init__(self, vault_url=None, vault_token: VaultToken=None, vault_token_required=False,
                    sync_client: SyncApiClient=None, async_client: AsyncApiClient=None, headers=None):

        self.vault_url = vault_url
        self.__sync_client, self.__async_client = sync_async_clients_fabric()

        self.headers = headers if headers is not None else Headers(self.__sync_client, self.__async_client)

        if self.vault_token is None and vault_token is not None: # если хедер уже не установлен, но токен передается в конструктор - устанавливаем
            self.vault_token = vault_token

        if vault_token_required and self.vault_token is None:
            raise Exception(f"No vault token provided via parameter or via another Api object. Can't create {__class__.__name__} object")
        

    @staticmethod
    def async_unavailable_fallback(fallback_func_name): # если async не поддерживается, то будет вызван синхронный метод (и разницы с запуском в синхронном режиме не будет)
        def fallback_decorator(target_func):
            async def wrapper(self, *args, **kwargs):
                if not self.__async_client:
                    return getattr(self,fallback_func_name)(*args, **kwargs) # это синхронный метод
                else:
                    return await target_func(self, *args, **kwargs) # это асинхронный метод
            return wrapper
        return fallback_decorator

    def persist_api_token(self, token: VaultToken):
        self.vault_token = token

    @property
    def vault_token(self):
        return self.headers['X-Vault-Token']
    
    @vault_token.setter
    def vault_token(self, token):
        self.headers['X-Vault-Token'] = token

    def _get(self, *args, **kwargs) -> ApiResponse:
        return self.__sync_client.get(*args, **kwargs)

    def _post(self, *args, **kwargs) -> ApiResponse:
        return self.__sync_client.post(*args, **kwargs)

    def _list(self, *args, **kwargs) -> ApiResponse:
        return self.__sync_client.list(*args, **kwargs)

    async def _a_get(self, *args, **kwargs) -> ApiResponse:
        return await self.__async_client.get(*args, **kwargs)

    async def _a_post(self, *args, **kwargs) -> ApiResponse:
        return await self.__async_client.post(*args, **kwargs)

    async def _a_list(self, *args, **kwargs) -> ApiResponse:
        return await self.__async_client.list(*args, **kwargs)

    @classmethod
    def from_api_instance(cls, api_instance, **kwargs): # создать API объект, копируя некоторые базовые сущности из другого (url, api_client)
        return cls(
            vault_url = api_instance.vault_url,
            sync_client = api_instance._BaseApi__sync_client, # private method name mangling
            async_client = api_instance._BaseApi__async_client,
            headers = api_instance.headers,
            **kwargs
        )