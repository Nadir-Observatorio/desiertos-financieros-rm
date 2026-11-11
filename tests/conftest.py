from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from desiertos import CRS_GEOGRAFICO


@pytest.fixture
def unidades_rm() -> gpd.GeoDataFrame:
    """Dos 'comunas' sintéticas cerca de Santiago centro, cada una con una manzana."""
    return gpd.GeoDataFrame(
        {
            "manzent": [1, 2],
            "cut": [13101, 13119],
            "comuna": ["SANTIAGO", "MAIPÚ"],
            "area": ["URBANO", "URBANO"],
            "n_per": [100.0, 100.0],
            "n_60_mas": [10.0, 10.0],
        },
        geometry=[
            box(-70.67, -33.46, -70.64, -33.43),
            box(-70.79, -33.54, -70.75, -33.50),
        ],
        crs=CRS_GEOGRAFICO,
    )
