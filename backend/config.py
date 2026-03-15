from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "SENREM3"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "data"

    study_area_center_lat: float = -11.699153
    study_area_center_lon: float = -47.155531
    study_area_radius_km: float = 25.0
    study_area_name: str = "Natividade-Almas Greenstone Belt"


settings = Settings()
