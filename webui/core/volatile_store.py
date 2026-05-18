# core/volatile_store.py

class VolatileStore:
    def __init__(self):
        self._memory = {}

    def save(self, key, value):
        self._memory[key] = value

    def get(self, key):
        return self._memory.get(key)

    def clear(self, key):
        if key in self._memory:
            # 명시적인 삭제 처리
            self._memory[key] = None
            del self._memory[key]
