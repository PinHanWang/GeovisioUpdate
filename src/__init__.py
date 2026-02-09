"""
GeoVisio 上傳系統 - 主模組

扁平化結構：
- api/          API 客戶端和上傳器
- config/       設定管理
- core/         核心處理邏輯
- optimization/ 效能優化模組
- pipeline/     流程管理
- tools/        獨立工具程式
- utils/        通用工具
"""

try:
    from src.pipeline.upload_pipeline import GeoVisioUploadPipeline
    from src.config.settings import Settings
except ImportError:
    from pipeline.upload_pipeline import GeoVisioUploadPipeline
    from config.settings import Settings

__all__ = ['GeoVisioUploadPipeline', 'Settings']
__version__ = '2.0.0'
