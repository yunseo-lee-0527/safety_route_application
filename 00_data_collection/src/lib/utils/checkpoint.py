"""
파일 기반 체크포인트 유틸리티

긴 처리 작업이 중단된 경우 재시작 시 이미 완료한 항목을 건너뜁니다.
"""
import json
from pathlib import Path


class CheckpointManager:
    """완료된 키 목록을 JSON 파일에 저장해 작업 재시작을 지원합니다.

    Usage:
        ckpt = CheckpointManager(Path("output/.checkpoints/my_task.json"))
        for item in items:
            if ckpt.is_done(item.key):
                continue
            # ... process item ...
            ckpt.mark_done(item.key)
    """

    def __init__(self, checkpoint_path: Path):
        self.path = Path(checkpoint_path)
        self.done: set = self._load()

    def _load(self) -> set:
        if self.path.exists():
            try:
                return set(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:
                return set()
        return set()

    def is_done(self, key: str) -> bool:
        return str(key) in self.done

    def mark_done(self, key: str):
        self.done.add(str(key))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(sorted(self.done), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def count(self) -> int:
        return len(self.done)

    def clear(self):
        self.done.clear()
        if self.path.exists():
            self.path.unlink()
