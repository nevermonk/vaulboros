import asyncio
import json

from vaulboros.api_client import ApiResponse
from vaulboros.api.base import BaseApi, VaultResponse
from typing import Union

def get_obj_from_args_kwargs(obj_type:Union[object,list[object]], args:list, kwargs:dict, 
                            obj_kwargs_key:Union[str,list[str]]=None, obj_args_index:int=1):
    if type(obj_type) is not list:
        obj_type = [obj_type]

    if type(obj_kwargs_key) is not list:
        obj_kwargs_key = list(obj_kwargs_key)
    
    target_kwarg_key = None
    for obj_key in obj_kwargs_key:
        if obj_key in kwargs.keys():
            target_kwarg_key = obj_key

    if target_kwarg_key != None:
        obj = kwargs[target_kwarg_key]
    else:
        obj = args[obj_args_index]

    if type(obj) in obj_type:
        return obj, target_kwarg_key
    else:
        return False, None

class KvSecret: # контейнер для секрета
    
    def __init__(self, secret_path):
        self.path = secret_path
        self.path_parts = list(filter(bool,self.path.split('/')))
        self.inner_path = '/'.join(self.path_parts[1:]) # путь без secret engine
        self.location_path = '/'.join(self.path_parts[:-1])
        
        self.name = self.path_parts[-1]
        self.secret_engine_name = self.path_parts[0]

        self.data: dict = dict()
        self.version = None # версия актуальна только в контексте kv v2

        self.api_response: ApiResponse = None

        #--conditions--
        self.not_found = False

    @property
    def json(self):
        return json.dumps(self.dict)

    @property
    def dict(self):
        return self.data

    def __repr__(self) -> str:
        return self.path

    @classmethod
    def from_string_path(cls, path:str):
        return cls(
            secret_path = path
        )
    
    def update_from_get_kv1_api_response(self, response: ApiResponse):
        if response.status_code == 200:
            self.data = response.content['data']

        self.api_response = response

    def update_from_get_kv2_api_response(self, response: ApiResponse):
        if response.status_code == 200:
            self.data = response.content['data']['data']

        self.api_response = response

    @classmethod
    def from_kv1_api_response(cls, response: ApiResponse):
        pass

    @classmethod
    def from_kv2_api_response(cls, response: ApiResponse):
        pass

class KvLocation: # контейнер для локейшена в kv secret engine. Содержит KvSecret и другие KvLocation

    def __init__(self, location_path=None):
        self.__path = location_path

        self.__set_paths()

        self.secrets: list[KvSecret] = list()
        self.locations: list[KvLocation] = list()

        self.api_response: ApiResponse = None

        self.status = dict()

        #--conditions--
        self.not_found = False

    @property
    def path(self):
        return self.__path
    
    @path.setter
    def path(self, new_path_value):
        self.__path = new_path_value
        self.__set_paths()

    def __set_paths(self):
        if self.__path != None:
            self.path_parts = list(filter(bool,self.path.split('/')))
            self.inner_path = '/'.join(self.path_parts[1:]) # путь без secret engine
            
            self.name = self.path_parts[-1]
            self.secret_engine_name = self.path_parts[0]

    @property
    def dict(self):
        result_dict = dict()

        for secret in self.secrets:
            result_dict[secret.name] = secret.dict

        for location in self.locations:
            result_dict[location.name] = location.dict

        return result_dict

    @property
    def json(self):
        return json.dumps(self.dict)
    
    @property
    def number_of_secrets(self):
        secrets_num = len(self.secrets)
        for location in self.locations:
            secrets_num += location.number_of_secrets

        return secrets_num
    
    def __contains__(self, secret_obj:Union[str,KvSecret]):
        s_path = secret_obj if type(secret_obj) is str else secret_obj.path
        return s_path in list(map(lambda s: s.path, self.secrets))
    
    def __repr__(self) -> str:
        return self.path

    def update_from_list_api_response(self, response: ApiResponse): # kv and kv2 совместимое API
        if response.status_code == 200:
            for key in response.content['data']['keys']:
                if key.endswith('/'):
                    self.locations.append(KvLocation('/'.join(self.path_parts+[key])))
                else:
                    self.secrets.append(KvSecret('/'.join(self.path_parts+[key])))

        self.api_response = response

    @classmethod
    def from_string_path(cls, path:str):
        return cls(
            location_path = path
        )

