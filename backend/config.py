from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env"}

    app_name: str = "SENREM3"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "data"
    gee_project: str = "c3po-461514"

    study_area_center_lat: float = -11.699153
    study_area_center_lon: float = -47.155531
    study_area_radius_km: float = 25.0
    study_area_name: str = "Natividade-Almas Greenstone Belt"

    earthdata_username: str = ""
    earthdata_password: str = ""


settings = Settings()
