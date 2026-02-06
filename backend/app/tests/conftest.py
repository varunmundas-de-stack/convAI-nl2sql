import os
import sys
import pytest
from pathlib import Path
import yaml

# Add backend directory to sys.path to allow imports from app
backend_path = Path(__file__).parent.parent.parent.resolve()
sys.path.append(str(backend_path))

from app.services.catalog_manager import CatalogManager

@pytest.fixture(scope="session")
def catalog_path():
    return backend_path / "catalog" / "catalog.yaml"

@pytest.fixture(scope="session")
def cube_model_path():
    return backend_path.parent / "cube" / "model" / "cubes"

@pytest.fixture(scope="session")
def catalog_manager(catalog_path):
    return CatalogManager(str(catalog_path))

@pytest.fixture
def load_cube_schema(cube_model_path):
    def _load():
        schemas = {}
        if not cube_model_path.exists():
            return schemas

        for file in cube_model_path.glob("*.yml"):
            with open(file, "r") as f:
                data = yaml.safe_load(f)
                schemas[file.name] = data
        return schemas
    return _load
