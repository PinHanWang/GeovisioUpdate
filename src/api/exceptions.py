"""
自定義異常模組

將異常類別獨立出來避免循環 import
"""


class ImageAlreadyExistsError(Exception):
    """圖片已存在的異常,不應重試"""
    pass


class RetryableUploadError(Exception):
    """可重試的上傳異常"""
    pass
