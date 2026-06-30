import asyncio
from typing import Union
from collections import defaultdict, namedtuple

from vaulboros.api import ApproleApi, KvApi, Kv2Api, MountApi, VaultToken, BaseApi, TokenApi
from vaulboros.api.base import VaultResponse
from vaulboros.api.kv import KvSecret, KvLocation

class Vault:
    # общий класс для работы с HashiCorp Vault, который использует сущности библиотеки

    def __init__(self, vault_url, login_obj: BaseApi):
        self.vault_url = vault_url
        self.login_obj = login_obj

        self.mounts: MountApi

    def init(self):
        mounts_api = MountApi.from_api_instance(self.login_obj)
        mounts_load_response = mounts_api.load_existing_mounts()

        self.__post_process_mounts_load(mounts_api, mounts_load_response)

    async def a_init(self):
        mounts_api = MountApi.from_api_instance(self.login_obj)
        mounts_load_response = await mounts_api.a_load_existing_mounts()

        self.__post_process_mounts_load(mounts_api, mounts_load_response)

    def __post_process_mounts_load(self, mounts: MountApi, vault_mounts_load_response: VaultResponse):
        if vault_mounts_load_response.api_response.status_code != 200:
            raise Exception(f"Failed to load secret mounts (/sys/mounts). {vault_mounts_load_response.api_response}")

        self.mounts = mounts

    def __get_api_instance_for_kv_object(self, kv_object: Union[KvSecret,KvLocation]) -> Union[KvApi,Kv2Api]:
        if kv_object.secret_engine_name in self.mounts:
            mount = self.mounts[kv_object.secret_engine_name]
            if mount.type == "kv":
                kv_api: KvApi = mount.api
                return kv_api
            else:
                raise Exception(f"{kv_object.secret_engine_name} is not a KV secret engine mount! It's {mount.path} - {mount.type}")
        else:
            raise Exception(f"Secret engine {kv_object.secret_engine_name} does not exist!")
        
    def __post_process_get_kv_secret(self, secret_vault_response: VaultResponse, not_found_ok=True) -> KvSecret:
        result: KvSecret = secret_vault_response.result

        if secret_vault_response.api_response.status_code == 200:
            return result
        elif secret_vault_response.api_response.status_code == 404:
            if not_found_ok is not True:
                raise Exception(f"Secret {result.path} not found. {secret_vault_response.api_response}")
            else: 
                result.not_found = True # setting condition
        elif secret_vault_response.api_response.status_code in (403,401):
            raise Exception(f"Permission denied getting secret {result.path}. {secret_vault_response.api_response}")
        
        return result

    def get_kv_secret(self, secret:Union[str,KvSecret], not_found_ok=True) -> KvSecret:
        if type(secret) is not KvSecret:
            secret = KvSecret(secret)

        kv_api = self.__get_api_instance_for_kv_object(secret)
        
        kv_secret_response = kv_api.get_secret(secret)
        return self.__post_process_get_kv_secret(kv_secret_response, not_found_ok)

    def __build_kv_secret_for_write(self, secret:Union[str,KvSecret], data:dict=None) -> KvSecret: # подготовка объекта секрета к записи
        if type(secret) is not KvSecret:
            secret = KvSecret(secret)
        if data is not None:
            secret.data = data
        return secret

    def __post_process_create_kv_secret(self, secret_vault_response: VaultResponse) -> KvSecret:
        result: KvSecret = secret_vault_response.result

        if secret_vault_response.api_response.status_code in (200, 204):
            return result
        elif secret_vault_response.api_response.status_code in (403, 401):
            raise Exception(f"Permission denied writing secret {result.path}. {secret_vault_response.api_response}")
        else:
            raise Exception(f"Failed to write secret {result.path}. {secret_vault_response.api_response}")

    def create_kv_secret(self, secret:Union[str,KvSecret], data:dict=None) -> KvSecret:
        secret = self.__build_kv_secret_for_write(secret, data)
        kv_api = self.__get_api_instance_for_kv_object(secret)

        kv_secret_response = kv_api.create_secret(secret)
        return self.__post_process_create_kv_secret(kv_secret_response)

    async def a_create_kv_secret(self, secret:Union[str,KvSecret], data:dict=None) -> KvSecret:
        secret = self.__build_kv_secret_for_write(secret, data)
        kv_api = self.__get_api_instance_for_kv_object(secret)

        kv_secret_response = await kv_api.a_create_secret(secret)
        return self.__post_process_create_kv_secret(kv_secret_response)
    
    def __get_locations_secret_map(self, secrets:list[KvSecret], min_secrets_for_location_mapping:int) -> dict[str, KvLocation]:
        
        class SecretLocation:
            def __init__(self):
                self.kv_location = KvLocation()
                self.secrets = []
                
        location_secrets_map: dict[str,SecretLocation] = defaultdict(SecretLocation)

        for secret_obj in secrets:
            location_secrets_map[secret_obj.location_path].secrets.append(secret_obj.name)
            location_secrets_map[secret_obj.location_path].kv_location.path = secret_obj.location_path

        location_secrets_map_result = {l_path: secret_location.kv_location for l_path, secret_location in location_secrets_map.items() if len(secret_location.secrets) >= min_secrets_for_location_mapping}

        return location_secrets_map_result

    def get_kv_secrets(self, secrets:Union[list[str],list[KvSecret]], not_found_ok=True, 
                            list_shared_location=False, list_shared_location_min_secrets=3, return_with_not_found=False) -> list[KvSecret]:
        secrets_result: list[KvSecret] = []
        secrets: list[KvSecret] = [KvSecret(secret_obj) if type(secret_obj) is str else secret_obj for secret_obj in secrets]

        if list_shared_location:
            location_mapping = self.__get_locations_secret_map(secrets, min_secrets_for_location_mapping=list_shared_location_min_secrets)

            for location_path,location_obj in location_mapping.items():
                self.get_kv_location(location_obj)

        for secret_obj in secrets:
            if list_shared_location:
                if secret_obj.location_path in location_mapping.keys():
                    if secret_obj not in location_mapping[secret_obj.location_path]:
                        secret_obj.not_found = True
                        secrets_result.append(secret_obj)
                        continue

            secrets_result.append(self.get_kv_secret(secret_obj, not_found_ok))

        if not return_with_not_found:
            return list(filter(lambda secret: secret.not_found == False, secrets_result))
        else:
            return secrets_result
    
    async def a_get_kv_secret(self, secret:Union[str,KvSecret], not_found_ok=True) -> KvSecret:
        if type(secret) is str:
            secret = KvSecret(secret)

        kv_api = self.__get_api_instance_for_kv_object(secret)
        
        kv_secret_response = await kv_api.a_get_secret(secret)
        return self.__post_process_get_kv_secret(kv_secret_response, not_found_ok)
    
    async def a_get_kv_secrets(self, secrets:Union[list[str],list[KvSecret]], 
                                    list_shared_location=False, list_shared_location_min_secrets=3, return_with_not_found=False) -> list[KvSecret]:
        secret_tasks: list[asyncio.Task] = []
        list_get_secrets_tasks: list[asyncio.Task] = []

        secrets_result: list[KvSecret] = []
        secrets: list[KvSecret] = [KvSecret(secret_obj) if type(secret_obj) is str else secret_obj for secret_obj in secrets]

        if list_shared_location:
            location_mapping = self.__get_locations_secret_map(secrets, min_secrets_for_location_mapping=list_shared_location_min_secrets)

            async def list_get_secrets_wrapped(location_path:str, secrets_for_location:list[KvSecret]):
                nonlocal secrets
                kv_location = location_mapping[location_path]

                get_location_task = asyncio.create_task(self.a_get_kv_location(kv_location))
                await get_location_task # загружаем объект

                for secret_obj in secrets_for_location:
                    if secret_obj in kv_location:
                        secret_tasks.append(asyncio.create_task(self.a_get_kv_secret(secret_obj)))
                    else:
                        secret_obj.not_found = True
                        secrets_result.append(secret_obj)

            for location_path,location_obj in location_mapping.items():
                secrets_for_location = list(filter(lambda secret: secret.location_path == location_path, secrets))
                secrets = list(set(secrets) - set(secrets_for_location))
                list_get_secrets_tasks.append(asyncio.create_task(list_get_secrets_wrapped(location_path, secrets_for_location)))

        for secret_obj in secrets:
            secret_tasks.append(asyncio.create_task(self.a_get_kv_secret(secret_obj)))

        if len(list_get_secrets_tasks) > 0:
            await asyncio.wait(list_get_secrets_tasks)

        secrets_result: list[KvSecret] = [*secrets_result, *await asyncio.gather(*secret_tasks)]

        if not return_with_not_found:
            return list(filter(lambda secret: secret.not_found == False, secrets_result))
        else:
            return secrets_result
        
    def __post_process_get_kv_location(self, location_vault_response: VaultResponse, not_found_ok=True) -> KvLocation:
        result: KvLocation = location_vault_response.result

        if location_vault_response.api_response.status_code == 200:
            return result
        elif location_vault_response.api_response.status_code == 404:
            if not_found_ok is not True:
                raise Exception(f"Secret location {result.path} not found. {location_vault_response.api_response}")
            else:
                result.not_found = True
        elif location_vault_response.api_response.status_code in (403,401):
            raise Exception(f"Permission denied getting secret {result.path}. {location_vault_response.api_response}")
        
        return result

    def get_kv_location(self, location_obj:Union[str,KvLocation], not_found_ok=True, 
                                load_location=False, load_location_recursive=False) -> KvLocation:
        if type(location_obj) is str:
            location_obj = KvLocation(location_obj)

        kv_api = self.__get_api_instance_for_kv_object(location_obj)

        if location_obj.api_response is None:
            kv_location_response = kv_api.list_location(location_obj)

        if load_location is True:
            for secret in location_obj.secrets:
                self.get_kv_secret(secret, not_found_ok)

            if load_location_recursive is True:
                for location in location_obj.locations:
                    self.get_kv_location(location, not_found_ok=not_found_ok, load_location=True, load_location_recursive=True)

        return self.__post_process_get_kv_location(kv_location_response, not_found_ok)

    def get_kv_locations(self, location_paths: list[str], not_found_ok=True,
                                load_location=False, load_location_recursive=False) -> list[KvLocation]:
        locations: list[KvLocation] = []

        for location_path in location_paths:
            locations.append(self.get_kv_location(location_path, not_found_ok, load_location, load_location_recursive))

        return locations

    async def a_get_kv_location(self, location_obj:Union[str,KvLocation], not_found_ok=True,
                                load_location=False, load_location_recursive=False) -> KvLocation:
        if type(location_obj) is str:
            location_obj = KvLocation(location_obj)

        kv_api = self.__get_api_instance_for_kv_object(location_obj)

        if location_obj.api_response is None:
            kv_location_response = await kv_api.a_list_location(location_obj)

        if load_location is True:
            load_location_tasks: list[asyncio.Task] = []

            for secret in location_obj.secrets:
                load_location_tasks.append(
                    asyncio.create_task(self.a_get_kv_secret(secret, not_found_ok))
                )

            if load_location_recursive is True:
                for location in location_obj.locations:
                    load_location_tasks.append(
                        asyncio.create_task(self.a_get_kv_location(location_obj=location, not_found_ok=not_found_ok,
                                                                   load_location=True, load_location_recursive=True))
                    )

            if len(load_location_tasks) > 0:
                await asyncio.wait(load_location_tasks)

        return self.__post_process_get_kv_location(kv_location_response, not_found_ok)

    async def a_get_kv_locations(self, location_paths: list[str], not_found_ok=True,
                                 load_location=True, load_location_recursive=True) -> list[KvLocation]:
        location_tasks: list[asyncio.Task] = []

        for location_path in location_paths:
            location_tasks.append(asyncio.create_task(self.a_get_kv_location(location_path, not_found_ok, load_location, load_location_recursive)))

        location_results: list[KvLocation] = await asyncio.gather(*location_tasks)

        return location_results

    @classmethod
    def from_approle(cls, vault_url, approle_id, approle_secret):
        approle_api = ApproleApi(vault_url)
        login_response = approle_api.login(approle_id, approle_secret)

        if login_response.api_response.status_code != 200:
            raise Exception(f"Failed to log in with approle {approle_id}. {login_response.api_response}")
        
        vault_obj = cls(vault_url, approle_api)
        vault_obj.init()

        return vault_obj
    
    @classmethod
    def from_token(cls, vault_url, token: VaultToken):
        token_api = TokenApi(vault_url, token)

        vault_obj = cls(vault_url, token_api)
        vault_obj.init()

        return vault_obj
    
    @classmethod
    async def a_from_token(cls, vault_url, token: VaultToken):
        token_api = TokenApi(vault_url, token)

        vault_obj = cls(vault_url, token_api)
        await asyncio.create_task(vault_obj.a_init())

        return vault_obj