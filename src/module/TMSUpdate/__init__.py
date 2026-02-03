# 修改為：
"""TMSUpdate 主模組"""

try:
    from src.module.TMSUpdate.pipeline.upload_pipeline import GeoVisioUploadPipeline
    from src.module.TMSUpdate.main import main
except ImportError:
    from pipeline.upload_pipeline import GeoVisioUploadPipeline
    from main import main

__all__ = ['GeoVisioUploadPipeline', 'main']
__version__ = '1.0.0'