class KvApi(BaseApi):

    def __init__(self, vault_url, vault_kv_engine_path, vault_token=None, **kwargs):
        super().__init__(vault_url=vault_url, vault_token=vault_token, vault_token_required=True, **kwargs)

        self.path = vault_kv_engine_path
        self.name = list(filter(bool,self.path.split('/')))[0]

    def secret_engine_obj_unification(unify_type: Union[KvSecret,KvLocation]):
        def obj_unification_wrapper(func):
            def wrapper(*args, **kwargs):
                args = list(args)

                target_obj, target_obj_kwargs_key = get_obj_from_args_kwargs([KvSecret,KvLocation,str], args, kwargs, ['secret_obj','location_obj'])

                if type(target_obj) == str:
                    target_obj = unify_type.from_string_path(target_obj)

                if target_obj_kwargs_key:
                    kwargs[target_obj_kwargs_key] = target_obj
                else:
                    args[1] = target_obj

                if asyncio.iscoroutinefunction(func):
                    async def awrapper():
                        return await func(*args, **kwargs)
                    return awrapper()
                else:
                    return func(*args, **kwargs)
            
            return wrapper
        return obj_unification_wrapper

    def check_secret_engine_obj_path(func):
        def wrapper(*args, **kwargs):
            target_obj, _ = get_obj_from_args_kwargs([KvSecret,KvLocation], args, kwargs, ['secret_obj','location_obj'])

            api_obj: KvApi = args[0]

            if api_obj.name != target_obj.secret_engine_name:
                raise Exception(f"Trying to process {type(target_obj)} for '{target_obj.secret_engine_name}' secret engine in '{api_obj.name}' secret engine api object")
            else:
                if asyncio.iscoroutinefunction(func):
                    async def awrapper():
                        return await func(*args, **kwargs)
                    return awrapper()
                else:
                    return func(*args, **kwargs)

        return wrapper
    
    def _get_get_secret_request_params(self, secret_obj:KvSecret) -> dict:

        return dict(
            url=f"{self.vault_url}/v1/{self.name}/{secret_obj.inner_path}"
        )
    
    def _post_process_get_secret_response(self, secret_obj:KvSecret, response: ApiResponse) -> KvSecret:
        if response.status_code == 200:
            secret_obj.update_from_get_kv1_api_response(response)
        
        return secret_obj

    @secret_engine_obj_unification(KvSecret)
    @check_secret_engine_obj_path
    def get_secret(self, secret_obj:Union[str,KvSecret]) -> VaultResponse:
        secret_response: ApiResponse = self._get(**self._get_get_secret_request_params(secret_obj))
        return VaultResponse(secret_response, self._post_process_get_secret_response(secret_obj, secret_response))
    
    @BaseApi.async_unavailable_fallback('get_secret')
    @secret_engine_obj_unification(KvSecret)
    @check_secret_engine_obj_path
    async def a_get_secret(self, secret_obj:Union[str,KvSecret]) -> VaultResponse:
        secret_response = await self._a_get(**self._get_get_secret_request_params(secret_obj))
        return VaultResponse(secret_response, self._post_process_get_secret_response(secret_obj, secret_response))

    def _get_list_secrets_request_params(self, location_obj:KvLocation) -> dict:
        return dict(
            url=f"{self.vault_url}/v1/{self.name}/{location_obj.inner_path}"
        )

    def _post_process_list_location_response(self, location_obj:KvLocation, response: ApiResponse) -> KvLocation:
        location_obj.update_from_list_api_response(response)

        return location_obj

    @secret_engine_obj_unification(KvLocation)
    @check_secret_engine_obj_path
    def list_location(self, location_obj:Union[str,KvLocation]):
        location_reponse = self._list(**self._get_list_secrets_request_params(location_obj))
        return VaultResponse(location_reponse, self._post_process_list_location_response(location_obj, location_reponse))

    @BaseApi.async_unavailable_fallback('list_location')
    @secret_engine_obj_unification(KvLocation)
    @check_secret_engine_obj_path
    async def a_list_location(self, location_obj:Union[str,KvLocation]):
        location_response = await self._a_list(**self._get_list_secrets_request_params(location_obj))
        return VaultResponse(location_response, self._post_process_list_location_response(location_obj, location_response))
    
    @secret_engine_obj_unification(KvLocation)
    @check_secret_engine_obj_path
    def load_location(self, location_obj:Union[str,KvLocation], recursive=False):
        if location_obj.api_response is None: # значит ничего для локейшена не спрашивалось
            self.list_location(location_obj)

        for secret in location_obj.secrets:
            self.get_secret(secret)

        if recursive:
            for location in location_obj.locations:
                self.load_location(location, recursive=True)

        return location_obj
    
    
    @BaseApi.async_unavailable_fallback('load_location')
    @secret_engine_obj_unification(KvLocation)
    @check_secret_engine_obj_path
    async def a_load_location(self, location_obj:Union[str,KvLocation], recursive=False, event_loop:asyncio.AbstractEventLoop=None):

        if event_loop is None:
            event_loop = asyncio.get_running_loop()

        if location_obj.api_response is None: # значит ничего для локейшена не спрашивалось
            #await event_loop.create_task(self.a_list_location(location_obj))
            await self.a_list_location(location_obj)

        tasks: list[asyncio.Task] = []

        if recursive:
            for location in location_obj.locations:
                tasks.append(event_loop.create_task(self.a_load_location(location, recursive=True, event_loop=event_loop)))

        for secret in location_obj.secrets:
            tasks.append(event_loop.create_task(self.a_get_secret(secret)))

        if len(tasks) != 0:
            await asyncio.wait(tasks)

        return location_obj

    def _get_create_secret_request_params(self, secret_obj:KvSecret) -> dict: # url и тело запроса для записи секрета
        return dict(
            url=f"{self.vault_url}/v1/{self.name}/{secret_obj.inner_path}",
            data=json.dumps(secret_obj.data)
        )

    def _post_process_create_secret_response(self, secret_obj:KvSecret, response: ApiResponse) -> KvSecret:
        if response.status_code in (200, 204):
            secret_obj.not_found = False

        secret_obj.api_response = response
        return secret_obj

    @secret_engine_obj_unification(KvSecret)
    @check_secret_engine_obj_path
    def create_secret(self, secret_obj:Union[str,KvSecret]) -> VaultResponse:
        secret_response: ApiResponse = self._post(**self._get_create_secret_request_params(secret_obj))
        return VaultResponse(secret_response, self._post_process_create_secret_response(secret_obj, secret_response))

    @BaseApi.async_unavailable_fallback('create_secret')
    @secret_engine_obj_unification(KvSecret)
    @check_secret_engine_obj_path
    async def a_create_secret(self, secret_obj:Union[str,KvSecret]) -> VaultResponse:
        secret_response: ApiResponse = await self._a_post(**self._get_create_secret_request_params(secret_obj))
        return VaultResponse(secret_response, self._post_process_create_secret_response(secret_obj, secret_response))

    def update_secret(self, secret_obj:Union[str,KvSecret]) -> VaultResponse:
        return self.create_secret(secret_obj)

    async def a_update_secret(self, secret_obj:Union[str,KvSecret]) -> VaultResponse:
        return await self.a_create_secret(secret_obj)

    def __get_delete_secret_request_params(self):
        pass

    def delete_secret(self):
        pass

    async def delete_secret(self):
        pass

class Kv2Api(KvApi):

    def __init__(self, vault_url, vault_kv_engine_path, vault_token=None, **kwargs):
        super().__init__(vault_url=vault_url, vault_token=vault_token, vault_kv_engine_path=vault_kv_engine_path,**kwargs)

    def _get_get_secret_request_params(self, secret_obj:KvSecret) -> dict:
    
        return dict(
            url=f"{self.vault_url}/v1/{self.name}/data/{secret_obj.inner_path}"
        )
    
    def _get_list_secrets_request_params(self, location_obj:KvLocation) -> dict:
        return dict(
            url=f"{self.vault_url}/v1/{self.name}/metadata/{location_obj.inner_path}"
        )
    
    def _post_process_get_secret_response(self, secret_obj: KvSecret, response: ApiResponse) -> KvSecret:
        secret_obj.update_from_get_kv2_api_response(response)

        return secret_obj

    def _get_create_secret_request_params(self, secret_obj: KvSecret) -> dict: # kv v2 пишет в /data/ и оборачивает данные в {"data": ...}
        return dict(
            url=f"{self.vault_url}/v1/{self.name}/data/{secret_obj.inner_path}",
            data=json.dumps({"data": secret_obj.data})
        )