upload_failures = []
collection_failures = set()


class FailureTracker:
    """失敗記錄追蹤器"""
    
    def __init__(self):
        self.upload_failures = []
        self.collection_failures = set()
    
    def record_upload_failure(self, keyname, collection_id, error, retry_count):
        """記錄上傳失敗"""
        pass
    
    def record_collection_failure(self, collection_id):
        """記錄 Collection 失敗"""
        pass
    
    def get_failure_summary(self) -> dict:
        """取得失敗摘要"""
        pass
    
    async def save_reports(self, output_dir: Path):
        """儲存失敗報告"""
        pass
    
    def clear(self):
        """清空記錄"""
        pass