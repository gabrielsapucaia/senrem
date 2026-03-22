from pydantic_settings import BaseSettings


STUDY_AREAS = {
    "paiol": {
        "name": "Paiol (Almas)",
        "center_lat": -11.699153,
        "center_lon": -47.155531,
        "radius_km": 30.0,
    },
    "engegold": {
        "name": "Engegold",
        "center_lat": -11.61884824630015,
        "center_lon": -47.74997845806124,
        "radius_km": 30.0,
    },
    "principe": {
        "name": "Principe",
        "center_lat": -11.926552258891494,
        "center_lon": -47.61025404303583,
        "radius_km": 30.0,
    },
    "manduca": {
        "name": "Manduca",
        "center_lat": -10.815478,
        "center_lon": -48.331875,
        "radius_km": 30.0,
    },
}

DEFAULT_AREA = "paiol"


class Settings(BaseSettings):
    model_config = {"env_file": ".env"}

    app_name: str = "SENREM3"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "data"
    gee_project: str = "c3po-461514"

    # Mantidos para compatibilidade (usados pelo VectorService ANM etc)
    study_area_center_lat: float = STUDY_AREAS[DEFAULT_AREA]["center_lat"]
    study_area_center_lon: float = STUDY_AREAS[DEFAULT_AREA]["center_lon"]
    study_area_radius_km: float = STUDY_AREAS[DEFAULT_AREA]["radius_km"]
    study_area_name: str = STUDY_AREAS[DEFAULT_AREA]["name"]

    earthdata_username: str = ""
    earthdata_password: str = ""

    gee_service_account_key: str = ""


settings = Settings()
